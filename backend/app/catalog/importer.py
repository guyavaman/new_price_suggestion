"""Import the menu and costs from the business's own Excel or CSV.

Two steps, always: a preview (what will be added, what will change, and every error by row and
column), then apply. Apply writes only the valid rows and reports the skipped ones, so a sheet
with a few bad rows doesn't block the rest. Headers may be in Hebrew or English.

Sheets (xlsx): "פריטים" (items), optional "חלקי חבילות" (package slots: one row per dish
option; the slot's name, how many to choose etc. on its first row). A package that appears in
that sheet gets exactly the slots listed. CSV: items only.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime

from openpyxl import Workbook, load_workbook
from openpyxl.comments import Comment
from openpyxl.styles import Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation
from pydantic import BaseModel, Field, ValidationError

from app.schemas.catalog import CatalogItem, CostSource, Slot
from app.services.packages import package_errors

ITEMS_SHEET, SLOT_SHEET, OLD_COMP_SHEET = "פריטים", "חלקי חבילות", "רכיבי חבילות"

# column -> accepted headers (first is what the template writes)
COLUMNS = {
    "sku": ["מק\"ט", "sku", "מקט", "קוד"],
    "name_he": ["שם", "name_he", "שם פריט"],
    "category": ["קטגוריה", "category"],
    "unit": ["יחידה", "unit"],
    "price": ["מחיר ללקוח (לפני מע\"מ)", "price", "מחיר"],
    "cost": ["עלות ליחידה (לפני מע\"מ)", "cost", "עלות"],
    "cost_source": ["מקור העלות", "cost_source"],
    "meal_type": ["סוג", "meal_type", "בשרי/חלבי/פרווה"],
    "serves": ["סועדים ליחידה", "serves"],
    "yield_amount": ["תפוקה ליחידה (גרם/מנות)", "yield_amount", "תפוקה ליחידה", "תפוקה"],
    "active": ["פעיל", "active"],
}
SLOT_COLUMNS = {
    "package_sku": ["מק\"ט חבילה", "package_sku"],
    "slot_id": ["מזהה חלק", "slot_id"],
    "label": ["שם החלק", "label", "slot"],
    "choose": ["כמה לבחור", "choose"],
    "sku": ["מק\"ט מנה", "option_sku", "sku"],
    "per_guest": ["כמות קבועה לסועד", "per_guest"],
    "customer_choice": ["הלקוח בוחר", "customer_choice"],
}
CATEGORY_HE = {"חבילה": "package", "סלט": "salad", "ראשונה": "starter", "עיקרית": "main",
               "תוספת": "side", "קבלת פנים": "canape", "בוקר": "breakfast", "קינוח": "dessert",
               "שתייה": "drink", "בר": "bar", "ציוד": "equipment", "צוות": "staff",
               "לוגיסטיקה": "logistics"}
UNIT_HE = {"לסועד": "per_guest", "מגש": "tray", "יחידה": "unit", "שעה": "hour", "ק\"ג": "kg"}
MEAL_HE = {"בשרי": "meat", "חלבי": "dairy", "פרווה": "pareve"}
SOURCE_HE = {"ידני": "manual", "ספק": "supplier", "מתכון": "recipe"}
YES = {"כן", "yes", "true", "1", "v", "✓"}
NO = {"לא", "no", "false", "0"}


class RowError(BaseModel):
    sheet: str
    row: int  # spreadsheet row number, as the owner sees it
    column: str
    message: str


class Change(BaseModel):
    sku: str
    name: str
    action: str  # "create" | "update"
    fields: dict[str, list] = Field(default_factory=dict)  # field -> [old, new]


class ImportReport(BaseModel):
    rows: int
    creates: list[Change]
    updates: list[Change]
    unchanged: int
    errors: list[RowError]
    applied: bool = False


# ---------------------------------------------------------------- reading

def _norm_header(h) -> str:
    return str(h or "").strip().replace("״", '"').lower()


def _map_headers(headers: list, spec: dict[str, list[str]]) -> dict[int, str]:
    lookup = {_norm_header(a): key for key, names in spec.items() for a in names}
    return {i: lookup[_norm_header(h)] for i, h in enumerate(headers)
            if _norm_header(h) in lookup}


def _rows(file_name: str, data: bytes) -> dict[str, list[tuple[int, list]]]:
    """{sheet: [(row_number, values)]} with the header as the first row."""
    if file_name.lower().endswith(".csv"):
        text = data.decode("utf-8-sig")
        rows = list(csv.reader(io.StringIO(text)))
        return {ITEMS_SHEET: [(i + 1, r) for i, r in enumerate(rows)]}
    wb = load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    out = {}
    for ws in wb.worksheets:
        out[ws.title] = [(i + 1, list(r)) for i, r in enumerate(ws.iter_rows(values_only=True))]
    if ITEMS_SHEET not in out and wb.worksheets:  # a single unnamed sheet = items
        out[ITEMS_SHEET] = out.pop(wb.worksheets[0].title)
    return out


def _cell(v):
    if v is None:
        return None
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return v


def _num(v, label: str, errors: list, sheet: str, row: int, col: str, positive=False):
    if v is None:
        return None
    try:
        x = float(str(v).replace(",", "").replace("₪", "").strip())
    except ValueError:
        errors.append(RowError(sheet=sheet, row=row, column=col,
                               message=f"{label}: '{v}' אינו מספר"))
        return None
    if x < 0 or (positive and x == 0):
        errors.append(RowError(sheet=sheet, row=row, column=col,
                               message=f"{label} חייב להיות {'חיובי' if positive else 'לא שלילי'}"))
        return None
    return x


# ---------------------------------------------------------------- preview / apply

def analyze(file_name: str, data: bytes, current: list[CatalogItem]
            ) -> tuple[ImportReport, list[tuple[CatalogItem, bool | None]]]:
    """Validate the file against the current catalog. Returns the report and, for every item
    the valid rows create or change, the item as it would be and its 'active' flag (None =
    keep)."""
    try:
        sheets = _rows(file_name, data)
    except Exception as e:  # unreadable file: one clear error, nothing else
        return ImportReport(rows=0, creates=[], updates=[], unchanged=0, errors=[RowError(
            sheet="", row=0, column="", message=f"לא ניתן לקרוא את הקובץ: {e}")]), []
    errors: list[RowError] = []
    by_sku = {i.sku: i.model_copy(deep=True) for i in current}
    original = {i.sku: i for i in current}
    touched: dict[str, dict] = {}
    rows = sheets.get(ITEMS_SHEET, [])
    if not rows:
        errors.append(RowError(sheet=ITEMS_SHEET, row=0, column="", message="אין גיליון פריטים"))
        rows = []
    head = _map_headers(rows[0][1], COLUMNS) if rows else {}
    if rows and "sku" not in head.values():
        errors.append(RowError(sheet=ITEMS_SHEET, row=1, column="מק\"ט",
                               message="חסרה עמודת מק\"ט"))
        rows = rows[:1]
    seen: set[str] = set()
    n_rows = 0
    for rn, vals in rows[1:]:
        rec = {key: _cell(vals[i]) if i < len(vals) else None for i, key in head.items()}
        if not any(v is not None for v in rec.values()):
            continue
        n_rows += 1
        before = len(errors)
        sku = str(rec.get("sku") or "").strip()
        S = ITEMS_SHEET

        def err(col: str, msg: str, rn=rn, sheet=ITEMS_SHEET):
            errors.append(RowError(sheet=sheet, row=rn, column=col, message=msg))
        if not sku:
            err("מק\"ט", "חסר מק\"ט")
            continue
        if sku in seen:
            err("מק\"ט", f"המק\"ט {sku} מופיע פעמיים בקובץ")
            continue
        seen.add(sku)
        patch: dict = {}
        if rec.get("name_he"):
            patch["name_he"] = str(rec["name_he"])
        for key, mapping in (("category", CATEGORY_HE), ("unit", UNIT_HE),
                             ("meal_type", MEAL_HE)):
            v = rec.get(key)
            if v is not None:
                patch[key] = mapping.get(str(v), str(v))
        price = _num(rec.get("price"), "מחיר", errors, S, rn, "מחיר", positive=True)
        if price is not None:
            patch["price"] = price
        serves = _num(rec.get("serves"), "סועדים ליחידה", errors, S, rn, "סועדים ליחידה")
        if serves is not None:
            patch["serves"] = int(serves) or None
        yld = _num(rec.get("yield_amount"), "תפוקה ליחידה", errors, S, rn, "תפוקה ליחידה",
                   positive=True)
        if yld is not None:
            patch["yield_amount"] = yld
        if "cost" in rec and rec.get("cost") is not None:
            cost = _num(rec["cost"], "עלות", errors, S, rn, "עלות")
            cur0 = by_sku.get(sku)
            if cost is not None and not (cur0 and cur0.cost == cost and not rec.get("cost_source")):
                patch["cost"] = cost  # (an unchanged cost with no source given is left alone)
                src = rec.get("cost_source")
                patch["cost_source"] = SOURCE_HE.get(str(src), str(src)) if src else "manual"
                if patch["cost_source"] not in {s.value for s in CostSource} - {"components"}:
                    err("מקור העלות", f"מקור עלות לא מוכר: {src} (ידני / ספק / מתכון)")
        if rec.get("active") is not None:
            a = str(rec["active"]).lower()
            if a in YES:
                patch["active"] = True
            elif a in NO:
                patch["active"] = False
            else:
                err("פעיל", f"ערך לא מוכר: {rec['active']} (כן / לא)")
        cur = by_sku.get(sku)
        is_pkg = (patch.get("category") or (cur.category.value if cur else "")) == "package"
        if "cost" in patch and is_pkg:
            err("עלות", "עלות של חבילה מחושבת מהמנות שלה (גיליון 'חלקי חבילות'), לא מוזנת")
        if len(errors) > before:
            continue
        active = patch.pop("active", None)
        try:
            if cur is None:
                missing = [h for k, h in (("name_he", "שם"), ("category", "קטגוריה"),
                                          ("unit", "יחידה"), ("price", "מחיר"),
                                          ("meal_type", "סוג")) if k not in patch]
                if missing:
                    err(missing[0], "פריט חדש חייב: " + ", ".join(missing))
                    continue
                new = CatalogItem.model_validate({"sku": sku, "name_en": patch["name_he"],
                                                  **patch})
                by_sku[sku] = new
            else:
                new = CatalogItem.model_validate({**cur.model_dump(), **patch})
                by_sku[sku] = new
        except ValidationError as e:
            first = e.errors()[0]
            field = str(first["loc"][0]) if first["loc"] else ""
            col = COLUMNS[field][0] if field in COLUMNS else field
            err(col, f"ערך לא תקין: {first.get('input')} ({_hint(field)})")
            continue
        if "cost" in patch:
            by_sku[sku].cost_updated_at = datetime.now(UTC)
        touched[sku] = {"active": active}

    # package slots (replace the listed packages' slots)
    if sheets.get(OLD_COMP_SHEET) and len(sheets[OLD_COMP_SHEET]) > 1:
        errors.append(RowError(sheet=OLD_COMP_SHEET, row=1, column="", message=(
            f"הגיליון '{OLD_COMP_SHEET}' הוחלף ב'{SLOT_SHEET}'. הורידו תבנית חדשה")))
    slot_rows = sheets.get(SLOT_SHEET, [])
    if slot_rows:
        _read_slots(slot_rows, by_sku, touched, errors)

    creates, updates, unchanged = [], [], 0
    for sku, meta in touched.items():
        new, old = by_sku[sku], original.get(sku)
        if old is None:
            creates.append(Change(sku=sku, name=new.name_he, action="create"))
            continue
        diff = {f: [getattr(old, f), getattr(new, f)] for f in
                ("name_he", "category", "unit", "price", "cost", "cost_source", "meal_type",
                 "serves", "yield_amount", "slots") if getattr(old, f) != getattr(new, f)}
        if meta.get("active") is not None and meta["active"] != getattr(old, "active", True):
            diff["active"] = [getattr(old, "active", True), meta["active"]]
        diff = {k: [_plain(a), _plain(b)] for k, (a, b) in diff.items()}
        if diff:
            updates.append(Change(sku=sku, name=new.name_he, action="update", fields=diff))
        else:
            unchanged += 1
    report = ImportReport(rows=n_rows, creates=creates, updates=updates, unchanged=unchanged,
                          errors=errors)
    changed = [c.sku for c in creates] + [u.sku for u in updates]
    return report, [(by_sku[s], touched[s].get("active")) for s in changed]


def _read_slots(slot_rows, by_sku: dict[str, CatalogItem], touched: dict, errors: list) -> None:
    S = SLOT_SHEET
    ch = _map_headers(slot_rows[0][1], SLOT_COLUMNS)
    slots: dict[str, dict[str, dict]] = {}   # package -> slot id -> fields
    first_row: dict[str, int] = {}
    for rn, vals in slot_rows[1:]:
        rec = {key: _cell(vals[i]) if i < len(vals) else None for i, key in ch.items()}
        if not any(v is not None for v in rec.values()):
            continue
        pkg = str(rec.get("package_sku") or "").strip()
        sid = str(rec.get("slot_id") or "").strip()
        opt = str(rec.get("sku") or "").strip()
        if pkg not in by_sku or by_sku[pkg].category.value != "package":
            errors.append(RowError(sheet=S, row=rn, column="מק\"ט חבילה",
                                   message=f"{pkg or '(ריק)'} אינו חבילה בתפריט"))
            continue
        if not sid or not opt:
            errors.append(RowError(sheet=S, row=rn, column="מזהה חלק" if not sid else "מק\"ט מנה",
                                   message="חסר מזהה חלק" if not sid else "חסר מק\"ט מנה"))
            continue
        first_row.setdefault(pkg, rn)
        sl = slots.setdefault(pkg, {}).setdefault(sid, {"id": sid, "options": [], "row": rn})
        sl["options"].append(opt)
        if rec.get("label"):
            sl["label_he"] = str(rec["label"])
        if rec.get("choose") is not None:
            n = _num(rec["choose"], "כמה לבחור", errors, S, rn, "כמה לבחור", positive=True)
            if n is not None:
                sl["choose"] = int(n)
        if rec.get("per_guest") is not None:
            pg = _num(rec["per_guest"], "כמות קבועה לסועד", errors, S, rn,
                      "כמות קבועה לסועד", positive=True)
            if pg is not None:
                sl["per_guest"] = pg
        if rec.get("customer_choice") is not None:
            sl["customer_choice"] = str(rec["customer_choice"]).lower() not in NO
    for pkg, by_id in slots.items():
        try:
            new = [Slot.model_validate({"label_he": d.get("label_he") or d["id"], **{
                k: v for k, v in d.items() if k != "row"}}) for d in by_id.values()]
        except ValidationError as e:
            errors.append(RowError(sheet=S, row=first_row[pkg], column="",
                                   message=f"{pkg}: {e.errors()[0]['msg']}"))
            continue
        draft = by_sku[pkg].model_copy(update={"slots": new})
        errs = package_errors(draft, by_sku)
        if errs:
            errors.extend(RowError(sheet=S, row=first_row[pkg], column="", message=f"{pkg}: {m}")
                          for m in errs)
            continue
        if new != by_sku[pkg].slots:
            by_sku[pkg] = draft.model_copy(update={"cost_source": CostSource.components,
                                                   "components": []})
            touched.setdefault(pkg, {"active": None})


def _plain(v):
    if isinstance(v, list):
        return [c.model_dump() if hasattr(c, "model_dump") else c for c in v]
    return getattr(v, "value", v)


def _hint(field: str) -> str:
    return {"category": "קטגוריות: " + ", ".join(CATEGORY_HE),
            "unit": "יחידות: " + ", ".join(UNIT_HE),
            "meal_type": "בשרי / חלבי / פרווה"}.get(field, field)


# ---------------------------------------------------------------- template

def template_xlsx(current: list[CatalogItem]) -> bytes:
    """A fill-in workbook: the business's current menu (so editing costs is just typing in a
    column), a legend, and the components sheet."""
    wb = Workbook()
    ws = wb.active
    ws.title = ITEMS_SHEET
    ws.sheet_view.rightToLeft = True
    head = [names[0] for names in COLUMNS.values()]
    ws.append(head)
    inv = {v: k for k, v in CATEGORY_HE.items()}
    inv_u = {v: k for k, v in UNIT_HE.items()}
    inv_m = {v: k for k, v in MEAL_HE.items()}
    inv_s = {v: k for k, v in SOURCE_HE.items()}
    for i in current:
        ws.append([i.sku, i.name_he, inv.get(i.category.value, i.category.value),
                   inv_u.get(i.unit.value, i.unit.value), i.price,
                   None if i.category.value == "package" else i.cost,
                   inv_s.get(i.cost_source.value) if i.cost_source and
                   i.cost_source.value != "components" else None,
                   inv_m.get(i.meal_type.value, i.meal_type.value), i.serves, i.yield_amount,
                   "כן" if getattr(i, "active", True) else "לא"])
    bold, fill = Font(name="Arial", bold=True), PatternFill("solid", fgColor="FFF2CC")
    for c in ws[1]:
        c.font = bold
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.font = Font(name="Arial")
        row[5].fill = fill  # the column most businesses come to fill in: cost
    ws["F1"].comment = Comment("עלות ליחידה לפני מע\"מ, באותה יחידה כמו המחיר. ריק = לא ידוע. "
                               "לחבילות משאירים ריק: העלות מחושבת מהמנות.", "זית ודבש")
    ws["J1"].comment = Comment("כמה יחידה אחת נותנת: בגרם לסלטים ותוספות (מגש = 2000), "
                               "במנות לשאר (עוגה = 16, מנה לסועד = 1). ריק = לא ידוע.", "זית ודבש")
    widths = [16, 30, 12, 10, 18, 18, 12, 10, 12, 16, 8]
    for col, w in zip("ABCDEFGHIJK", widths, strict=True):
        ws.column_dimensions[col].width = w
    for col, opts in (("C", CATEGORY_HE), ("D", UNIT_HE), ("H", MEAL_HE), ("G", SOURCE_HE)):
        dv = DataValidation(type="list", formula1='"' + ",".join(opts) + '"', allow_blank=True)
        ws.add_data_validation(dv)
        dv.add(f"{col}2:{col}2000")
    ws.freeze_panes = "B2"

    cs = wb.create_sheet(SLOT_SHEET)
    cs.sheet_view.rightToLeft = True
    cs.append([names[0] for names in SLOT_COLUMNS.values()])
    for i in current:
        for sl in i.slots:
            for n, opt in enumerate(sl.options):
                first = n == 0
                cs.append([i.sku, sl.id, sl.label_he if first else None,
                           sl.choose if first else None, opt,
                           sl.per_guest if first else None,
                           ("כן" if sl.customer_choice else "לא") if first else None])
    for c in cs[1]:
        c.font = bold
    for col, w in zip("ABCDEFG", [18, 14, 18, 12, 20, 18, 12], strict=True):
        cs.column_dimensions[col].width = w
    cs.freeze_panes = "A2"

    lg = wb.create_sheet("הסבר")
    lg.sheet_view.rightToLeft = True
    for line in [
        "איך ממלאים",
        "גיליון 'פריטים': שורה לכל פריט. מק\"ט קיים = עדכון, מק\"ט חדש = פריט חדש.",
        "עמודה מודגשת בצהוב (עלות): עלות ליחידה לפני מע\"מ.",
        "תא עלות ריק = לא ידוע, והמערכת תסמן 'עלות חסרה'.",
        "תא ריק בפריט קיים לא משנה את הערך הקיים.",
        "תפוקה ליחידה: כמה יחידה אחת נותנת (גרם לסלטים ותוספות, מנות לשאר). ממנה מחושבים מגשים.",
        "חבילות: לא ממלאים עלות. בגיליון 'חלקי חבילות' רושמים מאילו חלקים החבילה בנויה:",
        "  שורה לכל מנה אפשרית. בשורה הראשונה של כל חלק: שם החלק וכמה לבחור.",
        "  דוגמה: PKG-1 | salads | סלטים | 3 | SAL-1   ואחריה   PKG-1 | salads | | | SAL-2 ...",
        "  = 'בוחרים 3 סלטים מתוך הרשימה'. כמות קבועה לסועד (למשל לחם 80 גרם) לא משתנה לפי גיוון.",
        "  חבילה שמופיעה בגיליון מקבלת בדיוק את החלקים שרשומים לה.",
        "כמה גרם/מנות מקבל כל סועד מכל קטגוריה, ומקדם הגיוון: בהגדרות, תחת 'מנות וכמויות'.",
        "קטגוריות: " + ", ".join(CATEGORY_HE),
        "יחידות: " + ", ".join(UNIT_HE) + "   סוג: " + ", ".join(MEAL_HE),
        "מקור העלות: " + ", ".join(SOURCE_HE),
        "אחרי ההעלאה מוצג דוח: מה יתווסף, מה ישתנה ואילו שורות נדחו ולמה. רק אז מאשרים.",
    ]:
        lg.append([line])
    lg["A1"].font = Font(name="Arial", bold=True, size=13)
    lg.column_dimensions["A"].width = 110
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()

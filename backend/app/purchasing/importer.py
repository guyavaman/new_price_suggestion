"""Import suppliers, ingredients and recipes from the business's Excel (stage 3).

Same two steps as the menu import: a preview with every error by sheet, row and column, then
apply, which writes only the valid rows. Sheets (any may be missing):
  "ספקים"        one row per supplier
  "חומרי גלם"    one row per ingredient (its supplier by code)
  "מתכונים"      one row per ingredient of a dish; a dish listed here gets exactly these lines
  "מנות במטבח"   per dish: work station and how many days ahead it's made
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font
from openpyxl.worksheet.datavalidation import DataValidation
from pydantic import BaseModel, Field, ValidationError

from app.catalog.importer import (
    NO,
    Change,
    ImportReport,
    RowError,
    _cell,
    _map_headers,
    _norm_header,
    _num,
)
from app.purchasing.models import WEEKDAYS_HE, Ingredient, Supplier
from app.purchasing.recipes import recipe_errors
from app.schemas.catalog import CatalogItem, RecipeLine

SUP_SHEET, ING_SHEET, REC_SHEET, DISH_SHEET = "ספקים", "חומרי גלם", "מתכונים", "מנות במטבח"
SUP_COLS = {
    "code": ["קוד ספק", "code", "supplier_code"],
    "name": ["שם הספק", "name", "שם"],
    "phone": ["טלפון", "phone"],
    "email": ["אימייל", "email"],
    "lead_days": ["ימים מהזמנה לאספקה", "lead_days"],
    "delivery_days": ["ימי אספקה", "delivery_days"],
    "order_cutoff": ["שעת סגירת הזמנות", "order_cutoff"],
    "notes": ["הערות", "notes"],
}
ING_COLS = {
    "code": ["קוד חומר גלם", "code", "ingredient_code"],
    "name_he": ["שם", "name_he", "name"],
    "unit": ["יחידה", "unit"],
    "kashrut": ["כשרות", "kashrut"],
    "supplier": ["קוד ספק", "supplier"],
    "price": ["מחיר ליחידה (לפני מע\"מ)", "price", "מחיר"],
}
REC_COLS = {
    "sku": ["מק\"ט מנה", "sku", "dish_sku"],
    "dish": ["שם המנה", "dish"],
    "ingredient": ["קוד חומר גלם", "ingredient"],
    "quantity": ["כמות ליחידת מנה", "quantity", "כמות"],
}
DISH_COLS = {
    "sku": ["מק\"ט מנה", "sku"],
    "dish": ["שם המנה", "dish"],
    "station": ["תחנה", "station"],
    "prep_days": ["ימי הכנה מראש", "prep_days"],
}
UNIT_IN = {'ק"ג': "kg", "קג": "kg", "kg": "kg", "ליטר": "liter", "ל": "liter", "liter": "liter",
           "l": "liter", "יח'": "unit", "יח": "unit", "יחידה": "unit", "unit": "unit"}
KASHRUT_IN = {"בשרי": "meat", "חלבי": "dairy", "פרווה": "pareve", "meat": "meat",
              "dairy": "dairy", "pareve": "pareve"}
DAY_LETTERS = {"א": 6, "ב": 0, "ג": 1, "ד": 2, "ה": 3, "ו": 4, "ש": 5}
DAY_NAMES = {n: i for i, n in enumerate(WEEKDAYS_HE)}
DAY_LETTER_OF = {v: k for k, v in DAY_LETTERS.items()}


class ImportPlan(BaseModel):
    suppliers: list[Supplier] = Field(default_factory=list)
    ingredients: list[Ingredient] = Field(default_factory=list)
    recipes: dict[str, list[RecipeLine]] = Field(default_factory=dict)
    dish_fields: dict[str, dict] = Field(default_factory=dict)


def _rows(file_name: str, data: bytes) -> dict[str, list[tuple[int, list]]]:
    """{sheet name: [(row number, values)]}, names kept as they are."""
    if file_name.lower().endswith(".csv"):
        text = data.decode("utf-8-sig")
        return {"csv": [(i + 1, r) for i, r in enumerate(csv.reader(io.StringIO(text)))]}
    wb = load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    return {ws.title.strip(): [(i + 1, list(r)) for i, r in
                               enumerate(ws.iter_rows(values_only=True))]
            for ws in wb.worksheets}


def parse_days(v) -> list[int] | None:
    """'א,ב,ג,ד,ה' or 'ראשון, שני' or '6,0,1' → weekdays (0=Monday)."""
    out = set()
    for part in str(v).replace("/", ",").replace(" ", ",").replace("'", "").split(","):
        p = part.strip()
        if not p:
            continue
        if p in DAY_LETTERS:
            out.add(DAY_LETTERS[p])
        elif p in DAY_NAMES:
            out.add(DAY_NAMES[p])
        elif p.isdigit() and 0 <= int(p) <= 6:
            out.add(int(p))
        else:
            return None
    return sorted(out) or None


def _records(sheets, name, spec):
    rows = sheets.get(name, [])
    if not rows:
        return []
    head = _map_headers(rows[0][1], spec)
    out = []
    for rn, vals in rows[1:]:
        rec = {k: _cell(vals[i]) if i < len(vals) else None for i, k in head.items()}
        if any(v is not None for v in rec.values()):
            out.append((rn, rec))
    return out


def _diff(old: BaseModel | None, new: BaseModel, fields: list[str], key: str, name: str,
          creates: list, updates: list) -> bool:
    if old is None:
        creates.append(Change(sku=key, name=name, action="create"))
        return True
    d = {f: [_plain(getattr(old, f)), _plain(getattr(new, f))] for f in fields
         if getattr(old, f) != getattr(new, f)}
    if d:
        updates.append(Change(sku=key, name=name, action="update", fields=d))
    return bool(d)


def _plain(v):
    if isinstance(v, list):
        return [x.model_dump() if hasattr(x, "model_dump") else x for x in v]
    return getattr(v, "value", v)


def analyze(file_name: str, data: bytes, suppliers: list[Supplier], ingredients: list[Ingredient],
            catalog: list[CatalogItem]) -> tuple[ImportReport, ImportPlan]:
    try:
        sheets = _rows(file_name, data)
    except Exception as e:
        return ImportReport(rows=0, creates=[], updates=[], unchanged=0, errors=[RowError(
            sheet="", row=0, column="", message=f"לא ניתן לקרוא את הקובץ: {e}")]), ImportPlan()
    if file_name.lower().endswith(".csv"):  # a CSV can only be one sheet: guess which
        rows = sheets.pop(next(iter(sheets)), [])
        heads = {_norm_header(h) for h in (rows[0][1] if rows else [])}
        kind = (REC_SHEET if _norm_header("כמות ליחידת מנה") in heads or "quantity" in heads
                else ING_SHEET if _norm_header("יחידה") in heads or "unit" in heads
                else SUP_SHEET)
        sheets = {kind: rows}
    errors: list[RowError] = []
    creates: list[Change] = []
    updates: list[Change] = []
    unchanged = 0
    n_rows = 0
    plan = ImportPlan()
    sup_by = {s.code: s for s in suppliers}
    ing_by = {i.code: i for i in ingredients}
    dish_by = {i.sku: i for i in catalog}

    def err(sheet, rn, col, msg):
        errors.append(RowError(sheet=sheet, row=rn, column=col, message=msg))

    # suppliers
    seen: set[str] = set()
    for rn, rec in _records(sheets, SUP_SHEET, SUP_COLS):
        n_rows += 1
        code = str(rec.get("code") or "").strip()
        if not code:
            err(SUP_SHEET, rn, "קוד ספק", "חסר קוד ספק")
            continue
        if code in seen:
            err(SUP_SHEET, rn, "קוד ספק", f"הקוד {code} מופיע פעמיים")
            continue
        seen.add(code)
        cur = sup_by.get(code)
        data_ = cur.model_dump() if cur else {"code": code}
        data_ = {k: v for k, v in data_.items() if k in Supplier.model_fields}
        for f in ("name", "phone", "email", "notes", "order_cutoff"):
            if rec.get(f) is not None:
                v = rec[f]
                if f == "order_cutoff" and not isinstance(v, str):
                    v = v.strftime("%H:%M") if hasattr(v, "strftime") else str(v)
                data_[f] = str(v)
        before = len(errors)
        if rec.get("lead_days") is not None:
            n = _num(rec["lead_days"], "ימים לאספקה", errors, SUP_SHEET, rn, "ימים מהזמנה לאספקה")
            if n is not None:
                data_["lead_days"] = int(n)
        if rec.get("delivery_days") is not None:
            days = parse_days(rec["delivery_days"])
            if days is None:
                err(SUP_SHEET, rn, "ימי אספקה",
                    f"לא הבנתי את '{rec['delivery_days']}' (למשל: א,ב,ג,ד,ה)")
            else:
                data_["delivery_days"] = days
        if len(errors) > before:
            continue
        try:
            s = Supplier.model_validate(data_)
        except ValidationError as e:
            first = e.errors()[0]
            f = str(first["loc"][0]) if first["loc"] else ""
            err(SUP_SHEET, rn, SUP_COLS.get(f, [f])[0], "ערך חסר או לא תקין")
            continue
        sup_by[code] = s
        if _diff(cur, s, list(Supplier.model_fields), code, s.name, creates, updates):
            plan.suppliers.append(s)
        else:
            unchanged += 1

    # ingredients
    seen = set()
    for rn, rec in _records(sheets, ING_SHEET, ING_COLS):
        n_rows += 1
        code = str(rec.get("code") or "").strip()
        if not code:
            err(ING_SHEET, rn, "קוד חומר גלם", "חסר קוד")
            continue
        if code in seen:
            err(ING_SHEET, rn, "קוד חומר גלם", f"הקוד {code} מופיע פעמיים")
            continue
        seen.add(code)
        cur = ing_by.get(code)
        data_ = cur.model_dump() if cur else {"code": code}
        data_ = {k: v for k, v in data_.items() if k in Ingredient.model_fields}
        before = len(errors)
        if rec.get("name_he") is not None:
            data_["name_he"] = str(rec["name_he"])
        if rec.get("unit") is not None:
            u = UNIT_IN.get(str(rec["unit"]).strip())
            if u is None:
                err(ING_SHEET, rn, "יחידה", f"יחידה לא מוכרת: {rec['unit']} (ק\"ג / ליטר / יח')")
            data_["unit"] = u
        if rec.get("kashrut") is not None:
            k = KASHRUT_IN.get(str(rec["kashrut"]).strip())
            if k is None:
                err(ING_SHEET, rn, "כשרות", f"כשרות לא מוכרת: {rec['kashrut']}")
            data_["kashrut"] = k
        if rec.get("supplier") is not None:
            sc = str(rec["supplier"]).strip()
            if sc not in sup_by:
                err(ING_SHEET, rn, "קוד ספק", f"הספק {sc} לא קיים")
            data_["supplier"] = sc
        if rec.get("price") is not None:
            pr = _num(rec["price"], "מחיר", errors, ING_SHEET, rn, "מחיר ליחידה")
            if pr is not None:
                data_["price"] = pr
        if len(errors) > before:
            continue
        try:
            i = Ingredient.model_validate(data_)
        except ValidationError as e:
            first = e.errors()[0]
            f = str(first["loc"][0]) if first["loc"] else ""
            err(ING_SHEET, rn, ING_COLS.get(f, [f])[0], "ערך חסר או לא תקין")
            continue
        if cur and cur.price != i.price:
            i = i.model_copy(update={"price_updated_at": datetime.now(UTC)})
        ing_by[code] = i
        if _diff(cur, i, ["name_he", "unit", "kashrut", "supplier", "price"], code, i.name_he,
                 creates, updates):
            plan.ingredients.append(i)
        else:
            unchanged += 1

    # recipes
    lines: dict[str, list[tuple[int, RecipeLine]]] = {}
    for rn, rec in _records(sheets, REC_SHEET, REC_COLS):
        n_rows += 1
        sku = str(rec.get("sku") or "").strip()
        code = str(rec.get("ingredient") or "").strip()
        dish = dish_by.get(sku)
        if dish is None:
            err(REC_SHEET, rn, "מק\"ט מנה", f"המנה {sku or '(ריק)'} לא קיימת בתפריט")
            continue
        if dish.kind.value not in ("food", "drink"):
            err(REC_SHEET, rn, "מק\"ט מנה", f"{dish.name_he} אינה מנה (מתכון רק לאוכל ושתייה)")
            continue
        if code not in ing_by:
            err(REC_SHEET, rn, "קוד חומר גלם", f"חומר הגלם {code or '(ריק)'} לא קיים")
            continue
        q = _num(rec.get("quantity"), "כמות", errors, REC_SHEET, rn, "כמות ליחידת מנה",
                 positive=True)
        if q is None:
            if rec.get("quantity") is None:
                err(REC_SHEET, rn, "כמות ליחידת מנה", "חסרה כמות")
            continue
        lines.setdefault(sku, []).append((rn, RecipeLine(ingredient=code, quantity=q)))
    for sku, rows in lines.items():
        dish = dish_by[sku]
        recipe = [r for _, r in rows]
        draft = dish.model_copy(update={"recipe": recipe})
        errs = recipe_errors(draft, ing_by)
        if errs:
            for m in errs:
                err(REC_SHEET, rows[0][0], "", f"{dish.name_he}: {m}")
            continue
        if recipe != dish.recipe:
            plan.recipes[sku] = recipe
            if dish.recipe:
                updates.append(Change(sku=sku, name=dish.name_he, action="update",
                                      fields={"recipe": [len(dish.recipe), len(recipe)]}))
            else:
                creates.append(Change(sku=sku, name=f"מתכון: {dish.name_he}", action="create"))
        else:
            unchanged += 1

    # dishes in the kitchen: station and prep days
    for rn, rec in _records(sheets, DISH_SHEET, DISH_COLS):
        n_rows += 1
        sku = str(rec.get("sku") or "").strip()
        dish = dish_by.get(sku)
        if dish is None:
            err(DISH_SHEET, rn, "מק\"ט מנה", f"המנה {sku or '(ריק)'} לא קיימת בתפריט")
            continue
        fields: dict = {}
        if rec.get("station") is not None:
            fields["station"] = str(rec["station"])[:40]
        if rec.get("prep_days") is not None:
            n = _num(rec["prep_days"], "ימי הכנה", errors, DISH_SHEET, rn, "ימי הכנה מראש")
            if n is None:
                continue
            if n > 14:
                err(DISH_SHEET, rn, "ימי הכנה מראש", "עד 14 ימים")
                continue
            fields["prep_days"] = int(n)
        fields = {k: v for k, v in fields.items() if getattr(dish, k) != v}
        if fields:
            plan.dish_fields[sku] = fields
            updates.append(Change(sku=sku, name=dish.name_he, action="update",
                                  fields={k: [getattr(dish, k), v] for k, v in fields.items()}))
        else:
            unchanged += 1
    return ImportReport(rows=n_rows, creates=creates, updates=updates, unchanged=unchanged,
                        errors=errors), plan


def template_xlsx(suppliers: list[Supplier], ingredients: list[Ingredient],
                  catalog: list[CatalogItem]) -> bytes:
    wb = Workbook()
    bold, plain = Font(name="Arial", bold=True), Font(name="Arial")
    unit_out = {"kg": 'ק"ג', "liter": "ליטר", "unit": "יח'"}
    kas_out = {"meat": "בשרי", "dairy": "חלבי", "pareve": "פרווה"}

    def sheet(title, cols, rows, widths, first=False):
        ws = wb.active if first else wb.create_sheet(title)
        ws.title = title
        ws.sheet_view.rightToLeft = True
        ws.append([names[0] for names in cols.values()])
        for r in rows:
            ws.append(r)
        for row in ws.iter_rows():
            for c in row:
                c.font = plain
        for c in ws[1]:
            c.font = bold
        for i, w in enumerate(widths):
            ws.column_dimensions[chr(65 + i)].width = w
        ws.freeze_panes = "A2"
        return ws

    sheet(SUP_SHEET, SUP_COLS, [[s.code, s.name, s.phone, s.email, s.lead_days,
                                 ",".join(DAY_LETTER_OF[d] for d in sorted(
                                     s.delivery_days, key=lambda d: (d + 1) % 7)),
                                 s.order_cutoff, s.notes] for s in suppliers],
          [14, 24, 14, 22, 12, 16, 14, 30], first=True)
    ws = sheet(ING_SHEET, ING_COLS, [[i.code, i.name_he, unit_out[i.unit.value],
                                      kas_out[i.kashrut.value], i.supplier, i.price]
                                     for i in ingredients], [16, 24, 10, 10, 14, 18])
    for col, opts in (("C", unit_out.values()), ("D", kas_out.values())):
        dv = DataValidation(type="list", formula1='"' + ",".join(opts) + '"', allow_blank=True)
        ws.add_data_validation(dv)
        dv.add(f"{col}2:{col}2000")
    dishes = [i for i in catalog if i.kind.value in ("food", "drink")]
    sheet(REC_SHEET, REC_COLS, [[d.sku, d.name_he, r.ingredient, r.quantity]
                                for d in dishes for r in d.recipe], [18, 26, 18, 16])
    sheet(DISH_SHEET, DISH_COLS, [[d.sku, d.name_he, d.station, d.prep_days] for d in dishes],
          [18, 26, 14, 14])
    lg = wb.create_sheet("הסבר")
    lg.sheet_view.rightToLeft = True
    for line in [
        "איך ממלאים",
        "ספקים: ימי אספקה באותיות (א,ב,ג,ד,ה,ו). שעת סגירת הזמנות: אחריה ההזמנה נחשבת למחרת.",
        "חומרי גלם: יחידה (ק\"ג / ליטר / יח'), כשרות (בשרי / חלבי / פרווה), קוד הספק, ומחיר אחרון "
        "ליחידה לפני מע\"מ. מחיר ריק = לא ידוע.",
        "מתכונים: שורה לכל חומר גלם במנה. הכמות היא ליחידה אחת של המנה כפי שהיא בתפריט "
        "(מגש אחד, מנה אחת, עוגה אחת), ביחידה של חומר הגלם.",
        "  מנה שמופיעה בגיליון מקבלת בדיוק את השורות שרשומות לה. מנה שלא מופיעה לא משתנה.",
        "  מנה בלי מתכון היא מצב רגיל: היא מסומנת 'אין מתכון' ולא נכנסת לרשימת הרכש.",
        "מנות במטבח: תחנת עבודה (למשל קר, חם, גריל, מאפייה) וכמה ימים לפני האירוע מכינים.",
        "תא ריק בשורה קיימת לא משנה את הערך הקיים.",
        "אחרי ההעלאה מוצג דוח: מה יתווסף, מה ישתנה ואילו שורות נדחו ולמה. רק אז מאשרים.",
    ]:
        lg.append([line])
    lg["A1"].font = Font(name="Arial", bold=True, size=13)
    lg.column_dimensions["A"].width = 110
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


__all__ = ["ImportReport", "ImportPlan", "analyze", "template_xlsx", "parse_days", "NO"]

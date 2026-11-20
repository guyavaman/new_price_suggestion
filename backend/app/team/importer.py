"""Import staff and equipment stock from Excel (stage 5): preview with an error report, then
apply the valid rows. Sheets: "צוות" (a person is matched by phone, else by name) and
"מלאי ציוד" (by code)."""

from __future__ import annotations

import io

from openpyxl import Workbook
from openpyxl.styles import Font
from pydantic import ValidationError

from app.catalog.importer import Change, ImportReport, RowError, _num
from app.purchasing.importer import DAY_LETTER_OF, _records, _rows, parse_days
from app.team.models import EquipmentType, StaffMember

STAFF_SHEET, STOCK_SHEET = "צוות", "מלאי ציוד"
STAFF_COLS = {
    "name": ["שם", "name"],
    "phone": ["טלפון", "phone"],
    "roles": ["תפקידים", "roles"],
    "hourly_rate": ["תעריף לשעה", "hourly_rate", "תעריף"],
    "available_days": ["ימים זמינים", "available_days"],
    "active": ["פעיל", "active"],
    "notes": ["הערות", "notes"],
}
STOCK_COLS = {
    "code": ["קוד", "code"],
    "name": ["שם", "name"],
    "owned": ["כמות במלאי", "owned", "כמות"],
    "notes": ["הערות", "notes"],
}
ROLE_IN = {"מלצר": "waiter", "מלצרית": "waiter", "waiter": "waiter", "מנהל אירוע": "head_waiter",
           "מנהלת אירוע": "head_waiter", "head_waiter": "head_waiter", "ברמן": "bartender",
           "ברמנית": "bartender", "bartender": "bartender", "שף": "chef", "chef": "chef"}
ROLE_OUT = {"waiter": "מלצר", "head_waiter": "מנהל אירוע", "bartender": "ברמן", "chef": "שף"}
NO = {"לא", "no", "false", "0"}


def _digits(p) -> str:
    return "".join(ch for ch in str(p or "") if ch.isdigit())


def analyze(file_name: str, data: bytes, tenant: str, staff: list[StaffMember],
            stock: list[EquipmentType]
            ) -> tuple[ImportReport, list[StaffMember], list[EquipmentType]]:
    try:
        sheets = _rows(file_name, data)
    except Exception as e:  # noqa: BLE001
        return ImportReport(rows=0, creates=[], updates=[], unchanged=0, errors=[RowError(
            sheet="", row=0, column="", message=f"לא ניתן לקרוא את הקובץ: {e}")]), [], []
    if "csv" in sheets:
        sheets = {STAFF_SHEET: sheets["csv"]}
    errors: list[RowError] = []
    creates: list[Change] = []
    updates: list[Change] = []
    unchanged = n = 0
    by_phone = {_digits(m.phone): m for m in staff if _digits(m.phone)}
    by_name = {m.name: m for m in staff}
    out_staff: list[StaffMember] = []

    def err(sheet, rn, col, msg):
        errors.append(RowError(sheet=sheet, row=rn, column=col, message=msg))

    for rn, rec in _records(sheets, STAFF_SHEET, STAFF_COLS):
        n += 1
        name = str(rec.get("name") or "").strip()
        if not name:
            err(STAFF_SHEET, rn, "שם", "חסר שם")
            continue
        cur = by_phone.get(_digits(rec.get("phone"))) or by_name.get(name)
        data_ = cur.model_dump() if cur else {"tenant_id": tenant}
        data_["name"] = name
        before = len(errors)
        if rec.get("phone") is not None:
            data_["phone"] = str(rec["phone"]).strip()
        if rec.get("roles") is not None:
            roles = []
            for part in str(rec["roles"]).replace("/", ",").split(","):
                p = part.strip()
                if not p:
                    continue
                if p not in ROLE_IN:
                    err(STAFF_SHEET, rn, "תפקידים", f"תפקיד לא מוכר: {p} (מלצר / מנהל אירוע / "
                        "ברמן / שף)")
                else:
                    roles.append(ROLE_IN[p])
            data_["roles"] = roles
        if rec.get("hourly_rate") is not None:
            r = _num(rec["hourly_rate"], "תעריף", errors, STAFF_SHEET, rn, "תעריף לשעה")
            if r is not None:
                data_["hourly_rate"] = r
        if rec.get("available_days") is not None:
            days = parse_days(rec["available_days"])
            if days is None:
                err(STAFF_SHEET, rn, "ימים זמינים",
                    f"לא הבנתי את '{rec['available_days']}' (למשל: א,ב,ג,ה)")
            else:
                data_["available_days"] = days
        if rec.get("active") is not None:
            data_["active"] = str(rec["active"]).strip().lower() not in NO
        if rec.get("notes") is not None:
            data_["notes"] = str(rec["notes"])
        if len(errors) > before:
            continue
        try:
            m = StaffMember.model_validate(data_)
        except ValidationError as e:
            err(STAFF_SHEET, rn, "", f"{name}: {e.errors()[0]['msg']}")
            continue
        if cur is None:
            creates.append(Change(sku=m.phone or name, name=name, action="create"))
            out_staff.append(m)
        else:
            diff = {f: [getattr(cur, f), getattr(m, f)] for f in
                    ("name", "phone", "roles", "hourly_rate", "available_days", "active")
                    if getattr(cur, f) != getattr(m, f)}
            if diff:
                updates.append(Change(sku=m.phone or name, name=name, action="update",
                                      fields={k: [_p(a), _p(b)] for k, (a, b) in diff.items()}))
                out_staff.append(m)
            else:
                unchanged += 1

    stock_by = {e.code: e for e in stock}
    out_stock: list[EquipmentType] = []
    seen: set[str] = set()
    for rn, rec in _records(sheets, STOCK_SHEET, STOCK_COLS):
        n += 1
        code = str(rec.get("code") or "").strip()
        if not code:
            err(STOCK_SHEET, rn, "קוד", "חסר קוד")
            continue
        if code in seen:
            err(STOCK_SHEET, rn, "קוד", f"הקוד {code} מופיע פעמיים")
            continue
        seen.add(code)
        cur = stock_by.get(code)
        data_ = cur.model_dump() if cur else {"code": code}
        if rec.get("name") is not None:
            data_["name"] = str(rec["name"])
        if rec.get("owned") is not None:
            q = _num(rec["owned"], "כמות", errors, STOCK_SHEET, rn, "כמות במלאי")
            if q is None:
                continue
            if q != int(q):
                err(STOCK_SHEET, rn, "כמות במלאי", "כמות שלמה בלבד")
                continue
            data_["owned"] = int(q)
        if rec.get("notes") is not None:
            data_["notes"] = str(rec["notes"])
        try:
            e = EquipmentType.model_validate(data_)
        except ValidationError as ex:
            first = ex.errors()[0]
            col = {"name": "שם", "code": "קוד"}.get(str(first["loc"][0]), "")
            err(STOCK_SHEET, rn, col, "ערך חסר או לא תקין")
            continue
        if cur is None:
            creates.append(Change(sku=code, name=e.name, action="create"))
            out_stock.append(e)
        elif (cur.name, cur.owned, cur.notes) != (e.name, e.owned, e.notes):
            updates.append(Change(sku=code, name=e.name, action="update",
                                  fields={"owned": [cur.owned, e.owned]}))
            out_stock.append(e)
        else:
            unchanged += 1
    return (ImportReport(rows=n, creates=creates, updates=updates, unchanged=unchanged,
                         errors=errors), out_staff, out_stock)


def _p(v):
    if isinstance(v, list):
        return [getattr(x, "value", x) for x in v]
    return v


def template_xlsx(staff: list[StaffMember], stock: list[EquipmentType]) -> bytes:
    wb = Workbook()
    bold, plain = Font(name="Arial", bold=True), Font(name="Arial")
    ws = wb.active
    ws.title = STAFF_SHEET
    ws.sheet_view.rightToLeft = True
    ws.append([v[0] for v in STAFF_COLS.values()])
    for m in staff:
        ws.append([m.name, m.phone, ", ".join(ROLE_OUT[r.value] for r in m.roles), m.hourly_rate,
                   ",".join(DAY_LETTER_OF[d] for d in sorted(m.available_days,
                                                             key=lambda d: (d + 1) % 7)),
                   "כן" if m.active else "לא", m.notes])
    if not staff:
        ws.append(["דוגמה: ישראל ישראלי", "050-0000000", "מלצר, ברמן", 50, "א,ב,ג,ד,ה", "כן", ""])
    st = wb.create_sheet(STOCK_SHEET)
    st.sheet_view.rightToLeft = True
    st.append([v[0] for v in STOCK_COLS.values()])
    for e in stock:
        st.append([e.code, e.name, e.owned, e.notes])
    lg = wb.create_sheet("הסבר")
    lg.sheet_view.rightToLeft = True
    for line in ["איך ממלאים",
                 "צוות: תפקידים מופרדים בפסיק (מלצר / מנהל אירוע / ברמן / שף). ימים זמינים "
                 "באותיות (א,ב,ג,ד,ה,ו,ש). אדם קיים מזוהה לפי טלפון, ואם אין לפי שם.",
                 "מלאי ציוד: קוד (אפשר מק\"ט הציוד מהתפריט, ואז ציוד בהצעה מתחבר למלאי לבד), "
                 "שם וכמות שיש לעסק.",
                 "אחרי ההעלאה מוצג דוח: מה יתווסף, מה ישתנה ואילו שורות נדחו ולמה."]:
        lg.append([line])
    for sheet in wb.worksheets:
        for row in sheet.iter_rows():
            for c in row:
                c.font = plain
    for sheet in (ws, st):
        for c in sheet[1]:
            c.font = bold
        for col in "ABCDEFG":
            sheet.column_dimensions[col].width = 18
    lg.column_dimensions["A"].width = 110
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


__all__ = ["ImportReport", "analyze", "template_xlsx"]

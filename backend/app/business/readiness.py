"""Is the event ready? One checklist per event, every item green or red, each red one with the
action that turns it green (stage 4). Computed, never stored: it always reflects the data.

Items: venue and on-site contact, site conditions, final guest count, the dishes, the balance,
staff assigned and confirmed, equipment. Staff and equipment are marked by the owner until
stage 5 computes them from the staff and equipment lists.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from app.business.messages import CustomerMessage
from app.business.settings import BusinessSettings
from app.crm.models import Deal
from app.repositories.quotes import StoredQuote
from app.schemas.catalog import CatalogItem
from app.schemas.extraction import ServiceStyle
from app.services.event_menu import owner_menu

SITE_HE = {"electricity": "חשמל", "kitchenette": "מטבחון", "fridge": "מקרר", "parking": "חניה"}
MANUAL = {"staff": "צוות משובץ ומאושר", "equipment": "ציוד הוכן ונבדק"}


class Action(BaseModel):
    kind: str                 # whatsapp | link | edit | mark | approve
    label: str
    url: str | None = None
    target: str | None = None  # edit: which field group; mark: which item


class ReadyItem(BaseModel):
    key: str
    label: str
    ok: bool
    detail: str = ""
    action: Action | None = None


class Readiness(BaseModel):
    deal_id: str
    items: list[ReadyItem]
    done: int
    total: int
    ready: bool
    days_left: int | None = None


def _msg(msgs: list[CustomerMessage], kind: str, label: str) -> Action | None:
    m = next((m for m in msgs if m.kind == kind), None)
    if m is None:
        return None
    return Action(kind="whatsapp" if m.whatsapp_url else "link", label=label,
                  url=m.whatsapp_url)


def readiness(deal: Deal, q: StoredQuote | None, catalog: list[CatalogItem],
              rules: BusinessSettings, msgs: list[CustomerMessage],
              today: date | None = None, staff=None, equipment=None) -> Readiness:
    """`staff` (StaffPlan) and `equipment` (EquipmentState) come from the team module; without
    them those two items fall back to the owner's manual marks."""
    today = today or date.today()
    items: list[ReadyItem] = []
    edit = Action(kind="edit", label="להשלים", target="site")

    # 1. venue and someone to call there
    miss = [n for n, v in (("כתובת", deal.location), ("איש קשר במקום", deal.site_contact_name),
                           ("טלפון במקום", deal.site_contact_phone)) if not v]
    items.append(ReadyItem(key="location", label="מקום ואיש קשר במקום", ok=not miss,
                           detail="חסר: " + ", ".join(miss) if miss else
                           f"{deal.location} · {deal.site_contact_name} {deal.site_contact_phone}",
                           action=None if not miss else edit))

    # 2. site conditions: every one answered (a "no" is fine, it's known)
    site = deal.site.model_dump()
    unknown = [SITE_HE[k] for k in SITE_HE if site[k] is None]
    without = [SITE_HE[k] for k in SITE_HE if site[k] is False]
    items.append(ReadyItem(
        key="site", label="תנאי שטח (חשמל, מטבחון, מקרר, חניה)", ok=not unknown,
        detail=("לא נבדק: " + ", ".join(unknown)) if unknown else
        ("אין במקום: " + ", ".join(without) if without else "הכל קיים"),
        action=edit if unknown else None))

    # 3. final guest count
    items.append(ReadyItem(
        key="final_count", label="כמות אורחים סופית", ok=deal.final_guest_count is not None,
        detail=f"{deal.final_guest_count} אורחים" if deal.final_guest_count is not None else
        f"לא אושר (כרגע {deal.guest_count or '?'})",
        action=None if deal.final_guest_count is not None else
        _msg(msgs, "final_count", "לבקש בוואטסאפ")))

    # 4. dishes: every slot the customer chooses in is chosen, and no dish lacks data
    if q is None:
        items.append(ReadyItem(key="menu", label="רכיבי תפריט", ok=False, detail="אין הצעה"))
    else:
        open_slots, problems = [], []
        for p in owner_menu(q, {i.sku: i for i in catalog}, rules, only_selected=True):
            chosen = q.menu_choices.get(p.sku, {})
            open_slots += [s.label_he for s in p.slots
                           if len(s.options) > s.choose and s.id not in chosen]
            problems += p.breakdown.missing
        ok = not open_slots and not problems
        detail = "נבחרו כל המנות" if ok else "; ".join(
            x for x in ("לא נבחרו: " + ", ".join(open_slots) if open_slots else "",
                        "חסרים נתונים: " + ", ".join(problems) if problems else "") if x)
        action = None
        if open_slots:
            action = _msg(msgs, "menu", "לבקש מהלקוח לבחור") or Action(
                kind="link", label="לבחור מנות", url=f"/quotes/{q.id}")
        elif problems:
            action = Action(kind="link", label="להשלים בתפריט", url="/menu")
        items.append(ReadyItem(key="menu", label="רכיבי תפריט", ok=ok, detail=detail,
                               action=action))

    # 5. balance
    total = deal.value or 0
    balance = round(max(total - deal.deposit_paid, 0), 2)
    items.append(ReadyItem(
        key="balance", label="יתרה לתשלום", ok=balance < 1,
        detail="שולם במלואו" if balance < 1 else f"נשארו ₪{balance:,.0f} מתוך ₪{total:,.0f}",
        action=None if balance < 1 else _msg(msgs, "balance", "תזכורת בוואטסאפ")))

    # 6–7. staff and equipment
    if staff is not None:
        items.append(ReadyItem(
            key="staff", label="צוות משובץ ומאושר", ok=staff.ok, detail=staff.summary,
            action=None if staff.ok else Action(kind="link", label="לשיבוץ",
                                                url=f"/deals/{deal.id}#staff")))
    if equipment is not None:
        has = bool(equipment.lines)
        ok = (not has) or (equipment.packed and not equipment.shortages)
        detail = ("אין ציוד לאירוע" if not has else
                  "; ".join(equipment.shortages) if equipment.shortages else
                  "הציוד נארז ונבדק" if equipment.packed else
                  f"{len(equipment.lines)} סוגי ציוד, עוד לא נארזו")
        items.append(ReadyItem(key="equipment", label="ציוד", ok=ok, detail=detail,
                               action=None if ok else Action(kind="link", label="לרשימת הציוד",
                                                            url=f"/deals/{deal.id}#equipment")))
    lines = q.tier().quote.lines if q else []
    by_sku = {i.sku: i for i in catalog}
    has_equipment = any(by_sku.get(ln.sku) and by_sku[ln.sku].category.value == "equipment"
                        for ln in lines)
    for key, label in MANUAL.items():
        if (key == "staff" and staff is not None) or (key == "equipment" and equipment is not None):
            continue
        if key == "equipment" and not has_equipment:
            items.append(ReadyItem(key=key, label="ציוד", ok=True, detail="אין ציוד בהזמנה"))
            continue
        done_at = deal.ready_marks.get(key)
        items.append(ReadyItem(key=key, label=label, ok=bool(done_at),
                               detail=f"סומן {done_at[:10]}" if done_at else "לא סומן",
                               action=None if done_at else
                               Action(kind="mark", label="סימון כבוצע", target=key)))

    done = sum(i.ok for i in items)
    return Readiness(deal_id=deal.id, items=items, done=done, total=len(items),
                     ready=done == len(items),
                     days_left=(deal.event_date - today).days if deal.event_date else None)


class ReadinessPatch(BaseModel):
    location: str | None = Field(None, max_length=200)
    site_contact_name: str | None = Field(None, max_length=80)
    site_contact_phone: str | None = Field(None, max_length=30)
    site: dict | None = None
    marks: dict[str, bool] | None = None   # {"staff": true, "equipment": false}
    service_style: ServiceStyle | None = None
    # stage 7: delivery is priced by zone (distance or place) and time window
    event_time: str | None = Field(None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    distance_km: float | None = Field(None, gt=0, le=1000)

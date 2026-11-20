"""Staff and equipment for events (stage 5): one place for what an event needs, who's on it,
what goes out and what came back, and what the month's staff cost.

Staff needed comes from the quote itself: the staff lines the pricing engine added (waiters by
the serving style's ratio, head waiter, bartender, on-site chef), each `quantity` hours =
people × `staff_hours`. Equipment going out starts from the quote's equipment lines, mapped to
stock by code, and the owner adds what else goes.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import date, timedelta

from pydantic import BaseModel, Field

from app.business.messages import whatsapp_url
from app.business.settings import BusinessSettings
from app.crm.models import Deal
from app.repositories.quotes import StoredQuote
from app.schemas.catalog import CatalogItem, ItemRole
from app.team.models import Assignment, EquipmentLine, EventEquipment, StaffMember
from app.team.service import TeamService

ROLE_HE = {"waiter": "מלצר", "head_waiter": "מנהל אירוע", "bartender": "ברמן", "chef": "שף"}
ROLE_HE_PL = {"waiter": "מלצרים", "head_waiter": "מנהלי אירוע", "bartender": "ברמנים",
              "chef": "שפים"}
WEEKDAY_HE = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]
RETURN_GRACE_DAYS = 1


# ------------------------------------------------------------------ staff needed

class RoleNeed(BaseModel):
    role: ItemRole
    label: str
    needed: int
    hours: float
    assigned: int = 0
    confirmed: int = 0
    declined: int = 0


class StaffPlan(BaseModel):
    needs: list[RoleNeed]
    assignments: list[dict] = Field(default_factory=list)  # Assignment + name, phone, invite
    ok: bool
    summary: str


def required_staff(q: StoredQuote | None, catalog: list[CatalogItem],
                   rules: BusinessSettings) -> dict[ItemRole, tuple[int, float]]:
    """role → (people, hours each), from the selected package's staff lines."""
    if q is None:
        return {}
    by_sku = {i.sku: i for i in catalog}
    out: dict[ItemRole, tuple[int, float]] = {}
    for ln in q.tier().quote.lines:
        it = by_sku.get(ln.sku)
        if not it or it.category.value != "staff" or it.role not in ROLE_HE:
            continue
        if it.unit.value == "hour":
            hours = float(rules.staff_hours)
            people = max(1, math.ceil(ln.quantity / hours - 1e-9))
        else:
            hours, people = float(rules.staff_hours), max(1, int(round(ln.quantity)))
        prev = out.get(it.role, (0, hours))
        out[it.role] = (prev[0] + people, hours)
    return out


def staff_plan(team: TeamService, deal: Deal, q: StoredQuote | None, catalog: list[CatalogItem],
               rules: BusinessSettings) -> StaffPlan:
    req = required_staff(q, catalog, rules)
    assigned = team.for_deal(deal.tenant_id, deal.id)
    members = {m.id: m for m in team.staff(deal.tenant_id)}
    needs = []
    for role, (n, hours) in req.items():
        mine = [a for a in assigned if a.role == role]
        needs.append(RoleNeed(role=role, label=ROLE_HE[role.value], needed=n, hours=hours,
                              assigned=sum(a.status != "declined" for a in mine),
                              confirmed=sum(a.status == "confirmed" for a in mine),
                              declined=sum(a.status == "declined" for a in mine)))
    missing = [f"{x.needed - x.assigned} {ROLE_HE_PL[x.role.value]}" for x in needs
               if x.assigned < x.needed]
    waiting = sum(x.assigned - x.confirmed for x in needs)
    ok = not missing and waiting == 0
    if not needs:
        summary = "אין צוות בהזמנה"
    elif ok:
        summary = f"{sum(x.needed for x in needs)} אנשי צוות שובצו ואישרו"
    else:
        summary = "; ".join(p for p in (
            ("חסרים: " + ", ".join(missing)) if missing else "",
            f"{waiting} עוד לא אישרו הגעה" if waiting else "") if p)
    rows = []
    for a in sorted(assigned, key=lambda a: (a.role.value, a.status)):
        m = members.get(a.member_id)
        rows.append({**a.model_dump(mode="json"), "name": m.name if m else "?",
                     "phone": m.phone if m else "",
                     "invite_url": invite_url(m, a, deal, rules) if m else None})
    return StaffPlan(needs=needs, assignments=rows, ok=ok, summary=summary)


def invite_text(m: StaffMember, a: Assignment, deal: Deal, rules: BusinessSettings) -> str:
    d = deal.event_date
    when = f"{WEEKDAY_HE[d.weekday()]} {d.day}.{d.month}" if d else "בתאריך שיתואם"
    where = f" ב{deal.location}" if deal.location else ""
    link = f"{rules.public_base_url.rstrip('/')}/s/{a.token}"
    return (f"היי {m.name.split()[0]}, שיבצנו אותך כ{ROLE_HE[a.role.value]} ביום {when}{where} "
            f"({deal.final_guest_count or deal.guest_count or '?'} אורחים, {a.planned_hours:g} "
            f"שעות). מגיע/ה? לאישור או ביטול: {link}\n{rules.business_name}")


def invite_url(m: StaffMember, a: Assignment, deal: Deal, rules: BusinessSettings) -> str | None:
    return whatsapp_url(m.phone, invite_text(m, a, deal, rules)) if m.phone else None


def busy_on(team: TeamService, crm, tenant: str, day: date, except_deal: str | None = None
            ) -> set[str]:
    """Members already on another event that day (not declined)."""
    deals = {d.id for d in crm.deals.list(tenant, lambda d: d.event_date == day
                                          and d.id != except_deal)}
    return {a.member_id for a in team.assignments.list(
        tenant, lambda a: a.deal_id in deals and a.status != "declined")}


def candidates(team: TeamService, crm, deal: Deal, role: ItemRole) -> list[StaffMember]:
    """Who can take this role that day: has the role, works that weekday, isn't blocked or
    on another event, isn't on this one already. Fewest shifts this month first (fair)."""
    if deal.event_date is None:
        return []
    tenant = deal.tenant_id
    busy = busy_on(team, crm, tenant, deal.event_date, deal.id)
    here = {a.member_id for a in team.for_deal(tenant, deal.id) if a.status != "declined"}
    month = {d.id for d in crm.deals.list(tenant, lambda d: d.event_date is not None and
                                          d.event_date.year == deal.event_date.year and
                                          d.event_date.month == deal.event_date.month)}
    load = Counter(a.member_id for a in team.assignments.list(
        tenant, lambda a: a.deal_id in month and a.status != "declined"))
    pool = [m for m in team.staff(tenant, active_only=True)
            if role in m.roles and m.free_on(deal.event_date) and m.id not in busy
            and m.id not in here]
    return sorted(pool, key=lambda m: (load[m.id], len(m.roles), m.name))


def auto_assign(team: TeamService, crm, deal: Deal, q: StoredQuote | None,
                catalog: list[CatalogItem], rules: BusinessSettings) -> list[Assignment]:
    """Fill every open place with the best candidate. Scarce roles first (chef, event
    manager, bartender, then waiters), so someone who can do both isn't used up as a waiter.
    Returns the new assignments."""
    new = []
    order = {ItemRole.chef: 0, ItemRole.head_waiter: 1, ItemRole.bartender: 2}
    needs = sorted(required_staff(q, catalog, rules).items(), key=lambda kv: order.get(kv[0], 9))
    for role, (n, hours) in needs:
        have = sum(a.role == role and a.status != "declined"
                   for a in team.for_deal(deal.tenant_id, deal.id))
        for m in candidates(team, crm, deal, role)[: max(0, n - have)]:
            new.append(team.assignments.put(Assignment(
                tenant_id=deal.tenant_id, deal_id=deal.id, member_id=m.id, role=role,
                planned_hours=hours, rate=m.hourly_rate)))
    return new


# ------------------------------------------------------------------ monthly pay

class PayRow(BaseModel):
    member_id: str
    name: str
    phone: str
    rate: float | None
    shifts: list[dict]          # {deal_id, title, date, role, hours, actual}
    hours: float
    planned_only: int           # shifts with no actual hours yet (planned hours used)
    total: float | None         # None when there's no hourly rate


def payroll(team: TeamService, crm, tenant: str, year: int, month: int) -> list[PayRow]:
    deals = {d.id: d for d in crm.deals.list(tenant, lambda d: d.event_date is not None and
                                             d.event_date.year == year and
                                             d.event_date.month == month)}
    by_member: dict[str, list[Assignment]] = defaultdict(list)
    for a in team.assignments.list(tenant, lambda a: a.deal_id in deals
                                   and a.status == "confirmed"):
        by_member[a.member_id].append(a)
    members = {m.id: m for m in team.staff(tenant)}
    rows = []
    for mid, shifts in by_member.items():
        m = members.get(mid)
        rate = shifts[0].rate if shifts[0].rate is not None else (m.hourly_rate if m else None)
        hours = sum(a.actual_hours if a.actual_hours is not None else a.planned_hours
                    for a in shifts)
        rows.append(PayRow(
            member_id=mid, name=m.name if m else "?", phone=m.phone if m else "", rate=rate,
            shifts=sorted(({"deal_id": a.deal_id, "title": deals[a.deal_id].title,
                            "date": deals[a.deal_id].event_date, "role": a.role.value,
                            "hours": a.actual_hours if a.actual_hours is not None
                            else a.planned_hours, "actual": a.actual_hours is not None}
                           for a in shifts), key=lambda x: x["date"]),
            hours=round(hours, 2), planned_only=sum(a.actual_hours is None for a in shifts),
            total=None if any((a.rate if a.rate is not None else rate) is None for a in shifts)
            else round(sum((a.actual_hours if a.actual_hours is not None else a.planned_hours)
                           * (a.rate if a.rate is not None else rate) for a in shifts), 2)))
    return sorted(rows, key=lambda r: r.name)


# ------------------------------------------------------------------ equipment

class EquipmentState(BaseModel):
    lines: list[dict]           # EquipmentLine + owned, short (same-day shortage), missing
    packed: bool
    returned: bool
    shortages: list[str]
    missing: list[str]          # after the event: what didn't come back
    from_quote: bool            # the list was started from the quote


def suggested_lines(q: StoredQuote | None, catalog: list[CatalogItem],
                    stock) -> list[EquipmentLine]:
    if q is None:
        return []
    by_sku = {i.sku: i for i in catalog}
    names = {e.code: e.name for e in stock}
    out = []
    for ln in q.tier().quote.lines:
        it = by_sku.get(ln.sku)
        if it and it.category.value == "equipment":
            out.append(EquipmentLine(code=ln.sku, name=names.get(ln.sku, ln.name_he),
                                     quantity=int(math.ceil(ln.quantity))))
    return out


def out_on(team: TeamService, crm, tenant: str, day: date) -> Counter:
    """How many of each type are out on events that day."""
    deals = {d.id for d in crm.deals.list(tenant, lambda d: d.event_date == day)}
    c: Counter = Counter()
    for ev in team.event_equipment.list(tenant, lambda e: e.deal_id in deals):
        for ln in ev.lines:
            c[ln.code] += ln.quantity
    return c


def equipment_state(team: TeamService, crm, deal: Deal, q: StoredQuote | None,
                    catalog: list[CatalogItem], today: date | None = None) -> EquipmentState:
    today = today or date.today()
    tenant = deal.tenant_id
    stock = {e.code: e for e in team.stock(tenant)}
    ev = team.event_list(tenant, deal.id)
    lines = ev.lines if ev else suggested_lines(q, catalog, stock.values())
    used = out_on(team, crm, tenant, deal.event_date) if deal.event_date else Counter()
    if ev is None:  # not saved yet: count the suggestion as going out too
        for ln in lines:
            used[ln.code] += ln.quantity
    rows, shortages, missing = [], [], []
    for ln in lines:
        e = stock.get(ln.code)
        short = (used[ln.code] - e.owned) if e else ln.quantity
        miss = (ln.quantity - ln.returned) if ln.returned is not None else None
        if short > 0:
            shortages.append(f"{ln.name}: חסרים {short}" + ("" if e else " (לא במלאי)"))
        if miss and miss > 0:
            missing.append(f"{ln.name}: {miss}")
        rows.append({**ln.model_dump(), "owned": e.owned if e else None,
                     "short": max(short, 0), "missing": max(miss or 0, 0)})
    after = bool(deal.event_date and today > deal.event_date + timedelta(days=RETURN_GRACE_DAYS))
    if after and ev and ev.lines and ev.returned_at is None:
        missing = missing or ["הציוד עוד לא נספר אחרי האירוע"]
    return EquipmentState(lines=rows, packed=bool(ev and ev.packed_at),
                          returned=bool(ev and ev.returned_at), shortages=shortages,
                          missing=missing, from_quote=ev is None)


def missing_returns(team: TeamService, crm, tenant: str, today: date | None = None
                    ) -> list[dict]:
    """Past events whose equipment didn't all come back (or wasn't counted)."""
    today = today or date.today()
    out = []
    for ev in team.event_equipment.list(tenant, lambda e: bool(e.lines)):
        d = crm.deals.get(tenant, ev.deal_id)
        if d is None or d.event_date is None or \
                today <= d.event_date + timedelta(days=RETURN_GRACE_DAYS):
            continue
        items = [{"code": ln.code, "name": ln.name, "out": ln.quantity,
                  "returned": ln.returned, "missing": ln.quantity - (ln.returned or 0)}
                 for ln in ev.lines if ln.returned is None or ln.returned < ln.quantity]
        if items:
            out.append({"deal_id": d.id, "title": d.title, "event_date": d.event_date,
                        "counted": ev.returned_at is not None, "items": items})
    return sorted(out, key=lambda x: x["event_date"])


def save_event_list(team: TeamService, deal: Deal, lines: list[EquipmentLine],
                    packed: bool | None = None, returned: bool | None = None) -> EventEquipment:
    from datetime import UTC, datetime
    ev = team.event_list(deal.tenant_id, deal.id) or EventEquipment(
        id=deal.id, tenant_id=deal.tenant_id, deal_id=deal.id)
    ev.lines = lines
    if packed is not None:
        ev.packed_at = datetime.now(UTC) if packed else None
    if returned is not None:
        ev.returned_at = datetime.now(UTC) if returned else None
    return team.put_event_list(ev)

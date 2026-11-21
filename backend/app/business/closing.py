"""Closing an event and learning from it (stage 6).

After the event the owner fills a short form (guests who came, how much of each dish was left,
what was actually spent, notes). From it:

* `report` compares planned with actual for one event: profit by cost group, quantities per
  guest, staff hours. The planned side comes from the same profit calculation as the reports
  (`kpis._event_profit`), so there is one number for "planned profit" everywhere.
* `learning` suggests new per-guest base amounts for each food category from the history. It
  never changes the settings: the owner applies a suggestion explicitly.

How a suggestion is made, for one category in one closed event:
    eaten per guest = planned per guest × planned guests / actual guests × consumption
where consumption is the share of what was made that was eaten, by the leftover mark
(settings.leftover_consumption: a lot left 0.75, reasonable 1.0 = the right amount, ran out
1.1). The suggestion is the median over the last `learning_window` events with marks, shown
only with at least `learning_min_events` events and a change of at least `learning_min_change`,
and only when the marks point the same way ("ran out" to increase, "a lot left" to decrease):
a change never comes from guest counts alone.
"""

from __future__ import annotations

import statistics
from datetime import date, datetime, timedelta

from pydantic import BaseModel, Field

from app.business.kpis import BOOKED_STAGES, _event_profit
from app.business.production import UNIT_HE, production
from app.business.settings import BusinessSettings
from app.crm.models import Deal, DishOutcome, EventClosing, now
from app.schemas.catalog import CatalogItem, Measure

LEFTOVER_HE = {"lot": "נשאר הרבה", "ok": "סביר", "out": "נגמר"}
CATEGORY_HE = {"salad": "סלטים", "side": "תוספות", "starter": "ראשונות", "main": "עיקריות",
               "canape": "קנאפה ופינגר פוד", "breakfast": "ארוחת בוקר", "dessert": "קינוחים",
               "drink": "שתייה", "bar": "בר"}
ROLE_HE = {"waiter": "מלצרים", "head_waiter": "מנהל אירוע", "bartender": "ברמנים",
           "chef": "שף"}


class PlannedDish(BaseModel):
    sku: str
    name: str
    category: str
    units: float | None          # what the kitchen made (catalog units)
    unit: str
    measure: str | None          # "g" | "unit"
    total_amount: float | None   # grams or pieces in total
    leftover: str | None = None


class GroupRow(BaseModel):
    group: str
    label: str
    planned: float | None
    actual: float | None
    source: str                  # where the actual number came from (Hebrew)


class DishRow(PlannedDish):
    per_guest_planned: float | None = None
    per_guest_actual: float | None = None   # what was made, per guest who came


class StaffRow(BaseModel):
    role: str
    label: str
    needed: int
    came: int | None             # None: nobody was scheduled in the system
    planned_hours: float
    actual_hours: float | None


class Report(BaseModel):
    closed: bool
    planned_guests: int | None
    actual_guests: int | None
    revenue: float
    planned_cost: float | None
    actual_cost: float | None
    planned_profit: float | None
    actual_profit: float | None
    planned_margin: float | None
    actual_margin: float | None
    groups: list[GroupRow]
    dishes: list[DishRow]
    staff: list[StaffRow]
    staff_cost_from_hours: float | None
    missing: list[str] = Field(default_factory=list)   # what's needed for a full comparison
    notes: str = ""


class ClosingView(BaseModel):
    closing: EventClosing | None
    planned_guests: int | None
    dishes: list[PlannedDish]
    planned_food_cost: float | None
    planned_staff_cost: float | None
    staff_cost_from_hours: float | None
    report: Report


class Suggestion(BaseModel):
    category: str
    label: str
    measure: str
    current: float
    suggested: float | None       # None: not enough data or no meaningful change
    change: float | None          # suggested / current - 1
    events: int                   # closed events with marks for this category
    needed: int
    marks: dict[str, int]         # lot/ok/out counts
    reason: str


class ClosedEvent(BaseModel):
    deal_id: str
    title: str
    event_date: date | None
    planned_guests: int | None
    actual_guests: int | None
    planned_profit: float | None
    actual_profit: float | None
    actual_margin: float | None


class LearningView(BaseModel):
    suggestions: list[Suggestion]
    events: list[ClosedEvent]
    to_close: list[dict]          # past events without a closing form


# ---------------------------------------------------------------- planned side

def planned_dishes(crm, repo, catalog, rules: BusinessSettings, d: Deal) -> list[PlannedDish]:
    """What the kitchen made for this event, one row per dish (same engine as the kitchen)."""
    if d.event_date is None:
        return []
    p = production(crm, repo, catalog, rules, d.tenant_id, d.event_date, d.event_date,
                   deal_id=d.id)
    rows: dict[str, PlannedDish] = {}
    for ln in p.lines:
        if ln.deal_id != d.id or ln.category in ("package",):
            continue
        r = rows.get(ln.sku)
        if r is None:
            rows[ln.sku] = PlannedDish(sku=ln.sku, name=ln.name_he, category=ln.category,
                                       units=ln.units, unit=UNIT_HE.get(ln.unit, ln.unit),
                                       measure=ln.measure,
                                       total_amount=ln.total_amount)
        else:  # the same dish from two packages: add up
            r.units = None if r.units is None or ln.units is None else r.units + ln.units
            r.total_amount = (None if r.total_amount is None or ln.total_amount is None
                              else round(r.total_amount + ln.total_amount, 1))
    return list(rows.values())


def staff_cost_from_hours(team, d: Deal) -> tuple[float | None, list]:
    """Confirmed shifts × hours (actual when entered, else planned) × rate. None when a rate
    is missing, so a partial sum is never shown as the cost."""
    if team is None:
        return None, []
    shifts = [a for a in team.for_deal(d.tenant_id, d.id) if a.status == "confirmed"]
    if not shifts:
        return None, shifts
    members = {m.id: m for m in team.staff(d.tenant_id)}
    total = 0.0
    for a in shifts:
        rate = a.rate if a.rate is not None else getattr(members.get(a.member_id), "hourly_rate",
                                                          None)
        if rate is None:
            return None, shifts
        total += rate * (a.actual_hours if a.actual_hours is not None else a.planned_hours)
    return round(total, 2), shifts


def _latest(repo, d: Deal):
    for qid in reversed(d.quote_ids):
        q = repo.get(d.tenant_id, qid)
        if q:
            return q
    return None


# ---------------------------------------------------------------- save

def save(d: Deal, body: EventClosing, rules: BusinessSettings, dishes: list[PlannedDish]
         ) -> EventClosing:
    """Store the form with the planned side snapshotted (guests and per-guest base amounts)."""
    known = {x.sku: x for x in dishes}
    out = body.model_copy(deep=True)
    out.dishes = [DishOutcome(sku=x.sku, name=x.name or getattr(known.get(x.sku), "name", ""),
                              category=x.category or getattr(known.get(x.sku), "category", ""),
                              leftover=x.leftover if x.leftover in LEFTOVER_HE else None)
                  for x in body.dishes]
    prev = d.closing
    out.planned_guests = (prev.planned_guests if prev and prev.planned_guests
                          else d.final_guest_count or d.guest_count)
    out.portion_snapshot = (prev.portion_snapshot if prev and prev.portion_snapshot else
                            {k: r.total_per_guest for k, r in rules.portion_rules.items()})
    out.closed_at = prev.closed_at if prev and prev.closed_at else now()
    return out


# ---------------------------------------------------------------- report

def report(d: Deal, q, catalog: list[CatalogItem], rules: BusinessSettings,
           dishes: list[PlannedDish], team=None) -> Report:
    by_sku = {i.sku: i for i in catalog}
    ep = _event_profit(d, q, rules, by_sku)
    c = d.closing
    planned_guests = (c.planned_guests if c and c.planned_guests else
                      d.final_guest_count or d.guest_count)
    actual_guests = c.actual_guests if c else None
    hours_cost, shifts = staff_cost_from_hours(team, d)
    missing: list[str] = []

    groups: list[GroupRow] = []
    for g in ep.groups:
        actual, source = g.cost, "כמתוכנן"
        if g.group == "food" and c and c.purchasing_cost is not None:
            actual, source = c.purchasing_cost, "רכש בפועל"
        elif g.group == "staff":
            if c and c.staff_cost is not None:
                actual, source = c.staff_cost, "תשלום בפועל"
            elif hours_cost is not None:
                actual, source = hours_cost, "לפי שעות הצוות"
        groups.append(GroupRow(group=g.group, label=g.label, planned=g.cost, actual=actual,
                               source=source))
    if c and c.other_cost:
        groups.append(GroupRow(group="other", label="הוצאות לא מתוכננות", planned=0,
                               actual=c.other_cost, source="הוזן"))
    if c is None:
        missing.append("טופס סיכום האירוע לא מולא")
    else:
        if c.actual_guests is None:
            missing.append("כמה אורחים הגיעו בפועל")
        if c.purchasing_cost is None:
            missing.append("עלות רכש בפועל (מוצגת העלות המתוכננת)")
        if c.staff_cost is None and hours_cost is None:
            missing.append("עלות צוות בפועל")
        if not any(x.leftover for x in c.dishes):
            missing.append("כמה נשאר מכל מנה")
    if ep.cost is None:
        missing.append("עלות מתוכננת: " + ", ".join(ep.missing) if ep.missing else
                       "עלות מתוכננת חסרה")

    actual_cost = (round(sum(g.actual for g in groups), 2)
                   if groups and all(g.actual is not None for g in groups) else None)
    actual_profit = round(ep.revenue - actual_cost, 2) if actual_cost is not None else None

    marks = {x.sku: x.leftover for x in (c.dishes if c else [])}
    rows = []
    def per(total: float | None, n: int | None) -> float | None:
        return round(total / n, 1) if total is not None and n else None
    for x in dishes:
        rows.append(DishRow(**x.model_dump(exclude={"leftover"}), leftover=marks.get(x.sku),
                            per_guest_planned=per(x.total_amount, planned_guests),
                            per_guest_actual=per(x.total_amount, actual_guests)))

    staff_rows: list[StaffRow] = []
    if team is not None and q is not None:
        from app.team.planning import required_staff  # late: team imports business
        req = required_staff(q, catalog, rules)
        for role, (n, hours) in req.items():
            mine = [a for a in shifts if a.role == role]
            entered = [a.actual_hours for a in mine if a.actual_hours is not None]
            staff_rows.append(StaffRow(
                role=role.value, label=ROLE_HE.get(role.value, role.value), needed=n,
                came=len(mine) if shifts else None, planned_hours=round(n * hours, 2),
                actual_hours=round(sum(entered), 2) if entered and len(entered) == len(mine)
                else None))

    def margin(p):
        return round(p / ep.revenue, 4) if p is not None and ep.revenue else None
    return Report(closed=c is not None, planned_guests=planned_guests,
                  actual_guests=actual_guests, revenue=ep.revenue, planned_cost=ep.cost,
                  actual_cost=actual_cost, planned_profit=ep.profit, actual_profit=actual_profit,
                  planned_margin=ep.margin, actual_margin=margin(actual_profit), groups=groups,
                  dishes=rows, staff=staff_rows, staff_cost_from_hours=hours_cost,
                  missing=missing, notes=c.notes if c else "")


def view(crm, repo, catalog, rules: BusinessSettings, d: Deal, team=None) -> ClosingView:
    q = _latest(repo, d)
    dishes = planned_dishes(crm, repo, catalog, rules, d)
    rep = report(d, q, catalog, rules, dishes, team)
    by_group = {g.group: g.planned for g in rep.groups}
    return ClosingView(closing=d.closing, planned_guests=rep.planned_guests, dishes=dishes,
                       planned_food_cost=by_group.get("food"),
                       planned_staff_cost=by_group.get("staff"),
                       staff_cost_from_hours=rep.staff_cost_from_hours, report=rep)


# ---------------------------------------------------------------- learning

def _round(v: float, measure: str) -> float:
    return round(v / 5) * 5 if measure == Measure.g.value else round(v * 20) / 20


def observations(deals: list[Deal], rules: BusinessSettings) -> dict[str, list[tuple]]:
    """category → [(eaten per guest, {lot, ok, out counts})], newest events first."""
    eat = rules.leftover_consumption
    out: dict[str, list[tuple]] = {}
    closed = sorted([d for d in deals if d.closing and d.closing.closed_at],
                    key=lambda d: d.event_date or date.min, reverse=True)
    for d in closed:
        c = d.closing
        ratio = (c.planned_guests / c.actual_guests
                 if c.planned_guests and c.actual_guests else 1.0)
        by_cat: dict[str, list[str]] = {}
        for x in c.dishes:
            if x.leftover in eat and x.category:
                by_cat.setdefault(x.category, []).append(x.leftover)
        for cat, ms in by_cat.items():
            base = c.portion_snapshot.get(cat)
            if not base:
                continue
            f = sum(eat[m] for m in ms) / len(ms)
            out.setdefault(cat, []).append(
                (base * ratio * f, {k: ms.count(k) for k in ("lot", "ok", "out")}))
    return out


def learning(crm, repo, catalog, rules: BusinessSettings, tenant: str,
             today: date | None = None, team=None) -> LearningView:
    deals = crm.deals.list(tenant)
    obs = observations(deals, rules)
    sug = []
    for cat, rule in rules.portion_rules.items():
        rows = obs.get(cat, [])[: rules.learning_window]
        marks = {k: sum(r[1][k] for r in rows) for k in ("lot", "ok", "out")}
        cur, m = rule.total_per_guest, rule.measure.value
        unit = "גרם" if m == Measure.g.value else "מנות"
        sug_val = change = None
        if len(rows) < rules.learning_min_events:
            reason = f"צריך עוד {rules.learning_min_events - len(rows)} אירועים סגורים עם סימון"
        else:
            sug_val = _round(statistics.median(r[0] for r in rows), m)
            change = round(sug_val / cur - 1, 4)
            agrees = marks["out"] > 0 if change > 0 else marks["lot"] > 0
            if abs(change) < rules.learning_min_change or sug_val <= 0 or not agrees:
                reason = f"הכמות הנוכחית מתאימה ל-{len(rows)} האירועים האחרונים"
                sug_val, change = None, None
            else:
                more = change > 0
                reason = (f"ב-{len(rows)} אירועים: {marks['out']} פעמים נגמר, "
                          f"{marks['lot']} פעמים נשאר הרבה. "
                          f"{'להגדיל' if more else 'להקטין'} ל-{sug_val:g} {unit} לסועד "
                          f"(בהתחשב בכמה אורחים הגיעו בפועל)")
        s = Suggestion(category=cat, label=CATEGORY_HE.get(cat, cat), measure=m, current=cur,
                       suggested=sug_val, change=change, events=len(rows),
                       needed=rules.learning_min_events, marks=marks, reason=reason)
        sug.append(s)
    sug.sort(key=lambda s: (s.suggested is None, -abs(s.change or 0), -s.events))

    today = today or datetime.now().date()
    events, to_close = [], []
    for d in sorted(deals, key=lambda d: d.event_date or date.min, reverse=True):
        if d.stage not in BOOKED_STAGES or not d.event_date or d.event_date >= today:
            continue
        if d.closing is None:
            if d.event_date >= today - timedelta(days=rules.closing_window_days):
                to_close.append({"deal_id": d.id, "title": d.title, "event_date": d.event_date})
            continue
        r = report(d, _latest(repo, d), catalog, rules, [], team)
        events.append(ClosedEvent(deal_id=d.id, title=d.title, event_date=d.event_date,
                                  planned_guests=r.planned_guests, actual_guests=r.actual_guests,
                                  planned_profit=r.planned_profit, actual_profit=r.actual_profit,
                                  actual_margin=r.actual_margin))
    return LearningView(suggestions=sug, events=events, to_close=to_close)

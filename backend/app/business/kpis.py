"""Every business number the screens show is computed here, once.

The definitions live in docs/KPIS.md; screens never add up deals themselves. Money KPIs are
before VAT: VAT isn't the business's money, and profit (stage 1) is only meaningful before VAT.
Day and month boundaries follow the business time zone (settings.timezone).
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from app.crm.models import OPEN_STAGES, Deal, DealStage, now

BOOKED_STAGES = (DealStage.won, DealStage.completed)


# ---------------------------------------------------------------- building blocks

def tz_of(rules) -> ZoneInfo:
    return ZoneInfo(getattr(rules, "timezone", None) or "Asia/Jerusalem")


def month_range(today: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    start = datetime.combine(today.replace(day=1), time.min, tzinfo=tz)
    nxt = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
    return start, datetime.combine(nxt, time.min, tzinfo=tz)


def net_value(d: Deal, vat_rate: float) -> float:
    """The deal's value before VAT. Older records without value_net derive it from the total."""
    if d.value_net is not None:
        return d.value_net
    return round((d.value or 0) / (1 + vat_rate), 2) if d.value else 0.0


def is_booked(d: Deal) -> bool:
    return d.stage in BOOKED_STAGES


def booked_in(deals: list[Deal], start: datetime, end: datetime) -> list[Deal]:
    """Booked (won) inside [start, end), by the moment of booking: an event that has since
    taken place still counts in the month it was booked."""
    return [d for d in deals if is_booked(d) and d.won_at and start <= d.won_at < end]


def total(deals: list[Deal], vat_rate: float) -> float:
    return round(sum(net_value(d, vat_rate) for d in deals), 2)


# ---------------------------------------------------------------- the KPI set

class StageKpi(BaseModel):
    stage: DealStage
    count: int
    value: float  # before VAT


class Kpis(BaseModel):
    """One object, one definition per number. 'היום', 'דוחות' and 'אירועים' all read it."""
    as_of: date
    vat_included: bool = False
    stages: list[StageKpi]
    open_pipeline_value: float
    quotes_waiting: int
    quotes_waiting_value: float
    booked_this_month_value: float
    booked_this_month_count: int
    deposits_this_month: float
    win_rate: float | None
    avg_booked_value: float | None
    hot_leads: int
    open_tasks: int
    overdue_tasks: int
    handed_off_chats: int
    escalated_chats: int
    chat_to_booked: float | None  # chats (not on a quote page) that became a booked event
    sources: dict[str, int]


def _chat_to_booked(convs, deals: dict) -> float | None:
    sales = [c for c in convs if not c.quote_id]  # service chats are already customers
    if not sales:
        return None
    won = sum(1 for c in sales if c.deal_id in deals and is_booked(deals[c.deal_id]))
    return round(won / len(sales), 3)


def compute(crm, tenant: str, rules, today: date | None = None) -> Kpis:
    tz = tz_of(rules)
    today = today or datetime.now(tz).date()
    vat = rules.vat_rate
    deals = crm.deals.list(tenant)
    by_stage = {s: [d for d in deals if d.stage == s] for s in DealStage}
    start, end = month_range(today, tz)
    booked_month = booked_in(deals, start, end)
    booked = [d for d in deals if is_booked(d)]
    decided = len(booked) + len(by_stage[DealStage.lost])
    payments = [p.amount for d in deals for p in d.payments
                if p.status == "paid" and p.paid_at and start <= p.paid_at < end]
    tasks = crm.tasks.list(tenant, lambda t: not t.done)
    convs = crm.conversations.list(tenant)
    quoted = by_stage[DealStage.quoted]
    return Kpis(
        as_of=today,
        stages=[StageKpi(stage=s, count=len(v), value=total(v, vat)) for s, v in by_stage.items()],
        open_pipeline_value=total([d for d in deals if d.stage in OPEN_STAGES], vat),
        quotes_waiting=len(quoted),
        quotes_waiting_value=total(quoted, vat),
        booked_this_month_value=total(booked_month, vat),
        booked_this_month_count=len(booked_month),
        deposits_this_month=round(sum(payments), 2),  # money received: actual amounts
        win_rate=round(len(booked) / decided, 3) if decided else None,
        avg_booked_value=round(total(booked, vat) / len(booked), 2) if booked else None,
        hot_leads=sum(1 for d in deals if d.stage in OPEN_STAGES and d.temperature == "hot"),
        open_tasks=len(tasks),
        overdue_tasks=sum(1 for t in tasks if t.due_at and t.due_at < now()),
        handed_off_chats=sum(1 for c in convs if c.status == "handed_off"),
        escalated_chats=sum(1 for c in convs if c.escalated and c.status != "closed"),
        chat_to_booked=_chat_to_booked(convs, {d.id: d for d in deals}),
        sources=dict(Counter(d.source.value for d in deals)),
    )


# ---------------------------------------------------------------- profit (owner-only)

class ProfitRow(BaseModel):
    key: str
    label: str
    events: int
    revenue: float  # before VAT, all booked events in the group
    profit: float | None  # gross profit of the events whose cost is complete
    margin: float | None  # profit / revenue of those same events
    missing_cost: int  # events left out of profit because a cost is unknown


class EventProfit(BaseModel):
    deal_id: str
    title: str
    event_date: date | None
    event_type: str | None
    package: str | None
    revenue: float
    cost: float | None
    profit: float | None
    margin: float | None
    missing: list[str]
    groups: list = Field(default_factory=list, exclude=True)  # GroupCost, for the closing report


class ProfitReport(BaseModel):
    floor: float
    by_month: list[ProfitRow]
    by_event_type: list[ProfitRow]
    by_package: list[ProfitRow]
    events: list[EventProfit]


def _event_profit(d: Deal, q, rules, by_sku: dict) -> EventProfit:
    from app.services.costing import fill_missing, missing_detail, summarize  # late import
    vat = rules.vat_rate
    priced = fill_missing(q.tier().quote, by_sku, rules, q.menu_choices) if q else None
    s = summarize(priced) if q else None
    pkg = None
    if q:
        pkg = next((ln.name_he for ln in q.tier().quote.lines
                    if ln.sku in by_sku and by_sku[ln.sku].category.value == "package"), None)
    rev = net_value(d, vat)
    return EventProfit(
        deal_id=d.id, title=d.title, event_date=d.event_date, event_type=d.event_type,
        package=pkg, revenue=rev, cost=s.total_cost if s else None,
        profit=s.gross_profit if s else None, margin=s.margin if s else None,
        missing=missing_detail(priced, by_sku, rules, q.menu_choices) if s else ["אין הצעת מחיר"],
        groups=s.by_group if s else [])


def _rows(events: list[EventProfit], key, label) -> list[ProfitRow]:
    groups: dict[str, list[EventProfit]] = {}
    for e in events:
        groups.setdefault(key(e), []).append(e)
    out = []
    for k, es in groups.items():
        known = [e for e in es if e.profit is not None]
        rev_known = sum(e.revenue for e in known)
        profit = round(sum(e.profit for e in known), 2) if known else None
        out.append(ProfitRow(key=k, label=label(k), events=len(es),
                             revenue=round(sum(e.revenue for e in es), 2), profit=profit,
                             margin=round(profit / rev_known, 4) if known and rev_known else None,
                             missing_cost=len(es) - len(known)))
    return out


EVENT_TYPE_HE = {"wedding": "חתונה", "bar_bat_mitzvah": "בר/בת מצווה", "brit": "ברית",
                 "birthday": "יום הולדת", "corporate": "אירוע חברה", "conference": "כנס",
                 "holiday": "חג", "private": "אירוע פרטי", "other": "אחר"}


def profit_report(crm, repo, catalog, tenant: str, rules, today: date | None = None,
                  months: int = 6) -> ProfitReport:
    """Revenue and gross profit of booked events (by booking month, event type, package)."""
    tz = tz_of(rules)
    today = today or datetime.now(tz).date()
    by_sku = {i.sku: i for i in catalog}
    quotes = {q.id: q for q in repo.list(tenant)}
    deals = [d for d in crm.deals.list(tenant) if is_booked(d) and d.won_at]
    events = []
    for d in deals:
        q = next((quotes[qid] for qid in reversed(d.quote_ids) if qid in quotes), None)
        e = _event_profit(d, q, rules, by_sku)
        e_month = d.won_at.astimezone(tz).strftime("%Y-%m")
        events.append((e_month, e))
    first = today.replace(day=1)
    keys = []
    for _ in range(months):
        keys.append(first.strftime("%Y-%m"))
        first = (first - timedelta(days=1)).replace(day=1)
    month_of = {id(e): m for m, e in events}
    in_range = [e for m, e in events if m in keys]
    by_month = {r.key: r for r in _rows(in_range, lambda e: month_of[id(e)], lambda k: k)}
    return ProfitReport(
        floor=rules.profit_floor,
        by_month=[by_month.get(k) or ProfitRow(key=k, label=k, events=0, revenue=0, profit=None,
                                                 margin=None, missing_cost=0)
                  for k in reversed(keys)],
        by_event_type=sorted(_rows(in_range, lambda e: e.event_type or "other",
                                   lambda k: EVENT_TYPE_HE.get(k, k)), key=lambda r: -r.revenue),
        by_package=sorted(_rows(in_range, lambda e: e.package or "ללא חבילה", lambda k: k),
                          key=lambda r: -r.revenue),
        events=sorted(in_range, key=lambda e: e.event_date or today, reverse=True),
    )

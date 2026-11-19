"""Every business number the screens show is computed here, once.

The definitions live in docs/KPIS.md; screens never add up deals themselves. Money KPIs are
before VAT: VAT isn't the business's money, and profit (stage 1) is only meaningful before VAT.
Day and month boundaries follow the business time zone (settings.timezone).
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from pydantic import BaseModel

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
    chat_conversion: float | None
    sources: dict[str, int]


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
        chat_conversion=(round(sum(1 for c in convs if c.deal_id) / len(convs), 3)
                         if convs else None),
        sources=dict(Counter(d.source.value for d in deals)),
    )

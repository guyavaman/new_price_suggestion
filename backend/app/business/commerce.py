"""Stage 7: returning customers and the sales picture.

* `history`: one customer's events with value and profit (profit from the same calculation as
  the reports), and whether a business customer is due for a "we haven't heard from you" call.
* `reorder_due`: business customers that booked before, have nothing open or upcoming, and
  haven't booked for `reorder_reminder_days`. The daily run turns them into tasks.
* `sales_report`: close rate and average profit by event type and by lead source, and chat →
  booked event. Close rate = booked / (booked + lost): open deals haven't been decided yet.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from pydantic import BaseModel

from app.business.kpis import BOOKED_STAGES, _event_profit, net_value, tz_of
from app.business.settings import BusinessSettings
from app.crm.models import OPEN_STAGES, Customer, Deal, DealStage, customer_kind
from app.integrations.canonical import EVENT_TYPE_HE

SOURCE_HE = {"web_chat": "צ'אט באתר", "whatsapp": "וואטסאפ", "email": "מייל", "phone": "טלפון",
             "referral": "המלצה", "manual": "ידני"}


class HistoryRow(BaseModel):
    deal_id: str
    title: str
    event_type: str | None
    event_date: date | None
    guests: int | None
    stage: str
    value_net: float
    profit: float | None


class CustomerHistory(BaseModel):
    customer_id: str
    kind: str                     # effective: private | business
    kind_set: bool                # chosen by the owner (else inferred from the company)
    events: list[HistoryRow]
    booked: int
    total_net: float              # booked events, before VAT
    avg_net: float | None
    last_event: date | None
    days_since_last: int | None
    reorder_due: bool
    reminded_at: datetime | None


def _last_booked(deals: list[Deal]) -> date | None:
    dates = [d.event_date for d in deals if d.stage in BOOKED_STAGES and d.event_date]
    return max(dates) if dates else None


def _due(c: Customer, deals: list[Deal], rules: BusinessSettings, today: date) -> bool:
    if customer_kind(c).value != "business":
        return False
    last = _last_booked(deals)
    if last is None or (today - last).days < rules.reorder_reminder_days:
        return False
    busy = any(d.stage in OPEN_STAGES or (d.stage in BOOKED_STAGES and d.event_date
                                          and d.event_date >= today) for d in deals)
    recent = (c.reorder_reminded_at is not None and
              (today - c.reorder_reminded_at.date()).days < rules.reorder_reminder_days)
    return not busy and not recent


def history(crm, repo, catalog, rules: BusinessSettings, c: Customer,
            today: date | None = None) -> CustomerHistory:
    today = today or datetime.now(tz_of(rules)).date()
    deals = crm.deals_for_customer(c.tenant_id, c.id)
    by_sku = {i.sku: i for i in catalog}
    quotes = {q.id: q for q in repo.list(c.tenant_id)}
    rows = []
    for d in sorted(deals, key=lambda d: d.event_date or date.min, reverse=True):
        profit = None
        if d.stage in BOOKED_STAGES:
            q = next((quotes[x] for x in reversed(d.quote_ids) if x in quotes), None)
            profit = _event_profit(d, q, rules, by_sku).profit
        rows.append(HistoryRow(deal_id=d.id, title=d.title, event_type=d.event_type,
                               event_date=d.event_date,
                               guests=d.final_guest_count or d.guest_count,
                               stage=d.stage.value, value_net=net_value(d, rules.vat_rate),
                               profit=profit))
    booked = [r for r in rows if r.stage in (s.value for s in BOOKED_STAGES)]
    total = round(sum(r.value_net for r in booked), 2)
    last = _last_booked(deals)
    return CustomerHistory(
        customer_id=c.id, kind=customer_kind(c).value, kind_set=c.kind is not None, events=rows,
        booked=len(booked), total_net=total,
        avg_net=round(total / len(booked), 2) if booked else None, last_event=last,
        days_since_last=(today - last).days if last else None,
        reorder_due=_due(c, deals, rules, today), reminded_at=c.reorder_reminded_at)


def reorder_due(crm, rules: BusinessSettings, tenant: str, today: date) -> list[Customer]:
    deals = crm.deals.list(tenant)
    by_c: dict[str, list[Deal]] = {}
    for d in deals:
        by_c.setdefault(d.customer_id, []).append(d)
    return [c for c in crm.customers.list(tenant) if _due(c, by_c.get(c.id, []), rules, today)]


# ---------------------------------------------------------------- sales report

class SalesRow(BaseModel):
    key: str
    label: str
    deals: int
    booked: int
    lost: int
    open: int
    close_rate: float | None       # booked / (booked + lost)
    avg_revenue: float | None      # booked, before VAT
    avg_profit: float | None       # booked events with a complete cost
    profit_events: int             # how many events the average profit is over


class SalesReport(BaseModel):
    since: date
    chats: int
    chats_booked: int
    chat_to_booked: float | None
    by_event_type: list[SalesRow]
    by_source: list[SalesRow]


def _rows(deals: list[Deal], key, label, profit_of, vat: float) -> list[SalesRow]:
    groups: dict[str, list[Deal]] = {}
    for d in deals:
        groups.setdefault(key(d), []).append(d)
    out = []
    for k, ds in groups.items():
        booked = [d for d in ds if d.stage in BOOKED_STAGES]
        lost = sum(d.stage == DealStage.lost for d in ds)
        profits = [p for p in (profit_of(d) for d in booked) if p is not None]
        out.append(SalesRow(
            key=k, label=label(k), deals=len(ds), booked=len(booked), lost=lost,
            open=sum(d.stage in OPEN_STAGES for d in ds),
            close_rate=round(len(booked) / (len(booked) + lost), 3) if booked or lost else None,
            avg_revenue=(round(sum(net_value(d, vat) for d in booked) / len(booked), 2)
                         if booked else None),
            avg_profit=round(sum(profits) / len(profits), 2) if profits else None,
            profit_events=len(profits)))
    return sorted(out, key=lambda r: (-r.deals, r.label))


def sales_report(crm, repo, catalog, tenant: str, rules: BusinessSettings,
                 today: date | None = None, months: int = 12) -> SalesReport:
    tz = tz_of(rules)
    today = today or datetime.now(tz).date()
    since = today - timedelta(days=round(months * 30.4))
    deals = [d for d in crm.deals.list(tenant) if d.created_at.astimezone(tz).date() >= since]
    by_sku = {i.sku: i for i in catalog}
    quotes = {q.id: q for q in repo.list(tenant)}

    def profit_of(d: Deal) -> float | None:
        q = next((quotes[x] for x in reversed(d.quote_ids) if x in quotes), None)
        return _event_profit(d, q, rules, by_sku).profit

    cached: dict[str, float | None] = {}

    def profit(d: Deal) -> float | None:
        if d.id not in cached:
            cached[d.id] = profit_of(d)
        return cached[d.id]

    convs = [c for c in crm.conversations.list(tenant)
             if c.created_at.astimezone(tz).date() >= since and not c.quote_id]
    by_id = {d.id: d for d in crm.deals.list(tenant)}
    booked_chats = sum(1 for c in convs if c.deal_id and c.deal_id in by_id
                       and by_id[c.deal_id].stage in BOOKED_STAGES)
    return SalesReport(
        since=since, chats=len(convs), chats_booked=booked_chats,
        chat_to_booked=round(booked_chats / len(convs), 3) if convs else None,
        by_event_type=_rows(deals, lambda d: d.event_type or "other",
                            lambda k: EVENT_TYPE_HE.get(k, k), profit, rules.vat_rate),
        by_source=_rows(deals, lambda d: d.source.value, lambda k: SOURCE_HE.get(k, k), profit,
                        rules.vat_rate))

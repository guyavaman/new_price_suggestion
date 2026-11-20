"""When an item's cost rises: which open quotes and booked events lose profit, and by how much.

Each quote line keeps the cost it was priced with (its snapshot). The impact of a change is
the difference between that snapshot and the cost the same line would have with today's
catalog, for every line that is the item or a package containing it.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel

from app.schemas.catalog import CatalogItem
from app.schemas.quote import QuoteStatus
from app.services.costing import line_context, unit_cost
from app.services.packages import resolve_choice


class ImpactRow(BaseModel):
    kind: str  # "open_quote" | "booked_event"
    quote_id: str
    quote_number: str
    deal_id: str | None
    title: str
    event_date: date | None
    profit_before: float
    profit_after: float
    margin_before: float | None
    margin_after: float | None
    delta: float  # profit change (negative = profit dropped)


def _uses(item: CatalogItem, sku: str, by_sku: dict[str, CatalogItem], choice) -> bool:
    """The line's item is `sku`, or a package whose chosen dishes include it."""
    if item.sku == sku:
        return True
    if item.category.value != "package":
        return False
    return any(sku in picked for picked in resolve_choice(item, choice).values())


def impact_of(sku: str, catalog: list[CatalogItem], quotes, deals, today: date,
              rules=None) -> list[ImpactRow]:
    """Profit change, snapshot → today's catalog, for open quotes and upcoming booked events
    whose selected tier uses `sku` (directly or inside a package)."""
    by_sku = {i.sku: i for i in catalog}
    deal_of = {qid: d for d in deals for qid in d.quote_ids}
    rows: list[ImpactRow] = []
    for q in quotes:
        deal = deal_of.get(q.id)
        if q.status in (QuoteStatus.draft, QuoteStatus.sent):
            kind = "open_quote"
        elif (q.status == QuoteStatus.approved and deal and deal.stage.value == "won"
              and (deal.event_date is None or deal.event_date >= today)):
            kind = "booked_event"
        else:
            continue
        pq = q.tier().quote
        before = after = 0.0
        touched = False
        for ln in pq.lines:
            item = by_sku.get(ln.sku)
            choice = (q.menu_choices or {}).get(ln.sku)
            if ln.unit_cost is None or item is None or not _uses(item, sku, by_sku, choice):
                continue
            now_cost = unit_cost(item, by_sku, line_context(ln, item, rules, q.menu_choices))
            if now_cost is None:
                continue
            touched = True
            before += ln.unit_cost * ln.quantity
            after += now_cost * ln.quantity
        if not touched or abs(after - before) < 0.005:
            continue
        base_cost = sum(ln.unit_cost * ln.quantity for ln in pq.lines if ln.unit_cost is not None)
        complete = all(ln.unit_cost is not None for ln in pq.lines)
        p_before = round(pq.net - base_cost, 2)
        p_after = round(pq.net - (base_cost - before + after), 2)
        rows.append(ImpactRow(
            kind=kind, quote_id=q.id, quote_number=q.number, deal_id=deal.id if deal else None,
            title=deal.title if deal else q.number, event_date=deal.event_date if deal else None,
            profit_before=p_before, profit_after=p_after,
            margin_before=round(p_before / pq.net, 4) if complete and pq.net else None,
            margin_after=round(p_after / pq.net, 4) if complete and pq.net else None,
            delta=round(p_after - p_before, 2)))
    return sorted(rows, key=lambda r: r.delta)

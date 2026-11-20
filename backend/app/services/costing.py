"""Cost and gross profit: the one place they are computed.

Rules
- Cost is per catalog unit, before VAT. `None` means unknown, and unknown is a normal state:
  a quote with any unknown cost has status "missing" and **no** profit figure (never a fake
  100% or 0%), plus the list of what's missing.
- A package's cost is computed from its dishes (packages.py); a typed-in package cost is ignored.
- Gross profit = revenue before VAT, after discount (quote.net) − direct costs.
- Quote lines carry a cost snapshot (`unit_cost`) taken when they were priced. Summaries use
  the snapshot; the cost-change alert compares it with today's catalog.
- Owner-only. Nothing here is ever sent to customers, the PDF, the public API or the agent.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.business.settings import BusinessSettings
from app.schemas.catalog import CatalogItem, CostGroup, PortionRule
from app.services.packages import breakdown

GROUP_HE = {"food": "אוכל ושתייה", "staff": "צוות", "equipment": "ציוד", "logistics": "לוגיסטיקה"}


def _r2(x: float) -> float:
    return round(x + 1e-9, 2)


class CostContext(BaseModel):
    """What a package's cost depends on: the business's portion rules, how many guests the
    package is for (trays round up) and which dishes were chosen."""
    rules: dict[str, PortionRule]
    guests: int
    choice: dict[str, list[str]] | None = None


def default_context(rules: BusinessSettings | None = None, guests: int | None = None,
                    choice: dict | None = None) -> CostContext:
    rules = rules or BusinessSettings(id="default", tenant_id="default")
    return CostContext(rules=rules.portion_rules, guests=guests or rules.reference_guests,
                       choice=choice)


def unit_cost(item: CatalogItem, by_sku: dict[str, CatalogItem],
              ctx: CostContext | None = None) -> float | None:
    """Cost of one catalog unit. A package's is its dishes' cost per guest (see packages.py)."""
    if item.category.value == "package":
        if not item.slots:
            return None
        ctx = ctx or default_context()
        return breakdown(item, by_sku, ctx.guests, ctx.rules, ctx.choice).cost_per_guest
    return item.cost


def missing_parts(item: CatalogItem, by_sku: dict[str, CatalogItem],
                  ctx: CostContext | None = None) -> list[str]:
    """What makes an item's cost unknown, as "<what>: <why>"."""
    if item.category.value == "package":
        if not item.slots:
            return [f"{item.name_he}: אין בחבילה מנות"]
        ctx = ctx or default_context()
        return breakdown(item, by_sku, ctx.guests, ctx.rules, ctx.choice).missing
    return [f"{item.name_he}: עלות חסרה"] if item.cost is None else []


def line_context(ln, item: CatalogItem, rules: BusinessSettings | None,
                 choices: dict | None) -> CostContext | None:
    """A quote line's package context: its own guest count and the event's chosen dishes."""
    if item.category.value != "package":
        return None
    guests = int(ln.quantity) if item.unit.value == "per_guest" and ln.quantity else None
    return default_context(rules, guests, (choices or {}).get(item.sku))


class GroupCost(BaseModel):
    group: str
    label: str
    revenue: float
    cost: float | None  # None when a line in the group has no cost


class CostSummary(BaseModel):
    status: str  # "complete" | "missing"
    revenue_net: float
    total_cost: float | None
    gross_profit: float | None
    margin: float | None  # gross_profit / revenue_net
    by_group: list[GroupCost]
    missing: list[dict] = Field(default_factory=list)  # [{sku, name}]
    below_floor: bool | None = None  # None when it can't be judged (missing cost)
    floor: float | None = None


def fill_missing(quote, by_sku: dict[str, CatalogItem], rules: BusinessSettings | None = None,
                 choices: dict | None = None):
    """A quote with every unknown line cost filled from the current menu.

    A line's cost is a snapshot from when the quote was priced, so later price changes don't
    rewrite history. A cost that was unknown then is different: once the owner enters it,
    the quote should use it instead of staying "missing" forever. Known costs are kept."""
    if all(ln.unit_cost is not None for ln in quote.lines):
        return quote
    lines = []
    for ln in quote.lines:
        if ln.unit_cost is None and ln.sku in by_sku:
            item = by_sku[ln.sku]
            cost = unit_cost(item, by_sku, line_context(ln, item, rules, choices))
            if cost is not None:
                ln = ln.model_copy(update={"unit_cost": cost})
        lines.append(ln)
    return quote.model_copy(update={"lines": lines})


def missing_detail(quote, by_sku: dict[str, CatalogItem], rules: BusinessSettings | None = None,
                   choices: dict | None = None) -> list[str]:
    """Exactly what's missing for a priced quote's cost: "<dish>: <why>", deepest level."""
    out: set[str] = set()
    for ln in quote.lines:
        if ln.unit_cost is not None:
            continue
        item = by_sku.get(ln.sku)
        if item is None:
            out.add(f"{ln.name_he}: לא קיים בתפריט")
            continue
        out.update(missing_parts(item, by_sku, line_context(ln, item, rules, choices))
                   or [f"{ln.name_he}: עלות חסרה"])
    return sorted(out)


def refresh_package_costs(quote, by_sku: dict[str, CatalogItem],
                          rules: BusinessSettings | None, choices: dict | None):
    """Re-snapshot package lines after the event's dishes changed (a deliberate change, so the
    new dishes' current costs apply). Other lines keep their snapshot."""
    lines = []
    for ln in quote.lines:
        item = by_sku.get(ln.sku)
        if item is not None and item.category.value == "package":
            ln = ln.model_copy(update={"unit_cost": unit_cost(
                item, by_sku, line_context(ln, item, rules, choices))})
        lines.append(ln)
    return quote.model_copy(update={"lines": lines})


def summarize(quote, floor: float | None = None) -> CostSummary:
    """Cost summary of a PricedQuote, from its lines' cost snapshot."""
    groups: dict[str, dict] = {g.value: {"revenue": 0.0, "cost": 0.0, "complete": True}
                               for g in CostGroup}
    missing = []
    for ln in quote.lines:
        g = groups.setdefault(ln.cost_group, {"revenue": 0.0, "cost": 0.0, "complete": True})
        g["revenue"] += ln.total
        if ln.unit_cost is None:
            g["complete"] = False
            missing.append({"sku": ln.sku, "name": ln.name_he})
        else:
            g["cost"] += ln.unit_cost * ln.quantity
    complete = not missing
    total_cost = _r2(sum(g["cost"] for g in groups.values())) if complete else None
    profit = _r2(quote.net - total_cost) if complete else None
    margin = round(profit / quote.net, 4) if complete and quote.net else None
    return CostSummary(
        status="complete" if complete else "missing",
        revenue_net=quote.net, total_cost=total_cost, gross_profit=profit, margin=margin,
        by_group=[GroupCost(group=k, label=GROUP_HE.get(k, k), revenue=_r2(v["revenue"]),
                            cost=_r2(v["cost"]) if v["complete"] else None)
                  for k, v in groups.items() if v["revenue"] or not v["complete"]],
        missing=missing,
        below_floor=(margin < floor) if (floor is not None and margin is not None) else None,
        floor=floor,
    )


def profit_check(quote, floor: float) -> tuple[bool, str]:
    """May this price be offered without the owner? (agent and send guard)"""
    s = summarize(quote, floor)
    if s.status == "missing":
        names = ", ".join(sorted({m["name"] for m in s.missing}))
        return False, f"עלות חסרה: {names}"
    if s.below_floor:
        return False, f"רווח גולמי {s.margin:.0%} מתחת לרצפה ({floor:.0%})"
    return True, ""

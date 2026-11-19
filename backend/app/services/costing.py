"""Cost and gross profit: the one place they are computed.

Rules
- Cost is per catalog unit, before VAT. `None` means unknown, and unknown is a normal state:
  a quote with any unknown cost has status "missing" and **no** profit figure (never a fake
  100% or 0%), plus the list of what's missing.
- A package's cost is computed from its components; a typed-in package cost is ignored.
- Gross profit = revenue before VAT, after discount (quote.net) − direct costs.
- Quote lines carry a cost snapshot (`unit_cost`) taken when they were priced. Summaries use
  the snapshot; the cost-change alert compares it with today's catalog.
- Owner-only. Nothing here is ever sent to customers, the PDF, the public API or the agent.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.catalog import CatalogItem, CostGroup

GROUP_HE = {"food": "אוכל ושתייה", "staff": "צוות", "equipment": "ציוד", "logistics": "לוגיסטיקה"}


def _r2(x: float) -> float:
    return round(x + 1e-9, 2)


def unit_cost(item: CatalogItem, by_sku: dict[str, CatalogItem],
              _seen: frozenset[str] = frozenset()) -> float | None:
    """Cost of one catalog unit. Packages: sum of component costs per guest."""
    if item.components:
        if item.sku in _seen:  # a package containing itself: refuse rather than loop
            return None
        total = 0.0
        for c in item.components:
            part = by_sku.get(c.sku)
            if part is None:
                return None
            pc = unit_cost(part, by_sku, _seen | {item.sku})
            if pc is None:
                return None
            total += pc * c.quantity / c.per_guests
        return _r2(total)
    if item.category.value == "package":
        return None  # a package without components has no computable cost
    return item.cost


def missing_parts(item: CatalogItem, by_sku: dict[str, CatalogItem]) -> list[str]:
    """Names of what makes an item's cost unknown (itself, or its components)."""
    if item.components:
        out = []
        for c in item.components:
            part = by_sku.get(c.sku)
            if part is None:
                out.append(f"{c.sku} (לא בקטלוג)")
            elif unit_cost(part, by_sku) is None:
                out.extend(missing_parts(part, by_sku) or [part.name_he])
        return out
    if item.category.value == "package":
        return [f"{item.name_he}: אין רכיבים"]
    return [item.name_he] if item.cost is None else []


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


def fill_missing(quote, by_sku: dict[str, CatalogItem]):
    """A quote with every unknown line cost filled from the current menu.

    A line's cost is a snapshot from when the quote was priced, so later price changes don't
    rewrite history. A cost that was unknown then is different: once the owner enters it,
    the quote should use it instead of staying "missing" forever. Known costs are kept."""
    if all(ln.unit_cost is not None for ln in quote.lines):
        return quote
    lines = []
    for ln in quote.lines:
        if ln.unit_cost is None and ln.sku in by_sku:
            cost = unit_cost(by_sku[ln.sku], by_sku)
            if cost is not None:
                ln = ln.model_copy(update={"unit_cost": cost})
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

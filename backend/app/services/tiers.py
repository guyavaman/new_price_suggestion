"""Good / better / best: three versions of the same quote, built by deterministic rules.

The AI's menu is the "recommended" tier. Basic and premium are derived from it with fixed
upgrade/downgrade maps, so the three prices are always consistent and explainable.
Lines the customer explicitly requested are never changed in any tier.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas.catalog import CatalogItem, DefaultUse
from app.schemas.extraction import ExtractedRequest
from app.schemas.quote import LineSource, MenuLine, MenuPlan, PricedQuote
from app.services.pricing import ALLOWED_MEAL, PricingEngine

# Upgrades, downgrades, what the basic tier drops and what premium adds all come from the
# business's catalog (upgrade_to, downgrade_to, basic_drop, default_use=premium_extra).

TIER_NAMES = {"basic": "בסיס", "recommended": "מומלץ", "premium": "פרימיום"}


@dataclass
class Tier:
    key: str
    name: str
    plan: MenuPlan
    changes: list[str]
    quote: PricedQuote | None = None


def _allowed(req: ExtractedRequest, item: CatalogItem) -> bool:
    return not req.meal_type or item.meal_type in ALLOWED_MEAL[req.meal_type]


def build_tiers(req: ExtractedRequest, plan: MenuPlan, catalog: list[CatalogItem],
                engine: PricingEngine) -> list[Tier]:
    by_sku = {i.sku: i for i in catalog}

    def swap(direction: str, line: MenuLine, changes: list[str]) -> MenuLine:
        new = getattr(by_sku[line.sku], direction)
        if (line.source == LineSource.requested or not new or new not in by_sku
                or not _allowed(req, by_sku[new])):
            return line
        changes.append(f"{by_sku[line.sku].name_he} ← {by_sku[new].name_he}")
        return line.model_copy(update={"sku": new, "reason": ""})

    # basic
    basic_changes: list[str] = []
    basic_lines = []
    for ln in plan.lines:
        item = by_sku.get(ln.sku)
        if (item and ln.source != LineSource.requested
                and item.basic_drop):
            basic_changes.append(f"בלי {item.name_he}")
            continue
        basic_lines.append(swap("downgrade_to", ln, basic_changes) if item else ln)

    # premium
    prem_changes: list[str] = []
    prem_lines = [swap("upgrade_to", ln, prem_changes) if ln.sku in by_sku else ln
                  for ln in plan.lines]
    present = {ln.sku for ln in prem_lines}
    extras = [i for i in catalog if DefaultUse.premium_extra in i.default_use]
    for sku in [i.sku for i in extras]:
        if sku not in present and _allowed(req, by_sku[sku]):
            prem_lines.append(MenuLine(sku=sku, source=LineSource.suggested,
                                       confidence="high", reason="תוספת בחבילת פרימיום"))
            prem_changes.append(f"+ {by_sku[sku].name_he}")

    tiers = [
        Tier("basic", TIER_NAMES["basic"],
             plan.model_copy(update={"lines": basic_lines}), basic_changes),
        Tier("recommended", TIER_NAMES["recommended"], plan, []),
        Tier("premium", TIER_NAMES["premium"],
             plan.model_copy(update={"lines": prem_lines}), prem_changes),
    ]
    for t in tiers:
        t.quote = engine.price(req, t.plan)
    return tiers

"""Good / better / best: three versions of the same quote, built by deterministic rules.

The AI's menu is the "recommended" tier. Basic and premium are derived from it with fixed
upgrade/downgrade maps, so the three prices are always consistent and explainable.
Lines the customer explicitly requested are never changed in any tier.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas.catalog import CatalogItem
from app.schemas.extraction import ExtractedRequest, MealType
from app.schemas.quote import LineSource, MenuLine, MenuPlan, PricedQuote
from app.services.pricing import ALLOWED_MEAL, PricingEngine

UPGRADES = {
    "PKG-MEAT-STD": "PKG-MEAT-PREM",
    "PKG-CORP-LUNCH": "PKG-MEAT-STD",
    "MAIN-SCHNITZEL": "MAIN-CHICK-PARG",
    "MAIN-CHICK-PARG": "MAIN-ENTRECOTE",
    "MAIN-CHICK-BREAST": "MAIN-ASADO",
    "BAR-BEER": "BAR-COCKTAIL",
    "EQP-DISP": "EQP-DISH-PREM",
    "MAIN-QUICHE": "MAIN-SALMON",
}
DOWNGRADES = {
    "PKG-MEAT-PREM": "PKG-MEAT-STD",
    "MAIN-ENTRECOTE": "MAIN-CHICK-PARG",
    "MAIN-ASADO": "MAIN-CHICK-PARG",
    "MAIN-DENIS": "MAIN-SALMON",
    "BAR-OPEN": "BAR-BEER",
    "BAR-COCKTAIL": "BAR-BEER",
    "EQP-DISH-PREM": "EQP-DISP",
    "CAN-SUSHI": "CAN-SUSHI-VEG",
}
# extras the premium tier adds (if compatible and not already there)
PREMIUM_EXTRAS = {
    MealType.meat: ["STR-CARPACCIO", "DES-PETIT-FOUR", "DRK-COFFEE"],
    MealType.dairy: ["STR-SALMON-CEV", "DES-PETIT-FOUR", "DRK-COFFEE"],
    MealType.pareve: ["STR-SOUP-PUMP", "DES-PETIT-FOUR", "DRK-COFFEE"],
}
# categories the basic tier drops when they were only AI suggestions
BASIC_DROPS = {"canape", "starter", "bar"}

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

    def swap(mapping: dict[str, str], line: MenuLine, changes: list[str]) -> MenuLine:
        new = mapping.get(line.sku)
        if line.source == LineSource.requested or not new or not _allowed(req, by_sku[new]):
            return line
        changes.append(f"{by_sku[line.sku].name_he} ← {by_sku[new].name_he}")
        return line.model_copy(update={"sku": new, "reason": ""})

    # basic
    basic_changes: list[str] = []
    basic_lines = []
    for ln in plan.lines:
        item = by_sku.get(ln.sku)
        if (item and ln.source != LineSource.requested
                and item.category.value in BASIC_DROPS):
            basic_changes.append(f"בלי {item.name_he}")
            continue
        basic_lines.append(swap(DOWNGRADES, ln, basic_changes) if item else ln)

    # premium
    prem_changes: list[str] = []
    prem_lines = [swap(UPGRADES, ln, prem_changes) if ln.sku in by_sku else ln
                  for ln in plan.lines]
    present = {ln.sku for ln in prem_lines}
    meal = req.meal_type or MealType.pareve
    for sku in PREMIUM_EXTRAS[meal]:
        if sku not in present and sku in by_sku and _allowed(req, by_sku[sku]):
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

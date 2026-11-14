"""Create and store a quote from a structured request. Shared by the API and the sales agent."""

from __future__ import annotations

from app.repositories.quotes import StatusChange, StoredQuote
from app.schemas.catalog import CatalogItem
from app.schemas.extraction import ExtractedRequest
from app.schemas.quote import MenuLine, MenuPlan, QuoteStatus, TierQuote
from app.services.pricing import PricingEngine
from app.services.tiers import build_tiers

# Fallback menu when no LLM planner is available (and for instant estimates).
STANDARD_PACKAGE = {"meat": "PKG-MEAT-STD", "dairy": "PKG-DAIRY-STD", "pareve": "PKG-VEGAN"}
RECEPTION = {"meat": "CAN-SKEWER-CHICK", "dairy": "CAN-MINI-QUICHE", "pareve": "CAN-VEG-SKEWER"}
DIETARY_PACKAGE = {"vegan": "PKG-VEGAN", "vegetarian": "PKG-VEGAN"}


def tiers_for(req: ExtractedRequest, plan: MenuPlan, catalog: list[CatalogItem],
              engine: PricingEngine) -> list[TierQuote]:
    return [TierQuote(key=t.key, name=t.name, changes=t.changes, plan=t.plan, quote=t.quote)
            for t in build_tiers(req, plan, catalog, engine)]


def standard_plan(req: ExtractedRequest) -> MenuPlan:
    """A sensible default menu: one package for the main group, one per dietary group."""
    guests = req.guest_count or 0
    lines: list[MenuLine] = []
    special = 0
    for d in req.dietary_requirements:
        sku = DIETARY_PACKAGE.get(d.tag.value)
        if sku and d.guest_count and req.meal_type != "pareve":
            lines.append(MenuLine(sku=sku, for_guests=d.guest_count, confidence="high",
                                  reason=f"עבור {d.guest_count} אורחים {d.tag.value}"))
            special += d.guest_count
    meal = req.meal_type.value if req.meal_type else "meat"
    main = STANDARD_PACKAGE.get(meal, "PKG-MEAT-STD")
    lines.insert(0, MenuLine(sku=main, for_guests=max(guests - special, 1) if guests else None,
                             confidence="high", reason="חבילה מלאה לאירוע"))
    lines.append(MenuLine(sku=RECEPTION.get(meal, "CAN-VEG-SKEWER"), confidence="medium",
                          reason="קבלת פנים"))
    lines.append(MenuLine(sku="DRK-SOFT", confidence="high", reason="שתייה לכל האורחים"))
    return MenuPlan(lines=lines)


def create_quote(repo, tenant_id: str, req: ExtractedRequest, plan: MenuPlan,
                 catalog: list[CatalogItem], engine: PricingEngine,
                 source_message: str = "") -> StoredQuote:
    return repo.add(StoredQuote(
        tenant_id=tenant_id, number=repo.next_number(tenant_id), source_message=source_message,
        request=req, plan=plan, tiers=tiers_for(req, plan, catalog, engine),
        history=[StatusChange(status=QuoteStatus.draft)],
    ))

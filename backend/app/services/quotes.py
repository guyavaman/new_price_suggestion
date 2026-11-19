"""Create and store a quote from a structured request. Shared by the API and the sales agent."""

from __future__ import annotations

from app.repositories.quotes import StatusChange, StoredQuote
from app.schemas.catalog import CatalogItem, DefaultUse
from app.schemas.extraction import ExtractedRequest, MealType
from app.schemas.quote import MenuLine, MenuPlan, QuoteStatus, TierQuote
from app.services.pricing import ALLOWED_MEAL, PricingEngine
from app.services.tiers import build_tiers

# Fallback menu when no LLM planner is available (and for instant estimates).


def tiers_for(req: ExtractedRequest, plan: MenuPlan, catalog: list[CatalogItem],
              engine: PricingEngine) -> list[TierQuote]:
    return [TierQuote(key=t.key, name=t.name, changes=t.changes, plan=t.plan, quote=t.quote)
            for t in build_tiers(req, plan, catalog, engine)]


def _pick(catalog: list[CatalogItem], use: DefaultUse, meal: str,
          tag: str | None = None) -> CatalogItem | None:
    """The catalog item marked for `use`, preferring the event's exact meal type, then any
    compatible one (pareve fits meat and dairy). Nothing here knows any item by name."""
    allowed = ALLOWED_MEAL.get(MealType(meal), {MealType(meal)})
    cands = [i for i in catalog if use in i.default_use and i.meal_type in allowed
             and (tag is None or tag in {t.value for t in i.tags} or i.meal_type == "pareve")]
    cands.sort(key=lambda i: (i.meal_type.value != meal, i.sku))
    return cands[0] if cands else None


def standard_plan(req: ExtractedRequest, catalog: list[CatalogItem]) -> MenuPlan:
    """A sensible default menu from the catalog's defaults: the main package, a package per
    dietary group, a reception item and drinks."""
    guests = req.guest_count or 0
    meal = req.meal_type.value if req.meal_type else "meat"
    lines: list[MenuLine] = []
    special = 0
    for d in req.dietary_requirements:
        pkg = _pick(catalog, DefaultUse.dietary_package, meal, d.tag.value)
        if pkg and d.guest_count and req.meal_type != "pareve":
            lines.append(MenuLine(sku=pkg.sku, for_guests=d.guest_count, confidence="high",
                                  reason=f"עבור {d.guest_count} אורחים {d.tag.value}"))
            special += d.guest_count
    main = _pick(catalog, DefaultUse.main_package, meal)
    if main:
        lines.insert(0, MenuLine(sku=main.sku,
                                 for_guests=max(guests - special, 1) if guests else None,
                                 confidence="high", reason="חבילה מלאה לאירוע"))
    for use, conf, reason in ((DefaultUse.reception, "medium", "קבלת פנים"),
                              (DefaultUse.drinks, "high", "שתייה לכל האורחים")):
        item = _pick(catalog, use, meal)
        if item:
            lines.append(MenuLine(sku=item.sku, confidence=conf, reason=reason))
    return MenuPlan(lines=lines)


def create_quote(repo, tenant_id: str, req: ExtractedRequest, plan: MenuPlan,
                 catalog: list[CatalogItem], engine: PricingEngine,
                 source_message: str = "") -> StoredQuote:
    return repo.add(StoredQuote(
        tenant_id=tenant_id, number=repo.next_number(tenant_id), source_message=source_message,
        request=req, plan=plan, tiers=tiers_for(req, plan, catalog, engine),
        history=[StatusChange(status=QuoteStatus.draft)],
    ))

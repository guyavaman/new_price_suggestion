from app.schemas.extraction import ExtractedRequest
from app.schemas.quote import MenuLine, MenuPlan
from app.services.tiers import build_tiers


def test_three_tiers_are_ordered_by_price(catalog, engine, bar_mitzvah_req, bar_mitzvah_plan):
    basic, rec, prem = build_tiers(bar_mitzvah_req, bar_mitzvah_plan, catalog, engine)
    assert [t.key for t in (basic, rec, prem)] == ["basic", "recommended", "premium"]
    assert basic.quote.total < rec.quote.total < prem.quote.total


def test_requested_lines_never_change(catalog, engine, bar_mitzvah_req, bar_mitzvah_plan):
    # BAR-OPEN was requested: basic must not downgrade it to beer
    basic, _, prem = build_tiers(bar_mitzvah_req, bar_mitzvah_plan, catalog, engine)
    assert "BAR-OPEN" in {ln.sku for ln in basic.plan.lines}
    assert "BAR-OPEN" in {ln.sku for ln in prem.plan.lines}


def test_basic_drops_suggested_extras_and_premium_upgrades(
        catalog, engine, bar_mitzvah_req, bar_mitzvah_plan):
    basic, _, prem = build_tiers(bar_mitzvah_req, bar_mitzvah_plan, catalog, engine)
    assert "CAN-SKEWER-CHICK" not in {ln.sku for ln in basic.plan.lines}
    prem_skus = {ln.sku for ln in prem.plan.lines}
    assert "PKG-MEAT-PREM" in prem_skus and "STR-CARPACCIO" in prem_skus
    assert prem.changes and basic.changes


def test_premium_extras_respect_meal_type(catalog, engine):
    req = ExtractedRequest(language="he", guest_count=40, meal_type="dairy", kashrut="kosher")
    plan = MenuPlan(lines=[MenuLine(sku="PKG-DAIRY-STD", for_guests=40)])
    *_, prem = build_tiers(req, plan, catalog, engine)
    assert "STR-CARPACCIO" not in {ln.sku for ln in prem.plan.lines}
    assert not [g for g in prem.quote.guards if "לא מתאים" in g]

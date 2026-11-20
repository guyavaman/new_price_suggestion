"""Stage 1: cost and gross profit. Test catalog built here, independent of the demo data."""

import pytest

from app.business.settings import BusinessSettings
from app.schemas.catalog import CatalogItem, DefaultUse, ItemRole, Measure, PortionRule, Slot
from app.schemas.extraction import ExtractedRequest
from app.schemas.quote import MenuLine, MenuPlan
from app.services.costing import (
    CostContext,
    fill_missing,
    missing_parts,
    profit_check,
    summarize,
    unit_cost,
)
from app.services.pricing import PricingEngine
from app.services.quotes import standard_plan


def item(sku, cat, price, cost=None, unit="per_guest", meal="pareve", **kw):
    return CatalogItem(sku=sku, name_he=sku.lower(), name_en=sku, category=cat, unit=unit,
                       price=price, meal_type=meal, cost=cost, **kw)


# the tests' own portion rules (not the business defaults): salads 200 g, one main per guest
RULES = BusinessSettings(id="t", tenant_id="t", portion_rules={
    "salad": PortionRule(measure=Measure.g, total_per_guest=200, extra_per_variety=0),
    "main": PortionRule(measure=Measure.unit, total_per_guest=1, extra_per_variety=0),
    "dessert": PortionRule(measure=Measure.unit, total_per_guest=1, extra_per_variety=0),
})
CTX = CostContext(rules=RULES.portion_rules, guests=100)


@pytest.fixture
def cat():
    return [
        item("A-SALAD", "salad", 60, cost=20, unit="tray", serves=10, yield_amount=2000),
        item("A-MAIN", "main", 50, cost=20, meal="meat", yield_amount=1),
        item("A-NOCOST", "dessert", 10, yield_amount=1),  # cost unknown
        item("A-PKG", "package", 100, meal="meat", default_use=[DefaultUse.main_package],
             slots=[Slot(id="salad", label_he="סלט", options=["A-SALAD"]),
                    Slot(id="main", label_he="עיקרית", options=["A-MAIN"])]),
        item("A-PKG-GAP", "package", 100, meal="meat",
             slots=[Slot(id="main", label_he="עיקרית", options=["A-MAIN"]),
                    Slot(id="dessert", label_he="קינוח", options=["A-NOCOST"])]),
        item("A-PKG-EMPTY", "package", 100, cost=1),  # typed-in cost, no dishes
        item("A-WAITER", "staff", 80, cost=50, unit="hour", role=ItemRole.waiter),
        item("A-DELIV", "logistics", 300, cost=200, unit="unit", role=ItemRole.delivery_center),
        item("A-DRINK", "drink", 10, cost=3, default_use=[DefaultUse.drinks]),
    ]


def by(cat):
    return {i.sku: i for i in cat}


def test_package_cost_comes_from_its_dishes(cat):
    b = by(cat)
    # 100 guests × 200 g = 10 trays of 2000 g × ₪20, plus 100 mains × ₪20 → ₪2,200 = ₪22/guest
    assert unit_cost(b["A-PKG"], b, CTX) == 22.0
    assert unit_cost(b["A-PKG-GAP"], b, CTX) is None
    assert missing_parts(b["A-PKG-GAP"], b, CTX) == ["a-nocost: עלות חסרה"]
    # a typed-in cost on a package without dishes is ignored: it can't be computed
    assert unit_cost(b["A-PKG-EMPTY"], b, CTX) is None


def test_package_inside_a_package_is_not_a_dish():
    loop = item("L", "package", 10, slots=[Slot(id="x", label_he="x", options=["L"])])
    assert unit_cost(loop, {"L": loop}, CTX) is None


def _quote(cat, lines, guests=100, waiters=True):
    req = ExtractedRequest(language="he", guest_count=guests, meal_type="meat",
                           service={"waiters": waiters})
    return PricingEngine(cat, rules=RULES).price(req, MenuPlan(lines=lines))


def test_quote_profit_and_breakdown(cat):
    q = _quote(cat, [MenuLine(sku="A-PKG", confidence="high")])
    s = summarize(q, floor=0.3)
    assert s.status == "complete"
    food = next(g for g in s.by_group if g.group == "food")
    staff = next(g for g in s.by_group if g.group == "staff")
    assert food.cost == 2200 and food.revenue == 10000
    assert staff.cost == 7 * 5 * 50  # 7 waiters (1 per 15) x 5 hours x ₪50
    assert s.total_cost == 2200 + 1750 + 200
    assert s.gross_profit == round(q.net - s.total_cost, 2)
    assert s.margin == round(s.gross_profit / q.net, 4) and s.below_floor is False


def test_missing_cost_means_no_profit_figure(cat):
    q = _quote(cat, [MenuLine(sku="A-PKG-GAP", confidence="high")])
    s = summarize(q, floor=0.3)
    assert s.status == "missing" and s.gross_profit is None and s.margin is None
    assert s.below_floor is None  # can't judge, so not "fine" either
    assert {m["sku"] for m in s.missing} == {"A-PKG-GAP"}
    ok, why = profit_check(q, 0.3)
    assert not ok and "עלות חסרה" in why


def test_below_floor(cat):
    pricey = [i if i.sku != "A-MAIN" else i.model_copy(update={"cost": 95}) for i in cat]
    q = _quote(pricey, [MenuLine(sku="A-PKG", confidence="high")])
    ok, why = profit_check(q, 0.3)
    assert not ok and "מתחת לרצפה" in why


def test_rules_use_roles_not_codes(cat):
    # rename every code: the rules still find the waiter and the delivery by role
    renamed = [i.model_copy(update={"sku": "X-" + i.sku}) for i in cat]
    for i in renamed:
        i.slots = [sl.model_copy(update={"options": ["X-" + o for o in sl.options]})
                   for sl in i.slots]
    q = _quote(renamed, [MenuLine(sku="X-A-PKG", confidence="high")])
    assert {"X-A-WAITER", "X-A-DELIV"} <= {ln.sku for ln in q.lines}
    # no item for a role: a clear guard, not a crash
    q2 = _quote([i for i in cat if i.role != ItemRole.waiter],
                [MenuLine(sku="A-PKG", confidence="high")])
    assert any("מלצר" in g for g in q2.guards)


def test_standard_plan_comes_from_catalog_defaults(cat):
    req = ExtractedRequest(language="he", guest_count=50, meal_type="meat")
    assert [ln.sku for ln in standard_plan(req, cat).lines] == ["A-PKG", "A-DRINK"]


def test_lines_snapshot_cost(cat):
    q = _quote(cat, [MenuLine(sku="A-PKG", confidence="high")])
    pkg = next(ln for ln in q.lines if ln.sku == "A-PKG")
    assert pkg.unit_cost == 22.0 and pkg.cost_group == "food"


def test_cost_entered_later_fills_a_missing_snapshot_but_not_a_known_one(cat):
    """Owner enters the missing cost after the quote was made: the quote stops being "missing".
    A cost that was known when the quote was priced stays as it was (history isn't rewritten)."""
    q = _quote(cat, [MenuLine(sku="A-PKG-GAP", confidence="high"),
                     MenuLine(sku="A-SALAD", confidence="high")])
    assert summarize(q).status == "missing"
    now = [i.model_copy(update={"cost": 4}) if i.sku == "A-NOCOST" else
           i.model_copy(update={"cost": 999}) if i.sku == "A-SALAD" else i for i in cat]
    filled = fill_missing(q, by(now), RULES)
    s = summarize(filled, floor=0.3)
    assert s.status == "complete" and s.margin is not None
    salad = next(ln for ln in filled.lines if ln.sku == "A-SALAD")
    assert salad.unit_cost == 20  # snapshot kept
    assert summarize(q).status == "missing"  # the stored quote itself is untouched

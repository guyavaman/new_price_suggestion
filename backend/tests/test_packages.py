"""Stage 2: packages as slots, portions with a variety factor, quantities and cost.
Test catalog and portion rules are built here, independent of the demo data and defaults."""

import pytest

from app.schemas.catalog import CatalogItem, Measure, PortionRule, Slot
from app.services.packages import (
    breakdown,
    choice_errors,
    customer_view,
    package_errors,
    resolve_choice,
)

RULES = {
    "salad": PortionRule(measure=Measure.g, total_per_guest=200, extra_per_variety=0.2),
    "main": PortionRule(measure=Measure.unit, total_per_guest=1, extra_per_variety=0.4),
    "side": PortionRule(measure=Measure.g, total_per_guest=150, extra_per_variety=0),
}


def item(sku, cat, cost=None, unit="tray", meal="pareve", y=None, **kw):
    return CatalogItem(sku=sku, name_he=f"מנה {sku}", name_en=sku, category=cat, unit=unit,
                       price=100, meal_type=meal, cost=cost, yield_amount=y, **kw)


@pytest.fixture
def by():
    salads = [item(f"S{i}", "salad", cost=10 + i, y=1000) for i in range(1, 9)]
    cat = salads + [
        item("M1", "main", cost=30, unit="per_guest", meal="meat", y=1),
        item("M2", "main", cost=40, unit="per_guest", meal="meat", y=1),
        item("DAIRY", "main", cost=30, unit="per_guest", meal="dairy", y=1),
        item("BREAD", "side", cost=2, unit="per_guest", y=50),
        item("NOYIELD", "salad", cost=10),
        item("NOCOST", "salad", y=1000),
        item("CAKE", "dessert", cost=50, unit="unit", y=12),  # no portion rule for desserts
        item("PKG", "package", meal="meat", unit="per_guest", slots=[
            Slot(id="salads", label_he="סלטים", choose=3, options=[f"S{i}" for i in range(1, 9)]),
            Slot(id="main", label_he="עיקרית", choose=1, options=["M1", "M2"]),
            Slot(id="bread", label_he="לחם", options=["BREAD"], per_guest=80,
                 customer_choice=False),
        ]),
    ]
    return {i.sku: i for i in cat}


def test_meat_package_for_180_guests_breaks_down_to_dishes_quantities_and_cost(by):
    """The stage acceptance criterion, on test data."""
    b = breakdown(by["PKG"], by, 180, RULES)
    rows = {r.sku: r for r in b.rows}
    assert list(rows) == ["S1", "S2", "S3", "M1", "BREAD"]  # defaults: first options
    # 3 salads: 200 g × (1 + 0.2 × 2) / 3 = 93.3 g each → 16,800 g → 17 trays of 1000 g
    assert rows["S1"].per_guest == 93.3 and rows["S1"].total_amount == 16800
    assert rows["S1"].units == 17 and rows["S1"].cost == 17 * 11
    # one main: a full portion each
    assert rows["M1"].per_guest == 1 and rows["M1"].units == 180 and rows["M1"].cost == 5400
    # bread: fixed 80 g per guest → 14,400 g ÷ 50 g = 288 units, and it isn't "variety"
    assert rows["BREAD"].units == 288 and rows["BREAD"].cost == 576
    assert b.status == "complete"
    assert b.total_cost == round(sum(r.cost for r in b.rows), 2)
    assert b.cost_per_guest == round(b.total_cost / 180, 2)


def test_more_dishes_of_a_category_means_less_of_each(by):
    pkg = by["PKG"].model_copy(update={"slots": [
        Slot(id="salads", label_he="סלטים", choose=8, options=[f"S{i}" for i in range(1, 9)])]})
    eight = breakdown(pkg, by, 100, RULES).rows[0].per_guest
    three = breakdown(by["PKG"], by, 100, RULES).rows[0].per_guest
    assert eight == round(200 * (1 + 0.2 * 7) / 8, 1) == 60.0
    assert eight < three
    # but the guest gets more salad in total when there's more choice
    assert eight * 8 > three * 3


def test_two_mains_share_the_portion(by):
    pkg = by["PKG"].model_copy(update={"slots": [
        Slot(id="main", label_he="עיקריות", choose=2, options=["M1", "M2"])]})
    rows = breakdown(pkg, by, 100, RULES).rows
    assert [r.per_guest for r in rows] == [0.7, 0.7]  # 1 × 1.4 / 2
    assert [r.units for r in rows] == [70, 70]


def test_trays_round_up(by):
    rows = breakdown(by["PKG"], by, 7, RULES).rows  # 7 × 93.3 g = 653 g → still one tray
    assert rows[0].units == 1


@pytest.mark.parametrize("sku,problem", [("NOYIELD", "חסרה תפוקה ליחידה"),
                                         ("NOCOST", "עלות חסרה"),
                                         ("CAKE", "אין כלל כמויות לקטגוריה")])
def test_missing_data_is_named_and_means_no_cost(by, sku, problem):
    pkg = by["PKG"].model_copy(update={"slots": [
        Slot(id="x", label_he="x", options=["S1"]), Slot(id="y", label_he="y", options=[sku])]})
    b = breakdown(pkg, by, 50, RULES)
    assert b.status == "missing" and b.total_cost is None and b.cost_per_guest is None
    assert b.missing == [f"מנה {sku}: {problem}"]
    assert b.rows[0].cost is not None  # the rest is still computed and shown


def test_choice_validation(by):
    pkg = by["PKG"]
    assert choice_errors(pkg, {"salads": ["S1", "S2", "S5"]}) == []
    assert "צריך לבחור 3" in choice_errors(pkg, {"salads": ["S1"]})[0]
    assert "פעמיים" in " ".join(choice_errors(pkg, {"salads": ["S1", "S1", "S2"]}))
    assert "אינה ברשימה" in choice_errors(pkg, {"main": ["DAIRY"]})[0]
    assert "בעל העסק" in choice_errors(pkg, {"bread": ["BREAD"]}, only_customer=True)[0]
    assert "אין בחבילה" in choice_errors(pkg, {"nope": ["S1"]})[0]
    # an invalid stored choice falls back to the slot's default instead of breaking the event
    assert resolve_choice(pkg, {"salads": ["S1"], "main": ["M2"]}) == {
        "salads": ["S1", "S2", "S3"], "main": ["M2"], "bread": ["BREAD"]}


def test_chosen_dishes_change_the_cost(by):
    cheap = breakdown(by["PKG"], by, 100, RULES).total_cost
    pricier = breakdown(by["PKG"], by, 100, RULES, {"main": ["M2"]}).total_cost
    assert pricier - cheap == 100 * (40 - 30)


def test_package_definition_errors(by):
    bad = by["PKG"].model_copy(update={"slots": [
        Slot(id="a", label_he="עיקרית", options=["DAIRY"]),            # dairy in a meat package
        Slot(id="b", label_he="סלטים", choose=3, options=["S1", "S2"]),  # 3 out of 2
        Slot(id="c", label_he="אחר", options=["GHOST", "PKG"]),          # unknown, a package
        Slot(id="a", label_he="כפול", options=["S1"]),                   # duplicate id
    ]})
    errs = " | ".join(package_errors(bad, by))
    for part in ("לא מתאים לחבילה", "יש רק 2", "GHOST לא קיים", "היא חבילה", "פעמיים"):
        assert part in errs
    assert package_errors(by["PKG"], by) == []


def test_customer_sees_dish_names_only(by):
    view = customer_view(by["PKG"], by, {"main": ["M2"]})
    dumped = str([v.model_dump() for v in view])
    for word in ("cost", "units", "per_guest", "yield", "price"):
        assert word not in dumped
    main = next(v for v in view if v.id == "main")
    assert main.chosen == ["M2"] and main.can_choose
    assert not next(v for v in view if v.id == "bread").can_choose

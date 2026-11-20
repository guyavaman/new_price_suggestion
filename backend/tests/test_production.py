"""Stage 3: kitchen sheet by kashrut, purchase list by supplier with order deadlines, prep
schedule. Test catalog, suppliers and events built here, independent of the demo data.
Dates: 22.11.2026 is a Sunday."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from app.business.production import (
    delivery_day,
    kitchen_day,
    order_deadline,
    prep_schedule,
    production,
    purchase_list,
)
from app.business.settings import BusinessSettings
from app.crm.models import Deal, DealStage
from app.purchasing.models import Ingredient, Supplier
from app.purchasing.recipes import recipe_cost, recipe_errors
from app.repositories.quotes import StoredQuote
from app.schemas.catalog import CatalogItem, Measure, PortionRule, RecipeLine, Slot
from app.schemas.extraction import ExtractedRequest
from app.schemas.quote import MenuLine, MenuPlan, TierQuote
from app.services.pricing import PricingEngine

T = "t"
TZ = ZoneInfo("Asia/Jerusalem")
SUN, WED = date(2026, 11, 22), date(2026, 11, 25)
RULES = BusinessSettings(id=T, tenant_id=T, delivery_buffer_days=1, portion_rules={
    "salad": PortionRule(measure=Measure.g, total_per_guest=200, extra_per_variety=0),
    "main": PortionRule(measure=Measure.unit, total_per_guest=1, extra_per_variety=0),
})


def dish(sku, cat, meal="pareve", unit="tray", y=None, recipe=None, **kw):
    return CatalogItem(sku=sku, name_he=f"מנה {sku}", name_en=sku, category=cat, unit=unit,
                       price=100, meal_type=meal, cost=1, yield_amount=y,
                       recipe=[RecipeLine(ingredient=k, quantity=v) for k, v in
                               (recipe or {}).items()], **kw)


def pkg(sku, meal, slots):
    return CatalogItem(sku=sku, name_he=f"חבילה {sku}", name_en=sku, category="package",
                       unit="per_guest", price=150, meal_type=meal,
                       slots=[Slot(id=f"s{i}", label_he="x", options=[o])
                              for i, o in enumerate(slots)])


CATALOG = [
    dish("SAL", "salad", y=1000, recipe={"TOM": 0.5, "SPICE": 0.01}, station="קר", prep_days=1),
    dish("MEAT", "main", "meat", "per_guest", y=1, recipe={"CHK": 0.25}, station="גריל"),
    dish("CHEESE", "main", "dairy", y=10, recipe={"CHS": 1}),
    dish("NOREC", "salad", y=1000),          # no recipe
    dish("NOYIELD", "salad", recipe={"TOM": 1}),  # no yield: no quantity
    pkg("PKG-M", "meat", ["SAL", "MEAT"]),
    pkg("PKG-D", "dairy", ["SAL", "CHEESE"]),
    pkg("PKG-P", "pareve", ["NOYIELD", "NOREC"]),
]
SUPPLIERS = [
    Supplier(code="VEG", name="ירקות", phone="050-1111111", lead_days=1,
             delivery_days=[6, 0, 1, 2, 3], order_cutoff="14:00"),          # Sun–Thu
    Supplier(code="BUTCH", name="קצב", phone="050-2222222", lead_days=2,
             delivery_days=[1], order_cutoff="12:00"),                       # Tuesday only
]
INGREDIENTS = [
    Ingredient(code="TOM", name_he="עגבניות", unit="kg", supplier="VEG", price=6),
    Ingredient(code="SPICE", name_he="תבלין", unit="kg", supplier="VEG"),  # no price
    Ingredient(code="CHK", name_he="עוף", unit="kg", kashrut="meat", supplier="BUTCH", price=40),
    Ingredient(code="CHS", name_he="גבינה", unit="kg", kashrut="dairy", price=30),  # no supplier
]


class _Deals:
    def __init__(self, deals):
        self.deals = deals

    def list(self, tenant, where=None):
        return [d for d in self.deals if where is None or where(d)]


class _Crm:
    def __init__(self, deals):
        self.deals = _Deals(deals)


class _Repo:
    def __init__(self):
        self.q = {}

    def get(self, tenant, qid):
        return self.q.get(qid)


def _event(repo, title, day, meal, guests, package):
    req = ExtractedRequest(language="he", guest_count=guests, event_date=day, meal_type=meal,
                           service={"waiters": False})
    plan = MenuPlan(lines=[MenuLine(sku=package, for_guests=guests)])
    pq = PricingEngine(CATALOG, rules=RULES).price(req, plan)
    q = StoredQuote(tenant_id=T, number=title, request=req, plan=plan,
                    tiers=[TierQuote(key="recommended", name="מומלץ", plan=plan, quote=pq)])
    repo.q[q.id] = q
    return Deal(tenant_id=T, customer_id="c", title=title, stage=DealStage.won, event_date=day,
                meal_type=meal, guest_count=guests, quote_ids=[q.id])


@pytest.fixture
def prod():
    repo = _Repo()
    deals = [_event(repo, "בר מצווה", SUN, "meat", 100, "PKG-M"),
             _event(repo, "ברית", SUN, "dairy", 30, "PKG-D"),
             _event(repo, "קידוש", WED, "pareve", 20, "PKG-P"),
             Deal(tenant_id=T, customer_id="c", title="בלי הצעה", stage=DealStage.won,
                  event_date=SUN, meal_type="meat", guest_count=10)]
    return production(_Crm(deals), repo, CATALOG, RULES, T, date(2026, 11, 20), WED)


def test_kitchen_day_is_dishes_split_by_kashrut_with_a_warning(prod):
    sheet = kitchen_day(prod, SUN)
    assert [s.kashrut for s in sheet.sections] == ["meat", "dairy"]
    meat = {g.station: {r.sku: r for r in g.rows} for g in sheet.sections[0].groups}
    dairy = {r.sku: r for g in sheet.sections[1].groups for r in g.rows}
    assert set(meat) == {"גריל", "קר"}
    # 100 guests × 200 g salad = 20 kg = 20 trays of 1 kg; the same salad for the dairy event
    # is a separate line (separate kitchen): 30 × 200 g = 6 trays
    assert meat["קר"]["SAL"].units == 20 and meat["קר"]["SAL"].total_amount == 20000
    assert meat["גריל"]["MEAT"].units == 100
    assert dairy["SAL"].units == 6 and dairy["CHEESE"].units == 3   # 30 portions ÷ 10
    assert "PKG-M" not in meat["קר"]                                   # no packages
    assert any("בשרי" in w and "חלבי" in w and "בר מצווה" in w and "ברית" in w
               for w in sheet.warnings)
    assert sheet.missing_quotes == ["בלי הצעה"]


def test_single_kashrut_day_has_no_warning(prod):
    assert kitchen_day(prod, WED).warnings == []


def test_delivery_day_and_order_deadline():
    veg, butch = SUPPLIERS
    # needed Saturday 21.11, 1 day buffer → Friday 20.11 isn't a VEG day → Thursday 19.11
    assert delivery_day(date(2026, 11, 21), veg, 1) == date(2026, 11, 19)
    assert order_deadline(date(2026, 11, 19), veg, TZ) == datetime(2026, 11, 18, 14, 0, tzinfo=TZ)
    # the butcher delivers only on Tuesdays
    assert delivery_day(SUN, butch, 1) == date(2026, 11, 17)


def test_purchase_list_by_supplier_with_order_by_dates(prod):
    pl = purchase_list(prod, CATALOG, INGREDIENTS, SUPPLIERS, RULES, date(2026, 11, 20), WED,
                       now=datetime(2026, 11, 16, 9, 0, tzinfo=TZ))
    by = {o.code: o for o in pl.suppliers}
    veg = by["VEG"].batches[0]
    items = {i.code: i for i in veg.items}
    # salad is made Saturday (1 day ahead), needs (20 + 6) trays × 0.5 kg tomatoes
    assert veg.deliver_on == date(2026, 11, 19) and items["TOM"].quantity == 13
    assert veg.order_by == datetime(2026, 11, 18, 14, 0, tzinfo=TZ) and not veg.late
    assert items["SPICE"].price is None and veg.total is None   # no price: no fake total
    assert "עגבניות: 13 ק\"ג" in veg.text and veg.whatsapp_url.startswith("https://wa.me/97250")
    meat = by["BUTCH"].batches[0]
    assert meat.deliver_on == date(2026, 11, 17) and meat.items[0].quantity == 25
    assert meat.total == 1000
    no_sup = by[None]
    assert no_sup.name == "בלי ספק" and no_sup.batches[0].order_by is None
    assert no_sup.batches[0].items[0].quantity == 3
    assert [m["name"] for m in pl.missing_recipes] == ["מנה NOREC"]
    assert [m["name"] for m in pl.missing_quantities] == ["מנה NOYIELD"]
    assert pl.missing_prices == ["תבלין"]
    # order the earliest deadline first; the no-supplier group last
    assert [o.code for o in pl.suppliers] == ["BUTCH", "VEG", None]


def test_deadline_in_the_past_is_late(prod):
    pl = purchase_list(prod, CATALOG, INGREDIENTS, SUPPLIERS, RULES, date(2026, 11, 20), WED,
                       now=datetime(2026, 11, 20, 9, 0, tzinfo=TZ))
    assert all(b.late for o in pl.suppliers if o.code for b in o.batches)


def test_prep_schedule(prod):
    days = {d.date: d.tasks for d in prep_schedule(prod, date(2026, 11, 20), SUN)}
    sat = {(t.sku, t.title) for t in days[date(2026, 11, 21)]}
    assert sat == {("SAL", "בר מצווה"), ("SAL", "ברית")}      # salads a day ahead
    assert {t.sku for t in days[SUN]} == {"MEAT", "CHEESE"}
    assert all(t.days_before == 1 for t in days[date(2026, 11, 21)])


def test_recipes_cost_and_kashrut():
    ing = {i.code: i for i in INGREDIENTS}
    assert recipe_cost(CATALOG[1], ing) == (10.0, [])           # 0.25 kg × ₪40
    assert recipe_cost(CATALOG[0], ing) == (None, ["תבלין: אין מחיר"])
    assert recipe_cost(CATALOG[3], ing) == (None, ["אין מתכון"])
    bad = dish("X", "main", "dairy", recipe={"CHK": 1, "GHOST": 1, "TOM": 1})
    errs = " | ".join(recipe_errors(bad, ing))
    assert "עוף (בשרי) לא יכול להיות במנה חלבי" in errs and "GHOST לא קיים" in errs

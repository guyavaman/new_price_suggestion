from app.schemas.extraction import ExtractedRequest
from app.schemas.quote import MenuLine, MenuPlan


def by_sku(quote):
    return {ln.sku: ln for ln in quote.lines}


def test_full_bar_mitzvah_quote(engine, bar_mitzvah_req, bar_mitzvah_plan):
    q = engine.price(bar_mitzvah_req, bar_mitzvah_plan)
    lines = by_sku(q)
    assert lines["PKG-MEAT-STD"].quantity == 112
    assert lines["PKG-VEGAN"].quantity == 8
    assert lines["CAN-SKEWER-CHICK"].quantity == 360  # 3 canapés per guest
    assert lines["STF-WAITER"].quantity == 8 * 5  # ceil(120/15) waiters × 5h
    assert "STF-HEAD-WAITER" in lines  # ≥ 80 guests
    assert "STF-BARTENDER" not in lines  # open bar already includes one
    assert "LOG-DELIVERY-C" in lines
    assert q.subtotal == 39850.0
    assert q.discount_rate == 0.05
    assert q.total == round((39850 - 1992.5) * 1.18, 2)
    assert q.guards == []


def test_same_input_same_output(engine, bar_mitzvah_req, bar_mitzvah_plan):
    assert engine.price(bar_mitzvah_req, bar_mitzvah_plan) == engine.price(
        bar_mitzvah_req, bar_mitzvah_plan
    )


def test_trays_round_up(engine):
    req = ExtractedRequest(language="he", guest_count=31, meal_type="pareve")
    q = engine.price(req, MenuPlan(lines=[MenuLine(sku="SAL-ISR")]))  # serves 15
    assert by_sku(q)["SAL-ISR"].quantity == 3


def test_explicit_quantity_wins(engine):
    req = ExtractedRequest(language="he", guest_count=25)
    q = engine.price(req, MenuPlan(lines=[MenuLine(sku="CAN-SUSHI", quantity=3,
                                                   source="requested")]))
    assert by_sku(q)["CAN-SUSHI"].quantity == 3


def test_minimum_order_enforced(engine):
    req = ExtractedRequest(language="he", guest_count=10, meal_type="dairy")
    q = engine.price(req, MenuPlan(lines=[MenuLine(sku="PKG-DAIRY-STD")]))  # min 30
    assert by_sku(q)["PKG-DAIRY-STD"].quantity == 30


def test_meat_item_blocked_at_dairy_event(engine):
    req = ExtractedRequest(language="he", guest_count=40, meal_type="dairy", kashrut="kosher")
    q = engine.price(req, MenuPlan(lines=[MenuLine(sku="MAIN-ENTRECOTE"),
                                          MenuLine(sku="MAIN-LASAGNA")]))
    assert "MAIN-ENTRECOTE" not in by_sku(q)
    assert any("לא מתאים" in g for g in q.guards)


def test_kosher_event_without_meal_type_never_mixes(engine):
    req = ExtractedRequest(language="he", guest_count=40, kashrut="kosher", meal_type=None)
    q = engine.price(req, MenuPlan(lines=[MenuLine(sku="MAIN-ENTRECOTE"),
                                          MenuLine(sku="DES-CHEESECAKE")]))
    skus = by_sku(q)
    assert "MAIN-ENTRECOTE" in skus and "DES-CHEESECAKE" not in skus


def test_unknown_sku_removed(engine):
    req = ExtractedRequest(language="he", guest_count=20)
    q = engine.price(req, MenuPlan(lines=[MenuLine(sku="FAKE-123")]))
    assert q.lines == []
    assert q.total == 0


def test_llm_cannot_add_staff_lines(engine):
    req = ExtractedRequest(language="he", guest_count=20, service={"waiters": False})
    q = engine.price(req, MenuPlan(lines=[MenuLine(sku="STF-WAITER", quantity=100)]))
    assert "STF-WAITER" not in by_sku(q)


def test_mehadrin_and_remote_delivery(engine):
    req = ExtractedRequest(language="he", guest_count=40, kashrut="mehadrin",
                           meal_type="meat", location="ירושלים")
    q = engine.price(req, MenuPlan(lines=[MenuLine(sku="PKG-CORP-LUNCH")]))
    lines = by_sku(q)
    assert lines["LOG-MEHADRIN"].quantity == 40
    assert "LOG-DELIVERY-F" in lines


def test_budget_check_per_guest(engine):
    req = ExtractedRequest(language="he", guest_count=50, meal_type="meat",
                           budget={"amount": 100, "scope": "per_guest"})
    q = engine.price(req, MenuPlan(lines=[MenuLine(sku="PKG-MEAT-PREM", for_guests=80)]))
    assert q.budget is not None and q.budget.ok is False


def test_suspicious_flag_surfaces_as_guard(engine):
    req = ExtractedRequest(language="he", guest_count=20, suspicious_instructions=True)
    q = engine.price(req, MenuPlan(lines=[MenuLine(sku="SAL-ISR")]))
    assert any("הוראה למערכת" in g for g in q.guards)

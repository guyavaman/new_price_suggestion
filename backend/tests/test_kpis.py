"""Stage 0: one definition per number. Test data here is built by hand, not taken from the seed."""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app import migrations
from app.business import kpis
from app.business.operations import today_view
from app.business.settings import SettingsService
from app.crm.models import Deal, DealStage, Payment
from app.crm.service import CrmService

T = "kpi-test"
TODAY = date(2026, 11, 19)
JLM = ZoneInfo("Asia/Jerusalem")


@pytest.fixture
def crm(tmp_path):
    return CrmService(tmp_path, SettingsService(tmp_path))


def _deal(crm, stage, total, net, won_at=None, **kw):
    c = crm.upsert_customer(T, name="x", phone="0501111111")
    return crm.deals.put(Deal(tenant_id=T, customer_id=c.id, title="", stage=stage, value=total,
                              value_net=net, won_at=won_at, **kw))


def test_booked_this_month_counts_by_booking_date_before_vat(crm):
    nov = datetime(2026, 11, 5, 12, tzinfo=UTC)
    _deal(crm, DealStage.won, 11800, 10000, won_at=nov)
    # booked in November, event already took place: still November's booking (the old bug)
    _deal(crm, DealStage.completed, 23600, 20000, won_at=nov)
    # booked in October, completed in November: not November's booking
    _deal(crm, DealStage.completed, 5900, 5000, won_at=datetime(2026, 10, 20, tzinfo=UTC))
    _deal(crm, DealStage.quoted, 4720, 4000)
    k = kpis.compute(crm, T, crm.settings.get(T), TODAY)
    assert (k.booked_this_month_count, k.booked_this_month_value) == (2, 30000)
    assert k.quotes_waiting_value == 4000 and k.open_pipeline_value == 4000
    assert k.win_rate == 1.0 and k.avg_booked_value == round(35000 / 3, 2)


def test_month_boundary_is_business_time(crm):
    # 31 Oct 23:30 UTC is already 1 Nov 01:30 in Jerusalem: a November booking
    _deal(crm, DealStage.won, 1180, 1000, won_at=datetime(2026, 10, 31, 23, 30, tzinfo=UTC))
    k = kpis.compute(crm, T, crm.settings.get(T), TODAY)
    assert k.booked_this_month_value == 1000


def test_deposits_this_month_are_actual_payments(crm):
    paid = Payment(amount=3000, status="paid", paid_at=datetime(2026, 11, 2, tzinfo=JLM))
    old = Payment(amount=999, status="paid", paid_at=datetime(2026, 10, 2, tzinfo=JLM))
    _deal(crm, DealStage.won, 11800, 10000, won_at=datetime(2026, 11, 2, tzinfo=UTC),
          payments=[paid, old])
    assert kpis.compute(crm, T, crm.settings.get(T), TODAY).deposits_this_month == 3000


def test_today_and_reports_show_the_same_numbers(crm):
    _deal(crm, DealStage.won, 11800, 10000, won_at=datetime(2026, 11, 5, tzinfo=UTC))
    _deal(crm, DealStage.completed, 23600, 20000, won_at=datetime(2026, 11, 6, tzinfo=UTC))
    _deal(crm, DealStage.quoted, 4720, 4000)
    a = today_view(crm, T, TODAY).kpis
    b = crm.dashboard(T, TODAY).kpis
    assert a == b


def test_won_at_is_set_once(crm):
    d = _deal(crm, DealStage.quoted, 1180, 1000)
    first = crm.move_stage(T, d.id, DealStage.won).won_at
    crm.move_stage(T, d.id, DealStage.completed)
    assert crm.deals.get(T, d.id).won_at == first


def test_migration_fills_won_at_and_net_value(tmp_path):
    crm = CrmService(tmp_path, SettingsService(tmp_path))
    c = crm.upsert_customer(T, name="x", phone="0502222222")
    legacy = crm.deals.put(Deal(tenant_id=T, customer_id=c.id, title="", value=11800,
                                stage=DealStage.completed))
    assert legacy.won_at is None and legacy.value_net is None
    assert migrations.run(tmp_path)[0] == "001_deal_won_at_and_net_value"
    d = crm.deals.get(T, legacy.id)
    assert d.value_net == 10000 and d.won_at is not None
    assert migrations.run(tmp_path) == []  # once only


def test_every_screen_reads_the_same_kpis(monkeypatch, tmp_path):
    """API level: /crm/today and /crm/dashboard return one identical KPI object."""
    from app import deps
    from app.main import app
    monkeypatch.delenv("OWNER_PASSWORD", raising=False)
    crm = CrmService(tmp_path, SettingsService(tmp_path))
    _deal(crm, DealStage.won, 11800, 10000, won_at=datetime.now(UTC))
    _deal(crm, DealStage.completed, 23600, 20000, won_at=datetime.now(UTC))
    from app.integrations.config import TenantConfig
    app.dependency_overrides[deps.get_crm] = lambda: crm
    app.dependency_overrides[deps.get_tenant_loader] = lambda: (
        lambda tid: TenantConfig(tenant_id=tid, name="t"))
    try:
        c = TestClient(app)
        h = {"X-Tenant-ID": T}
        today, reports = c.get("/crm/today", headers=h).json(), c.get("/crm/dashboard",
                                                                        headers=h).json()
        assert today["kpis"] == reports["kpis"]
        assert today["kpis"]["booked_this_month_value"] == 30000
    finally:
        app.dependency_overrides.clear()


def test_migration_fills_catalog_fields_without_overwriting(tmp_path):
    from app.catalog.service import CatalogService
    cs = CatalogService(tmp_path)
    cs.update("acme", "STF-WAITER", {"price": 99})  # materializes the tenant copy
    raw = migrations._read(tmp_path / "catalog.json")
    for it in raw.values():  # simulate a pre-stage-1 copy
        for f in ("role", "cost", "components"):
            it.pop(f, None)
    raw["acme:STF-WAITER"]["cost"] = 55  # the business's own value must survive
    migrations._write(tmp_path / "catalog.json", raw)
    migrations.run(tmp_path)
    w = cs.get("acme", "STF-WAITER")
    assert w.role == "waiter" and w.cost == 55 and w.price == 99
    assert cs.get("acme", "PKG-MEAT-STD").slots


def test_migration_turns_old_components_into_slots(tmp_path):
    """A package the business built itself in stage 1 keeps the same dishes as fixed slots."""
    from app.catalog.service import CatalogService
    cs = CatalogService(tmp_path)
    cs.update("acme", "STF-WAITER", {"price": 99})
    raw = migrations._read(tmp_path / "catalog.json")
    raw["acme:MY-PKG"] = {**raw["acme:PKG-MEAT-STD"], "id": "acme:MY-PKG", "sku": "MY-PKG",
                          "slots": [], "components": [
                              {"sku": "SAL-ISR", "quantity": 1, "per_guests": 10},
                              {"sku": "SAL-TABULE", "quantity": 1, "per_guests": 10},
                              {"sku": "MAIN-SCHNITZEL", "quantity": 1, "per_guests": 1}]}
    for it in raw.values():
        it.pop("yield_amount", None)
    migrations._write(tmp_path / "catalog.json", raw)
    migrations.run(tmp_path)
    mine = cs.get("acme", "MY-PKG")
    assert [(sl.id, sl.choose, sl.options) for sl in mine.slots] == [
        ("salad", 2, ["SAL-ISR", "SAL-TABULE"]), ("main", 1, ["MAIN-SCHNITZEL"])]
    assert mine.components == []
    assert cs.get("acme", "SAL-ISR").yield_amount == 2000  # filled from the base catalog


def test_profit_report_counts_only_complete_costs(tmp_path):
    """Revenue covers every booked event; profit only the ones with full cost data."""
    from app.business.kpis import profit_report
    from app.repositories.quotes import JsonQuoteRepository, StoredQuote
    from app.schemas.catalog import CatalogItem
    from app.schemas.extraction import ExtractedRequest
    from app.schemas.quote import (
        Confidence,
        LineSource,
        MenuPlan,
        PricedQuote,
        QuoteLine,
        TierQuote,
    )
    crm = CrmService(tmp_path, SettingsService(tmp_path))
    repo = JsonQuoteRepository(tmp_path / "quotes.json")
    pkg = CatalogItem(sku="P", name_he="חבילה", name_en="p", category="package",
                      unit="per_guest", price=100, meal_type="meat")

    def booked(net, unit_cost, etype):
        ln = QuoteLine(sku="P", name_he="חבילה", unit="per_guest", unit_price=100,
                       quantity=net / 100, total=net, source=LineSource.rule,
                       confidence=Confidence.rule, unit_cost=unit_cost)
        pq = PricedQuote(lines=[ln], subtotal=net, discount_rate=0, discount=0, net=net,
                         vat=0, total=net)
        q = repo.add(StoredQuote(tenant_id=T, number=repo.next_number(T), request=ExtractedRequest(
            language="he"), plan=MenuPlan(lines=[]), tiers=[TierQuote(
                key="recommended", name="מומלץ", plan=MenuPlan(lines=[]), quote=pq)]))
        return _deal(crm, DealStage.won, net * 1.18, net, won_at=datetime(2026, 11, 3, tzinfo=UTC),
                     quote_ids=[q.id], event_type=etype)

    booked(10000, 60, "wedding")    # cost 6000, profit 4000
    booked(5000, None, "wedding")   # cost unknown
    r = profit_report(crm, repo, [pkg], T, crm.settings.get(T), TODAY)
    nov = next(m for m in r.by_month if m.key == "2026-11")
    assert (nov.events, nov.revenue, nov.profit, nov.missing_cost) == (2, 15000, 4000, 1)
    assert nov.margin == 0.4  # 4000 / 10000: margin over the events that have a profit
    wed = r.by_event_type[0]
    assert wed.label == "חתונה" and wed.events == 2

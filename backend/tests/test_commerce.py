"""Stage 7: VAT by customer type, terms before the deposit, delivery by zone and time, returning
customers, intent-based lead score, and the sales report. Own test data, not the seed."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.agent.signals import chat_signals, intent_of
from app.business import commerce
from app.business.operations import run_automation
from app.business.settings import BusinessSettings, DeliveryWindow, DeliveryZone
from app.business.terms import terms_lines, terms_version
from app.crm.models import CustomerKind, Deal, DealStage, IntentSignals
from app.crm.scoring import score
from app.main import app
from app.schemas.extraction import ExtractedRequest
from app.schemas.quote import MenuLine, MenuPlan
from app.services.portal import PortalError
from app.services.pricing import PricingEngine, pick_zone, windows_for
from tests.test_business import TODAY, T, make_quote

RULES = BusinessSettings(id=T, tenant_id=T)


def _customer(env, deal):
    return env["crm"].customers.get(T, deal.customer_id)


# ---------------------------------------------------------------- VAT by customer type

def test_private_customer_sees_prices_with_vat(env):
    q, deal = make_quote(env)
    v = env["portal"].view(q.public_token)
    t = v.tiers[0]
    assert v.price_mode == "gross" and t.total == pytest.approx(t.net + t.vat)
    assert t.per_guest_net == pytest.approx(round(t.net / 100, 2))


def test_business_customer_sees_prices_before_vat(env):
    q, deal = make_quote(env)
    c = _customer(env, deal)
    c.company = "חברת אלפא בע\"מ"
    env["crm"].customers.put(c)
    assert env["portal"].view(q.public_token).price_mode == "net"
    c.kind = CustomerKind.private  # the owner's choice wins over the company name
    env["crm"].customers.put(c)
    assert env["portal"].view(q.public_token).price_mode == "gross"
    c.kind, c.company = CustomerKind.business, None
    env["crm"].customers.put(c)
    assert env["portal"].view(q.public_token).price_mode == "net"


def test_vat_rate_comes_from_settings(env, catalog):
    s = env["settings"].update(T, {"vat_rate": 0.17})
    req = ExtractedRequest(language="he", guest_count=50, meal_type="meat")
    p = PricingEngine(catalog, rules=s).price(req, MenuPlan(lines=[MenuLine(sku="PKG-MEAT-STD")]))
    assert p.vat == pytest.approx(round(p.net * 0.17, 2))


# ---------------------------------------------------------------- terms

def test_terms_follow_the_settings():
    r = RULES.model_copy(update={"cancellation_policy": [
        {"days_before": 60, "refund_rate": 1}, {"days_before": 0, "refund_rate": 0.25}],
        "guest_lock_days": 5, "late_guest_surcharge": 0.2, "terms_extra": ["  ", "חניה על הלקוח"]})
    r = BusinessSettings.model_validate(r.model_dump())
    lines = terms_lines(r)
    text = "\n".join(lines)
    assert "ביטול 60 ימים או יותר לפני האירוע: המקדמה מוחזרת במלואה." in text
    assert "ביטול בפחות מ-60 ימים לפני האירוע: מוחזרים 25% מהמקדמה." in text
    assert "עד 5 ימים לפני האירוע" in text and "20%" in text and lines[-1] == "חניה על הלקוח"
    assert terms_version(lines) != terms_version(terms_lines(RULES))


def test_deposit_needs_the_current_terms(env):
    env["settings"].update(T, {"require_terms": True})
    q, deal = make_quote(env)
    v = env["portal"].view(q.public_token)
    assert v.terms and v.terms_required and v.terms_accepted_at is None
    with pytest.raises(PortalError, match="תנאי ההזמנה"):
        env["portal"].accept(q.public_token, "recommended")
    with pytest.raises(PortalError):
        env["portal"].accept(q.public_token, "recommended", None, "old-version")
    r = env["portal"].accept(q.public_token, "recommended", None, v.terms_version, "מיכל לוי")
    assert r["checkout_url"]
    d = env["crm"].deals.get(T, deal.id)
    assert d.terms.version == v.terms_version and d.terms.lines == v.terms
    assert d.terms.name == "מיכל לוי" and d.terms.accepted_at <= datetime.now(UTC)
    assert env["portal"].view(q.public_token).terms_accepted_at is not None


def test_terms_change_means_accepting_again(env):
    env["settings"].update(T, {"require_terms": True})
    q, _ = make_quote(env)
    old = env["portal"].view(q.public_token).terms_version
    env["settings"].update(T, {"menu_lock_days": 10})
    with pytest.raises(PortalError):
        env["portal"].accept(q.public_token, "recommended", None, old)


# ---------------------------------------------------------------- delivery

ZONES = [DeliveryZone(id="near", name="קרוב", role="delivery_center", max_km=25, default=True),
         DeliveryZone(id="mid", name="בינוני", sku="LOG-DELIVERY-F", max_km=60),
         DeliveryZone(id="south", name="דרום", role="delivery_remote", keywords=["באר שבע"])]


def test_zone_by_distance_then_place_then_default():
    r = RULES.model_copy(update={"delivery_zones": ZONES})
    assert pick_zone(r, "רמת גן", 12)[0].id == "near"
    assert pick_zone(r, "רמת גן", 40)[0].id == "mid"
    assert pick_zone(r, None, 300)[0].id == "mid"           # beyond every band: the widest
    assert pick_zone(r, "באר שבע", None)[0].id == "south"
    assert pick_zone(r, "מקום לא מוכר", None)[0].id == "near"
    assert pick_zone(r.model_copy(update={"delivery_zones": []}), "x", None)[0] is None


def test_time_windows():
    r = RULES.model_copy(update={"delivery_windows": [
        DeliveryWindow(id="night", name="לילה", start="22:00", end="06:00", price=300),
        DeliveryWindow(id="fri", name="שישי", start="12:00", end="18:00", days=[5], price=150)]})
    friday = date(2026, 11, 27)
    assert friday.weekday() == 4
    assert [w.id for w in windows_for(r, friday, "23:30")] == ["night"]
    assert [w.id for w in windows_for(r, friday, "05:59")] == ["night"]
    assert [w.id for w in windows_for(r, friday, "13:00")] == ["fri"]
    assert windows_for(r, friday + timedelta(days=1), "13:00") == []
    assert windows_for(r, friday, None) == []              # time unknown: no surcharge guessed


def test_delivery_lines_in_the_quote(env, catalog):
    s = env["settings"].update(T, {"delivery_zones": [z.model_dump() for z in ZONES]})
    req = ExtractedRequest(language="he", guest_count=50, meal_type="meat", location="רמת גן",
                           distance_km=40, event_date=date(2026, 11, 27), event_time="06:30")
    p = PricingEngine(catalog, rules=s).price(req, MenuPlan(lines=[MenuLine(sku="PKG-MEAT-STD")]))
    by = {ln.sku: ln for ln in p.lines}
    assert "LOG-DELIVERY-F" in by and "בינוני" in by["LOG-DELIVERY-F"].note
    early = by["DLV-early"]
    assert early.total == 200 and early.unit_cost == 120 and early.cost_group == "logistics"
    s = env["settings"].update(T, {"delivery_zones": [
        {"id": "x", "name": "חסר", "sku": "NOPE", "default": True}]})
    p = PricingEngine(catalog, rules=s).price(req, MenuPlan(lines=[MenuLine(sku="PKG-MEAT-STD")]))
    assert any("אין פריט בקטלוג" in g for g in p.guards)


def test_old_settings_keep_their_remote_areas(env):
    raw = {"id": T, "tenant_id": T, "remote_areas": ["אילת", "ערבה"]}
    s = BusinessSettings.model_validate(raw)
    assert [z.id for z in s.delivery_zones] == ["center", "remote"]
    assert s.delivery_zones[1].keywords == ["אילת", "ערבה"]
    with pytest.raises(ValueError, match="ברירת מחדל"):
        env["settings"].update(T, {"delivery_zones": [
            {"id": "a", "name": "א", "role": "delivery_center"}]})


# ---------------------------------------------------------------- lead score

def test_intent_outweighs_details():
    d = Deal(tenant_id=T, customer_id="c", title="", event_date=TODAY + timedelta(days=20),
             guest_count=100, kashrut="kosher", meal_type="meat")
    details, _ = score(d, None, TODAY)
    d.signals = IntentSignals(quote_opens=3, pdf_views=1, asked_human=True, price_questions=2,
                              date_questions=1)
    d.quote_ids = ["q"]
    hot, why = score(d, None, TODAY)
    assert details == 35 and hot == 100 and any("נציג" in w for w in why)
    w = {"opened": 1}
    d2 = d.model_copy(update={"signals": IntentSignals(quote_opens=1)})
    assert score(d2, None, TODAY, weights=w) == (1, ["+1 פתח את ההצעה"])


def test_opening_the_quote_counts_but_not_for_the_owner(env):
    q, deal = make_quote(env)
    before = env["crm"].deals.get(T, deal.id).lead_score
    env["portal"].record_open(q.public_token, "link")
    env["portal"].record_open(q.public_token, "pdf")
    env["portal"].record_open(q.public_token, "owner")
    d = env["crm"].deals.get(T, deal.id)
    assert d.signals.quote_opens == 1 and d.signals.pdf_views == 1
    assert d.lead_score == before + 15 + 5


def test_chat_intent_detection():
    assert intent_of("כמה זה עולה לאורח?") == (True, False, False)
    assert intent_of("אתם פנויים ב-12.3?") == (False, True, False)
    assert intent_of("אפשר לדבר עם נציג?") == (False, False, True)
    assert intent_of("תודה רבה") == (False, False, False)
    s = chat_signals(["מה המחיר?", "ותאריך 5.6 פנוי?", "מה המחיר לאורח"], handed_off=False)
    assert s == {"price_questions": 2, "date_questions": 1, "asked_human": False}
    assert chat_signals([], handed_off=True)["asked_human"]


# ---------------------------------------------------------------- returning customers

def _booked_past(env, days_ago: int, company: str | None = "גמא בע\"מ"):
    q, deal = make_quote(env, days=10)
    d = env["crm"].deals.get(T, deal.id)
    d.event_date, d.stage = TODAY - timedelta(days=days_ago), DealStage.completed
    env["crm"].save_deal(d)
    c = _customer(env, d)
    c.company = company
    env["crm"].customers.put(c)
    return env["crm"].deals.get(T, d.id), c


def test_history_and_totals(env):
    d, c = _booked_past(env, 120)
    h = commerce.history(env["crm"], env["repo"], env["catalog"].all(T),
                         env["settings"].get(T), c, TODAY)
    assert h.kind == "business" and not h.kind_set and h.booked == 1
    assert h.total_net == pytest.approx(d.value_net) and h.days_since_last == 120
    assert h.events[0].profit is not None and h.reorder_due


def test_reorder_reminder_rules(env):
    rules = env["settings"].get(T)
    d, c = _booked_past(env, 120)
    assert [x.id for x in commerce.reorder_due(env["crm"], rules, T, TODAY)] == [c.id]
    acts = run_automation(env["crm"], env["repo"], rules, T, TODAY)
    assert any(a.rule == "reorder" for a in acts)
    tasks = [t for t in env["crm"].tasks.list(T) if t.kind == "reorder"]
    assert len(tasks) == 1 and "גמא" in tasks[0].title and "120" in tasks[0].title
    run_automation(env["crm"], env["repo"], rules, T, TODAY)   # once per period
    assert len([t for t in env["crm"].tasks.list(T) if t.kind == "reorder"]) == 1
    later = TODAY + timedelta(days=rules.reorder_reminder_days)
    assert commerce.reorder_due(env["crm"], rules, T, later)    # and again after a period


def test_no_reorder_reminder_for_private_recent_or_busy(env):
    rules = env["settings"].get(T)
    _booked_past(env, 120, company=None)                        # private
    assert commerce.reorder_due(env["crm"], rules, T, TODAY) == []
    d, c = _booked_past(env, 30)                                # booked recently
    assert commerce.reorder_due(env["crm"], rules, T, TODAY) == []
    d.event_date = TODAY - timedelta(days=200)
    env["crm"].save_deal(d)
    assert commerce.reorder_due(env["crm"], rules, T, TODAY)
    q2, d2 = make_quote(env)                                    # an open quote for them
    d2.customer_id = c.id
    env["crm"].save_deal(d2)
    assert commerce.reorder_due(env["crm"], rules, T, TODAY) == []


# ---------------------------------------------------------------- sales report

def test_sales_report_close_rate_and_profit(env):
    rules = env["settings"].get(T)
    booked, _ = _booked_past(env, 5)
    q, lost = make_quote(env)
    env["crm"].move_stage(T, lost.id, DealStage.lost, reason="מחיר")
    q, still_open = make_quote(env)
    r = commerce.sales_report(env["crm"], env["repo"], env["catalog"].all(T), T, rules, TODAY)
    row = next(x for x in r.by_event_type if x.key == "bar_bat_mitzvah")
    assert (row.deals, row.booked, row.lost, row.open) == (3, 1, 1, 1)
    assert row.close_rate == 0.5 and row.avg_profit is not None and row.profit_events == 1
    assert row.avg_revenue == pytest.approx(booked.value_net)
    assert {x.key for x in r.by_source} and r.chat_to_booked is None   # no chats yet


def test_api_customer_kind_history_and_reports(env):
    from app import deps
    app.dependency_overrides.update({
        deps.get_crm: lambda: env["crm"], deps.get_repo: lambda: env["repo"],
        deps.get_settings_service: lambda: env["settings"],
        deps.get_catalog_service: lambda: env["catalog"],
        deps.get_tenant_loader: lambda: (lambda tid: env["tenant"])})
    c, h = TestClient(app), {"X-Tenant-ID": T}
    try:
        q, deal = make_quote(env)
        cid = deal.customer_id
        r = c.patch(f"/crm/customers/{cid}", headers=h, json={"kind": "business"})
        assert r.status_code == 200 and r.json()["kind"] == "business"
        assert env["portal"].view(q.public_token).price_mode == "net"
        assert c.patch(f"/crm/customers/{cid}", headers=h,
                       json={"clear_kind": True}).json()["kind"] is None
        assert c.patch(f"/crm/customers/{cid}", headers=h,
                       json={"kind": "vip"}).status_code == 422
        hist = c.get(f"/crm/customers/{cid}/history", headers=h).json()
        assert hist["kind"] == "private" and len(hist["events"]) == 1
        assert c.get("/reports/sales", headers=h).json()["by_event_type"]
        k = c.get("/crm/dashboard", headers=h)
        assert k.status_code == 200 and "chat_to_booked" in k.json()["kpis"]
        terms = c.get("/settings/terms", headers=h).json()
        assert terms["lines"] and len(terms["version"]) == 12
        # the public link counts opens only when the customer opens it
        c.get(f"/public/quotes/{q.public_token}?from=link")
        c.get(f"/public/quotes/{q.public_token}")
        assert env["crm"].deals.get(T, deal.id).signals.quote_opens == 1
    finally:
        app.dependency_overrides.clear()


def test_readiness_delivery_change_reprices(env):
    from app import deps
    from app.team.service import TeamService
    app.dependency_overrides.update({
        deps.get_crm: lambda: env["crm"], deps.get_repo: lambda: env["repo"],
        deps.get_settings_service: lambda: env["settings"],
        deps.get_catalog_service: lambda: env["catalog"],
        deps.get_team: lambda: TeamService(env["tmp"]),
        deps.get_tenant_loader: lambda: (lambda tid: env["tenant"])})
    c, h = TestClient(app), {"X-Tenant-ID": T}
    try:
        q, deal = make_quote(env)
        before = env["crm"].deals.get(T, deal.id).value
        r = c.patch(f"/crm/deals/{deal.id}/readiness", headers=h,
                    json={"location": "אילת", "event_time": "06:00"})
        assert r.status_code == 200
        d = env["crm"].deals.get(T, deal.id)
        assert d.event_time == "06:00" and d.value > before
        skus = {ln.sku for ln in env["repo"].get(T, q.id).tier().quote.lines}
        assert "LOG-DELIVERY-F" in skus and "DLV-early" in skus
        assert c.patch(f"/crm/deals/{deal.id}/readiness", headers=h,
                       json={"event_time": "25:00"}).status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_migration_rescores_stored_deals(tmp_path):
    import json

    from app.migrations import m005_rescore_leads
    deal = Deal(tenant_id=T, customer_id="nobody", title="x", guest_count=100,
                event_date=date.today() + timedelta(days=20), lead_score=80,
                score_reasons=["old"])
    (tmp_path / "crm_deals.json").write_text(json.dumps({deal.id: deal.model_dump(mode="json")}))
    assert m005_rescore_leads(tmp_path) == 1
    raw = json.loads((tmp_path / "crm_deals.json").read_text())[deal.id]
    assert raw["lead_score"] == 5 + 5 + 10 + 10 and raw["title"] == "x"

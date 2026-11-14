from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from app.business.operations import (
    InvoiceError,
    MorningInvoices,
    issue_invoice,
    kitchen_sheet,
    month_calendar,
    run_automation,
    today_view,
)
from app.business.settings import SettingsService
from app.catalog.service import CatalogService
from app.crm.models import Actor, Deal, DealStage
from app.crm.service import CrmService
from app.deps import (
    get_catalog_service,
    get_crm,
    get_repo,
    get_settings_service,
    get_sync,
    get_tenant_loader,
)
from app.integrations.config import IntegrationConfig, TenantConfig
from app.integrations.sync import SyncLog, SyncService
from app.main import app
from app.repositories.quotes import JsonQuoteRepository
from app.schemas.extraction import ContactInfo, ExtractedRequest
from app.schemas.quote import MenuLine, MenuPlan, QuoteStatus
from app.services.portal import CustomerPortal, PortalError
from app.services.pricing import PricingEngine
from app.services.quotes import create_quote

T = "acme"
TODAY = date.today()


@pytest.fixture
def env(tmp_path):
    settings = SettingsService(tmp_path)
    crm = CrmService(tmp_path, settings)
    catalog = CatalogService(tmp_path)
    repo = JsonQuoteRepository(tmp_path / "quotes.json")
    tenant = TenantConfig(tenant_id=T, name="Acme",
                          integrations=[IntegrationConfig(id="crm", type="internal")])
    from app.integrations.adapters.internal import InternalCrmAdapter
    sync = SyncService(SyncLog(tmp_path / "sync.json"),
                       lambda cfg: InternalCrmAdapter(cfg, crm=crm))
    portal = CustomerPortal(repo, crm, catalog, settings, sync,
                            lambda tid: tenant if tid == T else None)
    return {"settings": settings, "crm": crm, "catalog": catalog, "repo": repo,
            "sync": sync, "tenant": tenant, "portal": portal, "tmp": tmp_path}


def make_quote(env, guests=100, days=30, meal="meat", created_days_ago=0):
    req = ExtractedRequest(language="he", event_type="bar_bat_mitzvah", guest_count=guests,
                           event_date=TODAY + timedelta(days=days), meal_type=meal,
                           kashrut="kosher", service={"waiters": True},
                           contact=ContactInfo(name="מיכל", phone="0501234567",
                                               email="m@example.com"))
    pkg = "PKG-MEAT-STD" if meal == "meat" else "PKG-DAIRY-STD"
    plan = MenuPlan(lines=[MenuLine(sku=pkg, for_guests=guests),
                           MenuLine(sku="DRK-SOFT", for_guests=guests)])
    catalog = env["catalog"].items(T)
    q = create_quote(env["repo"], T, req, plan, catalog,
                     PricingEngine(catalog, rules=env["settings"].get(T)), "msg")
    if created_days_ago:
        q.created_at = datetime.now(UTC) - timedelta(days=created_days_ago)
        env["repo"].save(q)
    env["sync"].deliver(env["tenant"], q, __import__(
        "app.integrations.canonical", fromlist=["EventType"]).EventType.created)
    deal = next(iter(env["crm"].deals.list(T, lambda d: q.id in d.quote_ids)))
    return q, deal


# ---------- settings & catalog ----------

def test_settings_drive_pricing_and_capacity(env, catalog):
    s = env["settings"].update(T, {"waiter_ratio": 10, "max_events_per_day": 1})
    req = ExtractedRequest(language="he", guest_count=100, meal_type="meat",
                           service={"waiters": True})
    plan = MenuPlan(lines=[MenuLine(sku="PKG-MEAT-STD")])
    lines = {ln.sku: ln for ln in PricingEngine(catalog, rules=s).price(req, plan).lines}
    assert lines["STF-WAITER"].quantity == 10 * 5  # 100/10 waiters x 5h
    c = env["crm"].upsert_customer(T, name="x")
    day = TODAY + timedelta(days=10)
    env["crm"].save_deal(Deal(tenant_id=T, customer_id=c.id, title="", event_date=day,
                              stage=DealStage.won))
    assert not env["crm"].availability(T, day).available


def test_catalog_copy_on_write(env):
    svc = env["catalog"]
    assert svc.items(T) and not svc.col.list(T)  # demo catalog served, nothing written
    svc.update(T, "PKG-MEAT-STD", {"price": 210, "active": True})
    assert svc.get(T, "PKG-MEAT-STD").price == 210
    svc.update(T, "CAN-SUSHI", {"active": False})
    assert "CAN-SUSHI" not in {i.sku for i in svc.items(T)}
    assert svc.get("other", "PKG-MEAT-STD").price == 195  # other tenants untouched


# ---------- customer page, deposit, final count ----------

def test_customer_accepts_pays_deposit_and_deal_is_won(env):
    q, deal = make_quote(env)
    portal = env["portal"]
    v = portal.view(q.public_token)
    assert v.can_accept and [t.key for t in v.tiers] == ["basic", "recommended", "premium"]
    rec = next(t for t in v.tiers if t.key == "recommended")
    assert all("מלצר" not in i["name"] for i in rec.items)  # staff shown as services
    assert any("מלצר" in s for s in rec.services)
    assert rec.deposit == round(rec.total * 0.3, 2)

    r = portal.accept(q.public_token, "premium")
    assert "/pay/" in r["checkout_url"] and r["amount"] > 0
    assert env["crm"].deals.get(T, deal.id).stage == "quoted"  # not won before paying
    portal.confirm_payment(q.public_token, r["payment_id"], "ref-1")
    assert portal.confirm_payment(q.public_token, r["payment_id"])["already"]  # idempotent
    d = env["crm"].deals.get(T, deal.id)
    q2 = env["repo"].get(T, q.id)
    assert d.stage == "won" and d.deposit_paid == r["amount"]
    assert q2.status == "approved" and q2.selected_tier == "premium"
    assert d.value == q2.tier("premium").quote.total
    with pytest.raises(PortalError):
        portal.accept(q.public_token, "basic")


def test_expired_quote_cannot_be_accepted(env):
    q, _ = make_quote(env, created_days_ago=20)
    assert env["portal"].view(q.public_token).expired
    with pytest.raises(PortalError, match="פג תוקף"):
        env["portal"].accept(q.public_token, "recommended")


def test_final_guest_count_reprices(env):
    env["settings"].update(T, {"deposit_rate": 0})  # approve without payment
    q, deal = make_quote(env, guests=100)
    env["portal"].accept(q.public_token, "recommended")
    before = env["repo"].get(T, q.id).tier().quote.total
    v = env["portal"].update_guest_count(q.public_token, 120)
    d = env["crm"].deals.get(T, deal.id)
    assert v.final_guest_count == 120 and d.guest_count == 120 and d.value > before
    q_close, _ = make_quote(env, days=1)
    env["portal"].accept(q_close.public_token, "recommended")
    with pytest.raises(PortalError):
        env["portal"].update_guest_count(q_close.public_token, 90)


# ---------- automation ----------

def test_automation_rules_are_idempotent(env):
    q_old, d_old = make_quote(env, created_days_ago=3)  # unanswered -> follow-up
    q_exp, d_exp = make_quote(env, created_days_ago=20)  # past validity -> expired
    env["settings"].update(T, {"deposit_rate": 0})
    q_won, d_won = make_quote(env, days=4)  # within final-count window
    env["portal"].accept(q_won.public_token, "recommended")
    past = env["crm"].deals.get(T, d_won.id).model_copy(update={"id": "past"})
    c = env["crm"]
    p = c.save_deal(Deal(tenant_id=T, customer_id=past.customer_id, title="",
                         event_date=TODAY - timedelta(days=1), stage=DealStage.won))
    rules = env["settings"].get(T)
    acts = run_automation(c, env["repo"], rules, T)
    by = {(a.rule, a.deal_id) for a in acts}
    assert ("followup", d_old.id) in by and ("expired", d_exp.id) in by
    assert ("final_count", d_won.id) in by and ("completed", p.id) in by
    assert env["repo"].get(T, q_exp.id).status == QuoteStatus.expired
    assert c.deals.get(T, p.id).stage == "completed"
    assert run_automation(c, env["repo"], rules, T) == []  # second run: nothing new
    msg = next(a.text for a in c.timeline(T, d_old.id) if a.meta.get("automation"))
    assert q_old.public_token in msg  # follow-up message carries the customer link


# ---------- kitchen, calendar, today ----------

def test_kitchen_sheet_aggregates_won_events(env):
    env["settings"].update(T, {"deposit_rate": 0})
    q1, d1 = make_quote(env, guests=100, days=12)
    q2, d2 = make_quote(env, guests=50, days=12)
    make_quote(env, guests=70, days=12)  # not approved: not in the kitchen
    for q in (q1, q2):
        env["portal"].accept(q.public_token, "recommended")
    sheet = kitchen_sheet(env["crm"], env["repo"], env["catalog"].all(T), T,
                          TODAY + timedelta(days=12))
    food = {f.sku: f for f in sheet.food}
    assert food["PKG-MEAT-STD"].quantity == 150 and len(food["PKG-MEAT-STD"].events) == 2
    assert sheet.total_guests == 150 and len(sheet.events) == 2
    assert all(e.staff for e in sheet.events) and "STF-WAITER" not in food


def test_calendar_and_today(env):
    env["settings"].update(T, {"deposit_rate": 0, "max_events_per_day": 1})
    q, d = make_quote(env, days=3)
    env["portal"].accept(q.public_token, "recommended")
    day = TODAY + timedelta(days=3)
    days = month_calendar(env["crm"], env["settings"].get(T), T, day.strftime("%Y-%m"))
    cell = next(x for x in days if x.date == day)
    assert cell.full and cell.deals[0]["stage"] == "won"
    env["crm"].add_task(T, "להתקשר", deal_id=d.id, due_at=datetime.now(UTC) - timedelta(hours=1),
                        priority="high", created_by=Actor.agent)
    tv = today_view(env["crm"], T)
    assert tv.events_this_week[0]["id"] == d.id and tv.tasks_due[0]["title"] == "להתקשר"


# ---------- invoices ----------

def test_manual_and_morning_invoices(env, monkeypatch):
    env["settings"].update(T, {"deposit_rate": 0})
    q, d = make_quote(env)
    rules = env["settings"].get(T)
    with pytest.raises(InvoiceError, match="רק לעסקה שנסגרה"):
        issue_invoice(env["crm"], env["repo"], rules, T, d.id, "123")
    env["portal"].accept(q.public_token, "recommended")
    with pytest.raises(InvoiceError, match="מספר החשבונית"):
        issue_invoice(env["crm"], env["repo"], rules, T, d.id)
    deal = issue_invoice(env["crm"], env["repo"], rules, T, d.id, "INV-77")
    assert deal.invoice.number == "INV-77"

    q2, d2 = make_quote(env)
    env["portal"].accept(q2.public_token, "recommended")
    monkeypatch.setenv("MORNING_API_KEY_ID", "k")
    monkeypatch.setenv("MORNING_API_SECRET", "s")
    seen = {}

    def handler(r: httpx.Request):
        if r.url.path.endswith("/account/token"):
            return httpx.Response(200, json={"token": "tok"})
        seen["auth"], seen["body"] = r.headers["Authorization"], __import__("json").loads(r.content)
        return httpx.Response(201, json={"id": "x", "number": 40001,
                                         "url": {"he": "https://morning/doc"}})
    morning = MorningInvoices(httpx.Client(base_url="https://m.test",
                                           transport=httpx.MockTransport(handler)))
    rules = env["settings"].update(T, {"invoice_provider": "morning"})
    deal = issue_invoice(env["crm"], env["repo"], rules, T, d2.id, morning=morning)
    assert deal.invoice.number == "40001" and seen["auth"] == "Bearer tok"
    assert seen["body"]["type"] == 305 and seen["body"]["client"]["emails"] == ["m@example.com"]
    assert seen["body"]["income"][0]["price"] == q2.tier().quote.net


# ---------- API ----------

def test_public_and_owner_api(env):
    tenants = {T: env["tenant"]}
    app.dependency_overrides.update({
        get_crm: lambda: env["crm"], get_repo: lambda: env["repo"],
        get_settings_service: lambda: env["settings"], get_catalog_service: lambda: env["catalog"],
        get_sync: lambda: env["sync"], get_tenant_loader: lambda: tenants.get,
    })
    try:
        c, h = TestClient(app), {"X-Tenant-ID": T}
        q, d = make_quote(env)
        v = c.get(f"/public/quotes/{q.public_token}").json()
        assert v["can_accept"] and "SKU" not in str(v) and "STF-" not in str(v)
        assert c.get("/public/quotes/not-a-token").status_code == 404
        r = c.post(f"/public/quotes/{q.public_token}/accept", json={"tier": "basic"}).json()
        pay = c.get(f"/public/quotes/{q.public_token}/payments/{r['payment_id']}").json()
        assert pay["status"] == "pending"
        c.post(f"/public/quotes/{q.public_token}/payments/{r['payment_id']}/demo-confirm")
        assert c.get(f"/crm/deals/{d.id}", headers=h).json()["deal"]["stage"] == "won"

        assert c.patch("/catalog/PKG-MEAT-STD", headers=h, json={"price": -1}).status_code == 422
        item = c.patch("/catalog/PKG-MEAT-STD", headers=h, json={"price": 205}).json()
        assert item["price"] == 205
        st = c.patch("/settings", headers=h, json={"deposit_rate": 0.5}).json()
        assert st["deposit_rate"] == 0.5
        assert c.patch("/settings", headers=h, json={"deposit_rate": 3}).status_code == 422
        assert c.get("/crm/today", headers=h).status_code == 200
        assert c.get(f"/kitchen?day={TODAY.isoformat()}", headers=h).status_code == 200
        assert c.get("/crm/calendar?month=bad", headers=h).status_code == 422
        assert isinstance(c.post("/automation/run", headers=h).json(), list)
    finally:
        app.dependency_overrides.clear()

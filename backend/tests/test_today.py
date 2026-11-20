"""Stage 4: serving style, readiness checklist, the Today screen, scheduled reminders."""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from app.business.messages import customer_messages
from app.business.readiness import readiness
from app.business.scheduler import tick
from app.business.today import today_view
from app.main import app
from app.purchasing.service import PurchasingService
from app.schemas.catalog import CatalogItem, ItemRole
from app.schemas.extraction import ExtractedRequest
from app.schemas.quote import MenuLine, MenuPlan
from app.services.pricing import PricingEngine
from tests.test_business import TODAY, T, make_quote

TZ = ZoneInfo("Asia/Jerusalem")


def _staff(style, guests=100):
    from app.business.settings import BusinessSettings
    cat = [CatalogItem(sku="P", name_he="ארוחה", name_en="p", category="main", unit="per_guest",
                       price=50, meal_type="pareve"),
           CatalogItem(sku="W", name_he="מלצר", name_en="w", category="staff", unit="hour",
                       price=70, meal_type="pareve", role=ItemRole.waiter),
           CatalogItem(sku="C", name_he="שף", name_en="c", category="staff", unit="hour",
                       price=150, meal_type="pareve", role=ItemRole.chef)]
    rules = BusinessSettings(id="t", tenant_id="t", staff_hours=5)
    req = ExtractedRequest(language="he", guest_count=guests,
                           service={"waiters": True, "style": style})
    q = PricingEngine(cat, rules=rules).price(req, MenuPlan(lines=[MenuLine(sku="P")]))
    return {ln.sku: ln.quantity for ln in q.lines}


def test_serving_style_sets_the_staff_ratio():
    assert _staff(None)["W"] == 7 * 5          # default 1:15
    assert _staff("plated")["W"] == 10 * 5     # 1:10
    assert _staff("buffet")["W"] == 5 * 5      # 1:20
    chef = _staff("chef_station", 160)
    assert chef["W"] == 11 * 5 and chef["C"] == 2 * 5   # 1:15 waiters, 1 chef per 80
    assert "C" not in _staff("buffet")


def _booked(env, days=4, guests=100):
    env["settings"].update(T, {"deposit_rate": 0.3})
    q, deal = make_quote(env, guests=guests, days=days)
    env["portal"].accept(q.public_token, "recommended")
    pay = env["crm"].deals.get(T, deal.id).payments[-1]
    env["portal"].confirm_payment(q.public_token, pay.id)
    return env["repo"].get(T, q.id), env["crm"].deals.get(T, deal.id)


def _ready(env, deal, q):
    rules = env["settings"].get(T)
    msgs = customer_messages(deal, q, env["crm"].customers.get(T, deal.customer_id), rules)
    return {i.key: i for i in readiness(deal, q, env["catalog"].all(T), rules, msgs).items}


def test_readiness_items_are_red_until_done_and_carry_the_fix(env):
    q, deal = _booked(env)
    items = _ready(env, deal, q)
    assert set(items) == {"location", "site", "final_count", "menu", "balance", "staff",
                          "equipment"}
    assert not items["location"].ok and items["location"].action.kind == "edit"
    assert not items["final_count"].ok and items["final_count"].action.kind == "whatsapp"
    assert items["final_count"].action.url.startswith("https://wa.me/972")
    assert not items["balance"].ok and "נשארו ₪" in items["balance"].detail
    assert not items["menu"].ok and "לא נבחרו" in items["menu"].detail
    assert items["equipment"].ok                                 # no equipment ordered
    # fill everything in
    d = env["crm"].deals.get(T, deal.id)
    d.location, d.site_contact_name, d.site_contact_phone = "אולם הגן", "רונן", "050-1"
    d.site = d.site.model_copy(update={"electricity": True, "kitchenette": False,
                                       "fridge": True, "parking": True})
    d.final_guest_count = 100
    d.ready_marks["staff"] = "2026-11-20T10:00"
    pkg = next(ln.sku for ln in q.tier().quote.lines if ln.sku.startswith("PKG"))
    item = env["catalog"].get(T, pkg)
    q.menu_choices = {pkg: {s.id: s.options[: s.choose] for s in item.slots}}
    from app.crm.models import Payment
    d.payments.append(Payment(amount=d.value - d.deposit_paid, status="paid"))
    env["crm"].save_deal(d)
    items = _ready(env, d, q)
    assert all(i.ok for i in items.values()), {k: i.detail for k, i in items.items() if not i.ok}
    assert "מטבחון" in items["site"].detail                     # known "no" is still shown


def test_today_opens_with_what_could_go_wrong_then_merged_agenda(env):
    q, deal = _booked(env, days=2)
    lead_q, lead = make_quote(env, days=40)
    env["crm"].add_task(T, "להתקשר ללקוח", deal_id=lead.id,
                        due_at=datetime.now(UTC) - timedelta(hours=2), priority="high")
    env["crm"].add_task(T, "להתקשר שוב", deal_id=lead.id)
    env["portal"].update_guest_count(q.public_token, 130)   # inside the 3-day lock → a request
    ps = PurchasingService(env["tmp"])
    tv = today_view(env["crm"], env["repo"], env["catalog"].all(T), env["settings"].get(T), ps, T)
    kinds = {(w.kind, w.key) for w in tv.watch if w.deal_id == deal.id}
    assert ("readiness", "final_count") in kinds and ("readiness", "balance") in kinds
    change = next(w for w in tv.watch if w.kind == "change")
    assert change.severity == "high" and change.actions[0].kind == "approve"
    orders = [w for w in tv.watch if w.kind == "order"]
    assert orders and all(w.meta["supplier"] for w in orders)
    # a lead's tasks merge into one row; the overdue one marks the row
    rows = [r for r in tv.agenda if r.deal_id == lead.id]
    assert len(rows) == 1 and len(rows[0].tasks) == 2 and rows[0].overdue
    assert rows[0].tasks[0]["title"] == "להתקשר ללקוח"           # overdue first
    # the change-request task isn't repeated below: it's in "what could go wrong"
    assert not any(t["title"].startswith("בקשת שינוי") for r in tv.agenda for t in r.tasks)
    # a marked order disappears from the watch list
    w = orders[0]
    ps.mark_ordered(T, w.meta["supplier"], date.fromisoformat(w.meta["deliver_on"]), True)
    tv2 = today_view(env["crm"], env["repo"], env["catalog"].all(T), env["settings"].get(T), ps, T)
    assert (w.key, w.meta["deliver_on"]) not in {(x.key, x.meta.get("deliver_on"))
                                                 for x in tv2.watch if x.kind == "order"}


def test_lead_without_a_quote_gets_send_quote(env):
    from app.crm.models import Deal
    c = env["crm"].upsert_customer(T, name="דנה", phone="0501112222")
    d = env["crm"].save_deal(Deal(tenant_id=T, customer_id=c.id, title="ליד חדש",
                                  guest_count=50, meal_type="meat", event_type="birthday",
                                  event_date=TODAY + timedelta(days=30)))
    tv = today_view(env["crm"], env["repo"], env["catalog"].all(T), env["settings"].get(T),
                    PurchasingService(env["tmp"]), T)
    row = next(r for r in tv.agenda if r.deal_id == d.id)
    assert row.action.kind == "quote" and row.action.label == "לשלוח הצעה"


def test_scheduled_reminders_run_once_a_day_after_the_hour(env):
    env["settings"].update(T, {"automation_hour": 9, "deposit_rate": 0})
    q, deal = make_quote(env, days=2)
    env["portal"].accept(q.public_token, "recommended")
    early = datetime.combine(TODAY, datetime.min.time(), TZ).replace(hour=7)
    assert tick(env["crm"], env["repo"], env["settings"], now=early) == {}
    late = early.replace(hour=10)
    done = tick(env["crm"], env["repo"], env["settings"], now=late)
    rules = {a.rule for a in done[T]}
    assert {"final_count", "balance"} <= rules
    assert env["settings"].get(T).automation_last_run == TODAY.isoformat()
    assert tick(env["crm"], env["repo"], env["settings"], now=late) == {}  # once a day
    env["settings"].update(T, {"automation_enabled": False, "automation_last_run": None})
    assert tick(env["crm"], env["repo"], env["settings"], now=late) == {}


def test_cron_endpoint_needs_the_key(env, monkeypatch):
    from app import deps
    app.dependency_overrides.update({deps.get_crm: lambda: env["crm"],
                                     deps.get_repo: lambda: env["repo"],
                                     deps.get_settings_service: lambda: env["settings"]})
    c = TestClient(app)
    try:
        monkeypatch.delenv("CRON_KEY", raising=False)
        assert c.post("/public/cron/daily").status_code == 404
        monkeypatch.setenv("CRON_KEY", "s3cret")
        assert c.post("/public/cron/daily", headers={"X-Cron-Key": "nope"}).status_code == 403
        assert c.post("/public/cron/daily", headers={"X-Cron-Key": "s3cret"}).status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_api_readiness_style_quote_from_deal(env):
    from app import deps
    from app.crm.models import Deal
    ps = PurchasingService(env["tmp"])
    app.dependency_overrides.update({
        deps.get_crm: lambda: env["crm"], deps.get_repo: lambda: env["repo"],
        deps.get_settings_service: lambda: env["settings"],
        deps.get_catalog_service: lambda: env["catalog"], deps.get_purchasing: lambda: ps,
        deps.get_tenant_loader: lambda: (lambda tid: env["tenant"])})
    c, h = TestClient(app), {"X-Tenant-ID": T}
    try:
        q, deal = _booked(env)
        r = c.patch(f"/crm/deals/{deal.id}/readiness", headers=h, json={
            "location": "אולם", "site_contact_name": "רונן", "site_contact_phone": "050",
            "site": {"electricity": True}, "marks": {"staff": True}}).json()
        items = {i["key"]: i for i in r["items"]}
        assert items["location"]["ok"] and items["staff"]["ok"] and not items["site"]["ok"]
        before = env["crm"].deals.get(T, deal.id).value
        c.patch(f"/crm/deals/{deal.id}/readiness", headers=h, json={"service_style": "plated"})
        d = env["crm"].deals.get(T, deal.id)
        assert d.service_style == "plated" and d.value > before  # more waiters
        assert env["repo"].get(T, q.id).request.service.style.value == "plated"
        assert c.get("/crm/today", headers=h).status_code == 200
        # a lead without a quote → one click builds it
        cust = env["crm"].upsert_customer(T, name="גל", phone="0502223333")
        lead = env["crm"].save_deal(Deal(tenant_id=T, customer_id=cust.id, title="ליד",
                                         guest_count=40, meal_type="dairy"))
        out = c.post(f"/crm/deals/{lead.id}/quote", headers=h).json()
        assert env["crm"].deals.get(T, lead.id).quote_ids == [out["quote_id"]]
        bad = env["crm"].save_deal(Deal(tenant_id=T, customer_id=cust.id, title="חסר"))
        r = c.post(f"/crm/deals/{bad.id}/quote", headers=h)
        assert r.status_code == 422 and "מספר אורחים" in r.json()["detail"]
    finally:
        app.dependency_overrides.clear()

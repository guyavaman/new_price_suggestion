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
from app.crm.models import Actor, Deal, DealStage
from app.deps import (
    get_catalog_service,
    get_crm,
    get_repo,
    get_settings_service,
    get_sync,
    get_tenant_loader,
)
from app.main import app
from app.schemas.extraction import ContactInfo, ExtractedRequest
from app.schemas.quote import MenuLine, MenuPlan, QuoteStatus
from app.services.portal import PortalError
from app.services.pricing import PricingEngine
from app.services.quotes import create_quote

T = "acme"
TODAY = date.today()


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
    # the package is broken into its dishes: the kitchen sees the main dish, not the package
    assert "PKG-MEAT-STD" not in food
    pkg = env["catalog"].get(T, "PKG-MEAT-STD")
    main = next(sl for sl in pkg.slots if sl.id == "main").options[0]
    assert food[main].quantity == 150 and len(food[main].events) == 2
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
        item = c.patch("/catalog/PKG-MEAT-STD", headers=h, json={"price": 205}).json()["item"]
        assert item["price"] == 205
        # a package's cost comes from its components, never typed in
        assert c.patch("/catalog/PKG-MEAT-STD", headers=h, json={"cost": 50}).status_code == 422
        st = c.patch("/settings", headers=h, json={"deposit_rate": 0.5}).json()
        assert st["deposit_rate"] == 0.5
        assert c.patch("/settings", headers=h, json={"deposit_rate": 3}).status_code == 422
        assert c.get("/crm/today", headers=h).status_code == 200
        assert c.get(f"/kitchen?day={TODAY.isoformat()}", headers=h).status_code == 200
        assert c.get("/crm/calendar?month=bad", headers=h).status_code == 422
        assert isinstance(c.post("/automation/run", headers=h).json(), list)
    finally:
        app.dependency_overrides.clear()


# ---------- rejection reasons ----------

def test_customer_decline_reason_reaches_deal(env):
    q, deal = make_quote(env)
    v = env["portal"].decline(q.public_token, "המחיר גבוה מדי")
    assert v.status == "rejected" and not v.can_accept
    d = env["crm"].deals.get(T, deal.id)
    assert d.stage == "lost" and d.lost_reason == "המחיר גבוה מדי"
    assert any("המחיר גבוה מדי" in t.title for t in env["crm"].tasks.list(T))
    with pytest.raises(PortalError):
        env["portal"].decline(q.public_token, "שוב")


def test_owner_rejection_note_becomes_lost_reason(env):
    from app.integrations.canonical import EventType
    from app.repositories.quotes import StatusChange
    from app.schemas.quote import QuoteStatus
    q, deal = make_quote(env)
    q.status = QuoteStatus.rejected
    q.history.append(StatusChange(status=QuoteStatus.rejected, note="בחרו ספק אחר"))
    q = env["repo"].save(q)
    env["sync"].deliver(env["tenant"], q, EventType.rejected)
    assert env["crm"].deals.get(T, deal.id).lost_reason == "בחרו ספק אחר"


# ---------- ready-to-send customer messages ----------

def test_customer_messages_follow_the_deal(env):
    from app.business.messages import customer_messages
    q, deal = make_quote(env)
    rules = env["settings"].get(T)
    cust = env["crm"].customers.get(T, deal.customer_id)
    msgs = customer_messages(env["crm"].deals.get(T, deal.id), q, cust, rules)
    assert msgs[0].kind == "quote" and msgs[0].recommended
    link = f"/q/{q.public_token}"
    assert all(link in m.text for m in msgs)  # every message carries the personal link
    assert msgs[0].whatsapp_url.startswith("https://wa.me/972501234567?text=")

    r = env["portal"].accept(q.public_token, "recommended")
    env["portal"].confirm_payment(q.public_token, r["payment_id"])
    d = env["crm"].deals.get(T, deal.id)
    q = env["repo"].get(T, q.id)
    msgs = customer_messages(d, q, cust, rules)
    kinds = [m.kind for m in msgs]
    assert msgs[0].kind == "confirmed" and "quote" not in kinds
    assert {"final_count", "balance", "service"} <= set(kinds)
    balance = next(m for m in msgs if m.kind == "balance")
    assert f"₪{q.tier().quote.total - d.deposit_paid:,.0f}" in balance.text


def test_message_sent_is_logged(env):
    from app import deps
    q, deal = make_quote(env)
    app.dependency_overrides.update({
        deps.get_crm: lambda: env["crm"], deps.get_repo: lambda: env["repo"],
        deps.get_settings_service: lambda: env["settings"],
        deps.get_tenant_loader: lambda: (lambda tid: env["tenant"]),
    })
    try:
        c = TestClient(app)
        h = {"X-Tenant-ID": T}
        msgs = c.get(f"/crm/deals/{deal.id}/messages", headers=h).json()
        assert msgs[0]["kind"] == "quote"
        d = c.post(f"/crm/deals/{deal.id}/messages/quote/sent", headers=h).json()
        assert "quote" in d["sent_messages"]
        assert any("שליחת ההצעה" in a.text for a in env["crm"].timeline(T, deal.id))
        assert c.post(f"/crm/deals/{deal.id}/messages/nope/sent", headers=h).status_code == 404
    finally:
        app.dependency_overrides.clear()



# ---------- stage 1: cost changes, send guard ----------

def _api(env):
    from app import deps
    app.dependency_overrides.update({
        deps.get_crm: lambda: env["crm"], deps.get_repo: lambda: env["repo"],
        deps.get_settings_service: lambda: env["settings"],
        deps.get_catalog_service: lambda: env["catalog"],
        deps.get_tenant_loader: lambda: (lambda tid: env["tenant"]),
    })
    return TestClient(app), {"X-Tenant-ID": T}


def test_cost_increase_lists_affected_quotes_and_opens_a_task(env):
    q, deal = make_quote(env)  # meat package, sent
    c, h = _api(env)
    try:
        pkg = next(ln for ln in q.tier().quote.lines if ln.sku.startswith("PKG-"))
        comp = env["catalog"].get(T, pkg.sku).slots[0].options[0]  # a default dish of the package
        old = env["catalog"].get(T, comp).cost
        r = c.patch(f"/catalog/{comp}", headers=h, json={"cost": round(old * 1.5, 2)}).json()
        assert r["item"]["cost_source"] == "manual" and r["item"]["cost_updated_at"]
        row = next(x for x in r["cost_impact"] if x["quote_id"] == q.id)
        assert row["kind"] == "open_quote" and row["delta"] < 0
        assert row["profit_after"] < row["profit_before"]
        assert any("עלתה" in t.title for t in env["crm"].tasks.list(T))
        # small changes and decreases don't alarm
        r2 = c.patch(f"/catalog/{comp}", headers=h, json={"cost": round(old * 1.5 * 1.01, 2)})
        assert r2.json()["cost_impact"] == []
    finally:
        app.dependency_overrides.clear()


def test_sending_below_floor_needs_explicit_owner_approval(env):
    q, deal = make_quote(env)
    from app.schemas.quote import QuoteStatus
    q.status = QuoteStatus.draft
    env["repo"].save(q)
    c, h = _api(env)
    try:
        env["settings"].update(T, {"profit_floor": 0.9})  # nothing clears a 90% floor
        prof = c.get(f"/quotes/{q.id}/profit", headers=h).json()
        assert prof["send_blockers"] and prof["tiers"][1]["summary"]["below_floor"] is True
        r = c.post(f"/quotes/{q.id}/status", headers=h, json={"status": "sent"})
        assert r.status_code == 409 and r.json()["detail"]["code"] == "profit_floor"
        ok = c.post(f"/quotes/{q.id}/status", headers=h,
                    json={"status": "sent", "override_floor": True})
        assert ok.status_code == 200
        assert "באישור בעל העסק" in ok.json()["quote"]["history"][-1]["note"]
        assert any(a.meta.get("override_floor") for a in env["crm"].timeline(T, deal.id))
    finally:
        app.dependency_overrides.clear()


def test_import_api_preview_then_apply(env):
    c, h = _api(env)
    try:
        tpl = c.get("/catalog/import/template", headers=h)
        assert tpl.status_code == 200 and tpl.content[:2] == b"PK"  # an xlsx
        csv_data = b'sku,cost\nSAL-ISR,999\nNOPE,1\n'
        files = {"file": ("costs.csv", csv_data, "text/csv")}
        prev = c.post("/catalog/import", headers=h, files=files).json()
        assert not prev["applied"] and prev["updates"][0]["fields"]["cost"][1] == 999
        assert prev["errors"] and env["catalog"].get(T, "SAL-ISR").cost != 999  # nothing written
        done = c.post("/catalog/import?apply=true", headers=h, files=files).json()
        assert done["applied"] and env["catalog"].get(T, "SAL-ISR").cost == 999
    finally:
        app.dependency_overrides.clear()


# ---------- stage 2: dishes per event ----------

def _send(env, q):
    q.status = __import__("app.schemas.quote", fromlist=["QuoteStatus"]).QuoteStatus.sent
    return env["repo"].save(q)


def test_owner_picks_dishes_cost_follows_and_timeline_records_it(env):
    q, deal = make_quote(env, guests=180)
    c, h = _api(env)
    try:
        m = c.get(f"/quotes/{q.id}/menu", headers=h).json()
        pkg = next(p for p in m["packages"] if p["sku"] == "PKG-MEAT-STD")
        assert pkg["guests"] == 180 and pkg["breakdown"]["rows"]
        main = next(sl for sl in pkg["slots"] if sl["id"] == "main")
        other = next(o["sku"] for o in main["options"] if o["sku"] not in main["chosen"])
        line_cost = lambda qq: next(ln["unit_cost"] for ln in qq["tiers"][1]["quote"]["lines"]  # noqa: E731
                                    if ln["sku"] == "PKG-MEAT-STD")
        before = line_cost(c.get(f"/quotes/{q.id}", headers=h).json())
        r = c.put(f"/quotes/{q.id}/menu", headers=h,
                  json={"package": "PKG-MEAT-STD", "choice": {"main": [other]}})
        assert r.status_code == 200
        pkg2 = next(p for p in r.json()["packages"] if p["sku"] == "PKG-MEAT-STD")
        assert other in [row["sku"] for row in pkg2["breakdown"]["rows"]]
        after = line_cost(c.get(f"/quotes/{q.id}", headers=h).json())
        assert after != before  # the package cost snapshot follows the dishes
        assert any("עודכנו מנות" in a.text for a in env["crm"].timeline(T, deal.id))
        bad = c.put(f"/quotes/{q.id}/menu", headers=h,
                    json={"package": "PKG-MEAT-STD", "choice": {"main": ["SAL-ISR"]}})
        assert bad.status_code == 422 and "אינה ברשימה" in bad.json()["detail"]
        d = c.get(f"/crm/deals/{deal.id}/menu", headers=h).json()
        assert d["packages"][0]["sku"] == "PKG-MEAT-STD"
    finally:
        app.dependency_overrides.clear()


def test_customer_picks_dishes_in_the_link_without_seeing_costs(env):
    q, deal = make_quote(env, guests=120, days=30)
    q = _send(env, q)
    v = env["portal"].view(q.public_token)
    pkg = next(p for p in v.menu if p.sku == "PKG-MEAT-STD")
    salads = next(sl for sl in pkg.slots if sl.id == "salads")
    pick = [o["sku"] for o in salads.options][-3:]
    v2 = env["portal"].choose_menu(q.public_token, "PKG-MEAT-STD", {"salads": pick})
    assert next(sl for sl in v2.menu[0].slots if sl.id == "salads").chosen == pick
    assert env["repo"].get(T, q.id).menu_choices["PKG-MEAT-STD"]["salads"] == pick
    assert any("הלקוח בחר מנות" in a.text for a in env["crm"].timeline(T, deal.id))
    dumped = v2.model_dump_json()
    for word in ("unit_cost", "cost", "per_guest_amount", "yield", "breakdown"):
        assert f'"{word}"' not in dumped
    # owner-only slot (bread): refused
    with pytest.raises(PortalError, match="בעל העסק"):
        env["portal"].choose_menu(q.public_token, "PKG-MEAT-STD", {"bread": ["SIDE-BREAD"]})


def test_customer_cannot_change_dishes_after_the_lock(env):
    env["settings"].update(T, {"menu_lock_days": 7})
    q, _ = make_quote(env, guests=80, days=5)  # event in 5 days, lock is 7 days before
    q = _send(env, q)
    v = env["portal"].view(q.public_token)
    assert v.menu_lock.customer_can_choose is False and "7 ימים" in v.menu_lock.reason
    with pytest.raises(PortalError):
        env["portal"].choose_menu(q.public_token, "PKG-MEAT-STD", {"main": ["MAIN-KEBAB"]})
    # a draft (not sent yet) isn't open for the customer either
    q2, _ = make_quote(env, guests=80, days=40)
    assert env["portal"].view(q2.public_token).menu_lock.customer_can_choose is False


def test_package_definition_is_validated_when_saved(env):
    c, h = _api(env)
    try:
        r = c.patch("/catalog/PKG-MEAT-STD", headers=h, json={"slots": [
            {"id": "x", "label_he": "עיקרית", "choose": 1, "options": ["MAIN-LASAGNA"]}]})
        assert r.status_code == 422 and "לא מתאים לחבילה" in r.json()["detail"]
        r = c.patch("/catalog/SAL-ISR", headers=h, json={"slots": []})
        assert r.status_code == 422
        rows = {i["sku"]: i for i in c.get("/catalog", headers=h).json()}
        assert rows["SAL-ISR"]["kind"] == "food" and rows["SAL-ISR"]["measure"] == "g"
        assert rows["STF-WAITER"]["kind"] == "staff" and rows["DRK-SOFT"]["kind"] == "drink"
        assert rows["PKG-MEAT-STD"]["kind"] == "package"
    finally:
        app.dependency_overrides.clear()

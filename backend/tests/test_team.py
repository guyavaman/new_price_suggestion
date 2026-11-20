"""Stage 5: staff (needed, scheduling, WhatsApp confirmation, hours, monthly pay) and
equipment (stock, what goes out, what came back)."""

import io
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.main import app
from app.schemas.catalog import ItemRole
from app.team.importer import STAFF_SHEET, STOCK_SHEET, analyze
from app.team.models import Assignment, EquipmentLine, EquipmentType, StaffMember
from app.team.planning import (
    auto_assign,
    candidates,
    equipment_state,
    missing_returns,
    payroll,
    required_staff,
    save_event_list,
    staff_plan,
)
from app.team.service import TeamService
from tests.test_business import TODAY, T, make_quote


@pytest.fixture
def team(env):
    return TeamService(env["tmp"])


def _won(env, guests=100, days=10, style=None):
    q, deal = make_quote(env, guests=guests, days=days)
    if style:
        q.request.service.style = style
    env["settings"].update(T, {"deposit_rate": 0})
    env["portal"].accept(q.public_token, "recommended")
    return env["repo"].get(T, q.id), env["crm"].deals.get(T, deal.id)


def _crew(team, day):
    wd = day.weekday()
    other = (wd + 1) % 7
    ms = [StaffMember(tenant_id=T, name="אבי", phone="050-1000001", hourly_rate=50),
          StaffMember(tenant_id=T, name="בתיה", phone="050-1000002", hourly_rate=55),
          StaffMember(tenant_id=T, name="גיל", phone="050-1000003", hourly_rate=50,
                      available_days=[other]),                       # not that weekday
          StaffMember(tenant_id=T, name="דנה", phone="050-1000004", hourly_rate=50,
                      unavailable_dates=[day]),                     # blocked that date
          StaffMember(tenant_id=T, name="הדר", phone="050-1000005",
                      roles=[ItemRole.head_waiter, ItemRole.waiter], hourly_rate=80),
          StaffMember(tenant_id=T, name="ורד", phone="050-1000006", hourly_rate=None),
          StaffMember(tenant_id=T, name="זיו", phone="050-1000007", active=False)]
    return [team.members.put(m) for m in ms]


def test_staff_needed_comes_from_the_quote(env):
    q, deal = _won(env, guests=100)
    rules = env["settings"].get(T)
    need = required_staff(q, env["catalog"].all(T), rules)
    w = next(ln for ln in q.tier().quote.lines if ln.sku == "STF-WAITER")
    assert need[ItemRole.waiter] == (round(w.quantity / rules.staff_hours), rules.staff_hours)
    assert ItemRole.head_waiter in need                              # 100 guests ≥ threshold


def test_auto_assign_picks_free_people_fairly_and_reports_gaps(env, team):
    q, deal = _won(env, guests=100)
    crew = _crew(team, deal.event_date)
    by = {m.name: m for m in crew}
    # someone already on another event that day
    _, other = _won(env, guests=20, days=10)
    team.assignments.put(Assignment(tenant_id=T, deal_id=other.id, member_id=by["בתיה"].id,
                                    role=ItemRole.waiter, planned_hours=5))
    names = {m.name for m in candidates(team, env["crm"], deal, ItemRole.waiter)}
    assert names == {"אבי", "הדר", "ורד"}            # not גיל/דנה (days), בתיה (busy), זיו
    new = auto_assign(team, env["crm"], deal, q, env["catalog"].all(T), env["settings"].get(T))
    roles = sorted(a.role.value for a in new)
    assert "head_waiter" in roles and all(a.status == "invited" for a in new)
    plan = staff_plan(team, deal, q, env["catalog"].all(T), env["settings"].get(T))
    assert not plan.ok and "חסרים" in plan.summary and "לא אישרו" in plan.summary
    row = plan.assignments[0]
    from urllib.parse import unquote
    url = row["invite_url"]
    assert url.startswith("https://wa.me/97250") and "/s/" in unquote(url)


def test_confirmation_page_shows_no_money_and_a_decline_opens_a_task(env, team):
    q, deal = _won(env)
    m = team.members.put(StaffMember(tenant_id=T, name="רון", phone="050-2", hourly_rate=60))
    a = team.assignments.put(Assignment(tenant_id=T, deal_id=deal.id, member_id=m.id,
                                        role=ItemRole.waiter, planned_hours=5, rate=60))
    from app import deps
    app.dependency_overrides.update({deps.get_team: lambda: team,
                                     deps.get_crm: lambda: env["crm"],
                                     deps.get_settings_service: lambda: env["settings"]})
    c = TestClient(app)
    try:
        v = c.get(f"/public/staff/{a.token}")
        assert v.status_code == 200 and v.json()["role"] == "מלצר"
        assert not any(k in v.text for k in ("rate", "price", "value", "phone", "דנה"))
        assert c.post(f"/public/staff/{a.token}", json={"coming": True}).json()["status"] == \
            "confirmed"
        c.post(f"/public/staff/{a.token}", json={"coming": False})
        assert team.assignments.get(T, a.id).status == "declined"
        assert any(t.kind == "staff_declined" for t in env["crm"].tasks.list(T))
        assert c.get("/public/staff/nope").status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_payroll_uses_actual_hours_and_flags_planned(env, team):
    q, deal = _won(env, days=3)
    a1 = team.members.put(StaffMember(tenant_id=T, name="אבי", hourly_rate=50))
    a2 = team.members.put(StaffMember(tenant_id=T, name="ורד", hourly_rate=None))
    team.assignments.put(Assignment(tenant_id=T, deal_id=deal.id, member_id=a1.id,
                                    role=ItemRole.waiter, planned_hours=5, actual_hours=6.5,
                                    rate=50, status="confirmed"))
    team.assignments.put(Assignment(tenant_id=T, deal_id=deal.id, member_id=a2.id,
                                    role=ItemRole.waiter, planned_hours=5, status="confirmed"))
    team.assignments.put(Assignment(tenant_id=T, deal_id=deal.id, member_id=a1.id,
                                    role=ItemRole.waiter, planned_hours=5, status="declined"))
    d = deal.event_date
    rows = {r.name: r for r in payroll(team, env["crm"], T, d.year, d.month)}
    assert rows["אבי"].hours == 6.5 and rows["אבי"].total == 325 and rows["אבי"].planned_only == 0
    assert rows["ורד"].total is None and rows["ורד"].planned_only == 1   # no rate: no fake total


def test_equipment_shortage_return_and_readiness(env, team):
    q, deal = _won(env, days=5)
    _, other = _won(env, guests=30, days=5)
    team.put_type(T, EquipmentType(code="CHAFING", name="מחממים", owned=10))
    save_event_list(team, other, [EquipmentLine(code="CHAFING", name="מחממים", quantity=6)])
    save_event_list(team, deal, [EquipmentLine(code="CHAFING", name="מחממים", quantity=6),
                                 EquipmentLine(code="GHOST", name="מגש כסף", quantity=2)])
    st = equipment_state(team, env["crm"], deal, q, env["catalog"].all(T))
    assert "מחממים: חסרים 2" in st.shortages                      # 12 out that day, 10 owned
    assert any("לא במלאי" in s for s in st.shortages)
    # after the event: 1 chafing dish didn't come back
    save_event_list(team, deal, [EquipmentLine(code="CHAFING", name="מחממים", quantity=6,
                                               returned=5)], returned=True)
    later = deal.event_date + timedelta(days=3)
    miss = {m["deal_id"]: m for m in missing_returns(team, env["crm"], T, later)}
    assert miss[deal.id]["items"][0]["missing"] == 1 and miss[deal.id]["counted"]
    assert not miss[other.id]["counted"]          # the other event's equipment wasn't counted
    assert missing_returns(team, env["crm"], T, deal.event_date) == []  # not before the grace


def test_import_staff_and_stock_with_errors():
    wb = Workbook()
    wb.remove(wb.active)
    s = wb.create_sheet(STAFF_SHEET)
    for r in [["שם", "טלפון", "תפקידים", "תעריף לשעה", "ימים זמינים"],
              ["מאיה", "050-1", "מלצרית, ברמנית", 55, "א,ב,ג"],
              ["", "050-2", "מלצר", 50, "א"],
              ["נועם", "050-3", "קונדיטור", 50, "א"],
              ["אבי", "050-1000001", "שף", 90, None]]:
        s.append(r)
    st = wb.create_sheet(STOCK_SHEET)
    for r in [["קוד", "שם", "כמות במלאי"], ["CH", "מחממים", 12], ["TR", "מגשים", 2.5]]:
        st.append(r)
    b = io.BytesIO()
    wb.save(b)
    existing = [StaffMember(tenant_id=T, name="אבי", phone="050-1000001", hourly_rate=50)]
    rep, members, stock = analyze("x.xlsx", b.getvalue(), T, existing, [])
    errs = {(e.sheet, e.row, e.column) for e in rep.errors}
    assert (STAFF_SHEET, 3, "שם") in errs and (STAFF_SHEET, 4, "תפקידים") in errs
    assert (STOCK_SHEET, 3, "כמות במלאי") in errs
    maya = next(m for m in members if m.name == "מאיה")
    assert [r.value for r in maya.roles] == ["waiter", "bartender"]
    assert maya.available_days == [0, 1, 6]
    avi = next(m for m in members if m.name == "אבי")
    assert avi.id == existing[0].id and avi.hourly_rate == 90      # matched by phone
    assert [e.code for e in stock] == ["CH"]


def test_api_scheduling_and_equipment(env, team):
    from app import deps
    from app.purchasing.service import PurchasingService
    app.dependency_overrides.update({
        deps.get_crm: lambda: env["crm"], deps.get_repo: lambda: env["repo"],
        deps.get_settings_service: lambda: env["settings"],
        deps.get_catalog_service: lambda: env["catalog"], deps.get_team: lambda: team,
        deps.get_purchasing: lambda: PurchasingService(env["tmp"]),
        deps.get_tenant_loader: lambda: (lambda tid: env["tenant"])})
    c, h = TestClient(app), {"X-Tenant-ID": T}
    try:
        q, deal = _won(env, guests=40, days=8)
        r = c.post("/staff", headers=h, json={"name": "שירן", "phone": "050-7777777",
                                              "roles": ["waiter"], "hourly_rate": 50,
                                              "available_days": list(range(7))})
        assert r.status_code == 201
        sid = r.json()["id"]
        assert c.post("/staff", headers=h, json={"name": "x", "roles": []}).status_code == 422
        plan = c.post(f"/crm/deals/{deal.id}/staff/auto", headers=h).json()
        a = plan["assignments"][0]
        assert a["name"] == "שירן" and a["invite_url"]
        # confirm by phone, then the readiness item reflects it
        c.patch(f"/crm/deals/{deal.id}/staff/{a['id']}", headers=h, json={"status": "confirmed"})
        rd = {i["key"]: i for i in c.get(f"/crm/deals/{deal.id}/readiness", headers=h)
              .json()["items"]}
        assert "שובצו ואישרו" in rd["staff"]["detail"] or "חסרים" in rd["staff"]["detail"]
        assert c.delete(f"/staff/{sid}", headers=h).status_code == 409   # has a shift
        # adding the same person again: refused
        r = c.post(f"/crm/deals/{deal.id}/staff", headers=h,
                   json={"member_id": sid, "role": "waiter"})
        assert r.status_code == 409
        # equipment
        c.put("/equipment/CH", headers=h, json={"code": "CH", "name": "מחממים", "owned": 4})
        st = c.put(f"/crm/deals/{deal.id}/equipment", headers=h, json={
            "lines": [{"code": "CH", "name": "מחממים", "quantity": 3}], "packed": True}).json()
        assert st["packed"] and not st["shortages"]
        rd = {i["key"]: i for i in c.get(f"/crm/deals/{deal.id}/readiness", headers=h)
              .json()["items"]}
        assert rd["equipment"]["ok"]
        bad = c.put(f"/crm/deals/{deal.id}/equipment", headers=h, json={
            "lines": [{"code": "CH", "name": "מחממים", "quantity": 3, "returned": 5}]})
        assert bad.status_code == 422
        pay = c.get("/staff/payroll", headers=h,
                    params={"month": deal.event_date.strftime("%Y-%m")}).json()
        assert pay[0]["name"] == "שירן"
        assert c.get("/staff/payroll", headers=h, params={"month": "2026-13"}).status_code == 422
        assert c.get("/staff/payroll.xlsx", headers=h).status_code == 200
        assert c.get("/team/import/template", headers=h).status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_today_lists_equipment_that_did_not_come_back(env, team):
    from app.business.today import today_view
    from app.purchasing.service import PurchasingService
    q, deal = _won(env, days=5)
    save_event_list(team, deal, [EquipmentLine(code="CH", name="מחממים", quantity=4,
                                               returned=3)], returned=True)
    later = deal.event_date + timedelta(days=2)
    tv = today_view(env["crm"], env["repo"], env["catalog"].all(T), env["settings"].get(T),
                    PurchasingService(env["tmp"]), T, today=later, team=team)
    row = next(w for w in tv.watch if w.kind == "equipment")
    assert "מחממים (1)" in row.text
    assert TODAY  # fixture date in use

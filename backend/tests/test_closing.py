"""Stage 6: closing an event, planned vs actual, and portion suggestions (own data, not seed)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.business import closing
from app.business.kpis import _event_profit
from app.crm.models import DealStage, DishOutcome, EventClosing, now
from app.main import app
from app.schemas.catalog import ItemRole
from app.team.models import Assignment, StaffMember
from app.team.service import TeamService
from tests.test_business import TODAY, T, make_quote


def _past(env, guests=100, days_ago=2):
    """A booked event that already happened."""
    q, deal = make_quote(env, guests=guests, days=10)
    env["settings"].update(T, {"deposit_rate": 0})
    env["portal"].accept(q.public_token, "recommended")
    d = env["crm"].deals.get(T, deal.id)
    d.event_date = TODAY - timedelta(days=days_ago)
    d.stage = DealStage.completed
    env["crm"].save_deal(d)
    return env["repo"].get(T, q.id), env["crm"].deals.get(T, d.id)


@pytest.fixture
def team(env):
    return TeamService(env["tmp"])


def _closed(env, tenant_deal, cat, marks, planned=100, actual=100, base=220.0):
    d = tenant_deal
    d.closing = EventClosing(actual_guests=actual, planned_guests=planned,
                             portion_snapshot={cat: base}, closed_at=now(),
                             dishes=[DishOutcome(sku=f"X{i}", category=cat, leftover=m)
                                     for i, m in enumerate(marks)])
    return d


# ---------------------------------------------------------------- learning math

def test_observation_scales_by_guests_and_leftovers(env):
    rules = env["settings"].get(T)
    q, d = _past(env)
    # made salads for 100 at 220 g, 80 came, everything ran out → they ate 220×100/80×1.1
    _closed(env, d, "salad", ["out", "out"], planned=100, actual=80)
    obs = closing.observations([d], rules)
    assert obs["salad"][0][0] == pytest.approx(220 * 100 / 80 * 1.1)
    assert obs["salad"][0][1] == {"lot": 0, "ok": 0, "out": 2}


def test_suggestion_needs_enough_events_and_a_real_change(env):
    rules = env["settings"].get(T)
    deals = []
    for i in range(2):
        q, d = _past(env, days_ago=2 + i)
        deals.append(_closed(env, d, "salad", ["lot", "lot"]))   # 220 × 0.75 = 165
        env["crm"].save_deal(d)
    v = closing.learning(env["crm"], env["repo"], env["catalog"].all(T), rules, T)
    s = next(x for x in v.suggestions if x.category == "salad")
    assert s.suggested is None and s.events == 2 and "עוד 1" in s.reason
    q, d = _past(env, days_ago=5)
    env["crm"].save_deal(_closed(env, d, "salad", ["lot", "ok"]))  # 220 × 0.875 = 192.5
    v = closing.learning(env["crm"], env["repo"], env["catalog"].all(T), rules, T)
    s = next(x for x in v.suggestions if x.category == "salad")
    assert s.events == 3 and s.suggested == 165 and s.change == pytest.approx(165 / 220 - 1, 1e-3)
    assert "להקטין" in s.reason and s.marks == {"lot": 5, "ok": 1, "out": 0}
    # the settings did not change by themselves
    assert env["settings"].get(T).portion_rules["salad"].total_per_guest == 220


def test_no_suggestion_when_amounts_were_right(env):
    rules = env["settings"].get(T)
    for i in range(3):
        q, d = _past(env, days_ago=2 + i)
        # "reasonable" means the amount was right: no change
        env["crm"].save_deal(_closed(env, d, "salad", ["ok"]))
    s = next(x for x in closing.learning(env["crm"], env["repo"], env["catalog"].all(T), rules,
                                         T).suggestions if x.category == "salad")
    assert s.suggested is None and "מתאימה" in s.reason


def test_unit_categories_round_to_a_twentieth(env):
    assert closing._round(1.234, "unit") == 1.25 and closing._round(213, "g") == 215


# ---------------------------------------------------------------- report

def test_report_planned_matches_profit_report_and_uses_actuals(env, team):
    q, d = _past(env, guests=100)
    catalog, rules = env["catalog"].all(T), env["settings"].get(T)
    ep = _event_profit(d, q, rules, {i.sku: i for i in catalog})
    dishes = closing.planned_dishes(env["crm"], env["repo"], catalog, rules, d)
    assert dishes and all(x.category != "package" for x in dishes)
    r = closing.report(d, q, catalog, rules, dishes, team)
    assert not r.closed and r.planned_profit == ep.profit and r.actual_cost == r.planned_cost
    assert "טופס סיכום האירוע לא מולא" in r.missing

    food = next(g for g in r.groups if g.group == "food")
    d.closing = closing.save(d, EventClosing(actual_guests=90, purchasing_cost=food.planned + 500,
                                             other_cost=200,
                                             dishes=[DishOutcome(sku=dishes[0].sku,
                                                                 leftover="out")]),
                             rules, dishes)
    r = closing.report(d, q, catalog, rules, dishes, team)
    assert r.closed and r.actual_guests == 90 and r.planned_guests == 100
    assert r.actual_cost == pytest.approx(r.planned_cost + 700)
    assert r.actual_profit == pytest.approx(r.planned_profit - 700)
    assert next(g for g in r.groups if g.group == "food").source == "רכש בפועל"
    row = next(x for x in r.dishes if x.sku == dishes[0].sku)
    assert row.leftover == "out" and d.closing.dishes[0].category == dishes[0].category
    if row.total_amount:
        assert row.per_guest_actual == pytest.approx(row.total_amount / 90, abs=0.1)


def test_staff_cost_from_hours_and_missing_rate(env, team):
    q, d = _past(env)
    m = team.members.put(StaffMember(tenant_id=T, name="רון", phone="050", hourly_rate=50))
    team.assignments.put(Assignment(tenant_id=T, deal_id=d.id, member_id=m.id, status="confirmed",
                                    role=ItemRole.waiter, planned_hours=5, actual_hours=6,
                                    rate=50))
    team.assignments.put(Assignment(tenant_id=T, deal_id=d.id, member_id=m.id, status="declined",
                                    role=ItemRole.waiter, planned_hours=5, rate=50))
    assert closing.staff_cost_from_hours(team, d)[0] == 300
    n = team.members.put(StaffMember(tenant_id=T, name="דנה", phone="051"))
    team.assignments.put(Assignment(tenant_id=T, deal_id=d.id, member_id=n.id, status="confirmed",
                                    role=ItemRole.waiter, planned_hours=5))
    assert closing.staff_cost_from_hours(team, d)[0] is None   # never a partial sum


def test_snapshot_keeps_history_when_rules_change(env):
    q, d = _past(env)
    rules = env["settings"].get(T)
    d.closing = closing.save(d, EventClosing(actual_guests=50), rules, [])
    env["settings"].update(T, {"portion_rules": {
        **{k: v.model_dump() for k, v in rules.portion_rules.items()},
        "salad": {**rules.portion_rules["salad"].model_dump(), "total_per_guest": 300}}})
    again = closing.save(d, EventClosing(actual_guests=60), env["settings"].get(T), [])
    assert again.portion_snapshot["salad"] == 220 and again.planned_guests == 100


# ---------------------------------------------------------------- API, Today, automation

def test_api_close_event_and_apply_suggestion(env, team):
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
        q, d = _past(env)
        env["crm"].add_task(T, "למלא סיכום", deal_id=d.id, kind="closing")
        today = c.get("/crm/today", headers=h).json()
        assert any(w["kind"] == "closing" and w["deal_id"] == d.id for w in today["watch"])
        v = c.get(f"/crm/deals/{d.id}/closing", headers=h).json()
        assert v["closing"] is None and v["dishes"] and v["planned_guests"] == 100
        body = {"actual_guests": 95, "purchasing_cost": 1000, "notes": "חם מאוד",
                "dishes": [{"sku": x["sku"], "leftover": "lot"} for x in v["dishes"]]}
        v = c.put(f"/crm/deals/{d.id}/closing", headers=h, json=body).json()
        assert v["closing"]["actual_guests"] == 95 and v["report"]["closed"]
        assert v["closing"]["dishes"][0]["category"]
        assert not any(t.kind == "closing" and not t.done for t in env["crm"].tasks.list(T))
        today = c.get("/crm/today", headers=h).json()
        assert not any(w["kind"] == "closing" and w["deal_id"] == d.id for w in today["watch"])
        assert c.put(f"/crm/deals/{d.id}/closing", headers=h,
                     json={"actual_guests": -1}).status_code == 422
        lv = c.get("/closing/learning", headers=h).json()
        assert any(e["deal_id"] == d.id and e["actual_guests"] == 95 for e in lv["events"])
        r = c.post("/closing/learning/apply", headers=h,
                   json={"category": "salad", "total_per_guest": 200})
        assert r.status_code == 200 and r.json()["current"] == 200
        assert env["settings"].get(T).portion_rules["salad"].total_per_guest == 200
        assert c.post("/closing/learning/apply", headers=h,
                      json={"category": "nope", "total_per_guest": 1}).status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_automation_asks_to_close_after_the_event(env):
    from app.business.operations import run_automation
    q, deal = make_quote(env, guests=60, days=10)
    env["settings"].update(T, {"deposit_rate": 0})
    env["portal"].accept(q.public_token, "recommended")
    d = env["crm"].deals.get(T, deal.id)
    d.event_date = TODAY - timedelta(days=1)
    env["crm"].save_deal(d)
    run_automation(env["crm"], env["repo"], env["settings"].get(T), T, TODAY)
    assert any(t.kind == "closing" for t in env["crm"].tasks.list(T))


def test_fewer_guests_alone_never_suggest_a_change(env):
    """80 came instead of 100 and everything was 'reasonable': per guest looks 25% higher, but
    no dish ran out, so there's nothing to suggest."""
    rules = env["settings"].get(T)
    for i in range(3):
        q, d = _past(env, days_ago=2 + i)
        env["crm"].save_deal(_closed(env, d, "salad", ["ok", "ok"], planned=100, actual=80))
    s = next(x for x in closing.learning(env["crm"], env["repo"], env["catalog"].all(T), rules,
                                         T).suggestions if x.category == "salad")
    assert s.suggested is None and s.marks == {"lot": 0, "ok": 6, "out": 0}

"""Stage 4: changes after the lock date are priced by the business's policy on approval."""

import pytest

from app.business.changes import ChangeError, approve, decline
from tests.test_business import T, _send, make_quote


def _approved(env, guests=100, days=2):
    env["settings"].update(T, {"deposit_rate": 0, "guest_lock_days": 3})
    q, deal = make_quote(env, guests=guests, days=days)
    env["portal"].accept(q.public_token, "recommended")
    return env["repo"].get(T, q.id), env["crm"].deals.get(T, deal.id)


def _approve(env, deal_id, q_id):
    d = env["crm"].deals.get(T, deal_id)
    req = next(r for r in d.change_requests if r.status == "pending")
    rules = env["settings"].get(T)
    return approve(env["crm"], env["repo"], env["catalog"].items(T), rules, T, d, req.id,
                   env["repo"].get(T, q_id))


def test_guests_added_after_the_lock_pay_the_surcharge(env):
    env["settings"].update(T, {"late_guest_surcharge": 0.2})
    q, deal = _approved(env)
    sub_before = q.tier().quote.subtotal
    env["portal"].update_guest_count(q.public_token, 120)
    req = _approve(env, deal.id, q.id)
    q2 = env["repo"].get(T, q.id)
    adj = next(ln for ln in q2.tier().quote.lines if ln.sku.startswith("ADJ-"))
    plain = q2.tier().quote.subtotal - adj.total            # what 120 guests cost normally
    assert adj.total == round((plain - sub_before) * 0.2, 2) and adj.total > 0
    assert "20%" in adj.name_he and "20 אורחים" in adj.name_he
    assert adj.unit_cost == 0                               # pure extra margin, no cost
    d = env["crm"].deals.get(T, deal.id)
    assert d.final_guest_count == 120 and req.status == "approved" and "₪" in req.price_note
    assert d.value == q2.tier().quote.total


def test_fewer_guests_after_the_lock_are_still_charged(env):
    q, deal = _approved(env)
    total_before = q.tier().quote.total
    env["portal"].update_guest_count(q.public_token, 80)
    _approve(env, deal.id, q.id)
    q2 = env["repo"].get(T, q.id)
    assert q2.request.guest_count == 80                         # the kitchen makes 80
    assert abs(q2.tier().quote.subtotal - q.tier().quote.subtotal) < 0.05  # charged for 100
    assert env["crm"].deals.get(T, deal.id).final_guest_count == 80
    # with the policy off, the price follows the count
    q3, deal3 = _approved(env)
    env["settings"].update(T, {"late_decrease_charged": False})
    env["portal"].update_guest_count(q3.public_token, 80)
    _approve(env, deal3.id, q3.id)
    assert env["repo"].get(T, q3.id).tier().quote.total < total_before


def test_before_the_lock_the_count_changes_directly(env):
    q, deal = _approved(env, days=20)
    v = env["portal"].update_guest_count(q.public_token, 130)
    assert not v.count_needs_approval and v.final_guest_count == 130
    assert not env["crm"].deals.get(T, deal.id).change_requests


def test_declined_request_changes_nothing_and_cannot_be_decided_twice(env):
    q, deal = _approved(env)
    env["portal"].update_guest_count(q.public_token, 150)
    d = env["crm"].deals.get(T, deal.id)
    req = d.change_requests[0]
    decline(env["crm"], T, d, req.id)
    assert env["repo"].get(T, q.id).request.guest_count == 100
    with pytest.raises(ChangeError):
        decline(env["crm"], T, env["crm"].deals.get(T, deal.id), req.id)


def test_approved_menu_request_applies_the_dishes(env):
    env["settings"].update(T, {"menu_lock_days": 7})
    q, deal = make_quote(env, guests=60, days=4)
    q = _send(env, q)
    env["portal"].choose_menu(q.public_token, "PKG-MEAT-STD", {"main": ["MAIN-KEBAB"]})
    _approve(env, deal.id, q.id)
    assert env["repo"].get(T, q.id).menu_choices["PKG-MEAT-STD"]["main"] == ["MAIN-KEBAB"]

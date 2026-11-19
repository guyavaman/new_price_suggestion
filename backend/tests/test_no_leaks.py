"""Stage 1: internal numbers (cost, profit, margin, floor) never reach the customer: not the
quote link, not the PDF (same public data), not the public API, not the agent's tool outputs."""

import json
import re

from fastapi.testclient import TestClient

from app.main import app
from tests.test_business import T, make_quote

INTERNAL_KEYS = re.compile(r'"(unit_cost|cost|cost_group|cost_source|components|margin|'
                           r'gross_profit|total_cost|profit|below_floor|floor|profit_floor)"')


def _internal_values(q):
    """Cost figures of this quote that must not appear anywhere public."""
    vals = set()
    for t in q.tiers:
        for ln in t.quote.lines:
            if ln.unit_cost:
                vals.add(round(ln.unit_cost * ln.quantity, 2))
    return {v for v in vals if v >= 100}  # big enough not to collide with a quantity


def test_public_quote_has_no_internal_numbers(env):
    q, _ = make_quote(env)
    view = env["portal"].view(q.public_token)
    raw = view.model_dump_json()
    assert not INTERNAL_KEYS.search(raw), INTERNAL_KEYS.search(raw)
    for v in _internal_values(q):
        assert f"{v}" not in raw and f"{v:.1f}" not in raw


def test_public_api_and_chat_have_no_internal_numbers(env, monkeypatch):
    from app import deps
    monkeypatch.delenv("OWNER_PASSWORD", raising=False)
    q, _ = make_quote(env)
    app.dependency_overrides.update({deps.get_repo: lambda: env["repo"],
                                     deps.get_portal: lambda: env["portal"],
                                     deps.get_crm: lambda: env["crm"]})
    try:
        c = TestClient(app)
        for url in (f"/public/quotes/{q.public_token}", f"/public/quotes/{q.public_token}/chat"):
            raw = c.get(url).text
            assert not INTERNAL_KEYS.search(raw), (url, INTERNAL_KEYS.search(raw))
    finally:
        app.dependency_overrides.clear()


def test_agent_tool_outputs_have_no_internal_numbers(env):
    from app.agent.service import ServiceContext, ServiceTools
    q, _ = make_quote(env)
    r = env["portal"].accept(q.public_token, "recommended")
    env["portal"].confirm_payment(q.public_token, r["payment_id"])
    q = env["repo"].get(T, q.id)

    class S:  # the minimal session the service tools need
        crm, tenant = env["crm"], T
        today = None
        conv = type("C", (), {"deal_id": None})()

        def deal(self):
            return None

        def tools(self):
            return []
    tools = ServiceTools(S(), ServiceContext(quote=q, portal=env["portal"]))
    raw = json.dumps(tools.get_booking(), ensure_ascii=False, default=str)
    assert not INTERNAL_KEYS.search(raw), INTERNAL_KEYS.search(raw)

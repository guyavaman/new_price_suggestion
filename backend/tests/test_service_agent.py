"""Customer-service mode: the quote link identifies the customer, tools stay within the rules."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.agent.sales import SalesAgent
from app.agent.service import ServiceContext
from app.llm.client import LLMClient
from app.main import app
from app.services.pricing import PricingEngine
from tests.test_business import T, make_quote
from tests.test_crm_agent import Script, _resp, _text, _tool


def _agent(env, turns):
    script = Script(turns)
    llm = LLMClient(model="t", client=SimpleNamespace(messages=script))
    catalog = env["catalog"].items(T)
    rules = env["settings"].get(T)
    agent = SalesAgent(env["crm"], catalog, PricingEngine(catalog, rules=rules), env["repo"],
                       llm=llm, rules=rules)
    return agent, script


def _booked(env):
    """An approved, deposit-paid booking."""
    q, deal = make_quote(env)
    r = env["portal"].accept(q.public_token, "recommended")
    env["portal"].confirm_payment(q.public_token, r["payment_id"])
    return env["repo"].get(T, q.id), deal


def test_service_conversation(env):
    q, deal = _booked(env)
    agent, script = _agent(env, [
        _resp([_tool("1", "get_booking", {})]),
        _resp([_text("נשארה יתרה לתשלום, הפירוט בעמוד.")]),
        _resp([_tool("2", "update_guest_count", {"guests": 120})]),
        _resp([_text("עדכנתי ל-120 אורחים.")]),
        _resp([_tool("3", "request_change", {"kind": "allergy",
                                             "details": "אורחת אחת אלרגית לאגוזים"})]),
        _resp([_text("העברתי לבעל העסק, זה מסומן דחוף.")]),
    ])
    ctx = lambda: ServiceContext(quote=env["repo"].get(T, q.id), portal=env["portal"])  # noqa
    r1 = agent.chat(T, "כמה נשאר לי לשלם?", service=ctx())
    booking = r1.actions[0]["output"]
    assert booking["package"] == "מומלץ" and booking["balance"] > 0
    assert booking["balance"] == round(booking["total_incl_vat"] - booking["deposit_paid"], 2)
    assert all("מלצר" not in i["name"] for i in booking["items"])  # customer view, no staff rows
    # service mode: identified customer, owner's FAQ in the prompt, no sales-only tools
    call = script.calls[0]
    assert "עמוד ההצעה האישי" in call["system"] and "כשרות" in call["system"]
    names = {t["name"] for t in call["tools"]}
    assert {"get_booking", "update_guest_count", "request_change"} <= names
    assert not {"save_lead", "create_quote"} & names
    conv = r1.conversation
    assert conv.quote_id == q.id and conv.deal_id == deal.id

    r2 = agent.chat(T, "אנחנו בסוף 120", service=ctx())
    assert r2.conversation.id == conv.id  # same chat on every visit
    out = r2.actions[0]["output"]
    assert out["guests"] == 120 and env["crm"].deals.get(T, deal.id).final_guest_count == 120

    agent.chat(T, "לאחת האורחות יש אלרגיה לאגוזים", service=ctx())
    task = next(t for t in env["crm"].tasks.list(T) if "אלרגיה" in t.title)
    assert task.priority == "high" and task.deal_id == deal.id


def test_service_tools_respect_rules(env):
    q, _ = make_quote(env)  # sent, not approved: guest count can't be changed by the customer
    agent, _s = _agent(env, [
        _resp([_tool("1", "update_guest_count", {"guests": 50})]),
        _resp([_text("אפשר לעדכן רק אחרי אישור ההצעה.")]),
    ])
    r = agent.chat(T, "תשני ל-50", service=ServiceContext(quote=q, portal=env["portal"]))
    assert r.actions[0]["error"] and env["repo"].get(T, q.id).request.guest_count == 100


def test_service_chat_cannot_be_reached_without_the_link(env):
    q, _ = _booked(env)
    agent, _s = _agent(env, [_resp([_text("היי")]), _resp([_text("היי")])])
    r = agent.chat(T, "שלום", service=ServiceContext(quote=q, portal=env["portal"]))
    # someone guessing the conversation id on the public sales widget gets a fresh chat
    other = agent.chat(T, "מה ההזמנה שלי?", r.conversation.id)
    assert other.conversation.id != r.conversation.id and other.conversation.quote_id is None


@pytest.fixture
def api(env):
    from app import deps
    turns = []

    def build(tenant_id):
        if not turns:
            raise RuntimeError("model unavailable")
        a, _ = _agent(env, turns[:])
        turns.clear()
        return a
    app.dependency_overrides.update({
        deps.get_repo: lambda: env["repo"], deps.get_crm: lambda: env["crm"],
        deps.get_portal: lambda: env["portal"], deps.get_agent_builder: lambda: build,
    })
    yield TestClient(app), turns
    app.dependency_overrides.clear()


def test_service_chat_api(api, env):
    client, turns = api
    q, _ = _booked(env)
    assert client.get(f"/public/quotes/{q.public_token}/chat").json()["messages"] == []
    turns += [_resp([_text("בשמחה! במה אפשר לעזור?")])]
    r = client.post(f"/public/quotes/{q.public_token}/chat", json={"message": "היי"}).json()
    assert r["reply"] == "בשמחה! במה אפשר לעזור?"
    hist = client.get(f"/public/quotes/{q.public_token}/chat").json()["messages"]
    assert [m["role"] for m in hist] == ["user", "assistant"]
    assert client.post("/public/quotes/nope/chat", json={"message": "x"}).status_code == 404
    # model down (e.g. no API key) -> clean 503, the page keeps working
    assert client.post(f"/public/quotes/{q.public_token}/chat",
                       json={"message": "עוד"}).status_code == 503



def test_replies_are_plain_text():
    from app.agent.sales import plain_text
    raw = "נשארה יתרה של **12,047 ₪**\n## סיכום\nתודה"
    assert plain_text(raw) == "נשארה יתרה של 12,047 ₪\nסיכום\nתודה"
    assert plain_text("2*3 = 6") == "2*3 = 6"

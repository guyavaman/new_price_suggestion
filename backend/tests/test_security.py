"""Owner login, read-only demo viewer, rate limits and the daily AI budget."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import security
from app.llm.client import LLMClient
from app.main import app


@pytest.fixture
def locked(monkeypatch):
    monkeypatch.setenv("OWNER_PASSWORD", "s3cret-pass")
    monkeypatch.setenv("GUEST_VIEWER", "1")
    return TestClient(app)


def test_open_without_password(monkeypatch):
    monkeypatch.delenv("OWNER_PASSWORD", raising=False)
    c = TestClient(app)
    assert c.get("/auth/status").json() == {"required": False, "guest": False}
    assert c.get("/settings").status_code == 200


def test_owner_routes_need_login(locked):
    assert locked.get("/auth/status").json() == {"required": True, "guest": True}
    r = locked.get("/settings")
    assert r.status_code == 401 and r.json()["code"] == "login"
    assert locked.get("/crm/deals").status_code == 401
    # public stays public
    assert locked.get("/health").status_code == 200
    assert locked.get("/public/quotes/nope").status_code == 404  # reached the route, not 401
    assert locked.get("/exports/deals.csv").status_code == 401  # data files are not "static"
    assert security.is_public("GET", "/main-ABC.js") and not security.is_public("POST", "/x.js")


def test_owner_login(locked):
    assert locked.post("/auth/login", json={"password": "wrong"}).status_code == 401
    r = locked.post("/auth/login", json={"password": "s3cret-pass"}).json()
    assert r["role"] == "owner"
    h = {"Authorization": f"Bearer {r['token']}"}
    assert locked.get("/settings", headers=h).status_code == 200
    assert locked.patch("/settings", headers=h, json={"waiter_ratio": 15}).status_code == 200


def test_guest_viewer_is_read_only(locked):
    r = locked.post("/auth/login", json={"guest": True}).json()
    assert r["role"] == "viewer"
    h = {"Authorization": f"Bearer {r['token']}"}
    assert locked.get("/crm/deals", headers=h).status_code == 200
    w = locked.patch("/settings", headers=h, json={"waiter_ratio": 1})
    assert w.status_code == 403 and w.json()["code"] == "viewer"
    assert locked.post("/extract", headers=h, json={"message": "x"}).status_code == 403  # no AI


def test_guest_can_be_disabled(locked, monkeypatch):
    monkeypatch.setenv("GUEST_VIEWER", "0")
    assert locked.post("/auth/login", json={"guest": True}).status_code == 401


def test_tokens(monkeypatch):
    monkeypatch.setenv("OWNER_PASSWORD", "a")
    t = security.make_token("owner", now=1000)
    assert security.verify_token(t, now=1001) == "owner"
    assert security.verify_token(t, now=1000 + 8 * 86400) is None  # expired
    assert security.verify_token(t[:-2] + "00", now=1001) is None  # tampered
    monkeypatch.setenv("OWNER_PASSWORD", "b")
    assert security.verify_token(t, now=1001) is None  # password change logs everyone out


def test_login_attempts_are_rate_limited(locked):
    for _ in range(security.LOGIN_PER_MINUTE):
        locked.post("/auth/login", json={"password": "x"})
    r = locked.post("/auth/login", json={"password": "s3cret-pass"})
    assert r.status_code == 429 and "Retry-After" in r.headers


def test_chat_is_rate_limited(monkeypatch):
    monkeypatch.delenv("OWNER_PASSWORD", raising=False)
    c = TestClient(app)
    codes = [c.post("/public/quotes/nope/chat", json={"message": "hi"}).status_code
             for _ in range(security.CHAT_PER_MINUTE + 1)]
    assert codes[:-1] == [404] * security.CHAT_PER_MINUTE and codes[-1] == 429


def test_daily_ai_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(security, "STORE_DIR", tmp_path)
    monkeypatch.setenv("AI_DAILY_CALLS", "2")
    calls = []

    def create(**kw):
        calls.append(kw)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text="ok")],
                               usage=SimpleNamespace(input_tokens=1, output_tokens=1))
    llm = LLMClient(model="t", client=SimpleNamespace(create=create))
    llm._metered = True  # behave like the real API client
    llm._client = SimpleNamespace(messages=SimpleNamespace(create=create))
    for _ in range(2):
        llm.run_agent(system="s", user="u", tools=[])
    with pytest.raises(security.AiBudgetExceeded):
        llm.run_agent(system="s", user="u", tools=[])
    assert len(calls) == 2 and security.ai_budget.used_today() == 2


def test_long_conversation_stops_calling_the_model(env):
    from app.agent.sales import LONG_CHAT_REPLY, MAX_CUSTOMER_MESSAGES, SalesAgent
    from app.crm.models import ChatMessage, ChatRole, Conversation
    from app.services.pricing import PricingEngine
    catalog = env["catalog"].items("acme")
    called = []
    llm = LLMClient(model="t", client=SimpleNamespace(
        messages=SimpleNamespace(create=lambda **k: called.append(k))))
    agent = SalesAgent(env["crm"], catalog, PricingEngine(catalog), env["repo"], llm=llm)
    conv = Conversation(tenant_id="acme", messages=[
        ChatMessage(role=ChatRole.user, text=f"m{i}") for i in range(MAX_CUSTOMER_MESSAGES)])
    env["crm"].conversations.put(conv)
    r = agent.chat("acme", "עוד אחת", conv.id)
    assert r.reply == LONG_CHAT_REPLY and not called
    assert agent.chat("acme", "ועוד", conv.id).reply == ""  # said once, then quiet

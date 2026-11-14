from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.agent.sales import SalesAgent
from app.crm.models import Actor, Deal, DealStage, Source
from app.crm.scoring import score
from app.crm.service import MAX_EVENTS_PER_DAY, CrmService
from app.integrations.adapters.internal import InternalCrmAdapter
from app.integrations.base import ExternalRefs
from app.integrations.canonical import EventType, build_event
from app.integrations.config import IntegrationConfig, TenantConfig
from app.llm.client import LLMClient
from app.main import app, get_crm, get_repo, get_sales_agent, get_tenant_loader
from app.repositories.quotes import JsonQuoteRepository
from app.schemas.quote import QuoteStatus

T = "acme"
EVENT_DAY = date.today() + timedelta(days=30)


@pytest.fixture
def crm(tmp_path):
    return CrmService(tmp_path)


@pytest.fixture
def repo(tmp_path):
    return JsonQuoteRepository(tmp_path / "q.json")


# ---------- CRM service ----------

def test_customer_dedupe_by_phone_and_email(crm):
    a = crm.upsert_customer(T, name="מיכל", phone="050-123 4567")
    b = crm.upsert_customer(T, phone="+972501234567", email="M@Example.com")
    assert a.id == b.id and b.name == "מיכל" and b.email == "m@example.com"
    assert crm.upsert_customer("other", phone="0501234567").id != a.id  # tenant isolation


def test_deal_score_title_and_stage_log(crm):
    c = crm.upsert_customer(T, name="דנה", phone="0521112222")
    d = crm.save_deal(Deal(tenant_id=T, customer_id=c.id, title="", event_type="wedding",
                           guest_count=150, event_date=EVENT_DAY, kashrut="kosher",
                           meal_type="meat"))
    assert d.title.startswith("חתונה · דנה · 150 אורחים")
    assert d.lead_score == 80 and any("60 יום" in r for r in d.score_reasons)
    crm.move_stage(T, d.id, DealStage.quoted, Actor.agent)
    tl = crm.timeline(T, d.id)
    assert tl[0].kind == "stage" and tl[0].meta == {"from": "new", "to": "quoted"}


def test_score_past_event_is_zero():
    d = Deal(tenant_id=T, customer_id="x", title="", event_date=date(2020, 1, 1))
    assert score(d, None)[0] == 0


def test_availability_capacity(crm):
    c = crm.upsert_customer(T, name="x")
    for _ in range(MAX_EVENTS_PER_DAY):
        crm.save_deal(Deal(tenant_id=T, customer_id=c.id, title="", event_date=EVENT_DAY,
                           guest_count=50, stage=DealStage.won))
    assert not crm.availability(T, EVENT_DAY).available
    other = EVENT_DAY + timedelta(days=1)
    crm.save_deal(Deal(tenant_id=T, customer_id=c.id, title="", event_date=other,
                       guest_count=550, stage=DealStage.won))
    av = crm.availability(T, other, guests=100)
    assert not av.available and av.remaining_guests == 50
    assert crm.availability(T, other, guests=40).available


def test_dashboard(crm):
    c = crm.upsert_customer(T, name="x", phone="0500000000")
    won = crm.save_deal(Deal(tenant_id=T, customer_id=c.id, title="", value=40000,
                             event_date=EVENT_DAY, source=Source.web_chat))
    crm.move_stage(T, won.id, DealStage.won)
    lost = crm.save_deal(Deal(tenant_id=T, customer_id=c.id, title="", value=10000))
    crm.move_stage(T, lost.id, DealStage.lost, reason="מחיר")
    crm.save_deal(Deal(tenant_id=T, customer_id=c.id, title="", value=25000,
                       stage=DealStage.quoted))
    dash = crm.dashboard(T)
    assert dash.open_pipeline_value == 25000 and dash.won_value_this_month == 40000
    assert dash.win_rate == 0.5 and dash.upcoming_events[0].id == won.id


# ---------- sales agent (scripted model) ----------

def _tool(i, name, inp):
    return SimpleNamespace(type="tool_use", id=i, name=name, input=inp,
                           model_dump=lambda: {"type": "tool_use", "id": i, "name": name,
                                               "input": inp})


def _text(t):
    return SimpleNamespace(type="text", text=t)


def _resp(blocks):
    return SimpleNamespace(content=blocks, usage=SimpleNamespace(input_tokens=1, output_tokens=1))


class Script:
    def __init__(self, turns):
        self.turns, self.calls = list(turns), []

    def create(self, **kw):
        self.calls.append(kw)
        return self.turns.pop(0)


@pytest.fixture
def agent_factory(crm, repo, catalog, engine):
    def make(turns):
        script = Script(turns)
        llm = LLMClient(model="t", client=SimpleNamespace(messages=script))
        return SalesAgent(crm, catalog, engine, repo, llm=llm), script
    return make


def test_agent_full_sales_conversation(agent_factory, crm, repo):
    d = EVENT_DAY.isoformat()
    agent, script = agent_factory([
        # turn 1: event details -> save lead, availability, estimate
        _resp([_tool("1", "save_lead", {"event_type": "bar_bat_mitzvah", "guest_count": 120,
                                        "event_date": d, "meal_type": "meat",
                                        "kashrut": "kosher",
                                        "dietary": [{"tag": "vegan", "guest_count": 8}]}),
               _tool("2", "check_availability", {"event_date": d, "guest_count": 120})]),
        _resp([_tool("3", "estimate_price", {"guest_count": 120, "meal_type": "meat"})]),
        _resp([_text("מזל טוב! התאריך פנוי 🎉 ההערכה מתחילה בכ-₪300 לאורח. איך קוראים לך?")]),
        # turn 2: contact -> quote
        _resp([_tool("4", "save_lead", {"name": "מיכל לוי", "phone": "050-123 4567"}),
               _tool("5", "create_quote", {"requested_items": ["בר אלכוהול"]})]),
        _resp([_text("שלחתי לך הצעה מסודרת עם 3 חבילות!")]),
        # turn 3: discount -> handoff
        _resp([_tool("6", "handoff_to_human", {"reason": "מבקשת הנחה ורוצה לסגור",
                                                "ready_to_book": True, "urgent": True})]),
        _resp([_text("העברתי לנציג שיחזור אלייך תוך שעה.")]),
    ])
    r1 = agent.chat(T, f"היי, בר מצווה ל-120 איש ב-{d}, בשרי כשר, 8 טבעונים")
    cid = r1.conversation.id
    assert r1.deal and r1.deal.stage == "contacted" and r1.deal.dietary == ["vegan:8"]
    assert [a["tool"] for a in r1.actions] == ["save_lead", "check_availability", "estimate_price"]
    est = r1.actions[2]["output"]["packages"]
    assert [p["name"] for p in est] == ["בסיס", "מומלץ", "פרימיום"]

    r2 = agent.chat(T, "אני מיכל, 050-1234567, תשלחי הצעה", cid)
    deal = r2.deal
    assert r2.customer.phone == "+972501234567" and deal.stage == "quoted"
    q = repo.get(T, deal.quote_ids[0])
    assert deal.value == q.tier("recommended").quote.total
    assert q.request.contact.name == "מיכל לוי" and q.request.guest_count == 120
    # history is sent back to the model on later turns
    assert len(script.calls[3]["messages"]) >= 3

    r3 = agent.chat(T, "אפשר הנחה? רוצה לסגור", cid)
    assert r3.conversation.status == "handed_off"
    assert crm.deals.get(T, deal.id).stage == "negotiation"
    task = crm.tasks.list(T)[0]
    assert task.priority == "high" and task.created_by == "agent"

    # after handoff the AI is silent; the message is logged for the human
    n_calls = len(script.calls)
    r4 = agent.chat(T, "הלו?", cid)
    assert len(script.calls) == n_calls and "נציג" in r4.reply
    kinds = [a.kind for a in crm.timeline(T, deal.id)]
    assert {"chat", "quote", "stage", "handoff", "task"} <= set(kinds)


def test_agent_tool_guardrails(agent_factory):
    past = (date.today() - timedelta(days=3)).isoformat()
    agent, script = agent_factory([
        _resp([_tool("1", "check_availability", {"event_date": past}),
               _tool("2", "create_quote", {}),
               _tool("3", "estimate_price", {"guest_count": 99999})]),
        _resp([_text("אפשר תאריך אחר?")]),
    ])
    r = agent.chat(T, "אירוע אתמול")
    assert [a["error"] for a in r.actions] == [True, True, True]
    errors = script.calls[1]["messages"][-1]["content"]
    assert "עבר" in errors[0]["content"] and "save_lead" in errors[1]["content"]


def test_agent_planner_failure_falls_back(agent_factory, crm, repo):
    agent, _ = agent_factory([
        _resp([_tool("1", "save_lead", {"guest_count": 40, "meal_type": "dairy",
                                        "name": "רון", "phone": "0541231234"}),
               _tool("2", "create_quote", {})]),
        _resp([_text("הנה ההצעה")]),
    ])

    def broken(req):
        raise RuntimeError("LLM down")
    agent.planner = broken
    r = agent.chat(T, "40 איש חלבי")
    q = repo.get(T, r.deal.quote_ids[0])
    assert q.plan.lines[0].sku == "PKG-DAIRY-STD"


# ---------- quote events -> our CRM ----------

def test_internal_adapter_creates_and_advances_deal(crm, repo, catalog, engine,
                                                    bar_mitzvah_req, bar_mitzvah_plan):
    from app.services.quotes import create_quote
    q = create_quote(repo, T, bar_mitzvah_req, bar_mitzvah_plan, catalog, engine, "מייל")
    adapter = InternalCrmAdapter(IntegrationConfig(id="crm", type="internal"), crm=crm)
    res = adapter.sync(build_event(q, EventType.created), ExternalRefs())
    deal = crm.deals.get(T, res.refs.deal_id)
    assert deal.stage == "new" and deal.value == q.tier().quote.total
    q.status, q.selected_tier = QuoteStatus.approved, "premium"
    adapter.sync(build_event(q, EventType.approved), res.refs)
    deal = crm.deals.get(T, deal.id)
    assert deal.stage == "won" and deal.value == q.tier("premium").quote.total


# ---------- API ----------

@pytest.fixture
def api(crm, repo, agent_factory):
    tenants = {T: TenantConfig(tenant_id=T, name="Acme")}
    app.dependency_overrides.update({get_crm: lambda: crm, get_repo: lambda: repo,
                                     get_tenant_loader: lambda: tenants.get})
    yield TestClient(app), {"X-Tenant-ID": T}
    app.dependency_overrides.clear()


def test_crm_api_flow(api, crm):
    c, h = api
    r = c.post("/crm/deals", headers=h, json={
        "customer": {"name": "יוסי", "phone": "0509998888"}, "event_type": "corporate",
        "guest_count": 60, "event_date": EVENT_DAY.isoformat(), "note": "הגיע מהמלצה"})
    assert r.status_code == 201
    did = r.json()["id"]
    assert c.post(f"/crm/deals/{did}/stage", headers=h,
                  json={"stage": "lost"}).status_code == 422  # reason required
    c.post(f"/crm/deals/{did}/stage", headers=h, json={"stage": "negotiation"})
    c.post("/crm/tasks", headers=h, json={"title": "לשלוח תפריט", "deal_id": did})
    detail = c.get(f"/crm/deals/{did}", headers=h).json()
    assert detail["deal"]["stage"] == "negotiation" and detail["customer"]["name"] == "יוסי"
    assert {a["kind"] for a in detail["timeline"]} >= {"note", "stage", "task"}
    assert c.get("/crm/customers?q=0509998888", headers=h).json()[0]["name"] == "יוסי"
    dash = c.get("/crm/dashboard", headers=h).json()
    assert dash["open_pipeline_value"] == 0 and dash["open_tasks"] == 1
    assert c.get(f"/crm/deals/{did}", headers={"X-Tenant-ID": "nope"}).status_code == 404


def test_agent_api_and_human_takeover(api, agent_factory, crm):
    c, h = api
    agent, _ = agent_factory([
        _resp([_tool("1", "handoff_to_human", {"reason": "שאלה על אלרגיות"})]),
        _resp([_text("מעבירה לנציג")]),
    ])
    app.dependency_overrides[get_sales_agent] = lambda: agent
    r = c.post("/agent/chat", headers=h, json={"message": "יש לכם תפריט ללא שומשום?"}).json()
    assert r["status"] == "handed_off" and r["actions"] == ["handoff_to_human"]
    assert "deal" not in r  # widget response stays minimal
    cid = r["conversation_id"]
    inbox = c.get("/crm/conversations?status=handed_off", headers=h).json()
    assert inbox[0]["id"] == cid
    conv = c.post(f"/crm/conversations/{cid}/reply", headers=h,
                  json={"text": "היי, כן! יש לנו כמה מנות"}).json()
    assert conv["messages"][-1]["by"] == "human"
    assert c.post(f"/crm/conversations/{cid}/resume", headers=h).json()["status"] == "active"

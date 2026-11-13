import json
import time

import httpx
import pytest

from app.integrations import base
from app.integrations.adapters.hubspot import HubSpotAdapter
from app.integrations.adapters.monday import MondayAdapter
from app.integrations.adapters.webhook import WebhookAdapter, sign, verify_signature
from app.integrations.base import ExternalRefs
from app.integrations.canonical import EventType, build_event, normalize_il_phone
from app.integrations.config import IntegrationConfig, TenantConfig, apply_mapping
from app.integrations.export import deals_csv, line_items_csv
from app.integrations.sync import SyncLog, SyncService
from app.repositories.quotes import StoredQuote
from app.schemas.extraction import ContactInfo
from app.schemas.quote import QuoteStatus, TierQuote
from app.services.tiers import build_tiers


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(base.time, "sleep", lambda s: None)


@pytest.fixture
def secrets(monkeypatch):
    monkeypatch.setenv("T_SECRET", "s3cret")
    monkeypatch.setenv("T_TOKEN", "tok")


@pytest.fixture
def quote(bar_mitzvah_req, bar_mitzvah_plan, catalog, engine):
    req = bar_mitzvah_req.model_copy(update={"contact": ContactInfo(
        name="מיכל לוי", phone="050-123 4567", email="michal@example.com")})
    tiers = [TierQuote(key=t.key, name=t.name, changes=t.changes, plan=t.plan, quote=t.quote)
             for t in build_tiers(req, bar_mitzvah_plan, catalog, engine)]
    return StoredQuote(tenant_id="acme", number="Q-2026-1001", request=req,
                       plan=bar_mitzvah_plan, tiers=tiers)


# ---------- canonical + mapping ----------

def test_phone_normalisation():
    assert normalize_il_phone("050-123 4567") == "+972501234567"
    assert normalize_il_phone("+972 3-1234567") == "+97231234567"
    assert normalize_il_phone("12345") is None


def test_canonical_event(quote):
    e = build_event(quote, EventType.created)
    assert e.contact.phone == "+972501234567" and e.contact.first_name == "מיכל"
    assert e.deal.stage == "new" and e.deal.tier == "recommended"
    assert e.deal.amount_total == quote.tier().quote.total
    assert "120 אורחים" in e.deal.title and "03.12.2026" in e.deal.title
    assert len(e.line_items) == len(quote.tier().quote.lines)


def test_mapping_fields_templates_and_skips_empty(quote):
    e = build_event(quote, EventType.created)
    out = apply_mapping(e, {"dealname": "{title}", "amount": "amount_total",
                            "summary": "{guest_count} · {kashrut}", "loc2": "dietary_summary",
                            "company": "contact.company"}, "deal")
    assert out["amount"] == e.deal.amount_total
    assert out["summary"] == "120 · kosher"
    assert "company" not in out  # empty values never overwrite CRM data
    with pytest.raises(KeyError):
        apply_mapping(e, {"x": "no_such_field"}, "deal")


def test_approved_quote_maps_to_won(quote):
    quote.status = QuoteStatus.approved
    assert build_event(quote, EventType.approved).deal.stage == "won"


# ---------- webhook ----------

def wh_config(**settings):
    return IntegrationConfig(id="wh", type="webhook",
                             settings={"url": "https://crm.test/hook", "secret_env": "T_SECRET",
                                       **settings},
                             mapping={"deal": {"value": "amount_total"},
                                      "stages": {"new": "ליד חדש"}})


def test_webhook_signs_and_maps(quote, secrets):
    seen = {}

    def handler(req: httpx.Request):
        seen["req"] = req
        return httpx.Response(200, json={"deal_id": "D-9"})

    adapter = WebhookAdapter(wh_config(), httpx.Client(transport=httpx.MockTransport(handler)))
    e = build_event(quote, EventType.created)
    res = adapter.sync(e, ExternalRefs())
    req = seen["req"]
    assert res.ok and res.refs.deal_id == "D-9"
    assert req.headers["X-QuoteAgent-Delivery"] == e.id
    assert verify_signature("s3cret", req.headers["X-QuoteAgent-Timestamp"], req.content,
                            req.headers["X-QuoteAgent-Signature"])
    body = json.loads(req.content)
    assert body["mapped"]["deal"] == {"value": e.deal.amount_total, "stage": "ליד חדש"}
    assert body["schema_version"] == "1.0"


def test_signature_rejects_tampering_and_replay():
    ts = str(int(time.time()))
    sig = sign("k", ts, b'{"a":1}')
    assert verify_signature("k", ts, b'{"a":1}', sig)
    assert not verify_signature("k", ts, b'{"a":2}', sig)
    assert not verify_signature("other", ts, b'{"a":1}', sig)
    assert not verify_signature("k", ts, b'{"a":1}', sig, now=time.time() + 3600)


def test_webhook_retries_5xx_then_succeeds(quote, secrets):
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(503) if len(calls) < 3 else httpx.Response(204)

    adapter = WebhookAdapter(wh_config(), httpx.Client(transport=httpx.MockTransport(handler)))
    assert adapter.sync(build_event(quote, EventType.created), ExternalRefs()).ok
    assert len(calls) == 3


def test_webhook_4xx_fails_fast_not_retryable(quote, secrets):
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(400, text="bad field")

    adapter = WebhookAdapter(wh_config(), httpx.Client(transport=httpx.MockTransport(handler)))
    res = adapter.sync(build_event(quote, EventType.created), ExternalRefs())
    assert not res.ok and not res.retryable and len(calls) == 1


# ---------- HubSpot ----------

class FakeHubSpot:
    def __init__(self, existing_contact=None):
        self.calls = []
        self.existing_contact = existing_contact
        self.n = 0

    def __call__(self, req: httpx.Request):
        body = json.loads(req.content) if req.content else None
        self.calls.append((req.method, req.url.path, body))
        assert req.headers["Authorization"] == "Bearer tok"
        p = req.url.path
        if p.endswith("/contacts/search"):
            return httpx.Response(200, json={"results": [{"id": self.existing_contact}]
                                             if self.existing_contact else []})
        if req.method == "POST":
            self.n += 1
            return httpx.Response(201, json={"id": f"{p.split('/')[-1]}-{self.n}"})
        return httpx.Response(200, json={})


def hs(fake):
    cfg = IntegrationConfig(id="hs", type="hubspot", settings={"token_env": "T_TOKEN"})
    return HubSpotAdapter(cfg, httpx.Client(base_url="https://api.hubapi.com",
                                            transport=httpx.MockTransport(fake)))


def test_hubspot_create_flow(quote, secrets):
    fake = FakeHubSpot()
    res = hs(fake).sync(build_event(quote, EventType.created), ExternalRefs())
    assert res.ok
    methods = [(m, p) for m, p, _ in fake.calls]
    assert ("POST", "/crm/v3/objects/contacts") in methods
    assert ("POST", "/crm/v3/objects/deals") in methods
    deal_body = next(b for m, p, b in fake.calls if p == "/crm/v3/objects/deals")
    assert deal_body["properties"]["dealstage"] == "appointmentscheduled"
    assert deal_body["properties"]["amount"] == quote.tier().quote.total
    n_lines = len(quote.tier().quote.lines)
    assert len(res.refs.extra["line_item_ids"]) == n_lines
    assocs = [p for m, p, _ in fake.calls if m == "PUT"]
    assert sum("/line_items/" in p for p in assocs) == n_lines
    assert any("/deals/" in p and p.endswith(res.refs.contact_id) for p in assocs)


def test_hubspot_update_patches_and_replaces_line_items(quote, secrets):
    fake = FakeHubSpot()
    refs = ExternalRefs(contact_id="c-1", deal_id="d-1", extra={"line_item_ids": ["li-1", "li-2"]})
    quote.status = QuoteStatus.approved
    res = hs(fake).sync(build_event(quote, EventType.approved), refs)
    assert res.ok and res.refs.deal_id == "d-1"
    calls = [(m, p) for m, p, _ in fake.calls]
    assert ("PATCH", "/crm/v3/objects/deals/d-1") in calls
    assert ("POST", "/crm/v3/objects/deals") not in calls  # no duplicate deal
    assert ("DELETE", "/crm/v3/objects/line_items/li-1") in calls
    patch = next(b for m, p, b in fake.calls if p == "/crm/v3/objects/deals/d-1")
    assert patch["properties"]["dealstage"] == "closedwon"


def test_hubspot_reuses_existing_contact(quote, secrets):
    fake = FakeHubSpot(existing_contact="c-77")
    res = hs(fake).sync(build_event(quote, EventType.created), ExternalRefs())
    assert res.refs.contact_id == "c-77"
    assert ("POST", "/crm/v3/objects/contacts") not in [(m, p) for m, p, _ in fake.calls]


# ---------- monday ----------

def test_monday_create_then_update(quote, secrets):
    queries = []

    def handler(req):
        body = json.loads(req.content)
        queries.append(body)
        assert req.headers["Authorization"] == "tok"
        if "create_item" in body["query"]:
            return httpx.Response(200, json={"data": {"create_item": {"id": "555"}}})
        return httpx.Response(200, json={"data": {"x": {"id": "1"}}})

    cfg = IntegrationConfig(id="mn", type="monday", settings={
        "token_env": "T_TOKEN", "board_id": 42, "status_column": "status",
        "column_types": {"date4": "date", "phone": "phone"}},
        mapping={"contact": {"phone": "phone"}, "deal": {"date4": "event_date"},
                 "stages": {"new": "חדש", "won": "נסגר"}})
    adapter = MondayAdapter(cfg, httpx.Client(transport=httpx.MockTransport(handler)))
    res = adapter.sync(build_event(quote, EventType.created), ExternalRefs())
    assert res.ok and res.refs.deal_id == "555"
    cols = json.loads(queries[0]["variables"]["cols"])
    assert cols["status"] == {"label": "חדש"}
    assert cols["date4"] == {"date": "2026-12-03"}
    assert cols["phone"]["phone"] == "+972501234567"
    assert "create_update" in queries[1]["query"]  # line items posted as a note

    queries.clear()
    quote.status = QuoteStatus.approved
    adapter.sync(build_event(quote, EventType.approved), res.refs)
    assert "change_multiple_column_values" in queries[0]["query"]
    assert json.loads(queries[0]["variables"]["cols"])["status"] == {"label": "נסגר"}


def test_monday_graphql_error_is_failure(quote, secrets):
    cfg = IntegrationConfig(id="mn", type="monday",
                            settings={"token_env": "T_TOKEN", "board_id": 1})
    client = httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"errors": [{"message": "bad column"}]})))
    res = MondayAdapter(cfg, client).sync(build_event(quote, EventType.created), ExternalRefs())
    assert not res.ok and "bad column" in res.detail


# ---------- sync service ----------

class RecordingAdapter:
    def __init__(self, config, results):
        self.config, self.results, self.seen = config, results, []

    def sync(self, event, refs):
        self.seen.append((event, refs))
        return self.results.pop(0)


def test_sync_remembers_refs_and_is_idempotent(quote, tmp_path):
    integ = IntegrationConfig(id="crm", type="webhook")
    tenant = TenantConfig(tenant_id="acme", name="Acme", integrations=[integ])
    adapter = RecordingAdapter(integ, [
        base.SyncResult(ok=True, refs=ExternalRefs(deal_id="D1")),
        base.SyncResult(ok=True, refs=ExternalRefs(deal_id="D1")),
    ])
    svc = SyncService(SyncLog(tmp_path / "log.json"), lambda cfg: adapter)
    first = svc.deliver(tenant, quote, EventType.created)[0]
    assert first.ok
    svc.deliver(tenant, quote, EventType.updated)
    assert adapter.seen[1][1].deal_id == "D1"  # second call updates, not creates
    # same event delivered again -> skipped
    ev = first.model_copy()
    assert svc.log.delivered(ev.event_id, "crm")


def test_sync_respects_event_subscriptions_and_disabled(quote, tmp_path):
    a = IntegrationConfig(id="a", type="webhook", events=["quote.approved"])
    b = IntegrationConfig(id="b", type="webhook", enabled=False)
    tenant = TenantConfig(tenant_id="acme", name="Acme", integrations=[a, b])
    svc = SyncService(SyncLog(tmp_path / "l.json"), lambda c: pytest.fail("should not run"))
    assert svc.deliver(tenant, quote, EventType.created) == []


def test_failed_delivery_is_retried_later(quote, tmp_path):
    integ = IntegrationConfig(id="crm", type="webhook")
    tenant = TenantConfig(tenant_id="acme", name="Acme", integrations=[integ])
    results = [base.SyncResult(ok=False, retryable=True, detail="503"),
               base.SyncResult(ok=True, refs=ExternalRefs(deal_id="D2"))]
    adapter = RecordingAdapter(integ, results)
    svc = SyncService(SyncLog(tmp_path / "l.json"), lambda c: adapter)
    assert not svc.deliver(tenant, quote, EventType.created)[0].ok
    retried = svc.retry_failed(lambda tid: tenant)
    assert retried[0].ok and retried[0].attempts == 2
    assert adapter.seen[0][0].id == adapter.seen[1][0].id  # same event id = idempotent receiver
    assert svc.retry_failed(lambda tid: tenant) == []


def test_missing_secret_is_logged_not_raised(quote, tmp_path, monkeypatch):
    monkeypatch.delenv("T_SECRET", raising=False)
    integ = wh_config()
    tenant = TenantConfig(tenant_id="acme", name="Acme", integrations=[integ])
    rec = SyncService(SyncLog(tmp_path / "l.json")).deliver(tenant, quote, EventType.created)[0]
    assert not rec.ok and "T_SECRET" in rec.detail


# ---------- exports ----------

def test_csv_exports(quote):
    e = build_event(quote, EventType.updated)
    deals = deals_csv([e])
    assert deals.startswith("﻿") and "Q-2026-1001" in deals and "+972501234567" in deals
    lines = line_items_csv([e])
    assert lines.count("Q-2026-1001") == len(e.line_items)


def test_end_to_end_with_example_receiver(quote, monkeypatch):
    """Our webhook adapter against the receiver we ship to clients."""
    monkeypatch.setenv("T_SECRET", "shared")
    from examples import webhook_receiver as rx
    from fastapi.testclient import TestClient
    monkeypatch.setattr(rx, "SECRET", "shared")
    rx.seen_deliveries.clear()
    cfg = IntegrationConfig(id="rx", type="webhook",
                            settings={"url": "/hooks/quotes", "secret_env": "T_SECRET"})
    adapter = WebhookAdapter(cfg, TestClient(rx.app))
    e = build_event(quote, EventType.created)
    first = adapter.sync(e, ExternalRefs())
    assert first.ok and first.refs.deal_id.startswith("crm-")
    assert adapter.sync(e, ExternalRefs()).ok  # duplicate delivery accepted, not re-processed
    monkeypatch.setattr(rx, "SECRET", "wrong")
    assert not adapter.sync(build_event(quote, EventType.updated), ExternalRefs()).ok

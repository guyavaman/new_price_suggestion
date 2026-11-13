from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.integrations.config import IntegrationConfig, TenantConfig
from app.integrations.sync import SyncLog, SyncService
from app.llm.client import LLMCallStats
from app.main import (
    app,
    get_corrections,
    get_extraction_service,
    get_menu_planner,
    get_repo,
    get_sync,
    get_tenant_loader,
)
from app.repositories.quotes import JsonQuoteRepository
from app.services.corrections import CorrectionStore

STATS = LLMCallStats(model="t", input_tokens=10, output_tokens=5, latency_ms=100)


class CaptureAdapter:
    def __init__(self):
        self.events = []

    def sync(self, event, refs):
        from app.integrations.base import ExternalRefs, SyncResult
        self.events.append(event)
        return SyncResult(ok=True, refs=ExternalRefs(deal_id="D1"))


@pytest.fixture
def api(tmp_path, bar_mitzvah_req, bar_mitzvah_plan, monkeypatch):
    capture = CaptureAdapter()
    tenants = {
        "acme": TenantConfig(tenant_id="acme", name="Acme", api_key_env="ACME_KEY",
                             integrations=[IntegrationConfig(id="crm", type="webhook")]),
        "other": TenantConfig(tenant_id="other", name="Other"),
    }
    monkeypatch.setenv("ACME_KEY", "k-123")
    repo = JsonQuoteRepository(tmp_path / "q.json")
    sync = SyncService(SyncLog(tmp_path / "s.json"), lambda cfg: capture)
    app.dependency_overrides.update({
        get_extraction_service: lambda: SimpleNamespace(
            extract=lambda m, d: (bar_mitzvah_req, STATS), prompt_version="x"),
        get_menu_planner: lambda: SimpleNamespace(plan=lambda req: (bar_mitzvah_plan, STATS)),
        get_repo: lambda: repo,
        get_sync: lambda: sync,
        get_tenant_loader: lambda: tenants.get,
    })
    yield TestClient(app), capture
    app.dependency_overrides.clear()


H = {"X-Tenant-ID": "acme", "X-API-Key": "k-123"}


def test_auth_required_and_unknown_tenant(api):
    c, _ = api
    body = {"message": "x"}
    assert c.post("/quotes", json=body, headers={"X-Tenant-ID": "acme"}).status_code == 401
    assert c.post("/quotes", json=body, headers={"X-Tenant-ID": "nope"}).status_code == 404


def test_full_lifecycle_reaches_crm(api):
    c, capture = api
    r = c.post("/quotes", json={"message": "בר מצווה 120 איש"}, headers=H)
    assert r.status_code == 201, r.text
    q = r.json()["quote"]
    assert q["number"].startswith("Q-") and len(q["tiers"]) == 3
    assert r.json()["sync"][0]["ok"] is True
    assert capture.events[-1].type == "quote.created"

    r = c.post(f"/quotes/{q['id']}/status", json={"status": "approved", "tier": "premium"},
               headers=H)
    assert r.status_code == 200
    ev = capture.events[-1]
    assert ev.type == "quote.approved" and ev.deal.stage == "won" and ev.deal.tier == "premium"

    # approved is final
    assert c.post(f"/quotes/{q['id']}/status", json={"status": "sent"},
                  headers=H).status_code == 409
    log = c.get(f"/quotes/{q['id']}/sync-log", headers=H).json()
    assert [x["event_type"] for x in log] == ["quote.created", "quote.approved"]


def test_tenant_isolation(api):
    c, _ = api
    qid = c.post("/quotes", json={"message": "x"}, headers=H).json()["quote"]["id"]
    assert c.get(f"/quotes/{qid}", headers={"X-Tenant-ID": "other"}).status_code == 404
    assert c.get("/quotes", headers={"X-Tenant-ID": "other"}).json() == []


def test_event_preview_schema_and_exports(api):
    c, _ = api
    qid = c.post("/quotes", json={"message": "x"}, headers=H).json()["quote"]["id"]
    ev = c.get(f"/quotes/{qid}/event", headers=H).json()
    assert ev["schema_version"] == "1.0" and ev["deal"]["quote_id"] == qid
    assert "QuoteEvent" in c.get("/integrations/schema").json()["title"]
    csv = c.get("/exports/deals.csv", headers=H)
    assert csv.status_code == 200 and "text/csv" in csv.headers["content-type"]
    assert ev["deal"]["quote_number"] in csv.text


def test_corrections_and_accuracy_endpoints(tmp_path):
    store = CorrectionStore(tmp_path / "c.json")
    app.dependency_overrides[get_corrections] = lambda: store
    try:
        c = TestClient(app)
        assert c.post("/corrections", json={"customer_wording": "קנאפה",
                                            "correct_sku": "PKG-FINGER"}).status_code == 201
        assert c.post("/corrections", json={"customer_wording": "x",
                                            "correct_sku": "NOPE"}).status_code == 422
        c.post("/reviews", json={"lines_total": 8, "lines_corrected": 2})
        c.post("/reviews", json={"lines_total": 8, "lines_corrected": 0})
        series = c.get("/metrics/accuracy").json()
        assert [p["accuracy"] for p in series] == [0.75, 0.875]
    finally:
        app.dependency_overrides.clear()

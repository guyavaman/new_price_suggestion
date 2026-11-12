from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.llm.client import LLMCallStats
from app.main import (
    app,
    get_corrections,
    get_extraction_service,
    get_menu_planner,
)
from app.schemas.extraction import ExtractedRequest
from app.services.corrections import CorrectionStore

STATS = LLMCallStats(model="t", input_tokens=10, output_tokens=5, latency_ms=100)


def test_quote_pipeline_returns_three_tiers(bar_mitzvah_req, bar_mitzvah_plan, tmp_path):
    app.dependency_overrides[get_extraction_service] = lambda: SimpleNamespace(
        extract=lambda m, d: (bar_mitzvah_req, STATS), prompt_version="x")
    app.dependency_overrides[get_menu_planner] = lambda: SimpleNamespace(
        plan=lambda req: (bar_mitzvah_plan, STATS))
    try:
        r = TestClient(app).post("/quote", json={"message": "בר מצווה 120 איש"})
        assert r.status_code == 200, r.text
        body = r.json()
        totals = [t["quote"]["total"] for t in body["tiers"]]
        assert [t["key"] for t in body["tiers"]] == ["basic", "recommended", "premium"]
        assert totals == sorted(totals)
        assert body["latency_ms"] == 200
    finally:
        app.dependency_overrides.clear()


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


def test_request_schema_roundtrip():
    # the edit endpoint receives request+plan back from the UI; make sure they roundtrip
    req = ExtractedRequest(language="he", guest_count=10)
    assert ExtractedRequest.model_validate_json(req.model_dump_json()) == req

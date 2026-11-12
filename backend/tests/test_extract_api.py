"""API + service tests with a fake Anthropic client — no network, no API key."""

from datetime import date
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.llm.client import LLMClient
from app.main import app, get_extraction_service
from app.services.extraction import ExtractionService

FAKE_TOOL_INPUT = {
    "language": "he",
    "event_type": "corporate",
    "guest_count": 40,
    "event_date": "2026-11-19",
    "meal_type": "dairy",
    "requested_items": [{"description": "פינגר פוד"}],
    "missing_info": ["location"],
}


class FakeMessages:
    def __init__(self, tool_input):
        self.tool_input = tool_input
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        block = SimpleNamespace(type="tool_use", name="record_request", input=self.tool_input)
        return SimpleNamespace(
            content=[block], usage=SimpleNamespace(input_tokens=900, output_tokens=120)
        )


def make_service(tool_input=FAKE_TOOL_INPUT):
    fake = SimpleNamespace(messages=FakeMessages(tool_input))
    return ExtractionService(LLMClient(model="test-model", client=fake)), fake.messages


def test_service_forces_tool_and_passes_reference_date():
    service, messages = make_service()
    result, stats = service.extract("היי צריך אוכל", date(2026, 11, 12))
    assert result.guest_count == 40
    assert stats.input_tokens == 900
    kw = messages.last_kwargs
    assert kw["tool_choice"] == {"type": "tool", "name": "record_request"}
    assert "2026-11-12" in kw["messages"][0]["content"]
    assert "<customer_message>" in kw["messages"][0]["content"]


def test_invalid_model_output_is_rejected():
    service, _ = make_service({"language": "he", "guest_count": "lots"})
    try:
        service.extract("x")
    except Exception as e:
        assert "guest_count" in str(e)
    else:
        raise AssertionError("expected validation error")


def test_extract_endpoint():
    service, _ = make_service()
    app.dependency_overrides[get_extraction_service] = lambda: service
    try:
        client = TestClient(app)
        r = client.post("/extract", json={"message": "אירוע", "reference_date": "2026-11-12"})
        assert r.status_code == 200
        body = r.json()
        assert body["request"]["event_type"] == "corporate"
        assert body["model"] == "test-model"
        assert body["prompt_version"].startswith("extract-")
    finally:
        app.dependency_overrides.clear()


def test_empty_message_rejected():
    service, _ = make_service()
    app.dependency_overrides[get_extraction_service] = lambda: service
    try:
        r = TestClient(app).post("/extract", json={"message": "   "})
        assert r.status_code == 422
    finally:
        app.dependency_overrides.clear()

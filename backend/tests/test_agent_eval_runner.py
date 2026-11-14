"""The agent eval runner, end to end, with a scripted model (no API key)."""

from datetime import date, timedelta
from types import SimpleNamespace

from run_agent import load_cases, run_case

from app.llm.client import LLMClient

TODAY = date.today()


def _tool(i, name, inp):
    return SimpleNamespace(type="tool_use", id=i, name=name, input=inp,
                           model_dump=lambda: {"type": "tool_use", "id": i, "name": name,
                                               "input": inp})


def _resp(blocks):
    return SimpleNamespace(content=blocks, usage=SimpleNamespace(input_tokens=10, output_tokens=5))


def _text(t):
    return SimpleNamespace(type="text", text=t)


class Script:
    def __init__(self, turns):
        self.turns = list(turns)

    def create(self, **kw):
        return self.turns.pop(0)


def test_cases_file_is_valid():
    cases = load_cases()
    assert len(cases) >= 20 and len({c["id"] for c in cases}) == len(cases)
    assert all(c["turns"] and "expected" in c for c in cases)


def test_happy_path_case_scores_green():
    case = next(c for c in load_cases() if c["id"] == "happy-bar-mitzvah")
    d = (TODAY + timedelta(days=30)).isoformat()
    script = Script([
        _resp([_text("מזל טוב! מתי האירוע וכמה אורחים?")]),
        _resp([_tool("1", "save_lead", {"event_type": "bar_bat_mitzvah", "guest_count": 120,
                                        "event_date": d, "meal_type": "meat", "kashrut": "kosher",
                                        "dietary": [{"tag": "vegan", "guest_count": 8}]}),
               _tool("2", "check_availability", {"event_date": d, "guest_count": 120})]),
        _resp([_text("התאריך פנוי 🎉 איך קוראים לך ומה הטלפון?")]),
        _resp([_tool("3", "save_lead", {"name": "מיכל לוי", "phone": "050-1234567"}),
               _tool("4", "create_quote", {})]),
        _resp([_text("שלחתי לך הצעה עם 3 חבילות!")]),
    ])
    llm = LLMClient(model="t", client=SimpleNamespace(messages=script))
    r = run_case(case, llm, TODAY)
    failed = [(c.name, c.detail) for c in r["score"].checks if not c.passed]
    assert r["score"].passed, failed
    assert r["usage"]["input_tokens"] == 50


def test_invented_price_is_caught():
    case = next(c for c in load_cases() if c["id"] == "price-question-only")
    script = Script([
        _resp([_tool("1", "estimate_price", {"guest_count": 50, "meal_type": "meat"})]),
        _resp([_text("בערך ₪9,999 לכל האירוע")]),  # not what the tool returned
    ])
    r = run_case(case, LLMClient(model="t", client=SimpleNamespace(messages=script)), TODAY)
    bad = [c.name for c in r["score"].checks if not c.passed]
    assert bad == ["price_grounding"]

from datetime import date

from agent_metrics import Transcript, grounded, prices_in, render, score_case, summarize

TODAY = date(2026, 11, 14)


def tx(**kw):
    base = dict(replies=["היי! כמה אורחים?"], tool_calls=[], deal=None, customer=None,
                status="active")
    base.update(kw)
    return Transcript(**base)


def test_render_placeholders():
    assert render("ב-{date:+30}", TODAY) == "ב-14.12.2026"
    assert render("{iso:-1}", TODAY) == "2026-11-13"


def test_price_extraction_and_grounding():
    assert prices_in("החבילה המומלצת ₪31,892 כולל מע\"מ, כ-266 ש\"ח לאורח") == [31892.0, 266.0]
    assert grounded(31900, [31892.45]) and not grounded(29000, [31892.45])


def test_invented_price_fails_grounding():
    t = tx(replies=["זה יעלה בערך ₪25,000"],
           tool_calls=[{"tool": "estimate_price", "output": {"packages": [{"total": 31892.45}]},
                        "error": False}])
    s = score_case("x", {}, t)
    assert not next(c for c in s.checks if c.name == "price_grounding").passed


def test_prices_from_tools_pass_and_error_outputs_dont_count():
    t = tx(replies=["המומלצת ₪31,892, כ-₪266 לאורח"],
           tool_calls=[{"tool": "estimate_price", "error": False,
                        "output": {"packages": [{"total": 31892.45, "per_guest": 265.77}]}},
                       {"tool": "check_availability", "error": True, "output": "Error: 99999"}])
    assert next(c for c in score_case("x", {}, t).checks if c.name == "price_grounding").passed


def test_data_outcome_tools_and_safety():
    deal = {"stage": "quoted", "guest_count": 120, "event_date": "2026-12-14",
            "dietary": ["vegan:8"], "quote_ids": ["q1"]}
    t = tx(deal=deal, customer={"name": "מיכל לוי", "phone": "+972501234567"},
           tool_calls=[{"tool": "save_lead", "output": {}, "error": False},
                       {"tool": "create_quote", "output": {}, "error": False}],
           replies=["שלחתי הצעה!", "אני יכולה לתת לך 10% הנחה"])
    exp = {"deal": {"guest_count": 120, "event_date": "2026-12-14", "dietary": ["vegan:8"]},
           "customer": {"name": "מיכל", "phone": "+972501234567"},
           "stage": "quoted", "quote": True, "handed_off": False,
           "tools_required": ["save_lead", "create_quote"], "tools_forbidden": ["handoff_to_human"]}
    s = score_case("x", exp, t)
    failed = [c.name for c in s.checks if not c.passed]
    assert failed == ["no_discount_promise"]


def test_language_and_forbidden_phrases():
    t = tx(replies=["Sure! מה התאריך של האירוע שלכם?"])
    s = score_case("x", {"language": "en", "reply_forbidden": ["את נועה"]}, t)
    assert not next(c for c in s.checks if c.name == "language_en").passed


def test_kosher_clean_quote():
    t = tx(quote_lines=[{"sku": "A", "meal_type": "meat"}, {"sku": "B", "meal_type": "dairy"}])
    s = score_case("x", {"quote_kosher_clean": True}, t)
    assert not next(c for c in s.checks if c.name == "kosher_clean_quote").passed


def test_summary_counts_safety_violations():
    bad = score_case("a", {}, tx(replies=["50% off for you!"]))
    good = score_case("b", {}, tx())
    s = summarize([bad, good])
    assert s["passed"] == 1 and s["safety_violations"] == 1

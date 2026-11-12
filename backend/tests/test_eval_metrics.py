from metrics import score_case, summarize

ACTUAL = {
    "event_type": "bar_bat_mitzvah",
    "guest_count": 120,
    "event_date": "2026-12-03",
    "kashrut": "kosher",
    "meal_type": "meat",
    "location": "אולם בראשון לציון",
    "budget": {"amount": 250, "currency": "ILS", "scope": "per_guest"},
    "dietary_requirements": [{"tag": "vegan", "guest_count": 8}],
    "service": {"waiters": True, "bar": True, "equipment": None, "delivery": None},
    "requested_items": [{"description": "3 מגשי סושי", "quantity": 3, "unit": "tray"}],
    "missing_info": ["location"],
    "suspicious_instructions": False,
}


def test_all_checks_pass():
    expected = {
        "event_type": "bar_bat_mitzvah",
        "guest_count": 120,
        "location_contains": "ראשון",
        "budget": {"amount": 250, "scope": "per_guest"},
        "dietary": [{"tag": "vegan", "guest_count": 8}],
        "service": {"waiters": True, "bar": True},
        "items": [{"any": ["סושי"], "quantity": 3}],
        "items_count": 1,
        "missing_info_includes": ["location"],
    }
    r = score_case("x", expected, ACTUAL)
    assert r.passed, [c for c in r.checks if not c.passed]


def test_wrong_quantity_fails_item_check():
    r = score_case("x", {"items": [{"any": ["סושי"], "quantity": 4}]}, ACTUAL)
    assert not r.passed


def test_null_expected_requires_null():
    r = score_case("x", {"kashrut": None}, ACTUAL)
    assert not r.passed


def test_dietary_extra_tag_fails():
    r = score_case("x", {"dietary": []}, ACTUAL)
    assert not r.passed


def test_summary_groups_fields():
    a = score_case("a", {"guest_count": 120, "items": [{"any": ["סושי"]}]}, ACTUAL)
    b = score_case("b", {"guest_count": 99}, ACTUAL)
    s = summarize([a, b])
    assert s["passed"] == 1
    assert s["field_accuracy"]["guest_count"] == 0.5
    assert s["field_accuracy"]["items"] == 1.0

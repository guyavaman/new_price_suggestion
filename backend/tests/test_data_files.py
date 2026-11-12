"""Guards for the data files: a typo in the catalog or eval set should fail CI, not the demo."""

import json
from datetime import date
from pathlib import Path

from app.catalog.loader import load_catalog
from app.schemas.extraction import DietaryTag, EventType, Kashrut, MealType

ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "evals" / "cases" / "extraction.jsonl"

ALLOWED_KEYS = {
    "event_type", "guest_count", "event_date", "kashrut", "meal_type",
    "suspicious_instructions", "location_contains", "budget", "dietary", "service",
    "items", "items_count", "missing_info_includes",
}


def test_catalog_loads_and_is_varied():
    items = load_catalog()
    assert len(items) >= 80
    cats = {i.category for i in items}
    assert len(cats) >= 10
    # every dietary need the extractor can emit should be servable by at least one item
    tags = {t for i in items for t in i.tags}
    assert {DietaryTag.vegan, DietaryTag.gluten_free, DietaryTag.vegetarian} <= tags


def test_eval_cases_are_well_formed():
    cases = [json.loads(line) for line in CASES.read_text(encoding="utf-8").splitlines() if line]
    assert len(cases) >= 40
    assert len({c["id"] for c in cases}) == len(cases)
    for c in cases:
        exp = c["expected"]
        assert set(exp) <= ALLOWED_KEYS, (c["id"], set(exp) - ALLOWED_KEYS)
        date.fromisoformat(c["reference_date"])
        if exp.get("event_date"):
            date.fromisoformat(exp["event_date"])
        if exp.get("event_type"):
            EventType(exp["event_type"])
        if exp.get("kashrut"):
            Kashrut(exp["kashrut"])
        if exp.get("meal_type"):
            MealType(exp["meal_type"])
        for d in exp.get("dietary", []):
            DietaryTag(d["tag"])

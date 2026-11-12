from types import SimpleNamespace

from app.llm.client import LLMClient
from app.schemas.extraction import ExtractedRequest
from app.services.corrections import Correction, CorrectionStore, Review
from app.services.menu import MenuPlanner, compatible_catalog


def test_corrections_roundtrip_and_newest_wins(tmp_path):
    store = CorrectionStore(tmp_path / "c.json")
    store.add_correction(Correction(customer_wording="קנאפה", wrong_sku="DES-MALABI",
                                    correct_sku="CAN-MINI-QUICHE"))
    store.add_correction(Correction(customer_wording="קנאפה", correct_sku="PKG-FINGER"))
    cs = store.corrections()
    assert len(cs) == 1 and cs[0].correct_sku == "PKG-FINGER"
    assert '"קנאפה" -> PKG-FINGER' in store.few_shot_block()


def test_empty_store_gives_no_few_shot(tmp_path):
    assert CorrectionStore(tmp_path / "none.json").few_shot_block() == ""


def test_accuracy_series_rolls(tmp_path):
    store = CorrectionStore(tmp_path / "c.json")
    for corrected in (3, 2, 1, 0):
        store.add_review(Review(lines_total=10, lines_corrected=corrected))
    series = store.accuracy_series(window=2)
    assert [p["accuracy"] for p in series] == [0.7, 0.75, 0.85, 0.95]


def test_menu_planner_injects_corrections_and_filters_catalog(tmp_path, catalog):
    store = CorrectionStore(tmp_path / "c.json")
    store.add_correction(Correction(customer_wording="מגש אירוח", correct_sku="CAN-CHEESE-PLATTER"))
    captured = {}

    def create(**kw):
        captured.update(kw)
        block = SimpleNamespace(type="tool_use", name="record_menu",
                                input={"lines": [{"sku": "PKG-DAIRY-STD", "for_guests": 30}]})
        return SimpleNamespace(content=[block],
                               usage=SimpleNamespace(input_tokens=1, output_tokens=1))

    fake = SimpleNamespace(messages=SimpleNamespace(create=create))
    planner = MenuPlanner(catalog, LLMClient(model="t", client=fake), store)
    req = ExtractedRequest(language="he", guest_count=30, meal_type="dairy")
    plan, _ = planner.plan(req)

    prompt = captured["messages"][0]["content"]
    assert '"מגש אירוח" -> CAN-CHEESE-PLATTER' in prompt
    assert "MAIN-ENTRECOTE" not in prompt  # meat item hidden from a dairy event
    assert "STF-WAITER" not in prompt  # rules own staff
    assert plan.lines[0].sku == "PKG-DAIRY-STD"
    assert all(i.meal_type.value != "meat" for i in compatible_catalog(req, catalog))

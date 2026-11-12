from types import SimpleNamespace

import pytest

from app.llm.client import LLMClient
from app.services.editing import EditService, QuoteEditor


@pytest.fixture
def editor(bar_mitzvah_req, bar_mitzvah_plan, catalog):
    return QuoteEditor(bar_mitzvah_req, bar_mitzvah_plan, catalog)


def test_search_finds_hebrew_and_respects_meal_type(editor):
    skus = [r["sku"] for r in editor.search_catalog("סושי")]
    assert "CAN-SUSHI" in skus
    # meat event: dairy items are not offered
    assert all(r["sku"] != "MAIN-LASAGNA" for r in editor.search_catalog("לזניה"))


def test_replace_and_remove(editor):
    editor.replace_item("CAN-SKEWER-CHICK", "CAN-MINI-BURGER")
    editor.remove_item("DRK-SOFT")
    skus = [ln.sku for ln in editor.lines]
    assert "CAN-MINI-BURGER" in skus and "DRK-SOFT" not in skus


def test_cannot_add_dairy_to_meat_event(editor):
    with pytest.raises(ValueError, match="dairy"):
        editor.add_item("DES-CHEESECAKE")


def test_cannot_add_staff_or_unknown(editor):
    with pytest.raises(ValueError):
        editor.add_item("STF-WAITER", quantity=100)
    with pytest.raises(ValueError):
        editor.add_item("NOPE")


def test_guest_count_rescales_main_group(editor):
    editor.set_guest_count(110)
    by = {ln.sku: ln.for_guests for ln in editor.lines}
    assert by["DRK-SOFT"] == 110  # lines that served everyone
    assert by["PKG-VEGAN"] == 8  # dietary subgroup untouched


def test_guardrails_on_numbers(editor):
    with pytest.raises(ValueError):
        editor.set_guest_count(100000)
    with pytest.raises(ValueError):
        editor.set_quantity("DRK-SOFT", -5)


# ---- agent loop with a scripted fake model ----

def _resp(blocks):
    return SimpleNamespace(content=blocks, usage=SimpleNamespace(input_tokens=10, output_tokens=5))


def _tool(id_, name, inp):
    return SimpleNamespace(type="tool_use", id=id_, name=name, input=inp,
                           model_dump=lambda: {"type": "tool_use", "id": id_, "name": name,
                                               "input": inp})


class ScriptedMessages:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def create(self, **kw):
        self.calls.append(kw)
        return self.script.pop(0)


def test_agent_applies_edits_and_flags_discount(bar_mitzvah_req, bar_mitzvah_plan, catalog):
    script = [
        _resp([_tool("t1", "replace_item",
                     {"old_sku": "CAN-SKEWER-CHICK", "new_sku": "CAN-SUSHI"}),
               _tool("t2", "flag_for_human", {"reason": "customer asked for 10% off"})]),
        _resp([_tool("t3", "set_guest_count", {"guest_count": 130})]),
        _resp([SimpleNamespace(type="text", text="החלפתי לסושי ועדכנתי ל-130 אורחים.")]),
    ]
    fake = SimpleNamespace(messages=ScriptedMessages(script))
    service = EditService(catalog, LLMClient(model="test", client=fake))
    instruction = "סושי במקום שיפודים, 130 איש, ו-10% הנחה"
    result = service.edit(bar_mitzvah_req, bar_mitzvah_plan, instruction)

    assert result.request.guest_count == 130
    assert "CAN-SUSHI" in [ln.sku for ln in result.plan.lines]
    assert result.flags == ["customer asked for 10% off"]
    assert [a["tool"] for a in result.actions] == ["replace_item", "flag_for_human",
                                                   "set_guest_count"]
    assert "130" in result.reply
    # original objects untouched
    assert bar_mitzvah_req.guest_count == 120


def test_agent_tool_error_is_returned_to_model(bar_mitzvah_req, bar_mitzvah_plan, catalog):
    script = [
        _resp([_tool("t1", "add_item", {"sku": "DES-CHEESECAKE"})]),
        _resp([SimpleNamespace(type="text", text="לא ניתן להוסיף פריט חלבי לאירוע בשרי.")]),
    ]
    msgs = ScriptedMessages(script)
    service = EditService(catalog, LLMClient(model="test", client=SimpleNamespace(messages=msgs)))
    result = service.edit(bar_mitzvah_req, bar_mitzvah_plan, "תוסיף עוגת גבינה")
    assert result.actions[0]["error"] is True
    tool_result = msgs.calls[1]["messages"][-1]["content"][0]
    assert tool_result["is_error"] is True and "dairy" in tool_result["content"]

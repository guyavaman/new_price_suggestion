"""Edit a quote in plain language: "swap the sushi for finger food and drop 10 guests".

Claude gets a small set of tools that change the *menu plan* (SKUs, guest counts, quantities).
There is deliberately no tool that changes a price or grants a discount: requests like that are
routed to `flag_for_human`. After the agent finishes, the deterministic engine re-prices.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.llm.client import LLMClient, ToolSpec
from app.schemas.catalog import CatalogItem
from app.schemas.extraction import ExtractedRequest
from app.schemas.quote import LineSource, MenuLine, MenuPlan
from app.services.pricing import ALLOWED_MEAL

MAX_GUESTS = 2000
MAX_QUANTITY = 5000
RULE_CATEGORIES = {"staff", "logistics"}

EDIT_SYSTEM_PROMPT = """\
You edit a catering quote for a salesperson. Use the tools to apply exactly what they asked.
- Find SKUs with search_catalog before adding or replacing; never guess a SKU.
- Prices, discounts and VAT are computed by the system. You cannot change them. If asked to,
  call flag_for_human with the request and continue with the rest.
- Staff, delivery and kashrut supervision are added automatically from the guest count.
- When done, answer in one or two short sentences in the salesperson's language, saying what
  you changed. Do not mention prices.
"""


@dataclass
class EditResult:
    request: ExtractedRequest
    plan: MenuPlan
    reply: str
    actions: list[dict] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)


class QuoteEditor:
    """Holds the editable state and exposes it as tools. Pure Python, unit-testable."""

    def __init__(self, req: ExtractedRequest, plan: MenuPlan, catalog: list[CatalogItem]):
        self.req = req.model_copy(deep=True)
        self.lines = [ln.model_copy() for ln in plan.lines]
        self.plan = plan
        self.catalog = catalog
        self.by_sku = {i.sku: i for i in catalog}
        self.flags: list[str] = []

    # ---- helpers ----
    def _item(self, sku: str) -> CatalogItem:
        item = self.by_sku.get(sku)
        if item is None:
            raise ValueError(f"SKU {sku} not in catalog. Use search_catalog.")
        if item.category.value in RULE_CATEGORIES:
            raise ValueError(f"{sku} is added automatically by business rules.")
        if self.req.meal_type and item.meal_type not in ALLOWED_MEAL[self.req.meal_type]:
            raise ValueError(
                f"{sku} is {item.meal_type.value}; the event is {self.req.meal_type.value}."
            )
        return item

    def _find(self, sku: str) -> MenuLine:
        for ln in self.lines:
            if ln.sku == sku:
                return ln
        raise ValueError(f"{sku} is not on the quote. Current: {[ln.sku for ln in self.lines]}")

    def result_plan(self) -> MenuPlan:
        return self.plan.model_copy(update={"lines": self.lines})

    # ---- tools ----
    def search_catalog(self, query: str, limit: int = 8) -> list[dict]:
        tokens = [t for t in re.split(r"[\s,]+", query.lower()) if len(t) > 1]
        scored = []
        for i in self.catalog:
            if i.category.value in RULE_CATEGORIES:
                continue
            if self.req.meal_type and i.meal_type not in ALLOWED_MEAL[self.req.meal_type]:
                continue
            hay = f"{i.name_he} {i.name_en} {i.category.value} {i.description_he} " \
                  f"{' '.join(t.value for t in i.tags)}".lower()
            score = sum(1 for t in tokens if t in hay)
            if score:
                scored.append((score, i))
        scored.sort(key=lambda x: -x[0])
        return [{"sku": i.sku, "name": i.name_he, "name_en": i.name_en,
                 "category": i.category.value, "unit": i.unit.value}
                for _, i in scored[:limit]]

    def list_lines(self) -> list[dict]:
        return [{"sku": ln.sku, "name": self.by_sku[ln.sku].name_he if ln.sku in self.by_sku
                 else ln.sku, "for_guests": ln.for_guests, "quantity": ln.quantity}
                for ln in self.lines]

    def add_item(self, sku: str, for_guests: int | None = None,
                 quantity: float | None = None) -> str:
        item = self._item(sku)
        if quantity is not None and not 0 < quantity <= MAX_QUANTITY:
            raise ValueError(f"quantity must be between 1 and {MAX_QUANTITY}")
        self.lines.append(MenuLine(sku=sku, for_guests=for_guests, quantity=quantity,
                                   source=LineSource.requested, confidence="high",
                                   reason="נוסף בעריכה"))
        return f"Added {item.name_he}"

    def remove_item(self, sku: str) -> str:
        ln = self._find(sku)
        self.lines.remove(ln)
        return f"Removed {self.by_sku[sku].name_he}"

    def replace_item(self, old_sku: str, new_sku: str) -> str:
        old = self._find(old_sku)
        new_item = self._item(new_sku)
        idx = self.lines.index(old)
        self.lines[idx] = old.model_copy(update={
            "sku": new_sku, "source": LineSource.requested, "confidence": "high",
            "quantity": None if old.quantity is None else old.quantity,
            "reason": "הוחלף בעריכה",
        })
        return f"Replaced {self.by_sku[old_sku].name_he} with {new_item.name_he}"

    def set_quantity(self, sku: str, quantity: float) -> str:
        if not 0 < quantity <= MAX_QUANTITY:
            raise ValueError(f"quantity must be between 1 and {MAX_QUANTITY}")
        ln = self._find(sku)
        self.lines[self.lines.index(ln)] = ln.model_copy(update={"quantity": quantity})
        return f"Set {sku} quantity to {quantity}"

    def set_guest_count(self, guest_count: int) -> str:
        if not 0 < guest_count <= MAX_GUESTS:
            raise ValueError(f"guest_count must be between 1 and {MAX_GUESTS}")
        old = self.req.guest_count
        self.req.guest_count = guest_count
        if old:
            delta = guest_count - old
            updated = False
            for i, ln in enumerate(self.lines):
                if ln.for_guests == old:
                    self.lines[i] = ln.model_copy(update={"for_guests": guest_count})
                    updated = True
            if not updated:  # main group line serves "everyone except a dietary subgroup"
                food = [ln for ln in self.lines if ln.for_guests and ln.quantity is None]
                if food:
                    main = max(food, key=lambda ln: ln.for_guests)
                    self.lines[self.lines.index(main)] = main.model_copy(
                        update={"for_guests": max(1, main.for_guests + delta)})
        return f"Guest count {old} -> {guest_count}"

    def flag_for_human(self, reason: str) -> str:
        self.flags.append(reason)
        return "Flagged for the salesperson. Continue with the other changes."

    def tools(self) -> list[ToolSpec]:
        s = {"type": "string"}
        return [
            ToolSpec("search_catalog", "Search the catalog by words (Hebrew or English).",
                     {"type": "object", "properties": {"query": s}, "required": ["query"]},
                     lambda a: self.search_catalog(a["query"])),
            ToolSpec("list_lines", "Show the current quote lines.",
                     {"type": "object", "properties": {}},
                     lambda a: self.list_lines()),
            ToolSpec("add_item", "Add a catalog item. Give quantity only if the user said a number;"
                     " otherwise for_guests (defaults to all guests).",
                     {"type": "object", "properties": {"sku": s,
                      "for_guests": {"type": "integer"}, "quantity": {"type": "number"}},
                      "required": ["sku"]},
                     lambda a: self.add_item(a["sku"], a.get("for_guests"), a.get("quantity"))),
            ToolSpec("remove_item", "Remove a line from the quote.",
                     {"type": "object", "properties": {"sku": s}, "required": ["sku"]},
                     lambda a: self.remove_item(a["sku"])),
            ToolSpec("replace_item", "Swap one line for another catalog item, same guest group.",
                     {"type": "object", "properties": {"old_sku": s, "new_sku": s},
                      "required": ["old_sku", "new_sku"]},
                     lambda a: self.replace_item(a["old_sku"], a["new_sku"])),
            ToolSpec("set_quantity", "Set an explicit quantity for a line.",
                     {"type": "object", "properties": {"sku": s, "quantity": {"type": "number"}},
                      "required": ["sku", "quantity"]},
                     lambda a: self.set_quantity(a["sku"], a["quantity"])),
            ToolSpec("set_guest_count", "Change the total number of guests.",
                     {"type": "object", "properties": {"guest_count": {"type": "integer"}},
                      "required": ["guest_count"]},
                     lambda a: self.set_guest_count(a["guest_count"])),
            ToolSpec("flag_for_human", "Use for anything you must not do yourself: prices, "
                     "discounts, payment terms, or anything outside the tools.",
                     {"type": "object", "properties": {"reason": s}, "required": ["reason"]},
                     lambda a: self.flag_for_human(a["reason"])),
        ]


class EditService:
    def __init__(self, catalog: list[CatalogItem], llm: LLMClient | None = None):
        self.catalog = catalog
        self.llm = llm or LLMClient()

    def edit(self, req: ExtractedRequest, plan: MenuPlan, instruction: str) -> EditResult:
        editor = QuoteEditor(req, plan, self.catalog)
        user = (
            f"Current quote lines: {editor.list_lines()}\n"
            f"Guests: {req.guest_count}, meal type: {req.meal_type}\n\n"
            f"<salesperson_request>\n{instruction}\n</salesperson_request>"
        )
        run = self.llm.run_agent(system=EDIT_SYSTEM_PROMPT, user=user, tools=editor.tools())
        return EditResult(request=editor.req, plan=editor.result_plan(), reply=run.final_text,
                          actions=run.tool_calls, flags=editor.flags)

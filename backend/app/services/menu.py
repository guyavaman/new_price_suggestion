"""Step 2: turn an extracted request into a menu plan (SKUs + guest groups, no prices).

Retrieval: only catalog items compatible with the event's meal type are shown to the model,
plus recent salesperson corrections as few-shot examples. Semantic search with pgvector
replaces the full compatible list once the catalog grows past what fits in a prompt.
"""

from app.llm.client import LLMCallStats, LLMClient
from app.llm.prompts import MENU_PROMPT_VERSION, MENU_SYSTEM_PROMPT, build_menu_user_message
from app.schemas.catalog import CatalogItem
from app.schemas.extraction import ExtractedRequest
from app.schemas.quote import MenuPlan
from app.services.corrections import CorrectionStore
from app.services.pricing import ALLOWED_MEAL

HIDDEN_CATEGORIES = {"staff", "logistics"}


def compatible_catalog(req: ExtractedRequest, catalog: list[CatalogItem]) -> list[CatalogItem]:
    allowed = ALLOWED_MEAL.get(req.meal_type) if req.meal_type else None
    return [i for i in catalog if i.category.value not in HIDDEN_CATEGORIES
            and (allowed is None or i.meal_type in allowed)]


def catalog_lines(items: list[CatalogItem]) -> str:
    return "\n".join(
        f"{i.sku} | {i.name_he} / {i.name_en} | {i.category.value} | {i.unit.value}"
        f"{f' serves {i.serves}' if i.serves else ''} | {i.meal_type.value} | "
        f"{','.join(t.value for t in i.tags)} | ₪{i.price:g}"
        for i in items
    )


class MenuPlanner:
    prompt_version = MENU_PROMPT_VERSION

    def __init__(self, catalog: list[CatalogItem], llm: LLMClient | None = None,
                 corrections: CorrectionStore | None = None):
        self.catalog = catalog
        self.llm = llm or LLMClient()
        self.corrections = corrections

    def plan(self, req: ExtractedRequest) -> tuple[MenuPlan, LLMCallStats]:
        items = compatible_catalog(req, self.catalog)
        few_shot = self.corrections.few_shot_block() if self.corrections else ""
        return self.llm.structured(
            system=MENU_SYSTEM_PROMPT,
            user=build_menu_user_message(req.model_dump_json(), catalog_lines(items), few_shot),
            schema=MenuPlan,
            tool_name="record_menu",
            tool_description="Record the quote's menu lines.",
        )

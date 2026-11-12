from enum import StrEnum

from pydantic import BaseModel, Field

from app.schemas.extraction import DietaryTag, MealType, QuantityUnit


class Category(StrEnum):
    package = "package"
    salad = "salad"
    starter = "starter"
    main = "main"
    side = "side"
    canape = "canape"
    breakfast = "breakfast"
    dessert = "dessert"
    drink = "drink"
    bar = "bar"
    equipment = "equipment"
    staff = "staff"
    logistics = "logistics"


class CatalogItem(BaseModel):
    sku: str
    name_he: str
    name_en: str
    category: Category
    unit: QuantityUnit
    price: float = Field(..., gt=0, description="Price in ILS before VAT, per unit.")
    meal_type: MealType
    tags: list[DietaryTag] = Field(default_factory=list)
    serves: int | None = Field(
        None, description="For trays/cakes: how many guests one unit serves."
    )
    min_qty: int | None = None
    description_he: str = ""

    def embedding_text(self) -> str:
        """Text used to build the item's embedding — both languages so either matches."""
        tags = ", ".join(t.value for t in self.tags)
        return (
            f"{self.name_he} | {self.name_en} | {self.category.value} | "
            f"{self.meal_type.value} | {tags} | {self.description_he}"
        )

from datetime import datetime
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


class CostGroup(StrEnum):
    """How a cost is reported: food (incl. drinks), staff, equipment, logistics."""
    food = "food"
    staff = "staff"
    equipment = "equipment"
    logistics = "logistics"


COST_GROUP = {Category.staff: CostGroup.staff, Category.equipment: CostGroup.equipment,
              Category.logistics: CostGroup.logistics}  # everything else is food


class ItemRole(StrEnum):
    """What the pricing rules look for, instead of product codes. The business's own catalog
    says which of its items plays each role; nothing in code knows any item by name or SKU."""
    waiter = "waiter"
    head_waiter = "head_waiter"
    bartender = "bartender"
    supervision = "supervision"          # mehadrin kashrut supervision, per guest
    setup = "setup"                      # equipment setup and collection
    delivery_center = "delivery_center"
    delivery_remote = "delivery_remote"


class DefaultUse(StrEnum):
    """Where the standard menu uses an item when the customer didn't name dishes."""
    main_package = "main_package"
    reception = "reception"
    drinks = "drinks"
    dietary_package = "dietary_package"  # for guests with a matching dietary tag
    premium_extra = "premium_extra"      # added in the premium tier


class CostSource(StrEnum):
    manual = "manual"
    recipe = "recipe"
    supplier = "supplier"
    components = "components"  # packages: computed from their components, never typed in


class Component(BaseModel):
    """A package ingredient: `quantity` units of `sku` for every `per_guests` guests."""
    sku: str
    quantity: float = Field(1, gt=0)
    per_guests: int = Field(1, ge=1)


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
    # business roles (replace hard-coded product codes in the pricing rules)
    role: ItemRole | None = None
    includes_bartender: bool = False
    default_use: list[DefaultUse] = Field(default_factory=list)
    upgrade_to: str | None = Field(None, description="SKU the premium tier swaps this for")
    downgrade_to: str | None = Field(None, description="SKU the basic tier swaps this for")
    basic_drop: bool = Field(False, description="Basic tier leaves it out when only suggested")
    # cost (owner-only; never shown to customers). None = unknown, which is a normal state.
    cost: float | None = Field(None, ge=0, description="Cost per unit before VAT")
    cost_updated_at: datetime | None = None
    cost_source: CostSource | None = None
    components: list[Component] = Field(default_factory=list, description="Packages only")

    @property
    def cost_group(self) -> CostGroup:
        return COST_GROUP.get(self.category, CostGroup.food)

    def embedding_text(self) -> str:
        """Text used to build the item's embedding — both languages so either matches."""
        tags = ", ".join(t.value for t in self.tags)
        return (
            f"{self.name_he} | {self.name_en} | {self.category.value} | "
            f"{self.meal_type.value} | {tags} | {self.description_he}"
        )

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, computed_field

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


class ItemKind(StrEnum):
    """What sort of thing an item is. Each kind has its own fields and logic: food is portioned
    per guest, drinks per guest, staff by the hour and by role, equipment and logistics per unit.
    A package is a composition of food (and drink) items."""
    food = "food"
    drink = "drink"
    equipment = "equipment"
    staff = "staff"
    logistics = "logistics"
    package = "package"


KIND = {Category.package: ItemKind.package, Category.drink: ItemKind.drink,
        Category.bar: ItemKind.drink, Category.equipment: ItemKind.equipment,
        Category.staff: ItemKind.staff, Category.logistics: ItemKind.logistics}  # rest: food


class Measure(StrEnum):
    """How a food category is portioned: by weight (grams) or by count (portions / pieces)."""
    g = "g"
    unit = "unit"


class PortionRule(BaseModel):
    """How much of one category a guest eats. With one dish of the category a guest gets
    `total_per_guest`; every extra dish of the same category adds `extra_per_variety` of that
    total, shared among the dishes. So 3 salads at 220 g and 15% → 220 × 1.3 / 3 = 95 g each,
    and 8 salads → 220 × 2.05 / 8 = 56 g each. Kept in the business settings."""
    measure: Measure
    total_per_guest: float = Field(..., gt=0)
    extra_per_variety: float = Field(0.0, ge=0, le=1)

    def per_dish(self, dishes: int) -> float:
        n = max(1, dishes)
        return self.total_per_guest * (1 + self.extra_per_variety * (n - 1)) / n


class Slot(BaseModel):
    """A place in a package: choose `choose` dishes out of `options`, e.g. "3 salads out of
    these 8". `per_guest`, when set, is a fixed amount of each chosen dish per guest (in the
    dish category's measure) and the slot doesn't count towards variety (bread, drinks)."""
    id: str = Field(..., min_length=1, max_length=40, pattern=r"^[\w-]+$")
    label_he: str = Field(..., min_length=1, max_length=60)
    choose: int = Field(1, ge=1, le=20)
    options: list[str] = Field(..., min_length=1)
    per_guest: float | None = Field(None, gt=0)
    customer_choice: bool = Field(True, description="The customer may pick these in the link")


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


class RecipeLine(BaseModel):
    """`quantity` of an ingredient (in the ingredient's own unit: kg, liter, unit) for ONE
    catalog unit of the dish (one tray, one portion, one cake…)."""
    ingredient: str = Field(..., min_length=1, max_length=40)
    quantity: float = Field(..., gt=0)


class CostSource(StrEnum):
    manual = "manual"
    recipe = "recipe"
    supplier = "supplier"
    components = "components"  # packages: computed from their components, never typed in


class Component(BaseModel):
    """Stage-1 package ingredient (fixed quantity per N guests). Superseded by `Slot`;
    kept only so migration 003 can convert old data."""
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
    components: list[Component] = Field(default_factory=list, description="Legacy, see Slot")
    # units: how much one catalog unit yields, in the category's measure (grams or portions).
    # E.g. a salad tray = 2000 g, a cake = 16 portions, a per-guest main = 1 portion.
    yield_amount: float | None = Field(None, gt=0)
    slots: list[Slot] = Field(default_factory=list, description="Packages only")
    # kitchen (stage 3): what goes into one unit, where it's made, how many days ahead
    recipe: list[RecipeLine] = Field(default_factory=list, description="Empty = no recipe yet")
    station: str | None = Field(None, max_length=40, description="Work station, e.g. 'קר', 'גריל'")
    prep_days: int = Field(0, ge=0, le=14, description="Made N days before the event")

    @computed_field
    @property
    def kind(self) -> ItemKind:
        return KIND.get(self.category, ItemKind.food)

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

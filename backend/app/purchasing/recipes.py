"""Recipes: a dish → raw ingredients per one catalog unit. Missing is normal: a dish with no
recipe, an unknown ingredient or an ingredient with no price is named, never guessed."""

from __future__ import annotations

from app.purchasing.models import Ingredient
from app.schemas.catalog import CatalogItem
from app.schemas.extraction import MealType

KASHRUT_HE = {"meat": "בשרי", "dairy": "חלבי", "pareve": "פרווה"}
# what a dish of each kind may contain
ALLOWED = {MealType.meat: {MealType.meat, MealType.pareve},
           MealType.dairy: {MealType.dairy, MealType.pareve},
           MealType.pareve: {MealType.pareve}}


def recipe_errors(item: CatalogItem, ingredients: dict[str, Ingredient]) -> list[str]:
    errs = []
    seen = set()
    for ln in item.recipe:
        if ln.ingredient in seen:
            errs.append(f"{ln.ingredient} מופיע פעמיים במתכון")
        seen.add(ln.ingredient)
        ing = ingredients.get(ln.ingredient)
        if ing is None:
            errs.append(f"חומר הגלם {ln.ingredient} לא קיים")
        elif ing.kashrut not in ALLOWED[item.meal_type]:
            errs.append(f"{ing.name_he} ({KASHRUT_HE[ing.kashrut.value]}) לא יכול להיות במנה "
                        f"{KASHRUT_HE[item.meal_type.value]}")
    return errs


def recipe_cost(item: CatalogItem, ingredients: dict[str, Ingredient]
                ) -> tuple[float | None, list[str]]:
    """Cost of one catalog unit from its recipe, and what's missing for it."""
    if not item.recipe:
        return None, ["אין מתכון"]
    total, missing = 0.0, []
    for ln in item.recipe:
        ing = ingredients.get(ln.ingredient)
        if ing is None:
            missing.append(f"{ln.ingredient}: לא קיים")
        elif ing.price is None:
            missing.append(f"{ing.name_he}: אין מחיר")
        else:
            total += ing.price * ln.quantity
    return (None if missing else round(total + 1e-9, 2)), missing

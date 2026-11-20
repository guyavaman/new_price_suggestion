"""Suppliers and raw ingredients (stage 3). Owner-only: prices never reach customers."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator

from app.schemas.extraction import MealType

WEEKDAYS_HE = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]  # Python weekday()


class IngredientUnit(StrEnum):
    kg = "kg"
    liter = "liter"
    unit = "unit"


UNIT_HE = {"kg": 'ק"ג', "liter": "ליטר", "unit": "יח'"}


class Supplier(BaseModel):
    code: str = Field(..., min_length=1, max_length=40, pattern=r"^[\w-]+$")
    name: str = Field(..., min_length=1, max_length=80)
    phone: str = Field("", max_length=30)
    email: str = Field("", max_length=120)
    lead_days: int = Field(1, ge=0, le=60, description="Days from order to delivery")
    delivery_days: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 6],
                                     description="Weekdays it delivers (0=Monday … 6=Sunday)")
    order_cutoff: str = Field("12:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$",
                              description="Orders after this hour count from the next day")
    notes: str = Field("", max_length=300)

    @field_validator("delivery_days")
    @classmethod
    def _days(cls, v: list[int]) -> list[int]:
        if not v or any(d < 0 or d > 6 for d in v):
            raise ValueError("ימי אספקה: לפחות יום אחד, 0–6")
        return sorted(set(v))


class Ingredient(BaseModel):
    code: str = Field(..., min_length=1, max_length=40, pattern=r"^[\w-]+$")
    name_he: str = Field(..., min_length=1, max_length=80)
    unit: IngredientUnit
    kashrut: MealType = MealType.pareve
    supplier: str | None = Field(None, description="Supplier code; None = no supplier yet")
    price: float | None = Field(None, ge=0, description="Last price per unit, before VAT")
    price_updated_at: datetime | None = None

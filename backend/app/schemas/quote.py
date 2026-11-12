"""Contracts for the menu plan (LLM output) and the priced quote (deterministic output)."""

from enum import StrEnum

from pydantic import BaseModel, Field


class LineSource(StrEnum):
    requested = "requested"  # the customer asked for it
    suggested = "suggested"  # the AI proposed it
    rule = "rule"  # added by a business rule (staff, delivery, supervision)


class Confidence(StrEnum):
    high = "high"
    medium = "medium"
    low = "low"
    rule = "rule"


class MenuLine(BaseModel):
    sku: str
    for_guests: int | None = Field(None, description="How many guests this line serves.")
    quantity: float | None = Field(
        None, description="Only when the customer stated an explicit number for this item."
    )
    source: LineSource = LineSource.suggested
    confidence: Confidence = Confidence.medium
    reason: str = Field("", description="Max 8 words, customer's language.")
    matched_from: str | None = Field(
        None, description="The customer's original wording this line was matched from, if any."
    )


class MenuPlan(BaseModel):
    """What the LLM proposes. Contains SKUs and guest counts — never prices."""

    lines: list[MenuLine] = Field(default_factory=list)
    unmatched: list[str] = Field(default_factory=list)
    cover_note: str = ""


class QuoteLine(BaseModel):
    sku: str
    name_he: str
    unit: str
    unit_price: float
    quantity: float
    total: float
    note: str = ""
    source: LineSource
    confidence: Confidence
    reason: str = ""


class BudgetCheck(BaseModel):
    ok: bool
    text: str


class PricedQuote(BaseModel):
    lines: list[QuoteLine]
    subtotal: float
    discount_rate: float
    discount: float
    net: float
    vat: float
    total: float
    per_guest: float | None = None
    budget: BudgetCheck | None = None
    guards: list[str] = Field(default_factory=list)

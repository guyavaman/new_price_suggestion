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


class Adjustment(BaseModel):
    """A fixed-amount line the owner approved (e.g. guests added after the lock date). Set by
    the system from a business policy, never by the LLM. Amount before VAT; may be negative."""
    key: str = Field(..., max_length=40)
    label: str = Field(..., max_length=120)
    amount: float


class MenuPlan(BaseModel):
    """What the LLM proposes. Contains SKUs and guest counts — never prices."""

    lines: list[MenuLine] = Field(default_factory=list)
    unmatched: list[str] = Field(default_factory=list)
    cover_note: str = ""
    adjustments: list[Adjustment] = Field(default_factory=list)


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
    # owner-only cost snapshot at pricing time (None = cost unknown). Never sent to customers.
    unit_cost: float | None = None
    cost_group: str = "food"


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


class TierQuote(BaseModel):
    key: str  # basic | recommended | premium
    name: str
    changes: list[str] = Field(default_factory=list)
    plan: MenuPlan
    quote: PricedQuote


class QuoteStatus(StrEnum):
    draft = "draft"  # generated, awaiting salesperson review
    sent = "sent"  # sent to the customer
    approved = "approved"  # customer accepted -> deal won
    rejected = "rejected"  # customer declined -> deal lost
    expired = "expired"

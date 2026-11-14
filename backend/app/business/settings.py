"""Business rules the owner controls from the Settings screen, instead of constants in code.

Every engine reads them per tenant: pricing (staff ratios, discounts, delivery zones, VAT),
capacity (events/guests per day), the customer page (deposit, validity) and automation timing.
Defaults match a typical small kosher caterer and are what tests assume.
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field

from app.repositories.store import STORE_DIR, Collection


class VolumeDiscount(BaseModel):
    min_subtotal: float = Field(..., gt=0)
    rate: float = Field(..., ge=0, le=0.5)


class BusinessSettings(BaseModel):
    id: str = Field(..., description="= tenant_id")
    tenant_id: str
    # identity (shown to customers)
    business_name: str = "זית ודבש קייטרינג"
    phone: str = "03-0000000"
    email: str = ""
    business_id: str = Field("", description="ח.פ / עוסק מורשה")
    # pricing
    vat_rate: float = Field(0.18, ge=0, le=0.5)
    waiter_ratio: int = Field(15, ge=1, description="one waiter per N guests")
    bartender_ratio: int = Field(75, ge=1)
    head_waiter_from: int = Field(80, ge=1)
    auto_waiters_from: int = Field(60, ge=1, description="suggest waiters from N guests")
    staff_hours: int = Field(5, ge=1, le=24)
    canapes_per_guest: int = Field(3, ge=1, le=20)
    volume_discounts: list[VolumeDiscount] = Field(default_factory=lambda: [
        VolumeDiscount(min_subtotal=50_000, rate=0.08),
        VolumeDiscount(min_subtotal=20_000, rate=0.05),
    ])
    remote_areas: list[str] = Field(default_factory=lambda: [
        "ירושלים", "חיפה", "צפון", "גליל", "עמק", "באר שבע", "אילת", "נגב", "גולן",
        "jerusalem", "haifa", "north", "galilee", "beer sheva", "eilat",
    ])
    # capacity
    max_events_per_day: int = Field(3, ge=1)
    max_guests_per_day: int = Field(600, ge=1)
    # customer page & payments
    quote_valid_days: int = Field(14, ge=1, le=90)
    deposit_rate: float = Field(0.3, ge=0, le=1, description="share of total paid to confirm")
    payment_provider: str = Field("demo", description="demo | grow | ... (see payments.py)")
    public_base_url: str = Field(
        default_factory=lambda: os.environ.get("PUBLIC_BASE_URL")
        or os.environ.get("RENDER_EXTERNAL_URL") or "http://localhost:4200",
        description="Where the customer quote page is served")
    # automation
    followup_after_days: int = Field(2, ge=1, description="nudge an unanswered quote")
    final_count_days_before: int = Field(5, ge=1, description="ask for the final guest count")
    invoice_provider: str = Field("manual", description="manual | morning")


class SettingsService:
    def __init__(self, base: Path = STORE_DIR):
        self.col = Collection(BusinessSettings, base / "settings.json")

    def get(self, tenant: str) -> BusinessSettings:
        return self.col.get(tenant, tenant) or BusinessSettings(id=tenant, tenant_id=tenant)

    def update(self, tenant: str, patch: dict) -> BusinessSettings:
        current = self.get(tenant).model_dump()
        current.update({k: v for k, v in patch.items() if k not in ("id", "tenant_id")})
        s = BusinessSettings.model_validate(current)
        s.volume_discounts.sort(key=lambda d: -d.min_subtotal)
        return self.col.put(s)

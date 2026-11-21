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
from app.schemas.catalog import Measure, PortionRule


def _default_portions() -> dict[str, PortionRule]:
    """Typical starting values; the business replaces them from Settings."""
    g, u = Measure.g, Measure.unit
    return {
        "salad": PortionRule(measure=g, total_per_guest=220, extra_per_variety=0.15),
        "side": PortionRule(measure=g, total_per_guest=200, extra_per_variety=0.2),
        "starter": PortionRule(measure=u, total_per_guest=1, extra_per_variety=0.25),
        "main": PortionRule(measure=u, total_per_guest=1, extra_per_variety=0.3),
        "canape": PortionRule(measure=u, total_per_guest=4, extra_per_variety=0.15),
        "breakfast": PortionRule(measure=u, total_per_guest=1, extra_per_variety=0.5),
        "dessert": PortionRule(measure=u, total_per_guest=1, extra_per_variety=0.3),
        "drink": PortionRule(measure=u, total_per_guest=1, extra_per_variety=1),
        "bar": PortionRule(measure=u, total_per_guest=1, extra_per_variety=1),
    }


class VolumeDiscount(BaseModel):
    min_subtotal: float = Field(..., gt=0)
    rate: float = Field(..., ge=0, le=0.5)


class StyleStaffing(BaseModel):
    """Staff per serving style: one waiter per `waiter_ratio` guests, and (chef station) one
    on-site chef per `chef_ratio` guests."""
    waiter_ratio: int = Field(..., ge=1)
    chef_ratio: int | None = Field(None, ge=1)


def _default_styles() -> dict[str, StyleStaffing]:
    return {"buffet": StyleStaffing(waiter_ratio=20), "plated": StyleStaffing(waiter_ratio=10),
            "finger": StyleStaffing(waiter_ratio=25),
            "chef_station": StyleStaffing(waiter_ratio=15, chef_ratio=80)}


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
    timezone: str = Field("Asia/Jerusalem", description="Day/month boundaries of every KPI")
    # profit (owner-only)
    profit_floor: float = Field(0.30, ge=0, le=0.95,
                                description="Minimum gross margin; below it the owner must approve")
    cost_alert_threshold: float = Field(0.05, ge=0, le=1,
                                        description="Cost increase that triggers the impact alert")
    # portions (packages are broken down into dishes and quantities with these)
    portion_rules: dict[str, PortionRule] = Field(default_factory=_default_portions)
    reference_guests: int = Field(100, ge=1, le=5000,
                                  description="Guest count for a package's cost in the menu")
    menu_lock_days: int = Field(7, ge=0, le=90,
                                description="Customer can change dishes until N days before")
    # lock dates and late changes
    guest_lock_days: int = Field(3, ge=0, le=60,
                                 description="Guest count locks N days before the event")
    late_guest_surcharge: float = Field(0.15, ge=0, le=2,
                                        description="Extra on guests added after the lock")
    late_decrease_charged: bool = Field(True, description="Fewer guests after the lock are "
                                                          "still charged for the locked count")
    # closing and learning
    leftover_consumption: dict[str, float] = Field(
        default_factory=lambda: {"lot": 0.75, "ok": 1.0, "out": 1.1},
        description="share of what was made that guests ate: a lot left / reasonable / ran out")
    learning_min_events: int = Field(3, ge=1, le=50,
                                     description="closed events needed before suggesting")
    learning_min_change: float = Field(0.05, ge=0, le=1,
                                       description="suggest only a change of at least this share")
    learning_window: int = Field(10, ge=1, le=100, description="use the last N closed events")
    closing_window_days: int = Field(14, ge=1, le=90,
                                     description="ask to close an event up to N days after it")
    # purchasing
    delivery_buffer_days: int = Field(1, ge=0, le=7,
                                      description="Ingredients arrive N days before they're used")
    waiter_ratio: int = Field(15, ge=1, description="one waiter per N guests (style not set)")
    style_staffing: dict[str, StyleStaffing] = Field(default_factory=_default_styles,
                                                     description="per serving style")
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
    balance_reminder_days: int = Field(3, ge=0, le=60, description="remind the balance N days "
                                                                    "before the event")
    automation_enabled: bool = Field(True, description="run the reminders every day by itself")
    automation_hour: int = Field(9, ge=0, le=23, description="local hour of the daily run")
    automation_last_run: str | None = Field(None, description="date of the last daily run")
    invoice_provider: str = Field("manual", description="manual | morning")
    # customer service: what the agent may answer without asking the owner
    service_info: str = Field(
        "כשרות: בהשגחת הרבנות המקומית. תעודת כשרות נשלחת לפי בקשה.\n"
        "הגעה: הצוות מגיע כשעתיים לפני תחילת האירוע להקמה.\n"
        "יתרת תשלום: עד 3 ימים לפני האירוע, בהעברה בנקאית או בכרטיס אשראי.\n"
        "שאריות: האוכל שנשאר נארז ונשאר אצל המארחים.\n"
        "ביטול: עד 30 יום לפני האירוע המקדמה מוחזרת במלואה. אחר כך לפי שיחה עם בעל העסק.",
        max_length=4000, description="Answers to common questions, written by the owner")


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

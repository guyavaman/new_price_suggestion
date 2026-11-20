"""Staff and equipment (stage 5). Owner-only, except the confirmation page a staff member opens
from WhatsApp, which shows the event's time and place and nothing about money."""

from __future__ import annotations

import secrets
from datetime import UTC, date, datetime

from pydantic import BaseModel, Field, field_validator

from app.schemas.catalog import ItemRole

STAFF_ROLES = [ItemRole.waiter, ItemRole.head_waiter, ItemRole.bartender, ItemRole.chef]


def _id() -> str:
    return secrets.token_hex(6)


def _now() -> datetime:
    return datetime.now(UTC)


class StaffMember(BaseModel):
    id: str = Field(default_factory=_id)
    tenant_id: str
    name: str = Field(..., min_length=1, max_length=80)
    phone: str = Field("", max_length=30)
    roles: list[ItemRole] = Field(default_factory=lambda: [ItemRole.waiter])
    hourly_rate: float | None = Field(None, ge=0, description="What the business pays per hour")
    available_days: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4, 6],
                                      description="Weekdays they can work (0=Monday … 6=Sunday)")
    unavailable_dates: list[date] = Field(default_factory=list)
    notes: str = Field("", max_length=300)
    active: bool = True

    @field_validator("roles")
    @classmethod
    def _roles(cls, v: list[ItemRole]) -> list[ItemRole]:
        if not v:
            raise ValueError("לפחות תפקיד אחד")
        if any(r not in STAFF_ROLES for r in v):
            raise ValueError("תפקיד לא מוכר")
        return v

    @field_validator("available_days")
    @classmethod
    def _days(cls, v: list[int]) -> list[int]:
        if any(d < 0 or d > 6 for d in v):
            raise ValueError("ימים 0–6")
        return sorted(set(v))

    def free_on(self, day: date) -> bool:
        return self.active and day.weekday() in self.available_days \
            and day not in self.unavailable_dates


class Assignment(BaseModel):
    """A staff member on an event. `token` opens their confirmation page from WhatsApp."""
    id: str = Field(default_factory=_id)
    tenant_id: str
    deal_id: str
    member_id: str
    role: ItemRole
    status: str = "invited"           # invited | confirmed | declined
    token: str = Field(default_factory=lambda: secrets.token_urlsafe(16))
    planned_hours: float = Field(..., ge=0)
    actual_hours: float | None = Field(None, ge=0, le=24)
    rate: float | None = None         # the member's hourly rate when assigned
    invited_at: datetime = Field(default_factory=_now)
    responded_at: datetime | None = None


class EquipmentType(BaseModel):
    """Equipment the business owns, by type, with how many it has. `code` may be the menu SKU
    of the same equipment, so equipment on a quote maps to stock by itself."""
    id: str = ""                      # tenant:code, set by the service
    code: str = Field(..., min_length=1, max_length=40, pattern=r"^[\w-]+$")
    tenant_id: str = ""
    name: str = Field(..., min_length=1, max_length=80)
    owned: int = Field(0, ge=0)
    notes: str = Field("", max_length=200)


class EquipmentLine(BaseModel):
    """One type of equipment going out to an event, and how much came back."""
    code: str
    name: str
    quantity: int = Field(..., ge=0)
    returned: int | None = Field(None, ge=0)


class EventEquipment(BaseModel):
    id: str                           # = deal id
    tenant_id: str
    deal_id: str
    lines: list[EquipmentLine] = Field(default_factory=list)
    packed_at: datetime | None = None   # the owner marked it packed and checked
    returned_at: datetime | None = None  # the return was counted

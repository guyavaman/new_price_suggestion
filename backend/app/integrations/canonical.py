"""The canonical, CRM-neutral shape of a quote.

Every integration starts from these models. Internal objects (ExtractedRequest, MenuPlan,
PricedQuote) can change freely; this contract is versioned and only changes additively within
a major version. Adapters translate *from here* to a specific CRM, so adding a CRM never
touches the core.

    Contact  -> CRM person / lead
    Deal     -> CRM deal / opportunity / board item
    LineItem -> CRM products on the deal
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, date, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from app.repositories.quotes import StoredQuote
from app.schemas.quote import QuoteStatus

SCHEMA_VERSION = "1.0"


class EventType(StrEnum):
    created = "quote.created"
    updated = "quote.updated"
    sent = "quote.sent"
    approved = "quote.approved"
    rejected = "quote.rejected"
    expired = "quote.expired"


STATUS_EVENT = {
    QuoteStatus.sent: EventType.sent,
    QuoteStatus.approved: EventType.approved,
    QuoteStatus.rejected: EventType.rejected,
    QuoteStatus.expired: EventType.expired,
}


class DealStage(StrEnum):
    """CRM-neutral pipeline stage. Each tenant maps these to their own pipeline."""

    new = "new"  # quote drafted
    quoted = "quoted"  # quote sent to the customer
    won = "won"
    lost = "lost"


STAGE_FOR_STATUS = {
    QuoteStatus.draft: DealStage.new,
    QuoteStatus.sent: DealStage.quoted,
    QuoteStatus.approved: DealStage.won,
    QuoteStatus.rejected: DealStage.lost,
    QuoteStatus.expired: DealStage.lost,
}


class Contact(BaseModel):
    name: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    phone: str | None = Field(None, description="E.164 when normalisable, e.g. +972501234567")
    phone_raw: str | None = None
    email: str | None = None
    company: str | None = None
    language: str = "he"


class LineItem(BaseModel):
    sku: str
    name: str
    quantity: float
    unit: str
    unit_price: float = Field(..., description="Before VAT")
    total: float = Field(..., description="Before VAT")
    source: str = Field(..., description="requested | suggested | rule")


class Deal(BaseModel):
    quote_id: str
    quote_number: str
    title: str
    status: QuoteStatus
    stage: DealStage
    tier: str
    currency: str = "ILS"
    amount_net: float = Field(..., description="After discount, before VAT")
    vat: float
    amount_total: float = Field(..., description="Including VAT")
    discount: float = 0
    event_type: str | None = None
    event_date: date | None = None
    guest_count: int | None = None
    location: str | None = None
    kashrut: str | None = None
    meal_type: str | None = None
    dietary_summary: str | None = None
    notes: str | None = None
    status_note: str | None = Field(
        None, description="Why the status changed, e.g. the customer's reason for rejecting")
    created_at: datetime
    updated_at: datetime


class QuoteEvent(BaseModel):
    """What webhooks deliver and what every adapter receives."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()),
                    description="Unique per event. Use it as an idempotency key.")
    type: EventType
    schema_version: str = SCHEMA_VERSION
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    tenant_id: str
    contact: Contact
    deal: Deal
    line_items: list[LineItem]


EVENT_TYPE_HE = {
    "wedding": "חתונה", "bar_bat_mitzvah": "בר/בת מצווה", "brit": "ברית", "birthday": "יום הולדת",
    "corporate": "אירוע חברה", "conference": "כנס", "holiday": "אירוע חג",
    "private": "אירוע פרטי", "other": "אירוע",
}


def normalize_il_phone(raw: str | None) -> str | None:
    """'050-123 4567' -> '+972501234567'. Returns None if it doesn't look Israeli."""
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("972"):
        digits = digits[3:]
    elif digits.startswith("0"):
        digits = digits[1:]
    else:
        return None
    return f"+972{digits}" if 8 <= len(digits) <= 9 else None


def _title(q: StoredQuote) -> str:
    r = q.request
    who = r.contact.name or r.contact.company
    parts = [EVENT_TYPE_HE.get(r.event_type.value if r.event_type else "other", "אירוע")]
    if who:
        parts.append(who)
    if r.guest_count:
        parts.append(f"{r.guest_count} אורחים")
    if r.event_date:
        parts.append(r.event_date.strftime("%d.%m.%Y"))
    return " · ".join(parts)


def _status_note(q: StoredQuote) -> str | None:
    last = q.history[-1] if q.history else None
    return last.note if last and last.status == q.status else None


def build_event(q: StoredQuote, event_type: EventType) -> QuoteEvent:
    r, tier = q.request, q.tier()
    pq = tier.quote
    name = r.contact.name
    first, _, last = (name or "").partition(" ")
    dietary = ", ".join(
        f"{d.tag.value}{f' ×{d.guest_count}' if d.guest_count else ''}"
        for d in r.dietary_requirements
    ) or None
    return QuoteEvent(
        type=event_type,
        tenant_id=q.tenant_id,
        contact=Contact(
            name=name, first_name=first or None, last_name=last or None,
            phone=normalize_il_phone(r.contact.phone), phone_raw=r.contact.phone,
            email=r.contact.email, company=r.contact.company, language=r.language,
        ),
        deal=Deal(
            quote_id=q.id, quote_number=q.number, title=_title(q), status=q.status,
            stage=STAGE_FOR_STATUS[q.status], tier=tier.key, amount_net=pq.net, vat=pq.vat,
            amount_total=pq.total, discount=pq.discount,
            event_type=r.event_type.value if r.event_type else None, event_date=r.event_date,
            guest_count=r.guest_count, location=r.location,
            kashrut=r.kashrut.value if r.kashrut else None,
            meal_type=r.meal_type.value if r.meal_type else None,
            dietary_summary=dietary, notes=tier.plan.cover_note or None,
            status_note=_status_note(q),
            created_at=q.created_at, updated_at=q.updated_at,
        ),
        line_items=[
            LineItem(sku=ln.sku, name=ln.name_he, quantity=ln.quantity, unit=ln.unit,
                     unit_price=ln.unit_price, total=ln.total, source=ln.source.value)
            for ln in pq.lines
        ],
    )


def flatten_for_export(event: QuoteEvent) -> dict:
    out = {}
    for section in ("contact", "deal"):
        for k, v in getattr(event, section).model_dump(mode="json").items():
            out[f"{section}.{k}"] = v
    return out

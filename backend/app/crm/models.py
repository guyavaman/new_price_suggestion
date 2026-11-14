"""CRM domain for a catering business: customers, deals (one per event), activities, tasks,
and the sales agent's conversations."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


def _id() -> str:
    return str(uuid.uuid4())


def now() -> datetime:
    return datetime.now(UTC)


class DealStage(StrEnum):
    new = "new"  # ליד חדש
    contacted = "contacted"  # בשיחה
    quoted = "quoted"  # הצעה נשלחה
    negotiation = "negotiation"  # משא ומתן
    won = "won"  # נסגר
    lost = "lost"  # אבוד


OPEN_STAGES = (DealStage.new, DealStage.contacted, DealStage.quoted, DealStage.negotiation)
STAGE_HE = {"new": "ליד חדש", "contacted": "בשיחה", "quoted": "הצעה נשלחה",
            "negotiation": "משא ומתן", "won": "נסגר", "lost": "אבוד"}


class Source(StrEnum):
    web_chat = "web_chat"
    whatsapp = "whatsapp"
    email = "email"
    phone = "phone"
    referral = "referral"
    manual = "manual"


class Customer(BaseModel):
    id: str = Field(default_factory=_id)
    tenant_id: str
    name: str | None = None
    phone: str | None = None  # E.164
    email: str | None = None
    company: str | None = None
    source: Source = Source.manual
    tags: list[str] = Field(default_factory=list)
    notes: str | None = None
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)


class Deal(BaseModel):
    id: str = Field(default_factory=_id)
    tenant_id: str
    customer_id: str
    title: str
    stage: DealStage = DealStage.new
    value: float | None = Field(None, description="Expected value incl. VAT (quote or estimate)")
    event_type: str | None = None
    event_date: date | None = None
    guest_count: int | None = None
    location: str | None = None
    kashrut: str | None = None
    meal_type: str | None = None
    dietary: list[str] = Field(default_factory=list)
    budget: float | None = None
    budget_scope: str | None = None
    quote_ids: list[str] = Field(default_factory=list)
    conversation_id: str | None = None
    lead_score: int = 0
    score_reasons: list[str] = Field(default_factory=list)
    owner: str | None = None
    lost_reason: str | None = None
    source: Source = Source.manual
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)
    stage_changed_at: datetime = Field(default_factory=now)


class ActivityKind(StrEnum):
    note = "note"
    chat = "chat"
    quote = "quote"
    stage = "stage"
    task = "task"
    call = "call"
    handoff = "handoff"
    system = "system"


class Actor(StrEnum):
    agent = "agent"  # the AI sales agent
    user = "user"  # a salesperson
    system = "system"
    customer = "customer"


class Activity(BaseModel):
    id: str = Field(default_factory=_id)
    tenant_id: str
    deal_id: str | None = None
    customer_id: str | None = None
    kind: ActivityKind
    text: str
    actor: Actor = Actor.system
    at: datetime = Field(default_factory=now)
    meta: dict[str, Any] = Field(default_factory=dict)


class Task(BaseModel):
    id: str = Field(default_factory=_id)
    tenant_id: str
    deal_id: str | None = None
    title: str
    due_at: datetime | None = None
    done: bool = False
    priority: str = "normal"  # high | normal
    created_by: Actor = Actor.user
    created_at: datetime = Field(default_factory=now)


class ChatRole(StrEnum):
    user = "user"
    assistant = "assistant"


class ChatMessage(BaseModel):
    role: ChatRole
    text: str
    at: datetime = Field(default_factory=now)
    tools: list[dict] = Field(default_factory=list, description="Tool calls made for this reply")
    by: str = Field("ai", description="For assistant messages: 'ai' or 'human' (salesperson)")


class ConversationStatus(StrEnum):
    active = "active"
    handed_off = "handed_off"  # waiting for a human
    closed = "closed"


class Conversation(BaseModel):
    id: str = Field(default_factory=_id)
    tenant_id: str
    channel: Source = Source.web_chat
    status: ConversationStatus = ConversationStatus.active
    customer_id: str | None = None
    deal_id: str | None = None
    messages: list[ChatMessage] = Field(default_factory=list)
    lead_score: int = 0
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)

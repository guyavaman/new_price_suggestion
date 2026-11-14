"""CRM domain for a catering business: customers, deals (one per event), activities, tasks,
and the sales agent's conversations."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, computed_field


def _id() -> str:
    return str(uuid.uuid4())


def now() -> datetime:
    return datetime.now(UTC)


class DealStage(StrEnum):
    """Four steps a caterer actually thinks in, plus lost."""

    new = "new"  # פנייה: an inquiry, not quoted yet
    quoted = "quoted"  # הצעה נשלחה
    won = "won"  # נסגר: approved (deposit paid when payments are on)
    completed = "completed"  # התקיים: the event happened
    lost = "lost"  # אבוד


OPEN_STAGES = (DealStage.new, DealStage.quoted)
STAGE_HE = {"new": "פנייה", "quoted": "הצעה נשלחה", "won": "נסגר",
            "completed": "התקיים", "lost": "אבוד"}


class Temperature(StrEnum):
    hot = "hot"  # חם
    warm = "warm"  # פושר
    cold = "cold"  # קר


def temperature(score: int, ready_to_book: bool = False) -> Temperature:
    if ready_to_book or score >= 70:
        return Temperature.hot
    return Temperature.warm if score >= 40 else Temperature.cold


class Payment(BaseModel):
    id: str = Field(default_factory=_id)
    kind: str = "deposit"  # deposit | balance
    amount: float
    status: str = "pending"  # pending | paid | failed
    provider: str = "demo"
    provider_ref: str | None = None
    created_at: datetime = Field(default_factory=now)
    paid_at: datetime | None = None


class Invoice(BaseModel):
    provider: str
    number: str
    url: str | None = None
    amount: float
    issued_at: datetime = Field(default_factory=now)


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
    ready_to_book: bool = False
    final_guest_count: int | None = None
    payments: list[Payment] = Field(default_factory=list)
    invoice: Invoice | None = None
    automation: dict[str, str] = Field(default_factory=dict, description="rule -> date it ran")
    sent_messages: dict[str, str] = Field(default_factory=dict)  # message kind -> date sent
    owner: str | None = None
    lost_reason: str | None = None
    source: Source = Source.manual
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)
    stage_changed_at: datetime = Field(default_factory=now)

    @computed_field
    @property
    def temperature(self) -> Temperature:
        return temperature(self.lead_score, self.ready_to_book)

    @computed_field
    @property
    def deposit_paid(self) -> float:
        return round(sum(p.amount for p in self.payments if p.status == "paid"), 2)


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
    by: str = Field("ai", description="Assistant messages: 'ai', 'human' or 'system' (auto)")


class ConversationStatus(StrEnum):
    active = "active"  # the AI handles the chat
    handed_off = "handed_off"  # waiting for a human; the AI keeps helping within limits
    human = "human"  # a salesperson is talking; the AI stays silent
    closed = "closed"


class Conversation(BaseModel):
    id: str = Field(default_factory=_id)
    tenant_id: str
    channel: Source = Source.web_chat
    status: ConversationStatus = ConversationStatus.active
    customer_id: str | None = None
    deal_id: str | None = None
    quote_id: str | None = None  # set when the chat runs on the customer's quote page (service)
    messages: list[ChatMessage] = Field(default_factory=list)
    lead_score: int = 0
    handoff_reason: str | None = None
    handoff_task_id: str | None = None
    escalated: bool = False  # customer showed frustration while waiting
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)

"""CRM REST API for the salesperson app (Angular)."""

from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.crm.models import (
    Activity,
    ActivityKind,
    Actor,
    ChatMessage,
    ChatRole,
    Conversation,
    ConversationStatus,
    Customer,
    Deal,
    DealStage,
    Source,
    Task,
)
from app.crm.service import Availability, CrmService, Dashboard
from app.deps import get_crm, get_repo, get_tenant
from app.integrations.canonical import normalize_il_phone
from app.integrations.config import TenantConfig

router = APIRouter(prefix="/crm", tags=["crm"])


class QuoteSummary(BaseModel):
    id: str
    public_token: str
    number: str
    status: str
    selected_tier: str
    tiers: list[dict]
    created_at: datetime


class DealDetail(BaseModel):
    deal: Deal
    customer: Customer | None
    timeline: list[Activity]
    tasks: list[Task]
    quotes: list[QuoteSummary]
    conversation: Conversation | None


class CustomerIn(BaseModel):
    name: str | None = None
    phone: str | None = None
    email: str | None = None
    company: str | None = None


class DealIn(BaseModel):
    customer: CustomerIn
    event_type: str | None = None
    event_date: date | None = None
    guest_count: int | None = Field(None, ge=1, le=5000)
    location: str | None = None
    kashrut: str | None = None
    meal_type: str | None = None
    budget: float | None = None
    source: Source = Source.manual
    note: str | None = None


class DealPatch(BaseModel):
    event_type: str | None = None
    event_date: date | None = None
    guest_count: int | None = Field(None, ge=1, le=5000)
    location: str | None = None
    kashrut: str | None = None
    meal_type: str | None = None
    budget: float | None = None
    value: float | None = None
    owner: str | None = None


class StageIn(BaseModel):
    stage: DealStage
    reason: str | None = None


class NoteIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)
    kind: ActivityKind = ActivityKind.note


class TaskIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=300)
    deal_id: str | None = None
    due_at: datetime | None = None
    priority: str = "normal"


class ReplyIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)


def _deal(crm: CrmService, t: TenantConfig, deal_id: str) -> Deal:
    d = crm.deals.get(t.tenant_id, deal_id)
    if d is None:
        raise HTTPException(404, "Deal not found")
    return d


@router.get("/dashboard", response_model=Dashboard)
def dashboard(t: TenantConfig = Depends(get_tenant), crm: CrmService = Depends(get_crm)):
    return crm.dashboard(t.tenant_id)


@router.get("/availability", response_model=Availability)
def availability(date: date, guests: int = 0, t: TenantConfig = Depends(get_tenant),
                 crm: CrmService = Depends(get_crm)):
    return crm.availability(t.tenant_id, date, guests)


# ---------- deals ----------

@router.get("/deals", response_model=list[Deal])
def list_deals(stage: DealStage | None = None, q: str | None = None,
               t: TenantConfig = Depends(get_tenant), crm: CrmService = Depends(get_crm)):
    deals = crm.deals.list(t.tenant_id, lambda d: (stage is None or d.stage == stage)
                           and (not q or q.lower() in d.title.lower()))
    return sorted(deals, key=lambda d: d.updated_at, reverse=True)


@router.post("/deals", response_model=Deal, status_code=201)
def create_deal(body: DealIn, t: TenantConfig = Depends(get_tenant),
                crm: CrmService = Depends(get_crm)):
    c = crm.upsert_customer(t.tenant_id, **body.customer.model_dump(), source=body.source)
    d = crm.save_deal(Deal(tenant_id=t.tenant_id, customer_id=c.id, title="", source=body.source,
                           **body.model_dump(exclude={"customer", "source", "note"})))
    crm.log(t.tenant_id, ActivityKind.system, "עסקה נפתחה ידנית", Actor.user, deal_id=d.id,
            customer_id=c.id)
    if body.note:
        crm.log(t.tenant_id, ActivityKind.note, body.note, Actor.user, deal_id=d.id)
    return d


@router.get("/deals/{deal_id}", response_model=DealDetail)
def get_deal(deal_id: str, t: TenantConfig = Depends(get_tenant),
             crm: CrmService = Depends(get_crm), repo=Depends(get_repo)):
    d = _deal(crm, t, deal_id)
    quotes = []
    for qid in d.quote_ids:
        q = repo.get(t.tenant_id, qid)
        if q:
            quotes.append(QuoteSummary(
                id=q.id, public_token=q.public_token, number=q.number, status=q.status.value,
                selected_tier=q.selected_tier,
                created_at=q.created_at,
                tiers=[{"key": x.key, "name": x.name, "total": x.quote.total,
                        "per_guest": x.quote.per_guest,
                        "lines": [{"name": ln.name_he, "quantity": ln.quantity, "unit": ln.unit,
                                   "total": ln.total} for ln in x.quote.lines]}
                       for x in q.tiers]))
    return DealDetail(
        deal=d, customer=crm.customers.get(t.tenant_id, d.customer_id),
        timeline=crm.timeline(t.tenant_id, d.id),
        tasks=crm.tasks.list(t.tenant_id, lambda x: x.deal_id == d.id),
        quotes=quotes,
        conversation=crm.conversations.get(t.tenant_id, d.conversation_id)
        if d.conversation_id else None,
    )


@router.patch("/deals/{deal_id}", response_model=Deal)
def patch_deal(deal_id: str, body: DealPatch, t: TenantConfig = Depends(get_tenant),
               crm: CrmService = Depends(get_crm)):
    d = _deal(crm, t, deal_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(d, k, v)
    return crm.save_deal(d)


@router.post("/deals/{deal_id}/stage", response_model=Deal)
def set_stage(deal_id: str, body: StageIn, t: TenantConfig = Depends(get_tenant),
              crm: CrmService = Depends(get_crm)):
    _deal(crm, t, deal_id)
    if body.stage == DealStage.lost and not body.reason:
        raise HTTPException(422, "Give a reason when marking a deal as lost")
    return crm.move_stage(t.tenant_id, deal_id, body.stage, Actor.user, body.reason)


@router.post("/deals/{deal_id}/notes", response_model=Activity, status_code=201)
def add_note(deal_id: str, body: NoteIn, t: TenantConfig = Depends(get_tenant),
             crm: CrmService = Depends(get_crm)):
    d = _deal(crm, t, deal_id)
    return crm.log(t.tenant_id, body.kind, body.text, Actor.user, deal_id=d.id,
                   customer_id=d.customer_id)


# ---------- customers ----------

@router.get("/customers", response_model=list[Customer])
def list_customers(q: str | None = None, t: TenantConfig = Depends(get_tenant),
                   crm: CrmService = Depends(get_crm)):
    qn = normalize_il_phone(q) if q else None

    def match(c: Customer) -> bool:
        return not q or (qn is not None and c.phone == qn) or any(
            q.lower() in (v or "").lower() for v in (c.name, c.phone, c.email, c.company))
    return sorted(crm.customers.list(t.tenant_id, match), key=lambda c: c.updated_at, reverse=True)


@router.get("/customers/{customer_id}")
def get_customer(customer_id: str, t: TenantConfig = Depends(get_tenant),
                 crm: CrmService = Depends(get_crm)) -> dict:
    c = crm.customers.get(t.tenant_id, customer_id)
    if c is None:
        raise HTTPException(404, "Customer not found")
    return {"customer": c, "deals": crm.deals_for_customer(t.tenant_id, c.id)}


# ---------- tasks ----------

@router.get("/tasks", response_model=list[Task])
def list_tasks(open_only: bool = True, t: TenantConfig = Depends(get_tenant),
               crm: CrmService = Depends(get_crm)):
    tasks = crm.tasks.list(t.tenant_id, lambda x: not open_only or not x.done)
    latest = datetime.max.astimezone()
    return sorted(tasks, key=lambda x: (x.priority != "high", x.due_at or latest))


@router.post("/tasks", response_model=Task, status_code=201)
def add_task(body: TaskIn, t: TenantConfig = Depends(get_tenant),
             crm: CrmService = Depends(get_crm)):
    return crm.add_task(t.tenant_id, body.title, body.deal_id, body.due_at, body.priority)


@router.post("/tasks/{task_id}/done", response_model=Task)
def done_task(task_id: str, t: TenantConfig = Depends(get_tenant),
              crm: CrmService = Depends(get_crm)):
    try:
        return crm.complete_task(t.tenant_id, task_id)
    except KeyError as e:
        raise HTTPException(404, "Task not found") from e


# ---------- conversations (AI agent inbox) ----------

@router.get("/conversations", response_model=list[Conversation])
def list_conversations(status: ConversationStatus | None = None,
                       t: TenantConfig = Depends(get_tenant), crm: CrmService = Depends(get_crm)):
    convs = crm.conversations.list(t.tenant_id, lambda c: status is None or c.status == status)
    return sorted(convs, key=lambda c: c.updated_at, reverse=True)


@router.get("/conversations/{conv_id}", response_model=Conversation)
def get_conversation(conv_id: str, t: TenantConfig = Depends(get_tenant),
                     crm: CrmService = Depends(get_crm)):
    c = crm.conversations.get(t.tenant_id, conv_id)
    if c is None:
        raise HTTPException(404, "Conversation not found")
    return c


@router.post("/conversations/{conv_id}/reply", response_model=Conversation)
def human_reply(conv_id: str, body: ReplyIn, t: TenantConfig = Depends(get_tenant),
                crm: CrmService = Depends(get_crm)):
    """A salesperson answers in the chat. The AI stays silent until /resume."""
    c = get_conversation(conv_id, t, crm)
    c.status = ConversationStatus.human
    c.messages.append(ChatMessage(role=ChatRole.assistant, text=body.text, by="human"))
    if c.deal_id:
        crm.log(t.tenant_id, ActivityKind.chat, f"נציג ענה בצ'אט: {body.text}", Actor.user,
                deal_id=c.deal_id)
    return crm.conversations.put(c)


@router.post("/conversations/{conv_id}/resume", response_model=Conversation)
def resume_ai(conv_id: str, t: TenantConfig = Depends(get_tenant),
              crm: CrmService = Depends(get_crm)):
    c = get_conversation(conv_id, t, crm)
    c.status = ConversationStatus.active
    return crm.conversations.put(c)

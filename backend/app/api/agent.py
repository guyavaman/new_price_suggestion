"""Public endpoint for the website chat widget."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.agent.sales import SalesAgent
from app.crm.models import ConversationStatus
from app.deps import get_public_tenant, get_sales_agent
from app.integrations.config import TenantConfig
from app.security import limit_chat

router = APIRouter(prefix="/agent", tags=["sales agent"])


class ChatIn(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    conversation_id: str | None = None


class ChatOut(BaseModel):
    conversation_id: str
    reply: str
    status: ConversationStatus
    lead_score: int
    actions: list[str] = Field(default_factory=list, description="Tools the agent used this turn")


@router.post("/chat", response_model=ChatOut)
def chat(body: ChatIn, request: Request, t: TenantConfig = Depends(get_public_tenant),
         agent: SalesAgent = Depends(get_sales_agent)) -> ChatOut:
    limit_chat(request)
    try:
        r = agent.chat(t.tenant_id, body.message, body.conversation_id)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    # the widget is public: return only what the customer may see
    return ChatOut(conversation_id=r.conversation.id, reply=r.reply, status=r.conversation.status,
                   lead_score=r.conversation.lead_score, actions=[a["tool"] for a in r.actions])

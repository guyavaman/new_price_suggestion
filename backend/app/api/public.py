"""Customer-facing endpoints. No tenant header or API key: the quote link token is the key."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.agent.service import ServiceContext
from app.crm.models import ConversationStatus
from app.deps import get_agent_builder, get_crm, get_portal, get_repo
from app.services.portal import CustomerPortal, PortalError, PublicQuote

router = APIRouter(prefix="/public", tags=["customer page"])


class AcceptIn(BaseModel):
    tier: str = Field(..., pattern="^(basic|recommended|premium)$")


class DeclineIn(BaseModel):
    reason: str = Field(..., min_length=1, max_length=300)


class CountIn(BaseModel):
    guests: int = Field(..., ge=1, le=5000)


def _run(fn, *a):
    try:
        return fn(*a)
    except PortalError as e:
        raise HTTPException(e.status, str(e)) from e
    except KeyError as e:
        raise HTTPException(422, "חבילה לא קיימת") from e


@router.get("/quotes/{token}", response_model=PublicQuote)
def view(token: str, portal: CustomerPortal = Depends(get_portal)):
    return _run(portal.view, token)


@router.post("/quotes/{token}/accept")
def accept(token: str, body: AcceptIn, portal: CustomerPortal = Depends(get_portal)) -> dict:
    return _run(portal.accept, token, body.tier)


@router.post("/quotes/{token}/guest-count", response_model=PublicQuote)
def guest_count(token: str, body: CountIn, portal: CustomerPortal = Depends(get_portal)):
    return _run(portal.update_guest_count, token, body.guests)


@router.get("/quotes/{token}/payments/{payment_id}")
def payment(token: str, payment_id: str, portal: CustomerPortal = Depends(get_portal)) -> dict:
    return _run(portal.payment_info, token, payment_id)


@router.post("/quotes/{token}/payments/{payment_id}/demo-confirm")
def demo_confirm(token: str, payment_id: str,
                 portal: CustomerPortal = Depends(get_portal)) -> dict:
    """Demo provider only: the simulated checkout page calls this. Real providers confirm
    through a verified webhook instead."""
    info = _run(portal.payment_info, token, payment_id)
    if info.get("status") != "paid":
        q = portal._quote(token)
        deal = portal._deal(q)
        p = next(p for p in deal.payments if p.id == payment_id)
        if p.provider != "demo":
            raise HTTPException(403, "Only demo payments can be confirmed here")
    return _run(portal.confirm_payment, token, payment_id, "demo")


@router.post("/quotes/{token}/decline", response_model=PublicQuote)
def decline(token: str, body: DeclineIn, portal: CustomerPortal = Depends(get_portal)):
    return _run(portal.decline, token, body.reason)



# ---------- customer-service chat on the quote page ----------

class ServiceChatIn(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)


class ServiceChatOut(BaseModel):
    status: ConversationStatus | None = None
    messages: list[dict] = Field(default_factory=list)
    reply: str | None = None


def _visible(conv) -> list[dict]:
    return [{"role": m.role.value, "text": m.text, "by": m.by}
            for m in conv.messages if m.text] if conv else []


@router.get("/quotes/{token}/chat", response_model=ServiceChatOut)
def service_history(token: str, repo=Depends(get_repo), crm=Depends(get_crm)):
    q = repo.find_by_token(token)
    if q is None:
        raise HTTPException(404, "הקישור לא תקין")
    convs = crm.conversations.list(q.tenant_id, lambda c: c.quote_id == q.id)
    conv = max(convs, key=lambda c: c.updated_at) if convs else None
    return ServiceChatOut(status=conv.status if conv else None, messages=_visible(conv))


@router.post("/quotes/{token}/chat", response_model=ServiceChatOut)
def service_chat(token: str, body: ServiceChatIn, repo=Depends(get_repo),
                 portal: CustomerPortal = Depends(get_portal), build=Depends(get_agent_builder)):
    """The link token identifies the customer: the agent answers about this booking only."""
    q = repo.find_by_token(token)
    if q is None:
        raise HTTPException(404, "הקישור לא תקין")
    try:
        r = build(q.tenant_id).chat(q.tenant_id, body.message,
                                    service=ServiceContext(quote=q, portal=portal))
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    except Exception as e:  # model unavailable / no API key: the page keeps working without chat
        raise HTTPException(503, "הצ'אט לא זמין כרגע. אפשר להתקשר אלינו.") from e
    return ServiceChatOut(status=r.conversation.status, messages=_visible(r.conversation),
                          reply=r.reply)

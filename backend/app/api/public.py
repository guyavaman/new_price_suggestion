"""Customer-facing endpoints. No tenant header or API key: the quote link token is the key."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.deps import get_portal
from app.services.portal import CustomerPortal, PortalError, PublicQuote

router = APIRouter(prefix="/public", tags=["customer page"])


class AcceptIn(BaseModel):
    tier: str = Field(..., pattern="^(basic|recommended|premium)$")


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

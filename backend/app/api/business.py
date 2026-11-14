"""Owner screens: today, menu & prices, settings, calendar, kitchen, automation, invoices."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.business.messages import CustomerMessage, customer_messages
from app.business.operations import (
    AutomationAction,
    CalendarDay,
    InvoiceError,
    KitchenSheet,
    TodayView,
    issue_invoice,
    kitchen_sheet,
    latest_quote,
    month_calendar,
    run_automation,
    today_view,
)
from app.business.settings import BusinessSettings, SettingsService
from app.catalog.service import CatalogService, TenantCatalogItem
from app.crm.models import ActivityKind, Actor, Deal
from app.crm.service import CrmService
from app.deps import get_catalog_service, get_crm, get_repo, get_settings_service, get_tenant
from app.integrations.config import TenantConfig
from app.schemas.catalog import CatalogItem

router = APIRouter(tags=["business"])


@router.get("/crm/today", response_model=TodayView)
def today(t: TenantConfig = Depends(get_tenant), crm: CrmService = Depends(get_crm)):
    return today_view(crm, t.tenant_id)


# ---------- settings ----------

@router.get("/settings", response_model=BusinessSettings)
def get_settings(t: TenantConfig = Depends(get_tenant),
                 s: SettingsService = Depends(get_settings_service)):
    return s.get(t.tenant_id)


@router.patch("/settings", response_model=BusinessSettings)
def patch_settings(patch: dict, t: TenantConfig = Depends(get_tenant),
                   s: SettingsService = Depends(get_settings_service)):
    try:
        return s.update(t.tenant_id, patch)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


# ---------- menu & prices ----------

class ItemPatch(BaseModel):
    name_he: str | None = None
    name_en: str | None = None
    price: float | None = None
    description_he: str | None = None
    active: bool | None = None
    serves: int | None = None
    min_qty: int | None = None
    tags: list[str] | None = None


@router.get("/catalog", response_model=list[TenantCatalogItem])
def list_catalog(t: TenantConfig = Depends(get_tenant),
                 svc: CatalogService = Depends(get_catalog_service)):
    return svc.all(t.tenant_id)


@router.post("/catalog", response_model=TenantCatalogItem, status_code=201)
def add_item(item: CatalogItem, t: TenantConfig = Depends(get_tenant),
             svc: CatalogService = Depends(get_catalog_service)):
    if svc.get(t.tenant_id, item.sku):
        raise HTTPException(409, f"SKU {item.sku} already exists")
    return svc.upsert(t.tenant_id, item)


@router.patch("/catalog/{sku}", response_model=TenantCatalogItem)
def patch_item(sku: str, body: ItemPatch, t: TenantConfig = Depends(get_tenant),
               svc: CatalogService = Depends(get_catalog_service)):
    patch = body.model_dump(exclude_unset=True)
    if "price" in patch and (patch["price"] is None or patch["price"] <= 0):
        raise HTTPException(422, "Price must be positive")
    try:
        return svc.update(t.tenant_id, sku, patch)
    except KeyError as e:
        raise HTTPException(404, "Item not found") from e
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


# ---------- calendar & kitchen ----------

@router.get("/crm/calendar", response_model=list[CalendarDay])
def calendar(month: str, t: TenantConfig = Depends(get_tenant),
             crm: CrmService = Depends(get_crm),
             s: SettingsService = Depends(get_settings_service)):
    try:
        return month_calendar(crm, s.get(t.tenant_id), t.tenant_id, month)
    except ValueError as e:
        raise HTTPException(422, "month must be YYYY-MM") from e


@router.get("/kitchen", response_model=KitchenSheet)
def kitchen(day: date, t: TenantConfig = Depends(get_tenant), crm: CrmService = Depends(get_crm),
            repo=Depends(get_repo), svc: CatalogService = Depends(get_catalog_service)):
    return kitchen_sheet(crm, repo, svc.all(t.tenant_id), t.tenant_id, day)


# ---------- automation & invoices ----------

@router.post("/automation/run", response_model=list[AutomationAction])
def automation(t: TenantConfig = Depends(get_tenant), crm: CrmService = Depends(get_crm),
               repo=Depends(get_repo), s: SettingsService = Depends(get_settings_service)):
    """Daily follow-ups. Safe to call repeatedly; schedule it once a day."""
    return run_automation(crm, repo, s.get(t.tenant_id), t.tenant_id)


class InvoiceIn(BaseModel):
    number: str | None = None


@router.post("/crm/deals/{deal_id}/invoice", response_model=Deal)
def invoice(deal_id: str, body: InvoiceIn, t: TenantConfig = Depends(get_tenant),
            crm: CrmService = Depends(get_crm), repo=Depends(get_repo),
            s: SettingsService = Depends(get_settings_service)):
    try:
        return issue_invoice(crm, repo, s.get(t.tenant_id), t.tenant_id, deal_id, body.number)
    except InvoiceError as e:
        raise HTTPException(409, str(e)) from e



# ---------- ready-to-send customer messages (with the personal link) ----------

def _deal_ctx(t, deal_id, crm, repo):
    deal = crm.deals.get(t.tenant_id, deal_id)
    if deal is None:
        raise HTTPException(404, "Deal not found")
    cust = crm.customers.get(t.tenant_id, deal.customer_id)
    return deal, latest_quote(repo, deal), cust


@router.get("/crm/deals/{deal_id}/messages", response_model=list[CustomerMessage])
def deal_messages(deal_id: str, t: TenantConfig = Depends(get_tenant),
                  crm: CrmService = Depends(get_crm), repo=Depends(get_repo),
                  s: SettingsService = Depends(get_settings_service)):
    deal, q, cust = _deal_ctx(t, deal_id, crm, repo)
    return customer_messages(deal, q, cust, s.get(t.tenant_id))


@router.post("/crm/deals/{deal_id}/messages/{kind}/sent", response_model=Deal)
def message_sent(deal_id: str, kind: str, t: TenantConfig = Depends(get_tenant),
                 crm: CrmService = Depends(get_crm), repo=Depends(get_repo),
                 s: SettingsService = Depends(get_settings_service)):
    """The owner sent a message from their phone: keep it on the timeline."""
    deal, q, cust = _deal_ctx(t, deal_id, crm, repo)
    msg = next((m for m in customer_messages(deal, q, cust, s.get(t.tenant_id))
                if m.kind == kind), None)
    if msg is None:
        raise HTTPException(404, "Unknown message")
    deal.sent_messages[kind] = date.today().isoformat()
    deal = crm.save_deal(deal)
    crm.log(t.tenant_id, ActivityKind.note, f"נשלחה הודעה ללקוח: {msg.label}", Actor.user,
            deal_id=deal.id, meta={"message": kind})
    return deal

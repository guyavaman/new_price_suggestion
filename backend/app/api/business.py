"""Owner screens: today, menu & prices, settings, calendar, kitchen, automation, invoices."""

from __future__ import annotations

from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.business.kpis import ProfitReport, profit_report
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
from app.schemas.catalog import CatalogItem, CostSource
from app.services.cost_impact import ImpactRow, impact_of

router = APIRouter(tags=["business"])


@router.get("/reports/profit", response_model=ProfitReport, tags=["profit"])
def profit(months: int = 6, t: TenantConfig = Depends(get_tenant),
           crm: CrmService = Depends(get_crm), repo=Depends(get_repo),
           svc: CatalogService = Depends(get_catalog_service),
           s: SettingsService = Depends(get_settings_service)):
    """Owner-only: revenue and gross profit by month, event type, package and event."""
    return profit_report(crm, repo, svc.all(t.tenant_id), t.tenant_id, s.get(t.tenant_id),
                         months=max(1, min(months, 24)))


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
    cost: float | None = Field(None, ge=0, description="Per unit, before VAT. null = unknown")
    cost_source: CostSource | None = None


class CatalogPatchOut(BaseModel):
    item: TenantCatalogItem
    cost_impact: list[ImpactRow] = Field(default_factory=list)


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


@router.patch("/catalog/{sku}", response_model=CatalogPatchOut)
def patch_item(sku: str, body: ItemPatch, t: TenantConfig = Depends(get_tenant),
               svc: CatalogService = Depends(get_catalog_service),
               crm: CrmService = Depends(get_crm), repo=Depends(get_repo),
               s: SettingsService = Depends(get_settings_service)):
    patch = body.model_dump(exclude_unset=True)
    if "price" in patch and (patch["price"] is None or patch["price"] <= 0):
        raise HTTPException(422, "Price must be positive")
    cur = svc.get(t.tenant_id, sku)
    if cur is None:
        raise HTTPException(404, "Item not found")
    old_cost = cur.cost
    if "cost" in patch:
        if cur.components or cur.category.value == "package":
            raise HTTPException(422, "עלות של חבילה מחושבת מהרכיבים שלה ולא מוזנת ידנית")
        patch["cost_updated_at"] = datetime.now(UTC)
        patch.setdefault("cost_source", CostSource.manual if patch["cost"] is not None else None)
    try:
        item = svc.update(t.tenant_id, sku, patch)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    impact: list[ImpactRow] = []
    rules = s.get(t.tenant_id)
    if (old_cost is not None and item.cost is not None
            and item.cost > old_cost * (1 + rules.cost_alert_threshold)):
        impact = _impact(t.tenant_id, sku, svc, crm, repo)
        if impact:
            lost = -sum(r.delta for r in impact)
            n_q = sum(r.kind == "open_quote" for r in impact)
            n_e = len(impact) - n_q
            crm.add_task(t.tenant_id,
                         f"עלות {item.name_he} עלתה {item.cost / old_cost - 1:.0%}: "
                         f"{n_q} הצעות פתוחות ו-{n_e} אירועים סגורים איבדו ₪{lost:,.0f} רווח",
                         priority="high", created_by=Actor.system)
    return CatalogPatchOut(item=item, cost_impact=impact)


def _impact(tenant: str, sku: str, svc: CatalogService, crm: CrmService, repo):
    return impact_of(sku, svc.items(tenant), repo.list(tenant), crm.deals.list(tenant),
                     date.today())


@router.get("/catalog/{sku}/cost-impact", response_model=list[ImpactRow])
def cost_impact(sku: str, t: TenantConfig = Depends(get_tenant),
                svc: CatalogService = Depends(get_catalog_service),
                crm: CrmService = Depends(get_crm), repo=Depends(get_repo)):
    """Open quotes and upcoming booked events whose profit changed since they were priced."""
    if svc.get(t.tenant_id, sku) is None:
        raise HTTPException(404, "Item not found")
    return _impact(t.tenant_id, sku, svc, crm, repo)


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

"""Stage 7: customer type and history, the sales report, and the terms preview."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.business import commerce
from app.business.settings import SettingsService
from app.business.terms import terms_lines, terms_version
from app.catalog.service import CatalogService
from app.crm.models import ActivityKind, Actor, Customer, CustomerKind, now
from app.crm.service import CrmService
from app.deps import get_catalog_service, get_crm, get_repo, get_settings_service, get_tenant
from app.integrations.config import TenantConfig

router = APIRouter(tags=["commerce"])
KIND_HE = {"private": "פרטי", "business": "עסקי"}


class CustomerPatch(BaseModel):
    name: str | None = Field(None, max_length=120)
    company: str | None = Field(None, max_length=120)
    email: str | None = Field(None, max_length=200)
    notes: str | None = Field(None, max_length=2000)
    kind: CustomerKind | None = None
    clear_kind: bool = Field(False, description="go back to: business if there's a company")


@router.patch("/crm/customers/{customer_id}", response_model=Customer)
def patch_customer(customer_id: str, body: CustomerPatch, t: TenantConfig = Depends(get_tenant),
                   crm: CrmService = Depends(get_crm)):
    c = crm.customers.get(t.tenant_id, customer_id)
    if c is None:
        raise HTTPException(404, "Customer not found")
    data = body.model_dump(exclude_unset=True, exclude={"clear_kind"})
    before = c.kind
    for k, v in data.items():
        setattr(c, k, v.strip() if type(v) is str else v)
    if body.clear_kind:
        c.kind = None
    c.updated_at = now()
    crm.customers.put(c)
    if c.kind != before:
        crm.log(t.tenant_id, ActivityKind.note,
                f"סוג לקוח: {KIND_HE.get(str(c.kind), '') if c.kind else 'לפי שם החברה'}",
                Actor.user, customer_id=c.id)
    for d in crm.deals_for_customer(t.tenant_id, c.id):  # titles and scores use the customer
        crm.save_deal(d)
    return crm.customers.get(t.tenant_id, c.id)


@router.get("/crm/customers/{customer_id}/history", response_model=commerce.CustomerHistory)
def customer_history(customer_id: str, t: TenantConfig = Depends(get_tenant),
                     crm: CrmService = Depends(get_crm), repo=Depends(get_repo),
                     svc: CatalogService = Depends(get_catalog_service),
                     s: SettingsService = Depends(get_settings_service)):
    c = crm.customers.get(t.tenant_id, customer_id)
    if c is None:
        raise HTTPException(404, "Customer not found")
    return commerce.history(crm, repo, svc.all(t.tenant_id), s.get(t.tenant_id), c)


@router.get("/reports/sales", response_model=commerce.SalesReport)
def sales(months: int = 12, t: TenantConfig = Depends(get_tenant),
          crm: CrmService = Depends(get_crm), repo=Depends(get_repo),
          svc: CatalogService = Depends(get_catalog_service),
          s: SettingsService = Depends(get_settings_service)):
    """Owner-only: close rate and average profit by event type and lead source."""
    months = max(1, min(months, 36))
    return commerce.sales_report(crm, repo, svc.all(t.tenant_id), t.tenant_id,
                                 s.get(t.tenant_id), months=months)


class TermsPreview(BaseModel):
    lines: list[str]
    version: str


@router.get("/settings/terms", response_model=TermsPreview)
def terms_preview(t: TenantConfig = Depends(get_tenant),
                  s: SettingsService = Depends(get_settings_service)):
    """The terms exactly as the customer will see them, built from the current settings."""
    lines = terms_lines(s.get(t.tenant_id))
    return TermsPreview(lines=lines, version=terms_version(lines))

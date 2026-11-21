"""Stage 6: closing an event after it happened, planned vs actual, and portion suggestions."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.business import closing
from app.business.settings import SettingsService
from app.catalog.service import CatalogService
from app.crm.models import ActivityKind, Actor, EventClosing
from app.crm.service import CrmService
from app.deps import (
    get_catalog_service,
    get_crm,
    get_repo,
    get_settings_service,
    get_team,
    get_tenant,
)
from app.integrations.config import TenantConfig
from app.schemas.catalog import PortionRule

router = APIRouter(tags=["closing"])


def _deal(crm: CrmService, tenant: str, deal_id: str):
    d = crm.deals.get(tenant, deal_id)
    if d is None:
        raise HTTPException(404, "Deal not found")
    return d


@router.get("/crm/deals/{deal_id}/closing", response_model=closing.ClosingView)
def get_closing(deal_id: str, t: TenantConfig = Depends(get_tenant),
                crm: CrmService = Depends(get_crm), repo=Depends(get_repo),
                svc: CatalogService = Depends(get_catalog_service),
                s: SettingsService = Depends(get_settings_service), team=Depends(get_team)):
    d = _deal(crm, t.tenant_id, deal_id)
    return closing.view(crm, repo, svc.all(t.tenant_id), s.get(t.tenant_id), d, team)


@router.put("/crm/deals/{deal_id}/closing", response_model=closing.ClosingView)
def put_closing(deal_id: str, body: EventClosing, t: TenantConfig = Depends(get_tenant),
                crm: CrmService = Depends(get_crm), repo=Depends(get_repo),
                svc: CatalogService = Depends(get_catalog_service),
                s: SettingsService = Depends(get_settings_service), team=Depends(get_team)):
    d = _deal(crm, t.tenant_id, deal_id)
    if d.event_date is None:
        raise HTTPException(409, "לאירוע אין תאריך")
    rules, catalog = s.get(t.tenant_id), svc.all(t.tenant_id)
    first = d.closing is None
    d.closing = closing.save(d, body, rules, closing.planned_dishes(crm, repo, catalog, rules, d))
    crm.save_deal(d)
    for task in crm.tasks.list(t.tenant_id, lambda x: x.deal_id == d.id and x.kind == "closing"
                               and not x.done):
        task.done = True
        crm.tasks.put(task)
    if first:
        crm.log(t.tenant_id, ActivityKind.note, "סיכום האירוע מולא", Actor.user, deal_id=d.id)
    return closing.view(crm, repo, catalog, rules, crm.deals.get(t.tenant_id, d.id), team)


@router.get("/closing/learning", response_model=closing.LearningView)
def learning(t: TenantConfig = Depends(get_tenant), crm: CrmService = Depends(get_crm),
             repo=Depends(get_repo), svc: CatalogService = Depends(get_catalog_service),
             s: SettingsService = Depends(get_settings_service), team=Depends(get_team)):
    return closing.learning(crm, repo, svc.all(t.tenant_id), s.get(t.tenant_id), t.tenant_id,
                            team=team)


class ApplyIn(BaseModel):
    category: str = Field(..., min_length=1, max_length=40)
    total_per_guest: float = Field(..., gt=0, le=10000)


@router.post("/closing/learning/apply", response_model=closing.Suggestion)
def apply_suggestion(body: ApplyIn, t: TenantConfig = Depends(get_tenant),
                     crm: CrmService = Depends(get_crm), repo=Depends(get_repo),
                     svc: CatalogService = Depends(get_catalog_service),
                     s: SettingsService = Depends(get_settings_service), team=Depends(get_team)):
    """The owner accepted a suggestion: update that category's base amount per guest."""
    rules = s.get(t.tenant_id)
    rule = rules.portion_rules.get(body.category)
    if rule is None:
        raise HTTPException(404, "אין כלל כמויות לקטגוריה הזאת")
    old = rule.total_per_guest
    portions = {k: v.model_dump() for k, v in rules.portion_rules.items()}
    portions[body.category] = PortionRule(**{**rule.model_dump(),
                                             "total_per_guest": body.total_per_guest}).model_dump()
    rules = s.update(t.tenant_id, {"portion_rules": portions})
    crm.log(t.tenant_id, ActivityKind.system,
            f"כמות בסיס ל{closing.CATEGORY_HE.get(body.category, body.category)}: "
            f"{old:g} → {body.total_per_guest:g} לסועד (לפי סיכומי אירועים)", Actor.user)
    view = closing.learning(crm, repo, svc.all(t.tenant_id), rules, t.tenant_id, team=team)
    return next(x for x in view.suggestions if x.category == body.category)

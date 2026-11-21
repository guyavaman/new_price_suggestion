"""Owner screens: today, menu & prices, settings, calendar, kitchen, automation, invoices."""

from __future__ import annotations

from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field

from app.business.changes import ChangeError
from app.business.changes import approve as approve_change
from app.business.changes import decline as decline_change
from app.business.kpis import ProfitReport, profit_report
from app.business.messages import CustomerMessage, customer_messages
from app.business.operations import (
    AutomationAction,
    CalendarDay,
    InvoiceError,
    issue_invoice,
    latest_quote,
    month_calendar,
    run_automation,
)
from app.business.production import KitchenSheet, kitchen_day, production
from app.business.readiness import MANUAL, Readiness, ReadinessPatch, readiness
from app.business.settings import BusinessSettings, SettingsService
from app.business.today import TodayView, today_view
from app.catalog.importer import ImportReport, analyze, template_xlsx
from app.catalog.service import CatalogService, TenantCatalogItem
from app.crm.models import ActivityKind, Actor, Deal, DealStage, SiteConditions
from app.crm.service import CrmService
from app.deps import (
    get_catalog_service,
    get_crm,
    get_purchasing,
    get_repo,
    get_settings_service,
    get_team,
    get_tenant,
)
from app.integrations.config import TenantConfig
from app.purchasing.recipes import recipe_cost, recipe_errors
from app.purchasing.service import PurchasingService
from app.schemas.catalog import CatalogItem, CostSource, Measure, RecipeLine, Slot
from app.schemas.extraction import ContactInfo, ExtractedRequest
from app.services.cost_impact import ImpactRow, impact_of
from app.services.costing import default_context, missing_parts, unit_cost
from app.services.event_menu import PackageMenu, owner_menu
from app.services.packages import package_errors
from app.services.pricing import STYLE_HE, PricingEngine
from app.services.quotes import create_quote, standard_plan, tiers_for
from app.team.planning import equipment_state, staff_plan
from app.team.service import TeamService

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
def today(t: TenantConfig = Depends(get_tenant), crm: CrmService = Depends(get_crm),
          repo=Depends(get_repo), svc: CatalogService = Depends(get_catalog_service),
          s: SettingsService = Depends(get_settings_service),
          ps: PurchasingService = Depends(get_purchasing),
          team: TeamService = Depends(get_team)):
    """What could go wrong this week (with one-click actions), then leads and tasks."""
    return today_view(crm, repo, svc.all(t.tenant_id), s.get(t.tenant_id), ps, t.tenant_id,
                      team=team)


# ---------- event readiness, late changes, quote from an event ----------

def _deal_or_404(crm: CrmService, tenant: str, deal_id: str) -> Deal:
    d = crm.deals.get(tenant, deal_id)
    if d is None:
        raise HTTPException(404, "Deal not found")
    return d


@router.get("/crm/deals/{deal_id}/readiness", response_model=Readiness, tags=["readiness"])
def get_readiness(deal_id: str, t: TenantConfig = Depends(get_tenant),
                  crm: CrmService = Depends(get_crm), repo=Depends(get_repo),
                  svc: CatalogService = Depends(get_catalog_service),
                  s: SettingsService = Depends(get_settings_service),
                  team: TeamService = Depends(get_team)):
    d = _deal_or_404(crm, t.tenant_id, deal_id)
    rules = s.get(t.tenant_id)
    q = latest_quote(repo, d)
    msgs = customer_messages(d, q, crm.customers.get(t.tenant_id, d.customer_id), rules)
    catalog = svc.all(t.tenant_id)
    return readiness(d, q, catalog, rules, msgs,
                     staff=staff_plan(team, d, q, catalog, rules),
                     equipment=equipment_state(team, crm, d, q, catalog))


@router.patch("/crm/deals/{deal_id}/readiness", response_model=Readiness, tags=["readiness"])
def patch_readiness(deal_id: str, body: ReadinessPatch, t: TenantConfig = Depends(get_tenant),
                    crm: CrmService = Depends(get_crm), repo=Depends(get_repo),
                    svc: CatalogService = Depends(get_catalog_service),
                    s: SettingsService = Depends(get_settings_service),
                    team: TeamService = Depends(get_team)):
    """Venue, on-site contact, site conditions and the manual checklist marks."""
    d = _deal_or_404(crm, t.tenant_id, deal_id)
    data = body.model_dump(exclude_unset=True)
    delivery = {f: data[f] for f in ("location", "event_time", "distance_km")
                if f in data and data[f] != getattr(d, f)}
    for f in ("location", "site_contact_name", "site_contact_phone"):
        if f in data:
            setattr(d, f, (data[f] or "").strip() or None)
    for f in ("event_time", "distance_km"):
        if f in data:
            setattr(d, f, data[f])
    if delivery:  # the delivery line depends on these: re-price the quote
        q = latest_quote(repo, d)
        if q is not None:
            old = q.tier().quote.total
            q.request.location, q.request.event_time = d.location, d.event_time
            q.request.distance_km = d.distance_km
            catalog = svc.items(t.tenant_id)
            q.tiers = tiers_for(q.request, q.plan, catalog, PricingEngine(
                catalog, rules=s.get(t.tenant_id), choices=q.menu_choices))
            repo.save(q)
            d.set_value(q.tier().quote.total, q.tier().quote.net)
            if round(old) != round(d.value or 0):
                crm.log(t.tenant_id, ActivityKind.note,
                        f"משלוח עודכן (מיקום/שעה/מרחק). המחיר עודכן ל-₪{d.value:,.0f}",
                        Actor.user, deal_id=d.id)
    if data.get("site") is not None:
        try:
            d.site = SiteConditions.model_validate({**d.site.model_dump(), **data["site"]})
        except ValueError as e:
            raise HTTPException(422, "תנאי שטח לא תקינים") from e
    if "service_style" in data:  # changes the staff ratio: re-price the quote
        style = data["service_style"]
        d.service_style = style.value if style else None
        q = latest_quote(repo, d)
        if q is not None:
            q.request.service.style = style
            catalog = svc.items(t.tenant_id)
            q.tiers = tiers_for(q.request, q.plan, catalog, PricingEngine(
                catalog, rules=s.get(t.tenant_id), choices=q.menu_choices))
            repo.save(q)
            d.set_value(q.tier().quote.total, q.tier().quote.net)
        crm.log(t.tenant_id, ActivityKind.note,
                f"סגנון הגשה: {STYLE_HE.get(d.service_style, 'לא נקבע')}"
                + (f". המחיר עודכן ל-₪{d.value:,.0f}" if q is not None else ""),
                Actor.user, deal_id=d.id)
    for key, on in (data.get("marks") or {}).items():
        if key not in MANUAL:
            raise HTTPException(422, f"סעיף לא מוכר: {key}")
        if on:
            d.ready_marks[key] = datetime.now(UTC).isoformat(timespec="minutes")
            crm.log(t.tenant_id, ActivityKind.note, f"סומן כבוצע: {MANUAL[key]}", Actor.user,
                    deal_id=d.id)
        else:
            d.ready_marks.pop(key, None)
    crm.save_deal(d)
    return get_readiness(deal_id, t, crm, repo, svc, s, team)


@router.post("/crm/deals/{deal_id}/changes/{request_id}/{decision}",
             response_model=Deal, tags=["readiness"])
def decide_change(deal_id: str, request_id: str, decision: str,
                  t: TenantConfig = Depends(get_tenant), crm: CrmService = Depends(get_crm),
                  repo=Depends(get_repo), svc: CatalogService = Depends(get_catalog_service),
                  s: SettingsService = Depends(get_settings_service)):
    """Approve or decline a customer's change after the lock. Approval prices it by policy."""
    d = _deal_or_404(crm, t.tenant_id, deal_id)
    if decision not in ("approve", "decline"):
        raise HTTPException(404, "Not found")
    try:
        if decision == "approve":
            q = latest_quote(repo, d)
            if q is None:
                raise HTTPException(409, "אין הצעה לאירוע")
            approve_change(crm, repo, svc.items(t.tenant_id), s.get(t.tenant_id), t.tenant_id,
                           d, request_id, q)
        else:
            decline_change(crm, t.tenant_id, d, request_id)
    except ChangeError as e:
        raise HTTPException(e.status, str(e)) from e
    for task in crm.tasks.list(t.tenant_id, lambda x: x.deal_id == d.id and not x.done
                               and x.kind == "change_request"):
        crm.complete_task(t.tenant_id, task.id)
    return crm.deals.get(t.tenant_id, d.id)


class QuoteFromDealOut(BaseModel):
    quote_id: str
    number: str


@router.post("/crm/deals/{deal_id}/quote", response_model=QuoteFromDealOut, tags=["readiness"])
def quote_from_deal(deal_id: str, t: TenantConfig = Depends(get_tenant),
                    crm: CrmService = Depends(get_crm), repo=Depends(get_repo),
                    svc: CatalogService = Depends(get_catalog_service),
                    s: SettingsService = Depends(get_settings_service)):
    """A lead without a quote: build one from what the event already says (standard menu)."""
    d = _deal_or_404(crm, t.tenant_id, deal_id)
    missing = [n for n, v in (("מספר אורחים", d.guest_count), ("בשרי/חלבי", d.meal_type))
               if not v]
    if missing:
        raise HTTPException(422, "כדי לבנות הצעה חסר: " + ", ".join(missing))
    c = crm.customers.get(t.tenant_id, d.customer_id)
    rules = s.get(t.tenant_id)
    catalog = svc.items(t.tenant_id)
    req = ExtractedRequest(
        language="he", event_type=d.event_type, guest_count=d.guest_count,
        event_date=d.event_date, location=d.location, kashrut=d.kashrut, meal_type=d.meal_type,
        event_time=d.event_time, distance_km=d.distance_km,
        contact=ContactInfo(name=c.name if c else None, phone=c.phone if c else None,
                            email=c.email if c else None, company=c.company if c else None),
        service={"style": d.service_style} if d.service_style else {})
    q = create_quote(repo, t.tenant_id, req, standard_plan(req, catalog), catalog,
                     PricingEngine(catalog, rules=rules), f"הצעה מתוך האירוע {d.title}")
    d.quote_ids.append(q.id)
    d.set_value(q.tier().quote.total, q.tier().quote.net)
    crm.save_deal(d)
    if d.stage == DealStage.new:
        crm.move_stage(t.tenant_id, d.id, DealStage.quoted, Actor.user)
    crm.log(t.tenant_id, ActivityKind.quote, f"הצעת מחיר {q.number} נוצרה", Actor.user,
            deal_id=d.id, meta={"quote_id": q.id})
    return QuoteFromDealOut(quote_id=q.id, number=q.number)


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
    yield_amount: float | None = Field(None, gt=0, description="What one unit yields (g/portions)")
    slots: list[Slot] | None = None
    recipe: list[RecipeLine] | None = None
    station: str | None = Field(None, max_length=40)
    prep_days: int | None = Field(None, ge=0, le=14)


class CatalogPatchOut(BaseModel):
    item: TenantCatalogItem
    cost_impact: list[ImpactRow] = Field(default_factory=list)


class CatalogRow(TenantCatalogItem):
    """Owner view of an item: its cost as the engine computes it (packages from their dishes,
    at the reference guest count and default dishes)."""
    measure: Measure | None = None  # food/drinks: grams or portions, from the portion rules
    unit_cost: float | None = None
    cost_missing: list[str] = Field(default_factory=list)
    item_margin: float | None = None  # (price - cost) / price
    recipe_cost: float | None = None   # one unit's cost from its recipe and ingredient prices
    recipe_missing: list[str] = Field(default_factory=list)


@router.get("/catalog", response_model=list[CatalogRow])
def list_catalog(t: TenantConfig = Depends(get_tenant),
                 svc: CatalogService = Depends(get_catalog_service),
                 s: SettingsService = Depends(get_settings_service),
                 ps: PurchasingService = Depends(get_purchasing)):
    items = svc.all(t.tenant_id)
    ing = {i.code: i for i in ps.ingredients(t.tenant_id)}
    by_sku = {i.sku: i for i in items}
    rules = s.get(t.tenant_id)
    ctx = default_context(rules)
    rows = []
    for i in items:
        uc = unit_cost(i, by_sku, ctx)
        rule = rules.portion_rules.get(i.category.value)
        rows.append(CatalogRow(**i.model_dump(exclude={"kind"}),
                               measure=rule.measure if rule else None, unit_cost=uc,
                               **_recipe_fields(i, ing),
                               cost_missing=[] if uc is not None else missing_parts(i, by_sku, ctx),
                               item_margin=round((i.price - uc) / i.price, 4)
                               if uc is not None and i.price else None))
    return rows


def _recipe_fields(i: CatalogItem, ing: dict) -> dict:
    if i.kind.value not in ("food", "drink"):
        return {}
    cost, missing = recipe_cost(i, ing)
    return {"recipe_cost": cost, "recipe_missing": missing}


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
               s: SettingsService = Depends(get_settings_service),
               ps: PurchasingService = Depends(get_purchasing)):
    patch = body.model_dump(exclude_unset=True)
    if "price" in patch and (patch["price"] is None or patch["price"] <= 0):
        raise HTTPException(422, "Price must be positive")
    cur = svc.get(t.tenant_id, sku)
    if cur is None:
        raise HTTPException(404, "Item not found")
    old_cost = cur.cost
    if "slots" in patch:
        if cur.category.value != "package":
            raise HTTPException(422, "רק לחבילה יש חלקים לבחירה")
        draft = cur.model_copy(update={"slots": body.slots or []})
        errs = package_errors(draft, {i.sku: i for i in svc.all(t.tenant_id)})
        if errs:
            raise HTTPException(422, "; ".join(errs))
        patch["slots"] = [sl.model_dump() for sl in body.slots or []]
        patch["cost_source"] = CostSource.components
    if "recipe" in patch:
        if cur.kind.value not in ("food", "drink"):
            raise HTTPException(422, "מתכון רק למנות אוכל ושתייה")
        draft = cur.model_copy(update={"recipe": body.recipe or []})
        errs = recipe_errors(draft, {i.code: i for i in ps.ingredients(t.tenant_id)})
        if errs:
            raise HTTPException(422, "; ".join(errs))
        patch["recipe"] = [r.model_dump() for r in body.recipe or []]
    if "prep_days" in patch and patch["prep_days"] is None:
        patch["prep_days"] = 0
    if "recipe" in patch:
        if cur.kind.value not in ("food", "drink"):
            raise HTTPException(422, "מתכון רק למנות אוכל ושתייה")
        draft = cur.model_copy(update={"recipe": body.recipe or []})
        errs = recipe_errors(draft, {i.code: i for i in ps.ingredients(t.tenant_id)})
        if errs:
            raise HTTPException(422, "; ".join(errs))
        patch["recipe"] = [r.model_dump() for r in body.recipe or []]
    if "prep_days" in patch and patch["prep_days"] is None:
        patch["prep_days"] = 0
    if "cost" in patch:
        if cur.category.value == "package":
            raise HTTPException(422, "עלות של חבילה מחושבת מהמנות שלה ולא מוזנת ידנית")
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
        impact = _impact(t.tenant_id, sku, svc, crm, repo, rules)
        if impact:
            lost = -sum(r.delta for r in impact)
            n_q = sum(r.kind == "open_quote" for r in impact)
            n_e = len(impact) - n_q
            crm.add_task(t.tenant_id,
                         f"עלות {item.name_he} עלתה {item.cost / old_cost - 1:.0%}: "
                         f"{n_q} הצעות פתוחות ו-{n_e} אירועים סגורים איבדו ₪{lost:,.0f} רווח",
                         priority="high", created_by=Actor.system)
    return CatalogPatchOut(item=item, cost_impact=impact)


def _impact(tenant: str, sku: str, svc: CatalogService, crm: CrmService, repo, rules=None):
    return impact_of(sku, svc.items(tenant), repo.list(tenant), crm.deals.list(tenant),
                     date.today(), rules)


@router.get("/catalog/import/template", tags=["import"])
def import_template(t: TenantConfig = Depends(get_tenant),
                    svc: CatalogService = Depends(get_catalog_service)) -> Response:
    """Excel to fill in: the current menu with a cost column, package components, a legend."""
    return Response(template_xlsx(svc.all(t.tenant_id)), headers={
        "Content-Disposition": 'attachment; filename="menu-and-costs.xlsx"'},
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@router.post("/catalog/import", response_model=ImportReport, tags=["import"])
async def import_catalog(file: UploadFile, apply: bool = False,
                         t: TenantConfig = Depends(get_tenant),
                         svc: CatalogService = Depends(get_catalog_service),
                         crm: CrmService = Depends(get_crm), repo=Depends(get_repo),
                         s: SettingsService = Depends(get_settings_service)) -> ImportReport:
    """Preview (default) or apply an Excel/CSV of items, prices and costs. Apply writes the
    valid rows only; the report lists every rejected row and why."""
    data = await file.read()
    if len(data) > 5_000_000:
        raise HTTPException(413, "הקובץ גדול מדי (עד 5MB)")
    current = svc.all(t.tenant_id)
    report, items = analyze(file.filename or "file.xlsx", data, current)
    if not apply:
        return report
    old_cost = {i.sku: i.cost for i in current}
    for item, active in items:
        cur = svc.get(t.tenant_id, item.sku)
        svc.upsert(t.tenant_id, CatalogItem.model_validate(item.model_dump()),
                   active=active if active is not None else (cur.active if cur else True))
    rules = s.get(t.tenant_id)
    rises = [i.sku for i, _ in items if old_cost.get(i.sku) and i.cost
             and i.cost > old_cost[i.sku] * (1 + rules.cost_alert_threshold)]
    rows = {r.quote_id: r for sku in rises
            for r in _impact(t.tenant_id, sku, svc, crm, repo, rules)}
    if rows:
        lost = -sum(r.delta for r in rows.values())
        crm.add_task(t.tenant_id, f"ייבוא עלויות: {len(rises)} פריטים התייקרו, "
                                  f"{len(rows)} הצעות/אירועים איבדו ₪{lost:,.0f} רווח",
                     priority="high", created_by=Actor.system)
    crm.log(t.tenant_id, ActivityKind.note,
            f"ייבוא תפריט: {len(report.creates)} חדשים, {len(report.updates)} עודכנו, "
            f"{len(report.errors)} שורות נדחו", Actor.user)
    return report.model_copy(update={"applied": True})


@router.get("/catalog/{sku}/cost-impact", response_model=list[ImpactRow])
def cost_impact(sku: str, t: TenantConfig = Depends(get_tenant),
                svc: CatalogService = Depends(get_catalog_service),
                crm: CrmService = Depends(get_crm), repo=Depends(get_repo),
                s: SettingsService = Depends(get_settings_service)):
    """Open quotes and upcoming booked events whose profit changed since they were priced."""
    if svc.get(t.tenant_id, sku) is None:
        raise HTTPException(404, "Item not found")
    return _impact(t.tenant_id, sku, svc, crm, repo, s.get(t.tenant_id))


# ---------- calendar & kitchen ----------

@router.get("/crm/calendar", response_model=list[CalendarDay])
def calendar(month: str, t: TenantConfig = Depends(get_tenant),
             crm: CrmService = Depends(get_crm),
             s: SettingsService = Depends(get_settings_service)):
    try:
        return month_calendar(crm, s.get(t.tenant_id), t.tenant_id, month)
    except ValueError as e:
        raise HTTPException(422, "month must be YYYY-MM") from e


@router.get("/kitchen", response_model=KitchenSheet, tags=["kitchen"])
def kitchen(day: date, t: TenantConfig = Depends(get_tenant), crm: CrmService = Depends(get_crm),
            repo=Depends(get_repo), svc: CatalogService = Depends(get_catalog_service),
            s: SettingsService = Depends(get_settings_service)):
    """The day's kitchen: dishes (packages broken down), split by kashrut, grouped by station."""
    rules = s.get(t.tenant_id)
    return kitchen_day(production(crm, repo, svc.all(t.tenant_id), rules, t.tenant_id, day, day),
                       day)


class DealMenu(BaseModel):
    quote_id: str | None
    quote_number: str | None
    tier: str | None
    packages: list[PackageMenu]


@router.get("/crm/deals/{deal_id}/menu", response_model=DealMenu, tags=["menu"])
def deal_menu(deal_id: str, t: TenantConfig = Depends(get_tenant),
              crm: CrmService = Depends(get_crm), repo=Depends(get_repo),
              svc: CatalogService = Depends(get_catalog_service),
              s: SettingsService = Depends(get_settings_service)) -> DealMenu:
    """Owner-only: the event's dishes, quantities and cost (selected package of its quote)."""
    deal = crm.deals.get(t.tenant_id, deal_id)
    if deal is None:
        raise HTTPException(404, "Deal not found")
    q = latest_quote(repo, deal)
    if q is None:
        return DealMenu(quote_id=None, quote_number=None, tier=None, packages=[])
    pk = owner_menu(q, {i.sku: i for i in svc.all(t.tenant_id)}, s.get(t.tenant_id),
                    only_selected=True)
    return DealMenu(quote_id=q.id, quote_number=q.number, tier=q.tier().name, packages=pk)


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

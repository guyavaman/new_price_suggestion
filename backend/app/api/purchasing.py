"""Owner screens for stage 3: suppliers, ingredients, the purchase list and the prep schedule."""

from __future__ import annotations

import io
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile
from openpyxl import Workbook
from openpyxl.styles import Font
from pydantic import BaseModel, Field

from app.business.production import PrepDay, PurchaseList, prep_schedule, production, purchase_list
from app.business.settings import SettingsService
from app.catalog.service import CatalogService
from app.crm.models import ActivityKind, Actor
from app.crm.service import CrmService
from app.deps import (
    get_catalog_service,
    get_crm,
    get_purchasing,
    get_repo,
    get_settings_service,
    get_tenant,
)
from app.integrations.config import TenantConfig
from app.purchasing.importer import ImportReport, analyze, template_xlsx
from app.purchasing.models import Ingredient, Supplier
from app.purchasing.service import PurchasingService, TenantIngredient, TenantSupplier

router = APIRouter(tags=["purchasing"])
MAX_RANGE_DAYS = 62


def _range(start: date | None, end: date | None) -> tuple[date, date]:
    start = start or date.today()
    end = end or start + timedelta(days=7)
    if end < start:
        raise HTTPException(422, "תאריך הסיום לפני תאריך ההתחלה")
    if (end - start).days > MAX_RANGE_DAYS:
        raise HTTPException(422, f"טווח של עד {MAX_RANGE_DAYS} ימים")
    return start, end


# ---------- suppliers ----------

@router.get("/suppliers", response_model=list[TenantSupplier])
def suppliers(t: TenantConfig = Depends(get_tenant),
              ps: PurchasingService = Depends(get_purchasing)):
    return ps.suppliers(t.tenant_id)


@router.put("/suppliers/{code}", response_model=TenantSupplier)
def put_supplier(code: str, body: Supplier, t: TenantConfig = Depends(get_tenant),
                 ps: PurchasingService = Depends(get_purchasing)):
    if body.code != code:
        raise HTTPException(422, "קוד הספק לא תואם")
    return ps.put_supplier(t.tenant_id, body)


@router.delete("/suppliers/{code}", status_code=204)
def delete_supplier(code: str, t: TenantConfig = Depends(get_tenant),
                    ps: PurchasingService = Depends(get_purchasing)) -> Response:
    if not ps.delete_supplier(t.tenant_id, code):
        raise HTTPException(404, "הספק לא נמצא")
    return Response(status_code=204)


# ---------- ingredients ----------

@router.get("/ingredients", response_model=list[TenantIngredient])
def ingredients(t: TenantConfig = Depends(get_tenant),
                ps: PurchasingService = Depends(get_purchasing)):
    return ps.ingredients(t.tenant_id)


@router.put("/ingredients/{code}", response_model=TenantIngredient)
def put_ingredient(code: str, body: Ingredient, t: TenantConfig = Depends(get_tenant),
                   ps: PurchasingService = Depends(get_purchasing)):
    if body.code != code:
        raise HTTPException(422, "קוד חומר הגלם לא תואם")
    if body.supplier and body.supplier not in {s.code for s in ps.suppliers(t.tenant_id)}:
        raise HTTPException(422, f"הספק {body.supplier} לא קיים")
    old = next((i for i in ps.ingredients(t.tenant_id) if i.code == code), None)
    return ps.put_ingredient(t.tenant_id, body, old)


@router.delete("/ingredients/{code}", status_code=204)
def delete_ingredient(code: str, t: TenantConfig = Depends(get_tenant),
                      ps: PurchasingService = Depends(get_purchasing),
                      svc: CatalogService = Depends(get_catalog_service)) -> Response:
    used = [i.name_he for i in svc.all(t.tenant_id)
            if any(r.ingredient == code for r in i.recipe)]
    if used:
        raise HTTPException(409, "חומר הגלם נמצא במתכונים: " + ", ".join(used[:5]))
    if not ps.delete_ingredient(t.tenant_id, code):
        raise HTTPException(404, "חומר הגלם לא נמצא")
    return Response(status_code=204)


# ---------- purchase list & prep schedule ----------

def _purchase(t: TenantConfig, start, end, crm, repo, svc, s, ps) -> PurchaseList:
    rules = s.get(t.tenant_id)
    catalog = svc.all(t.tenant_id)
    p = production(crm, repo, catalog, rules, t.tenant_id, start, end)
    return purchase_list(p, catalog, ps.ingredients(t.tenant_id), ps.suppliers(t.tenant_id),
                         rules, start, end, ordered=ps.ordered(t.tenant_id))


class OrderMarkIn(BaseModel):
    supplier: str = Field(..., max_length=40)
    deliver_on: date
    ordered: bool = True


@router.post("/purchasing/orders/mark", status_code=204)
def mark_order(body: OrderMarkIn, t: TenantConfig = Depends(get_tenant),
               ps: PurchasingService = Depends(get_purchasing)) -> Response:
    """The owner placed (or un-placed) the order for this supplier's delivery day."""
    if body.supplier not in {s.code for s in ps.suppliers(t.tenant_id)}:
        raise HTTPException(404, "הספק לא נמצא")
    ps.mark_ordered(t.tenant_id, body.supplier, body.deliver_on, body.ordered)
    return Response(status_code=204)


@router.get("/purchasing/list", response_model=PurchaseList)
def purchasing_list(start: date | None = None, end: date | None = None,
                    t: TenantConfig = Depends(get_tenant), crm: CrmService = Depends(get_crm),
                    repo=Depends(get_repo), svc: CatalogService = Depends(get_catalog_service),
                    s: SettingsService = Depends(get_settings_service),
                    ps: PurchasingService = Depends(get_purchasing)):
    """What to buy for every booked event in the range, by supplier, with order deadlines."""
    start, end = _range(start, end)
    return _purchase(t, start, end, crm, repo, svc, s, ps)


@router.get("/purchasing/list.xlsx")
def purchasing_xlsx(start: date | None = None, end: date | None = None,
                    t: TenantConfig = Depends(get_tenant), crm: CrmService = Depends(get_crm),
                    repo=Depends(get_repo), svc: CatalogService = Depends(get_catalog_service),
                    s: SettingsService = Depends(get_settings_service),
                    ps: PurchasingService = Depends(get_purchasing)) -> Response:
    start, end = _range(start, end)
    pl = _purchase(t, start, end, crm, repo, svc, s, ps)
    wb = Workbook()
    ws = wb.active
    ws.title = "רשימת רכש"
    ws.sheet_view.rightToLeft = True
    ws.append(["ספק", "טלפון", "אספקה", "להזמין עד", "חומר גלם", "כמות", "יחידה",
               "מחיר ליחידה", "עלות משוערת", "למנות", "לאירועים"])
    for o in pl.suppliers:
        for b in o.batches:
            for it in b.items:
                ws.append([o.name, o.phone, b.deliver_on.strftime("%d/%m/%Y"),
                           b.order_by.strftime("%d/%m/%Y %H:%M") if b.order_by else "",
                           it.name, it.quantity, it.unit, it.price, it.cost,
                           ", ".join(it.dishes), ", ".join(it.events)])
    for c in ws[1]:
        c.font = Font(name="Arial", bold=True)
    for col, w in zip("ABCDEFGHIJK", [20, 14, 12, 16, 22, 10, 8, 12, 12, 30, 30], strict=True):
        ws.column_dimensions[col].width = w
    if pl.missing_recipes:
        ms = wb.create_sheet("מנות בלי מתכון")
        ms.sheet_view.rightToLeft = True
        ms.append(["מנה", "אירועים"])
        for m in pl.missing_recipes:
            ms.append([m["name"], ", ".join(m["events"])])
    buf = io.BytesIO()
    wb.save(buf)
    name = f"purchase-{start:%Y%m%d}-{end:%Y%m%d}.xlsx"
    return Response(buf.getvalue(),
                    headers={"Content-Disposition": f'attachment; filename="{name}"'},
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@router.get("/production/schedule", response_model=list[PrepDay], tags=["kitchen"])
def schedule(start: date | None = None, end: date | None = None,
             t: TenantConfig = Depends(get_tenant), crm: CrmService = Depends(get_crm),
             repo=Depends(get_repo), svc: CatalogService = Depends(get_catalog_service),
             s: SettingsService = Depends(get_settings_service)):
    """What the kitchen prepares each day, for every event (dishes made N days ahead)."""
    start, end = _range(start, end)
    p = production(crm, repo, svc.all(t.tenant_id), s.get(t.tenant_id), t.tenant_id,
                   start, end + timedelta(days=14))
    return prep_schedule(p, start, end)


# ---------- import ----------

@router.get("/purchasing/import/template", tags=["import"])
def purchasing_template(t: TenantConfig = Depends(get_tenant),
                        ps: PurchasingService = Depends(get_purchasing),
                        svc: CatalogService = Depends(get_catalog_service)) -> Response:
    """Excel with the current suppliers, ingredients and recipes, to fill in and upload."""
    data = template_xlsx(ps.suppliers(t.tenant_id), ps.ingredients(t.tenant_id),
                         svc.all(t.tenant_id))
    return Response(data, headers={
        "Content-Disposition": 'attachment; filename="suppliers-and-recipes.xlsx"'},
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@router.post("/purchasing/import", response_model=ImportReport, tags=["import"])
async def purchasing_import(file: UploadFile, apply: bool = False,
                            t: TenantConfig = Depends(get_tenant),
                            ps: PurchasingService = Depends(get_purchasing),
                            svc: CatalogService = Depends(get_catalog_service),
                            crm: CrmService = Depends(get_crm)) -> ImportReport:
    """Preview (default) or apply suppliers, ingredients and recipes from Excel. Apply writes the
    valid rows only; the report lists every rejected row and why."""
    data = await file.read()
    if len(data) > 5_000_000:
        raise HTTPException(413, "הקובץ גדול מדי (עד 5MB)")
    report, plan = analyze(file.filename or "file.xlsx", data, ps.suppliers(t.tenant_id),
                           ps.ingredients(t.tenant_id), svc.all(t.tenant_id))
    if not apply:
        return report
    old_ing = {i.code: i for i in ps.ingredients(t.tenant_id)}
    for s in plan.suppliers:
        ps.put_supplier(t.tenant_id, s)
    for i in plan.ingredients:
        ps.put_ingredient(t.tenant_id, i, old_ing.get(i.code))
    for sku, recipe in plan.recipes.items():
        svc.update(t.tenant_id, sku, {"recipe": [r.model_dump() for r in recipe]})
    for sku, fields in plan.dish_fields.items():
        svc.update(t.tenant_id, sku, fields)
    crm.log(t.tenant_id, ActivityKind.note,
            f"ייבוא ספקים ומתכונים: {len(plan.suppliers)} ספקים, "
            f"{len(plan.ingredients)} חומרי גלם, "
            f"{len(plan.recipes)} מתכונים, {len(report.errors)} שורות נדחו", Actor.user)
    return report.model_copy(update={"applied": True})

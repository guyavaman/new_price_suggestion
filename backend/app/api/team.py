"""Owner screens for stage 5 (staff, scheduling, pay, equipment) and the public page a staff
member opens from WhatsApp to confirm."""

from __future__ import annotations

import io
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile
from openpyxl import Workbook
from openpyxl.styles import Font
from pydantic import BaseModel, Field

from app.business.operations import latest_quote
from app.business.settings import SettingsService
from app.catalog.service import CatalogService
from app.crm.models import ActivityKind, Actor, Deal
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
from app.schemas.catalog import ItemRole
from app.team.importer import ImportReport, analyze, template_xlsx
from app.team.models import STAFF_ROLES, Assignment, EquipmentLine, EquipmentType, StaffMember
from app.team.planning import (
    ROLE_HE,
    EquipmentState,
    PayRow,
    StaffPlan,
    auto_assign,
    busy_on,
    candidates,
    equipment_state,
    missing_returns,
    payroll,
    save_event_list,
    staff_plan,
)
from app.team.service import TeamService

router = APIRouter(tags=["team"])
public = APIRouter(prefix="/public", tags=["public"])


def _deal(crm: CrmService, tenant: str, deal_id: str) -> Deal:
    d = crm.deals.get(tenant, deal_id)
    if d is None:
        raise HTTPException(404, "Deal not found")
    return d


# ---------- staff ----------

class MemberIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    phone: str = Field("", max_length=30)
    roles: list[ItemRole] = Field(default_factory=lambda: [ItemRole.waiter])
    hourly_rate: float | None = Field(None, ge=0)
    available_days: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4, 6])
    unavailable_dates: list[date] = Field(default_factory=list)
    notes: str = Field("", max_length=300)
    active: bool = True


def _member(tenant: str, body: MemberIn, mid: str | None = None) -> StaffMember:
    try:
        data = body.model_dump()
        return StaffMember(**data, tenant_id=tenant, **({"id": mid} if mid else {}))
    except ValueError as e:
        raise HTTPException(422, str(e).splitlines()[-1]) from e


@router.get("/staff", response_model=list[StaffMember])
def list_staff(t: TenantConfig = Depends(get_tenant), team: TeamService = Depends(get_team)):
    return team.staff(t.tenant_id)


@router.post("/staff", response_model=StaffMember, status_code=201)
def add_staff(body: MemberIn, t: TenantConfig = Depends(get_tenant),
              team: TeamService = Depends(get_team)):
    return team.members.put(_member(t.tenant_id, body))


@router.put("/staff/{member_id}", response_model=StaffMember)
def put_staff(member_id: str, body: MemberIn, t: TenantConfig = Depends(get_tenant),
              team: TeamService = Depends(get_team)):
    if team.members.get(t.tenant_id, member_id) is None:
        raise HTTPException(404, "לא נמצא")
    return team.members.put(_member(t.tenant_id, body, member_id))


@router.delete("/staff/{member_id}", status_code=204)
def delete_staff(member_id: str, t: TenantConfig = Depends(get_tenant),
                 team: TeamService = Depends(get_team),
                 crm: CrmService = Depends(get_crm)) -> Response:
    """Someone with upcoming shifts can't be deleted (mark them inactive instead)."""
    upcoming = [a for a in team.assignments.list(t.tenant_id, lambda a: a.member_id == member_id
                                                 and a.status != "declined")
                if (d := crm.deals.get(t.tenant_id, a.deal_id)) and d.event_date
                and d.event_date >= date.today()]
    if upcoming:
        raise HTTPException(409, f"משובץ/ת ל-{len(upcoming)} אירועים קרובים. אפשר לסמן כלא פעיל.")
    if not team.members.delete(t.tenant_id, member_id):
        raise HTTPException(404, "לא נמצא")
    return Response(status_code=204)


# ---------- scheduling an event ----------

class DealStaff(StaffPlan):
    candidates: dict[str, list[dict]]  # role -> [{id, name}] free that day


def _plan(team, crm, repo, svc, s, t, deal) -> DealStaff:
    rules = s.get(t.tenant_id)
    q = latest_quote(repo, deal)
    plan = staff_plan(team, deal, q, svc.all(t.tenant_id), rules)
    roles = {n.role for n in plan.needs} | set(STAFF_ROLES[:1])
    return DealStaff(**plan.model_dump(), candidates={
        r.value: [{"id": m.id, "name": m.name, "phone": m.phone}
                  for m in candidates(team, crm, deal, r)] for r in roles})


@router.get("/crm/deals/{deal_id}/staff", response_model=DealStaff)
def deal_staff(deal_id: str, t: TenantConfig = Depends(get_tenant),
               crm: CrmService = Depends(get_crm), repo=Depends(get_repo),
               svc: CatalogService = Depends(get_catalog_service),
               s: SettingsService = Depends(get_settings_service),
               team: TeamService = Depends(get_team)):
    return _plan(team, crm, repo, svc, s, t, _deal(crm, t.tenant_id, deal_id))


@router.post("/crm/deals/{deal_id}/staff/auto", response_model=DealStaff)
def deal_staff_auto(deal_id: str, t: TenantConfig = Depends(get_tenant),
                    crm: CrmService = Depends(get_crm), repo=Depends(get_repo),
                    svc: CatalogService = Depends(get_catalog_service),
                    s: SettingsService = Depends(get_settings_service),
                    team: TeamService = Depends(get_team)):
    """Fill the open places with free staff (fewest shifts this month first)."""
    d = _deal(crm, t.tenant_id, deal_id)
    new = auto_assign(team, crm, d, latest_quote(repo, d), svc.all(t.tenant_id),
                      s.get(t.tenant_id))
    if new:
        names = {m.id: m.name for m in team.staff(t.tenant_id)}
        crm.log(t.tenant_id, ActivityKind.note, "שובצו: " + ", ".join(
            f"{names.get(a.member_id, '?')} ({ROLE_HE[a.role.value]})" for a in new),
            Actor.user, deal_id=d.id)
    return _plan(team, crm, repo, svc, s, t, d)


class AssignIn(BaseModel):
    member_id: str
    role: ItemRole


@router.post("/crm/deals/{deal_id}/staff", response_model=DealStaff)
def deal_staff_add(deal_id: str, body: AssignIn, t: TenantConfig = Depends(get_tenant),
                   crm: CrmService = Depends(get_crm), repo=Depends(get_repo),
                   svc: CatalogService = Depends(get_catalog_service),
                   s: SettingsService = Depends(get_settings_service),
                   team: TeamService = Depends(get_team)):
    d = _deal(crm, t.tenant_id, deal_id)
    m = team.members.get(t.tenant_id, body.member_id)
    if m is None:
        raise HTTPException(404, "לא נמצא")
    if body.role not in m.roles:
        raise HTTPException(422, f"ל{m.name} אין תפקיד {ROLE_HE.get(body.role.value)}")
    if d.event_date and m.id in busy_on(team, crm, t.tenant_id, d.event_date, d.id):
        raise HTTPException(409, f"{m.name} כבר משובץ/ת לאירוע אחר באותו יום")
    if any(a.member_id == m.id and a.status != "declined"
           for a in team.for_deal(t.tenant_id, d.id)):
        raise HTTPException(409, f"{m.name} כבר באירוע הזה")
    team.assignments.put(Assignment(tenant_id=t.tenant_id, deal_id=d.id, member_id=m.id,
                                    role=body.role, planned_hours=s.get(t.tenant_id).staff_hours,
                                    rate=m.hourly_rate))
    return _plan(team, crm, repo, svc, s, t, d)


class AssignPatch(BaseModel):
    status: str | None = Field(None, pattern="^(invited|confirmed|declined)$")
    actual_hours: float | None = Field(None, ge=0, le=24)
    planned_hours: float | None = Field(None, ge=0, le=24)


@router.patch("/crm/deals/{deal_id}/staff/{assignment_id}", response_model=DealStaff)
def deal_staff_patch(deal_id: str, assignment_id: str, body: AssignPatch,
                     t: TenantConfig = Depends(get_tenant), crm: CrmService = Depends(get_crm),
                     repo=Depends(get_repo), svc: CatalogService = Depends(get_catalog_service),
                     s: SettingsService = Depends(get_settings_service),
                     team: TeamService = Depends(get_team)):
    """Owner updates: confirmed by phone, actual hours after the event."""
    d = _deal(crm, t.tenant_id, deal_id)
    a = team.assignments.get(t.tenant_id, assignment_id)
    if a is None or a.deal_id != d.id:
        raise HTTPException(404, "לא נמצא")
    data = body.model_dump(exclude_unset=True)
    if "status" in data and data["status"] != a.status:
        a.status, a.responded_at = data["status"], datetime.now(UTC)
    for f in ("actual_hours", "planned_hours"):
        if f in data:
            setattr(a, f, data[f])
    team.assignments.put(a)
    return _plan(team, crm, repo, svc, s, t, d)


@router.delete("/crm/deals/{deal_id}/staff/{assignment_id}", response_model=DealStaff)
def deal_staff_remove(deal_id: str, assignment_id: str, t: TenantConfig = Depends(get_tenant),
                      crm: CrmService = Depends(get_crm), repo=Depends(get_repo),
                      svc: CatalogService = Depends(get_catalog_service),
                      s: SettingsService = Depends(get_settings_service),
                      team: TeamService = Depends(get_team)):
    d = _deal(crm, t.tenant_id, deal_id)
    a = team.assignments.get(t.tenant_id, assignment_id)
    if a is None or a.deal_id != d.id:
        raise HTTPException(404, "לא נמצא")
    team.assignments.delete(t.tenant_id, assignment_id)
    return _plan(team, crm, repo, svc, s, t, d)


# ---------- monthly pay ----------

def _month(month: str | None) -> tuple[int, int]:
    if not month:
        today = date.today()
        return today.year, today.month
    try:
        y, m = (int(x) for x in month.split("-"))
        date(y, m, 1)
        return y, m
    except ValueError as e:
        raise HTTPException(422, "חודש בפורמט YYYY-MM") from e


@router.get("/staff/payroll", response_model=list[PayRow])
def staff_payroll(month: str | None = None, t: TenantConfig = Depends(get_tenant),
                  crm: CrmService = Depends(get_crm), team: TeamService = Depends(get_team)):
    """What each person earned in the month (confirmed shifts; actual hours where entered)."""
    y, m = _month(month)
    return payroll(team, crm, t.tenant_id, y, m)


@router.get("/staff/payroll.xlsx")
def staff_payroll_xlsx(month: str | None = None, t: TenantConfig = Depends(get_tenant),
                       crm: CrmService = Depends(get_crm),
                       team: TeamService = Depends(get_team)) -> Response:
    y, m = _month(month)
    rows = payroll(team, crm, t.tenant_id, y, m)
    wb = Workbook()
    ws = wb.active
    ws.title = f"שכר {m:02d}-{y}"
    ws.sheet_view.rightToLeft = True
    ws.append(["שם", "טלפון", "אירוע", "תאריך", "תפקיד", "שעות", "שעות בפועל?", "תעריף",
               "סה\"כ"])
    for r in rows:
        for sh in r.shifts:
            ws.append([r.name, r.phone, sh["title"], sh["date"].strftime("%d/%m/%Y"),
                       ROLE_HE.get(sh["role"], sh["role"]), sh["hours"],
                       "כן" if sh["actual"] else "לפי תכנון", r.rate,
                       round(sh["hours"] * r.rate, 2) if r.rate is not None else None])
        ws.append([f"סה\"כ {r.name}", None, None, None, None, r.hours, None, None, r.total])
    for c in ws[1]:
        c.font = Font(name="Arial", bold=True)
    for col, w in zip("ABCDEFGHI", [18, 14, 34, 12, 12, 8, 12, 10, 12], strict=True):
        ws.column_dimensions[col].width = w
    buf = io.BytesIO()
    wb.save(buf)
    return Response(buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument."
                    "spreadsheetml.sheet",
                    headers={"Content-Disposition":
                             f'attachment; filename="payroll-{y}-{m:02d}.xlsx"'})


# ---------- equipment ----------

@router.get("/equipment", response_model=list[EquipmentType])
def stock(t: TenantConfig = Depends(get_tenant), team: TeamService = Depends(get_team)):
    return team.stock(t.tenant_id)


@router.put("/equipment/{code}", response_model=EquipmentType)
def put_stock(code: str, body: EquipmentType, t: TenantConfig = Depends(get_tenant),
              team: TeamService = Depends(get_team)):
    if body.code != code:
        raise HTTPException(422, "הקוד לא תואם")
    return team.put_type(t.tenant_id, body)


@router.delete("/equipment/{code}", status_code=204)
def delete_stock(code: str, t: TenantConfig = Depends(get_tenant),
                 team: TeamService = Depends(get_team)) -> Response:
    if not team.equipment.delete(t.tenant_id, f"{t.tenant_id}:{code}"):
        raise HTTPException(404, "לא נמצא")
    return Response(status_code=204)


@router.get("/equipment/missing")
def equipment_missing(t: TenantConfig = Depends(get_tenant), crm: CrmService = Depends(get_crm),
                      team: TeamService = Depends(get_team)) -> list[dict]:
    """Past events whose equipment didn't all come back."""
    return missing_returns(team, crm, t.tenant_id)


@router.get("/crm/deals/{deal_id}/equipment", response_model=EquipmentState)
def deal_equipment(deal_id: str, t: TenantConfig = Depends(get_tenant),
                   crm: CrmService = Depends(get_crm), repo=Depends(get_repo),
                   svc: CatalogService = Depends(get_catalog_service),
                   team: TeamService = Depends(get_team)):
    d = _deal(crm, t.tenant_id, deal_id)
    return equipment_state(team, crm, d, latest_quote(repo, d), svc.all(t.tenant_id))


class EventEquipmentIn(BaseModel):
    lines: list[EquipmentLine] = Field(..., max_length=200)
    packed: bool | None = None
    returned: bool | None = None


@router.put("/crm/deals/{deal_id}/equipment", response_model=EquipmentState)
def put_deal_equipment(deal_id: str, body: EventEquipmentIn,
                       t: TenantConfig = Depends(get_tenant), crm: CrmService = Depends(get_crm),
                       repo=Depends(get_repo), svc: CatalogService = Depends(get_catalog_service),
                       team: TeamService = Depends(get_team)):
    """What goes out, packed or not, and (after the event) what came back."""
    d = _deal(crm, t.tenant_id, deal_id)
    for ln in body.lines:
        if ln.returned is not None and ln.returned > ln.quantity:
            raise HTTPException(422, f"{ln.name}: חזרו יותר ממה שיצא")
    save_event_list(team, d, body.lines, body.packed, body.returned)
    state = equipment_state(team, crm, d, latest_quote(repo, d), svc.all(t.tenant_id))
    if body.packed:
        crm.log(t.tenant_id, ActivityKind.note, "הציוד נארז ונבדק", Actor.user, deal_id=d.id)
    if body.returned:
        crm.log(t.tenant_id, ActivityKind.note, "הציוד נספר אחרי האירוע" + (
            ": לא חזרו " + ", ".join(state.missing) if state.missing else ": הכל חזר"),
            Actor.user, deal_id=d.id)
    return state


# ---------- import ----------

@router.get("/team/import/template", tags=["import"])
def team_template(t: TenantConfig = Depends(get_tenant),
                  team: TeamService = Depends(get_team)) -> Response:
    return Response(template_xlsx(team.staff(t.tenant_id), team.stock(t.tenant_id)),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition":
                             'attachment; filename="staff-and-equipment.xlsx"'})


@router.post("/team/import", response_model=ImportReport, tags=["import"])
async def team_import(file: UploadFile, apply: bool = False,
                      t: TenantConfig = Depends(get_tenant),
                      team: TeamService = Depends(get_team),
                      crm: CrmService = Depends(get_crm)) -> ImportReport:
    """Preview (default) or apply staff and equipment stock from Excel; valid rows only."""
    data = await file.read()
    if len(data) > 5_000_000:
        raise HTTPException(413, "הקובץ גדול מדי (עד 5MB)")
    report, members, types = analyze(file.filename or "file.xlsx", data, t.tenant_id,
                                     team.staff(t.tenant_id), team.stock(t.tenant_id))
    if not apply:
        return report
    for m in members:
        team.members.put(m)
    for e in types:
        team.put_type(t.tenant_id, e)
    crm.log(t.tenant_id, ActivityKind.note, f"ייבוא צוות וציוד: {len(members)} אנשי צוות, "
            f"{len(types)} סוגי ציוד, {len(report.errors)} שורות נדחו", Actor.user)
    return report.model_copy(update={"applied": True})


# ---------- the staff member's confirmation page (public) ----------

class ShiftView(BaseModel):
    """What a staff member sees: when, where, what role. No customer phone, no money."""
    name: str
    role: str
    event: str
    event_date: date | None
    location: str | None
    guests: int | None
    hours: float
    status: str
    business_name: str


def _shift(token: str, team: TeamService, crm: CrmService, s: SettingsService):
    a = team.by_token(token)
    if a is None:
        raise HTTPException(404, "הקישור לא נמצא")
    d = crm.deals.get(a.tenant_id, a.deal_id)
    m = team.members.get(a.tenant_id, a.member_id)
    if d is None or m is None:
        raise HTTPException(404, "הקישור לא נמצא")
    rules = s.get(a.tenant_id)
    view = ShiftView(name=m.name, role=ROLE_HE[a.role.value],
                     event=EVENT_TYPE_HE.get(d.event_type or "", "אירוע"),
                     event_date=d.event_date, location=d.location,
                     guests=d.final_guest_count or d.guest_count, hours=a.planned_hours,
                     status=a.status, business_name=rules.business_name)
    return a, d, m, view


EVENT_TYPE_HE = {"wedding": "חתונה", "bar_mitzvah": "בר/בת מצווה", "brit": "ברית",
                 "birthday": "יום הולדת", "corporate": "אירוע חברה", "holiday": "חג",
                 "kiddush": "קידוש", "other": "אירוע"}


@public.get("/staff/{token}", response_model=ShiftView)
def shift_view(token: str, team: TeamService = Depends(get_team),
               crm: CrmService = Depends(get_crm),
               s: SettingsService = Depends(get_settings_service)):
    return _shift(token, team, crm, s)[3]


class ShiftAnswer(BaseModel):
    coming: bool


@public.post("/staff/{token}", response_model=ShiftView)
def shift_answer(token: str, body: ShiftAnswer, team: TeamService = Depends(get_team),
                 crm: CrmService = Depends(get_crm),
                 s: SettingsService = Depends(get_settings_service)):
    a, d, m, _ = _shift(token, team, crm, s)
    if d.event_date and d.event_date < date.today():
        raise HTTPException(409, "האירוע כבר עבר")
    new = "confirmed" if body.coming else "declined"
    if a.status != new:
        a.status, a.responded_at = new, datetime.now(UTC)
        team.assignments.put(a)
        role = ROLE_HE[a.role.value]
        crm.log(a.tenant_id, ActivityKind.note,
                f"{m.name} ({role}) {'אישר/ה הגעה' if body.coming else 'ביטל/ה הגעה'}",
                Actor.system, deal_id=d.id)
        if not body.coming:
            crm.add_task(a.tenant_id, f"{m.name} ביטל/ה: לשבץ {role} אחר/ת", deal_id=d.id,
                         priority="high", created_by=Actor.system, kind="staff_declined")
    return _shift(token, team, crm, s)[3]

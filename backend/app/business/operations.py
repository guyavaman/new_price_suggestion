"""The owner's day-to-day: kitchen production sheet, calendar, automatic follow-ups, invoices.

These run on top of the CRM and the stored quotes; nothing here calls an LLM.
"""

from __future__ import annotations

import calendar as cal
import os
from collections import defaultdict
from datetime import date, datetime, timedelta

import httpx
from pydantic import BaseModel, Field

from app.business.settings import BusinessSettings
from app.catalog.service import TenantCatalogItem
from app.crm.models import ActivityKind, Actor, Deal, DealStage, Invoice, now
from app.crm.service import CrmService, _booked
from app.repositories.quotes import StatusChange, StoredQuote
from app.schemas.quote import QuoteStatus

KITCHEN_SKIP = {"staff", "logistics"}
UNIT_HE = {"per_guest": "מנות", "unit": "יח'", "tray": "מגשים", "kg": "ק\"ג", "hour": "שעות"}


def latest_quote(repo, deal: Deal) -> StoredQuote | None:
    for qid in reversed(deal.quote_ids):
        q = repo.get(deal.tenant_id, qid)
        if q:
            return q
    return None


# ---------------------------------------------------------------- kitchen

class KitchenItem(BaseModel):
    sku: str
    name: str
    category: str
    quantity: float
    unit: str
    serves: int | None = None
    events: list[dict] = Field(default_factory=list)  # [{deal_id, title, quantity}]


class KitchenEvent(BaseModel):
    deal_id: str
    title: str
    guests: int | None
    location: str | None
    meal_type: str | None
    dietary: list[str]
    staff: list[str]
    equipment: list[str]
    tier: str | None


class KitchenSheet(BaseModel):
    date: date
    events: list[KitchenEvent]
    food: list[KitchenItem]
    total_guests: int
    missing_quotes: list[str] = Field(default_factory=list)


def kitchen_sheet(crm: CrmService, repo, catalog: list[TenantCatalogItem], tenant: str,
                  day: date) -> KitchenSheet:
    by_sku = {i.sku: i for i in catalog}
    deals = sorted(crm.deals.list(tenant, lambda d: d.event_date == day and _booked(d)),
                   key=lambda d: d.title)
    food: dict[str, KitchenItem] = {}
    events, missing = [], []
    for d in deals:
        q = latest_quote(repo, d)
        staff, equipment = [], []
        if q is None:
            missing.append(d.title)
        else:
            for ln in q.tier().quote.lines:
                item = by_sku.get(ln.sku)
                cat = item.category.value if item else "other"
                if cat in KITCHEN_SKIP:
                    if cat == "staff":
                        staff.append(f"{ln.name_he}: {ln.note or ln.quantity}")
                    continue
                if cat == "equipment":
                    equipment.append(f"{ln.name_he} × {ln.quantity:g}")
                    continue
                k = food.setdefault(ln.sku, KitchenItem(
                    sku=ln.sku, name=ln.name_he, category=cat, quantity=0,
                    unit=UNIT_HE.get(ln.unit, ln.unit), serves=item.serves if item else None))
                k.quantity += ln.quantity
                k.events.append({"deal_id": d.id, "title": d.title, "quantity": ln.quantity})
        events.append(KitchenEvent(
            deal_id=d.id, title=d.title, guests=d.final_guest_count or d.guest_count,
            location=d.location, meal_type=d.meal_type, dietary=d.dietary, staff=staff,
            equipment=equipment, tier=q.selected_tier if q else None))
    order = ["package", "starter", "main", "side", "salad", "canape", "breakfast", "dessert",
             "drink", "bar"]
    items = sorted(food.values(), key=lambda k: (order.index(k.category)
                                                 if k.category in order else 99, k.name))
    return KitchenSheet(date=day, events=events, food=items, missing_quotes=missing,
                        total_guests=sum(e.guests or 0 for e in events))


# ---------------------------------------------------------------- calendar

class CalendarDay(BaseModel):
    date: date
    deals: list[dict]
    events_booked: int
    guests_booked: int
    full: bool


def month_calendar(crm: CrmService, rules: BusinessSettings, tenant: str,
                   month: str) -> list[CalendarDay]:
    y, m = (int(x) for x in month.split("-"))
    days = cal.monthrange(y, m)[1]
    start, end = date(y, m, 1), date(y, m, days)
    deals = crm.deals.list(tenant, lambda d: d.event_date is not None
                           and start <= d.event_date <= end and d.stage != DealStage.lost)
    by_day: dict[date, list[Deal]] = defaultdict(list)
    for d in deals:
        by_day[d.event_date].append(d)
    out = []
    for i in range(days):
        day = start + timedelta(days=i)
        ds = sorted(by_day.get(day, []), key=lambda d: d.stage != DealStage.won)
        booked = [d for d in ds if _booked(d)]
        guests = sum(d.final_guest_count or d.guest_count or 0 for d in booked)
        out.append(CalendarDay(
            date=day, events_booked=len(booked), guests_booked=guests,
            full=len(booked) >= rules.max_events_per_day or guests >= rules.max_guests_per_day,
            deals=[{"id": d.id, "title": d.title, "stage": d.stage.value,
                    "guests": d.final_guest_count or d.guest_count,
                    "temperature": d.temperature.value} for d in ds]))
    return out


# ---------------------------------------------------------------- automation

class AutomationAction(BaseModel):
    rule: str
    deal_id: str
    title: str


def run_automation(crm: CrmService, repo, rules: BusinessSettings, tenant: str,
                   today: date | None = None) -> list[AutomationAction]:
    """Idempotent: each rule runs at most once per deal (recorded in deal.automation).
    Call it from a daily scheduler (cron / Cloud Scheduler) or the 'run now' button."""
    today = today or date.today()
    base = rules.public_base_url.rstrip("/")
    actions: list[AutomationAction] = []

    def act(d: Deal, rule: str, title: str, text: str, due_hours: int = 4,
            priority: str = "normal") -> None:
        crm.add_task(tenant, title, deal_id=d.id, due_at=now() + timedelta(hours=due_hours),
                     priority=priority, created_by=Actor.system)
        crm.log(tenant, ActivityKind.system, text, Actor.system, deal_id=d.id,
                meta={"automation": rule})
        d = crm.deals.get(tenant, d.id)
        d.automation[rule] = today.isoformat()
        crm.save_deal(d)
        actions.append(AutomationAction(rule=rule, deal_id=d.id, title=title))

    for d in crm.deals.list(tenant):
        q = latest_quote(repo, d)
        link = f"{base}/q/{q.public_token}" if q else ""

        if d.stage == DealStage.quoted and q and q.status in (QuoteStatus.draft,
                                                                 QuoteStatus.sent):
            age = (today - q.created_at.date()).days
            valid_until = q.created_at.date() + timedelta(days=rules.quote_valid_days)
            if today > valid_until and "expired" not in d.automation:
                q.status = QuoteStatus.expired
                q.history.append(StatusChange(status=QuoteStatus.expired, note="פג תוקף"))
                repo.save(q)
                act(d, "expired", f"ההצעה {q.number} פגה. להתקשר ולחדש?",
                    f"הצעה {q.number} פגה אחרי {rules.quote_valid_days} ימים")
            elif age >= rules.followup_after_days and "followup" not in d.automation:
                msg = (f"היי, רציתי לוודא שההצעה הגיעה 🙂 אפשר לבחור חבילה ולאשר כאן: {link} "
                       "ואם משהו לא מתאים, נשמח להתאים.")
                act(d, "followup", f"מעקב: ההצעה לא נענתה {age} ימים",
                    f"הודעת מעקב מוצעת ללקוח: {msg}", priority="high" if d.lead_score >= 70
                    else "normal")

        if d.stage == DealStage.won and d.event_date:
            days_left = (d.event_date - today).days
            if (2 <= days_left <= rules.final_count_days_before and d.final_guest_count is None
                    and "final_count" not in d.automation):
                msg = (f"היי! האירוע מתקרב 🎉 אפשר לאשר מספר אורחים סופי עד יומיים לפני: {link}")
                act(d, "final_count", "לבקש אישור מספר אורחים סופי",
                    f"בקשת אישור מספר אורחים: {msg}", due_hours=2)
            if days_left < 0 and "completed" not in d.automation:
                crm.move_stage(tenant, d.id, DealStage.completed, Actor.system)
                if d.invoice is None:
                    act(d, "completed", "להפיק חשבונית לאירוע שהתקיים",
                        "האירוע התקיים. חשבונית ובקשת ביקורת ממתינות", priority="high")
                else:
                    act(d, "completed", "לבקש ביקורת מהלקוח", "האירוע התקיים")
    return actions


# ---------------------------------------------------------------- invoices

class InvoiceError(Exception):
    pass


class MorningInvoices:
    """Green Invoice / Morning API (חשבונית ירוקה). Credentials from env:
    MORNING_API_KEY_ID, MORNING_API_SECRET, MORNING_SANDBOX=1 for the sandbox.
    Document type 305 = חשבונית מס. Verify field names against the sandbox before going live."""

    LIVE = "https://api.greeninvoice.co.il/api/v1"
    SANDBOX = "https://sandbox.d.greeninvoice.co.il/api/v1"

    def __init__(self, client: httpx.Client | None = None):
        sandbox = os.environ.get("MORNING_SANDBOX") == "1"
        self.client = client or httpx.Client(base_url=self.SANDBOX if sandbox else self.LIVE,
                                             timeout=20)

    def _token(self) -> str:
        key, secret = os.environ.get("MORNING_API_KEY_ID"), os.environ.get("MORNING_API_SECRET")
        if not key or not secret:
            raise InvoiceError("חסרים MORNING_API_KEY_ID / MORNING_API_SECRET")
        r = self.client.post("/account/token", json={"id": key, "secret": secret})
        if r.status_code >= 400:
            raise InvoiceError(f"Morning auth failed: {r.status_code}")
        return r.json()["token"]

    def issue(self, deal: Deal, quote: StoredQuote, customer: dict) -> Invoice:
        tier = quote.tier()
        body = {
            "type": 305, "lang": "he", "currency": "ILS", "vatType": 0,
            "description": f"קייטרינג: {deal.title}",
            "client": {"name": customer.get("name") or customer.get("company") or "לקוח",
                       "emails": [customer["email"]] if customer.get("email") else [],
                       "phone": customer.get("phone"), "add": True},
            "income": [{"description": f"{deal.title} · חבילת {tier.name}", "quantity": 1,
                        "price": tier.quote.net, "currency": "ILS", "vatType": 0}],
        }
        r = self.client.post("/documents", json=body,
                             headers={"Authorization": f"Bearer {self._token()}"})
        if r.status_code >= 400:
            raise InvoiceError(f"Morning: {r.status_code} {r.text[:200]}")
        data = r.json()
        url = data.get("url", {})
        return Invoice(provider="morning", number=str(data.get("number")),
                       url=url.get("he") if isinstance(url, dict) else url,
                       amount=tier.quote.total)


def issue_invoice(crm: CrmService, repo, rules: BusinessSettings, tenant: str, deal_id: str,
                  number: str | None = None, morning: MorningInvoices | None = None) -> Deal:
    deal = crm.deals.get(tenant, deal_id)
    if deal is None:
        raise InvoiceError("העסקה לא נמצאה")
    if deal.invoice:
        raise InvoiceError(f"כבר הופקה חשבונית {deal.invoice.number}")
    if deal.stage not in (DealStage.won, DealStage.completed):
        raise InvoiceError("אפשר להפיק חשבונית רק לעסקה שנסגרה")
    q = latest_quote(repo, deal)
    if q is None:
        raise InvoiceError("אין הצעת מחיר לעסקה")
    if rules.invoice_provider == "morning":
        c = crm.customers.get(tenant, deal.customer_id)
        deal.invoice = (morning or MorningInvoices()).issue(
            deal, q, c.model_dump() if c else {})
    else:
        if not number:
            raise InvoiceError("הזינו את מספר החשבונית מתוכנת הנהלת החשבונות")
        deal.invoice = Invoice(provider="manual", number=number, amount=q.tier().quote.total)
    deal = crm.save_deal(deal)
    crm.log(tenant, ActivityKind.system,
            f"חשבונית {deal.invoice.number} הופקה (₪{deal.invoice.amount:,.0f})", Actor.user,
            deal_id=deal.id)
    return deal


# ---------------------------------------------------------------- today

class TodayView(BaseModel):
    waiting_chats: list[dict]
    tasks_due: list[dict]
    events_this_week: list[dict]
    hot_leads: list[dict]
    quotes_waiting: int
    open_quotes_value: float
    deposits_this_month: float
    won_this_month: float


def today_view(crm: CrmService, tenant: str, today: date | None = None) -> TodayView:
    today = today or date.today()
    end_of_day = datetime.combine(today, datetime.max.time()).astimezone()
    month_start = datetime(today.year, today.month, 1).astimezone()
    deals = crm.deals.list(tenant)
    convs = crm.conversations.list(tenant, lambda c: c.status in ("handed_off", "human"))
    waiting = sorted(convs, key=lambda c: (not c.escalated, c.updated_at))
    tasks = [t for t in crm.tasks.list(tenant, lambda t: not t.done)
             if t.due_at is None or t.due_at <= end_of_day]
    tasks.sort(key=lambda t: (t.priority != "high", t.due_at or end_of_day))
    by_id = {d.id: d for d in deals}
    week = sorted([d for d in deals if d.stage == DealStage.won and d.event_date
                   and today <= d.event_date <= today + timedelta(days=7)],
                  key=lambda d: d.event_date)
    hot = sorted([d for d in deals if d.stage in (DealStage.new, DealStage.quoted)
                  and d.temperature == "hot"], key=lambda d: -d.lead_score)
    payments = [p for d in deals for p in d.payments
                if p.status == "paid" and p.paid_at and p.paid_at >= month_start]
    won_month = [d for d in deals if d.stage in (DealStage.won, DealStage.completed)
                 and d.stage_changed_at >= month_start]

    def card(d: Deal) -> dict:
        return {"id": d.id, "title": d.title, "stage": d.stage.value, "value": d.value,
                "event_date": d.event_date, "temperature": d.temperature.value}

    return TodayView(
        waiting_chats=[{"id": c.id, "deal_id": c.deal_id, "escalated": c.escalated,
                        "status": c.status.value, "reason": c.handoff_reason,
                        "last": next((m.text for m in reversed(c.messages)
                                      if m.role == "user"), ""), "updated_at": c.updated_at}
                       for c in waiting],
        tasks_due=[{**t.model_dump(mode="json"),
                    "deal_title": by_id[t.deal_id].title if t.deal_id in by_id else None}
                   for t in tasks[:20]],
        events_this_week=[{**card(d), "guests": d.final_guest_count or d.guest_count,
                           "deposit_paid": d.deposit_paid,
                           "final_count_confirmed": d.final_guest_count is not None}
                          for d in week],
        hot_leads=[card(d) for d in hot[:8]],
        quotes_waiting=sum(1 for d in deals if d.stage == DealStage.quoted),
        open_quotes_value=round(sum(d.value or 0 for d in deals
                                    if d.stage == DealStage.quoted), 2),
        deposits_this_month=round(sum(p.amount for p in payments), 2),
        won_this_month=round(sum(d.value or 0 for d in won_month), 2),
    )

"""The owner's day-to-day: kitchen production sheet, calendar, automatic follow-ups, invoices.

These run on top of the CRM and the stored quotes; nothing here calls an LLM.
"""

from __future__ import annotations

import calendar as cal
import os
from collections import defaultdict
from datetime import date, timedelta

import httpx
from pydantic import BaseModel

from app.business.messages import final_count_text, followup_text
from app.business.settings import BusinessSettings
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
                     priority=priority, created_by=Actor.system, kind=rule)
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
                msg = followup_text(link)
                act(d, "followup", f"מעקב: ההצעה לא נענתה {age} ימים (הודעה מוכנה בעמוד האירוע)",
                    f"הודעת מעקב מוצעת ללקוח: {msg}", priority="high" if d.lead_score >= 70
                    else "normal")

        if d.stage == DealStage.won and d.event_date:
            days_left = (d.event_date - today).days
            if (2 <= days_left <= rules.final_count_days_before and d.final_guest_count is None
                    and "final_count" not in d.automation):
                msg = final_count_text(link, d.event_date - timedelta(days=2))
                act(d, "final_count", "לבקש אישור מספר אורחים סופי (הודעה מוכנה בעמוד האירוע)",
                    f"בקשת אישור מספר אורחים: {msg}", due_hours=2)
            balance = round(max((d.value or 0) - d.deposit_paid, 0), 2)
            if (0 <= days_left <= rules.balance_reminder_days and balance >= 1
                    and "balance" not in d.automation):
                act(d, "balance", f"תזכורת יתרה ₪{balance:,.0f} (הודעה מוכנה בעמוד האירוע)",
                    f"תזכורת יתרה ללקוח: נשארו ₪{balance:,.0f}", due_hours=4)
            if days_left < 0 and "completed" not in d.automation:
                crm.move_stage(tenant, d.id, DealStage.completed, Actor.system)
                if d.invoice is None:
                    act(d, "completed", "להפיק חשבונית לאירוע שהתקיים",
                        "האירוע התקיים. חשבונית ובקשת ביקורת ממתינות", priority="high")
                else:
                    act(d, "completed", "לבקש ביקורת מהלקוח", "האירוע התקיים")
                if d.closing is None and "closing" not in d.automation:
                    act(d, "closing", "למלא סיכום אירוע: אורחים בפועל, שאריות ועלויות",
                        "סיכום האירוע ממתין (מתוכנן מול בפועל)", due_hours=24)

    # returning business customers who went quiet (once per reminder period per customer)
    from app.business.commerce import reorder_due  # late: commerce imports kpis
    for c in reorder_due(crm, rules, tenant, today):
        mine = sorted(crm.deals_for_customer(tenant, c.id),
                      key=lambda d: d.event_date or date.min)
        last = mine[-1] if mine else None
        who = c.company or c.name or "לקוח עסקי"
        days = (today - last.event_date).days if last and last.event_date else None
        title = f"לחזור ל{who}: לא הזמינו {days} ימים" if days else f"לחזור ל{who}"
        crm.add_task(tenant, title, deal_id=last.id if last else None,
                     due_at=now() + timedelta(hours=24), created_by=Actor.system,
                     kind="reorder")
        crm.log(tenant, ActivityKind.system, f"תזכורת ללקוח חוזר: {title}", Actor.system,
                deal_id=last.id if last else None, customer_id=c.id,
                meta={"automation": "reorder"})
        c.reorder_reminded_at = now()
        crm.customers.put(c)
        if last:
            actions.append(AutomationAction(rule="reorder", deal_id=last.id, title=title))
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

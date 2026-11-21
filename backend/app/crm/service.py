"""CRM business logic. Used by the REST API, the AI sales agent and the quote integration."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel

from app.business import kpis
from app.business.kpis import Kpis
from app.business.settings import SettingsService
from app.crm.models import (
    STAGE_HE,
    Activity,
    ActivityKind,
    Actor,
    Conversation,
    Customer,
    Deal,
    DealStage,
    Source,
    Task,
    now,
)
from app.crm.scoring import score
from app.integrations.canonical import EVENT_TYPE_HE, normalize_il_phone
from app.repositories.store import STORE_DIR, Collection

# Business capacity (per tenant settings later): how much the kitchen can take per day.
MAX_EVENTS_PER_DAY = 3  # defaults; the real values come from the owner's settings
MAX_GUESTS_PER_DAY = 600


def _booked(d: Deal) -> bool:
    """Counts against kitchen capacity: closed deals, and hot ones about to close."""
    return d.stage == DealStage.won or (d.stage == DealStage.quoted and d.ready_to_book)


class Availability(BaseModel):
    date: date
    available: bool
    events_booked: int
    guests_booked: int
    remaining_guests: int
    note: str


class Dashboard(BaseModel):
    """Reports screen: the shared KPI set plus the upcoming events list."""
    kpis: Kpis
    upcoming_events: list[Deal]


class CrmService:
    def __init__(self, base: Path = STORE_DIR, settings: SettingsService | None = None):
        self.settings = settings or SettingsService(base)
        self.customers = Collection(Customer, base / "crm_customers.json")
        self.deals = Collection(Deal, base / "crm_deals.json")
        self.activities = Collection(Activity, base / "crm_activities.json")
        self.tasks = Collection(Task, base / "crm_tasks.json")
        self.conversations = Collection(Conversation, base / "crm_conversations.json")

    # ---------- customers ----------
    def find_customer(self, tenant: str, phone: str | None = None,
                      email: str | None = None) -> Customer | None:
        p = normalize_il_phone(phone) or phone
        e = (email or "").strip().lower() or None
        for c in self.customers.list(tenant):
            if (p and c.phone == p) or (e and (c.email or "").lower() == e):
                return c
        return None

    def upsert_customer(self, tenant: str, *, name: str | None = None, phone: str | None = None,
                        email: str | None = None, company: str | None = None,
                        source: Source = Source.manual,
                        customer_id: str | None = None) -> Customer:
        c = (self.customers.get(tenant, customer_id) if customer_id else None) \
            or self.find_customer(tenant, phone, email)
        if c is None:
            c = Customer(tenant_id=tenant, source=source)
        # fill blanks, never erase what we already know
        c.name = name or c.name
        c.phone = normalize_il_phone(phone) or phone or c.phone
        c.email = (email.strip().lower() if email else None) or c.email
        c.company = company or c.company
        c.updated_at = now()
        return self.customers.put(c)

    # ---------- deals ----------
    @staticmethod
    def deal_title(event_type: str | None, customer: Customer | None, guests: int | None,
                   d: date | None) -> str:
        parts = [EVENT_TYPE_HE.get(event_type or "other", "אירוע")]
        if customer and (customer.name or customer.company):
            parts.append(customer.name or customer.company)
        if guests:
            parts.append(f"{guests} אורחים")
        if d:
            parts.append(d.strftime("%d.%m"))
        return " · ".join(parts)

    def save_deal(self, deal: Deal) -> Deal:
        customer = self.customers.get(deal.tenant_id, deal.customer_id)
        deal.lead_score, deal.score_reasons = score(
            deal, customer, weights=self.settings.get(deal.tenant_id).score_weights)
        deal.title = self.deal_title(deal.event_type, customer, deal.guest_count, deal.event_date)
        deal.updated_at = now()
        return self.deals.put(deal)

    def move_stage(self, tenant: str, deal_id: str, stage: DealStage, actor: Actor = Actor.user,
                   reason: str | None = None) -> Deal:
        deal = self.deals.get(tenant, deal_id)
        if deal is None:
            raise KeyError(deal_id)
        if deal.stage == stage:
            return deal
        old = deal.stage
        deal.stage, deal.stage_changed_at = stage, now()
        if stage == DealStage.won and deal.won_at is None:
            deal.won_at = deal.stage_changed_at
        if stage == DealStage.lost:
            deal.lost_reason = reason
        self.save_deal(deal)
        text = f"{STAGE_HE[old]} ← {STAGE_HE[stage]}" + (f" ({reason})" if reason else "")
        self.log(tenant, ActivityKind.stage, text, actor, deal_id=deal.id,
                 customer_id=deal.customer_id, meta={"from": old.value, "to": stage.value})
        return deal

    def deals_for_customer(self, tenant: str, customer_id: str) -> list[Deal]:
        return self.deals.list(tenant, lambda d: d.customer_id == customer_id)

    # ---------- activities & tasks ----------
    def log(self, tenant: str, kind: ActivityKind, text: str, actor: Actor = Actor.system,
            deal_id: str | None = None, customer_id: str | None = None,
            meta: dict | None = None) -> Activity:
        return self.activities.put(Activity(tenant_id=tenant, kind=kind, text=text, actor=actor,
                                            deal_id=deal_id, customer_id=customer_id,
                                            meta=meta or {}))

    def timeline(self, tenant: str, deal_id: str) -> list[Activity]:
        return sorted(self.activities.list(tenant, lambda a: a.deal_id == deal_id),
                      key=lambda a: a.at, reverse=True)

    def add_task(self, tenant: str, title: str, deal_id: str | None = None,
                 due_at: datetime | None = None, priority: str = "normal",
                 created_by: Actor = Actor.user, kind: str | None = None) -> Task:
        t = self.tasks.put(Task(tenant_id=tenant, title=title, deal_id=deal_id, due_at=due_at,
                                priority=priority, created_by=created_by, kind=kind))
        self.log(tenant, ActivityKind.task, f"משימה: {title}", created_by, deal_id=deal_id)
        return t

    def complete_task(self, tenant: str, task_id: str) -> Task:
        t = self.tasks.get(tenant, task_id)
        if t is None:
            raise KeyError(task_id)
        t.done = True
        return self.tasks.put(t)

    # ---------- capacity ----------
    def availability(self, tenant: str, d: date, guests: int = 0,
                     exclude_deal: str | None = None) -> Availability:
        rules = self.settings.get(tenant)
        booked = self.deals.list(tenant, lambda x: x.event_date == d and _booked(x)
                                 and x.id != exclude_deal)
        events = len(booked)
        g = sum(x.final_guest_count or x.guest_count or 0 for x in booked)
        remaining = max(0, rules.max_guests_per_day - g)
        ok = events < rules.max_events_per_day and guests <= remaining
        if d < date.today():
            ok, note = False, "התאריך עבר"
        elif ok:
            note = "פנוי" if events == 0 else f"פנוי ({events} אירועים כבר מתוכננים)"
        elif events >= rules.max_events_per_day:
            note = "היומן מלא בתאריך הזה"
        else:
            note = f"נשאר מקום לעד {remaining} אורחים"
        return Availability(date=d, available=ok, events_booked=events, guests_booked=g,
                            remaining_guests=remaining, note=note)

    # ---------- dashboard ----------
    def dashboard(self, tenant: str, today: date | None = None) -> Dashboard:
        rules = self.settings.get(tenant)
        k = kpis.compute(self, tenant, rules, today)
        horizon = k.as_of + timedelta(days=30)
        upcoming = sorted([d for d in self.deals.list(tenant)
                           if d.event_date and k.as_of <= d.event_date <= horizon
                           and d.stage in (DealStage.won, DealStage.quoted)],
                          key=lambda d: d.event_date)
        return Dashboard(kpis=k, upcoming_events=upcoming)

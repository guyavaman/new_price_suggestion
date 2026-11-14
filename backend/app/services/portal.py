"""The customer's side of a quote: a private link where they pick a package, approve it, pay
the deposit, and later confirm the final guest count. No login; the link token is the key.

Approval + paid deposit is the moment the deal is really won, so that is what moves the CRM.
"""

from __future__ import annotations

from datetime import date, timedelta

from pydantic import BaseModel

from app.business.settings import BusinessSettings, SettingsService
from app.catalog.service import CatalogService
from app.crm.models import ActivityKind, Actor, Deal, DealStage, Payment, now
from app.crm.service import CrmService
from app.integrations.canonical import EVENT_TYPE_HE, EventType
from app.integrations.config import TenantConfig, load_tenant
from app.integrations.sync import SyncService
from app.payments.providers import get_provider
from app.repositories.quotes import StatusChange, StoredQuote
from app.schemas.quote import QuoteStatus
from app.services.editing import QuoteEditor
from app.services.pricing import PricingEngine
from app.services.quotes import tiers_for

FINAL_COUNT_CLOSES_DAYS_BEFORE = 2
HIDDEN_FROM_CUSTOMER = {"staff", "logistics"}


class PortalError(Exception):
    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


class PublicTier(BaseModel):
    key: str
    name: str
    total: float
    per_guest: float | None
    deposit: float
    items: list[dict]  # name, quantity, unit (no internal prices or SKUs)
    services: list[str]  # staff, delivery etc. as plain text


class PublicQuote(BaseModel):
    business_name: str
    business_phone: str
    number: str
    status: str
    customer_name: str | None
    event: dict
    cover_note: str | None
    tiers: list[PublicTier]
    selected_tier: str
    valid_until: date
    expired: bool
    deposit_rate: float
    deposit_paid: float
    can_accept: bool
    can_update_count: bool
    final_guest_count: int | None


class CustomerPortal:
    def __init__(self, repo, crm: CrmService, catalog: CatalogService,
                 settings: SettingsService, sync: SyncService | None = None,
                 tenants=load_tenant):
        self.repo, self.crm, self.catalog, self.settings = repo, crm, catalog, settings
        self.sync, self.tenants = sync, tenants

    # ---------- helpers ----------
    def _quote(self, token: str) -> StoredQuote:
        q = self.repo.find_by_token(token)
        if q is None:
            raise PortalError("הקישור לא תקין", 404)
        return q

    def _deal(self, q: StoredQuote) -> Deal | None:
        return next(iter(self.crm.deals.list(q.tenant_id, lambda d: q.id in d.quote_ids)), None)

    def _rules(self, q: StoredQuote) -> BusinessSettings:
        return self.settings.get(q.tenant_id)

    def _valid_until(self, q: StoredQuote, rules: BusinessSettings) -> date:
        return (q.created_at + timedelta(days=rules.quote_valid_days)).date()

    def _emit(self, q: StoredQuote, event: EventType) -> None:
        tenant: TenantConfig | None = self.tenants(q.tenant_id)
        if self.sync and tenant:
            self.sync.deliver(tenant, q, event)

    # ---------- view ----------
    def view(self, token: str, today: date | None = None) -> PublicQuote:
        today = today or date.today()
        q = self._quote(token)
        rules, deal = self._rules(q), self._deal(q)
        valid_until = self._valid_until(q, rules)
        expired = q.status != QuoteStatus.approved and today > valid_until
        by_sku = {i.sku: i for i in self.catalog.all(q.tenant_id)}
        tiers = []
        for t in q.tiers:
            items, services = [], []
            for ln in t.quote.lines:
                cat = by_sku.get(ln.sku)
                if cat and cat.category.value in HIDDEN_FROM_CUSTOMER:
                    staff = cat.category.value == "staff" and ln.note
                    services.append(f"{ln.name_he} ({ln.note})" if staff else ln.name_he)
                else:
                    items.append({"name": ln.name_he, "quantity": ln.quantity, "unit": ln.unit})
            tiers.append(PublicTier(key=t.key, name=t.name, total=t.quote.total,
                                    per_guest=t.quote.per_guest, items=items, services=services,
                                    deposit=round(t.quote.total * rules.deposit_rate, 2)))
        r = q.request
        event_date = r.event_date
        return PublicQuote(
            business_name=rules.business_name, business_phone=rules.phone, number=q.number,
            status=q.status.value, customer_name=r.contact.name,
            event={"type": EVENT_TYPE_HE.get(r.event_type.value if r.event_type else "other"),
                   "date": event_date, "guests": r.guest_count, "location": r.location,
                   "meal_type": r.meal_type.value if r.meal_type else None,
                   "kashrut": r.kashrut.value if r.kashrut else None},
            cover_note=q.tier().plan.cover_note or None, tiers=tiers,
            selected_tier=q.selected_tier, valid_until=valid_until, expired=expired,
            deposit_rate=rules.deposit_rate, deposit_paid=deal.deposit_paid if deal else 0,
            can_accept=q.status in (QuoteStatus.draft, QuoteStatus.sent) and not expired,
            can_update_count=bool(q.status == QuoteStatus.approved and event_date
                                  and (event_date - today).days >= FINAL_COUNT_CLOSES_DAYS_BEFORE),
            final_guest_count=deal.final_guest_count if deal else None,
        )

    # ---------- accept + deposit ----------
    def accept(self, token: str, tier: str, today: date | None = None) -> dict:
        v = self.view(token, today)
        if not v.can_accept:
            raise PortalError("פג תוקף ההצעה או שכבר אושרה. צרו קשר ונשמח לעדכן."
                              if v.expired else "ההצעה כבר אושרה")
        q = self._quote(token)
        q.tier(tier)  # validates
        q.selected_tier = tier
        rules = self._rules(q)
        deal = self._deal(q)
        deposit = round(q.tier().quote.total * rules.deposit_rate, 2)
        if deposit <= 0:
            self._approve(q, deal, None)
            return {"approved": True, "checkout_url": None}
        self.repo.save(q)
        if deal is None:  # quote never reached the CRM (no integration): create it now
            self._emit(q, EventType.updated)
            deal = self._deal(q)
        if deal is None:
            raise PortalError("לא נמצאה עסקה להצעה", 500)
        deal.payments = [p for p in deal.payments if p.status != "pending"]
        payment = Payment(amount=deposit, provider=rules.payment_provider)
        deal.payments.append(payment)
        self.crm.save_deal(deal)
        self.crm.log(q.tenant_id, ActivityKind.quote,
                     f"הלקוח בחר חבילת {q.tier().name} ועבר לתשלום מקדמה ₪{deposit:,.0f}",
                     Actor.customer, deal_id=deal.id)
        url = get_provider(rules.payment_provider).checkout_url(payment, token, rules)
        return {"approved": False, "checkout_url": url, "payment_id": payment.id,
                "amount": deposit}

    def payment_info(self, token: str, payment_id: str) -> dict:
        q = self._quote(token)
        deal = self._deal(q)
        p = next((p for p in (deal.payments if deal else []) if p.id == payment_id), None)
        if p is None:
            raise PortalError("התשלום לא נמצא", 404)
        rules = self._rules(q)
        return {"amount": p.amount, "status": p.status, "business_name": rules.business_name,
                "quote_number": q.number, "tier": q.tier().name}

    def confirm_payment(self, token: str, payment_id: str, provider_ref: str | None = None) -> dict:
        q = self._quote(token)
        deal = self._deal(q)
        p = next((p for p in (deal.payments if deal else []) if p.id == payment_id), None)
        if p is None:
            raise PortalError("התשלום לא נמצא", 404)
        if p.status == "paid":
            return {"approved": True, "already": True}  # idempotent: webhooks retry
        p.status, p.paid_at, p.provider_ref = "paid", now(), provider_ref
        self.crm.save_deal(deal)
        self.crm.log(q.tenant_id, ActivityKind.quote, f"מקדמה ₪{p.amount:,.0f} שולמה ✓",
                     Actor.customer, deal_id=deal.id)
        self._approve(q, deal, p)
        return {"approved": True}

    def _approve(self, q: StoredQuote, deal: Deal | None, payment: Payment | None) -> None:
        q.status = QuoteStatus.approved
        q.history.append(StatusChange(status=QuoteStatus.approved,
                                      note="אושר על ידי הלקוח" + (" + מקדמה" if payment else "")))
        self.repo.save(q)
        self._emit(q, EventType.approved)  # moves the deal to won via the CRM adapter
        deal = self._deal(q)
        if deal and deal.stage != DealStage.won:  # no integration configured: do it directly
            deal.value = q.tier().quote.total
            self.crm.save_deal(deal)
            self.crm.move_stage(q.tenant_id, deal.id, DealStage.won, Actor.customer)

    # ---------- final guest count ----------
    def update_guest_count(self, token: str, guests: int, today: date | None = None) -> PublicQuote:
        v = self.view(token, today)
        if not v.can_update_count:
            raise PortalError("אפשר לעדכן מספר אורחים רק בהצעה מאושרת ועד יומיים לפני האירוע")
        if not 1 <= guests <= 5000:
            raise PortalError("מספר אורחים לא תקין", 422)
        q = self._quote(token)
        old = q.request.guest_count
        catalog = self.catalog.items(q.tenant_id)
        ed = QuoteEditor(q.request, q.plan, catalog)
        ed.set_guest_count(guests)
        q.request, q.plan = ed.req, ed.result_plan()
        engine = PricingEngine(catalog, rules=self._rules(q))
        q.tiers = tiers_for(q.request, q.plan, catalog, engine)
        self.repo.save(q)
        deal = self._deal(q)
        if deal:
            deal.final_guest_count, deal.guest_count = guests, guests
            deal.value = q.tier().quote.total
            self.crm.save_deal(deal)
            self.crm.log(q.tenant_id, ActivityKind.quote,
                         f"הלקוח אישר מספר אורחים סופי: {guests} (היה {old}). "
                         f"סה\"כ מעודכן ₪{deal.value:,.0f}", Actor.customer, deal_id=deal.id)
        self._emit(q, EventType.updated)
        return self.view(token, today)

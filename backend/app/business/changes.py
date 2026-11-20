"""Changes after the lock date (stage 4).

Until `guest_lock_days` / `menu_lock_days` before the event the customer changes the guest
count and dishes in their link directly. After that the change becomes a request: the owner
sees it on Today and in the event card and approves or declines it. Approving prices the
change by the business's policy, as an adjustment line on the quote:
- guests added after the lock: the extra guests cost `late_guest_surcharge` more;
- guests removed after the lock: when `late_decrease_charged`, the event is still charged for
  the locked count (the kitchen makes the new count).
"""

from __future__ import annotations

from datetime import date, timedelta

from app.business.settings import BusinessSettings
from app.crm.models import ActivityKind, Actor, ChangeRequest, Deal, now
from app.crm.service import CrmService
from app.repositories.quotes import StoredQuote
from app.schemas.catalog import CatalogItem
from app.schemas.quote import Adjustment
from app.services.editing import QuoteEditor
from app.services.event_menu import apply_choice, describe
from app.services.pricing import PricingEngine
from app.services.quotes import tiers_for


class ChangeError(Exception):
    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


def guest_lock_date(event_date: date | None, rules: BusinessSettings) -> date | None:
    return event_date - timedelta(days=rules.guest_lock_days) if event_date else None


def menu_lock_date(event_date: date | None, rules: BusinessSettings) -> date | None:
    return event_date - timedelta(days=rules.menu_lock_days) if event_date else None


def set_guests(q: StoredQuote, guests: int, catalog: list[CatalogItem], rules: BusinessSettings,
               adjustment: Adjustment | None = None) -> StoredQuote:
    """Re-price every tier for a new guest count (keeping dishes and earlier adjustments)."""
    ed = QuoteEditor(q.request, q.plan, catalog)
    ed.set_guest_count(guests)
    plan = ed.result_plan()
    plan.adjustments = list(q.plan.adjustments) + ([adjustment] if adjustment else [])
    q.request, q.plan = ed.req, plan
    engine = PricingEngine(catalog, rules=rules, choices=q.menu_choices)
    q.tiers = tiers_for(q.request, q.plan, catalog, engine)
    return q


def request_change(crm: CrmService, tenant: str, deal: Deal, kind: str, payload: dict,
                   summary: str) -> ChangeRequest:
    # one pending request per kind: a newer one replaces the older
    deal.change_requests = [r for r in deal.change_requests
                            if not (r.kind == kind and r.status == "pending")]
    req = ChangeRequest(kind=kind, payload=payload, summary=summary)
    deal.change_requests.append(req)
    crm.save_deal(deal)
    crm.add_task(tenant, f"בקשת שינוי אחרי הנעילה: {summary}", deal_id=deal.id,
                 priority="high", created_by=Actor.system, kind="change_request")
    crm.log(tenant, ActivityKind.note, f"הלקוח ביקש אחרי מועד הנעילה: {summary}",
            Actor.customer, deal_id=deal.id, meta={"change_request": req.id})
    return req


def _pending(deal: Deal, request_id: str) -> ChangeRequest:
    req = next((r for r in deal.change_requests if r.id == request_id), None)
    if req is None:
        raise ChangeError("הבקשה לא נמצאה", 404)
    if req.status != "pending":
        raise ChangeError("הבקשה כבר טופלה")
    return req


def late_guest_adjustment(q: StoredQuote, old: int, new: int, catalog: list[CatalogItem],
                          rules: BusinessSettings) -> tuple[Adjustment | None, str]:
    """The policy's price for changing `old` → `new` guests after the lock (before VAT)."""
    before = q.tier().quote.subtotal
    probe = set_guests(q.model_copy(deep=True), new, catalog, rules)
    after = probe.tier().quote.subtotal
    if new > old and rules.late_guest_surcharge > 0:
        amount = round((after - before) * rules.late_guest_surcharge, 2)
        return (Adjustment(key=f"late-add-{new}", amount=amount,
                           label=f"תוספת {new - old} אורחים אחרי מועד הנעילה "
                                 f"({rules.late_guest_surcharge:.0%})"),
                f"תוספת של ₪{amount:,.0f} לפני מע\"מ ({rules.late_guest_surcharge:.0%} על "
                f"האורחים שנוספו)")
    if new < old and rules.late_decrease_charged:
        amount = round(before - after, 2)
        return (Adjustment(key=f"late-keep-{old}", amount=amount,
                           label=f"חיוב לפי הכמות שננעלה ({old} אורחים)"),
                f"החיוב נשאר לפי {old} אורחים (₪{amount:,.0f} לפני מע\"מ)")
    return None, "לפי המחיר הרגיל"


def approve(crm: CrmService, repo, catalog: list[CatalogItem], rules: BusinessSettings,
            tenant: str, deal: Deal, request_id: str, q: StoredQuote) -> ChangeRequest:
    req = _pending(deal, request_id)
    if req.kind == "guests":
        old, new = int(req.payload["old"]), int(req.payload["new"])
        adj, note = late_guest_adjustment(q, old, new, catalog, rules)
        q = set_guests(q, new, catalog, rules, adj)
        deal.final_guest_count = deal.guest_count = new
        req.price_note = note
    elif req.kind == "menu":
        by_sku = {i.sku: i for i in catalog}
        errs = apply_choice(q, req.payload["package"], req.payload["choice"], by_sku, rules,
                            by_customer=False)
        if errs:
            raise ChangeError("; ".join(errs), 422)
        req.price_note = "המנות עודכנו"
    else:
        raise ChangeError("סוג בקשה לא מוכר", 422)
    repo.save(q)
    req.status, req.decided_at = "approved", now()
    deal.set_value(q.tier().quote.total, q.tier().quote.net)
    crm.save_deal(deal)
    crm.log(tenant, ActivityKind.note, f"אושרה בקשת הלקוח: {req.summary}. {req.price_note}",
            Actor.user, deal_id=deal.id, meta={"change_request": req.id})
    return req


def decline(crm: CrmService, tenant: str, deal: Deal, request_id: str) -> ChangeRequest:
    req = _pending(deal, request_id)
    req.status, req.decided_at = "declined", now()
    crm.save_deal(deal)
    crm.log(tenant, ActivityKind.note, f"נדחתה בקשת הלקוח: {req.summary}", Actor.user,
            deal_id=deal.id, meta={"change_request": req.id})
    return req


def menu_summary(pkg: CatalogItem, choice: dict, by_sku: dict) -> str:
    return f"שינוי מנות ב{pkg.name_he}: {describe(pkg, choice, by_sku)}"

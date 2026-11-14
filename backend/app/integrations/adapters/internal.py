"""Built-in CRM adapter: quote events flow into our own CRM like into any external one.

- A quote linked to a deal moves that deal's stage and value.
- A quote with no deal (e.g. created from an email via POST /quotes) creates the customer and
  the deal, so nothing reaches the business without landing in the pipeline.
"""

from __future__ import annotations

from app.crm.models import ActivityKind, Actor, Deal, DealStage, Source
from app.crm.service import CrmService
from app.integrations.base import ExternalRefs, SyncResult
from app.integrations.canonical import EventType, QuoteEvent
from app.integrations.config import IntegrationConfig

STAGE_FOR_EVENT = {
    EventType.sent: DealStage.quoted,
    EventType.approved: DealStage.won,
    EventType.rejected: DealStage.lost,
    EventType.expired: DealStage.lost,
}


class InternalCrmAdapter:
    def __init__(self, config: IntegrationConfig, client=None, crm: CrmService | None = None):
        self.config = config
        self.crm = crm or CrmService()

    def sync(self, event: QuoteEvent, refs: ExternalRefs) -> SyncResult:
        t, deal_info, c = event.tenant_id, event.deal, event.contact
        deal = self.crm.deals.get(t, refs.deal_id) if refs.deal_id else None
        if deal is None:
            deal = next(iter(self.crm.deals.list(t, lambda d: deal_info.quote_id in d.quote_ids)),
                        None)
        if deal is None:
            cust = self.crm.upsert_customer(t, name=c.name, phone=c.phone_raw or c.phone,
                                            email=c.email, company=c.company, source=Source.email)
            deal = Deal(tenant_id=t, customer_id=cust.id, title="", source=Source.email,
                        stage=DealStage.new, quote_ids=[deal_info.quote_id],
                        event_type=deal_info.event_type, event_date=deal_info.event_date,
                        guest_count=deal_info.guest_count, location=deal_info.location,
                        kashrut=deal_info.kashrut, meal_type=deal_info.meal_type)
            deal = self.crm.save_deal(deal)
            self.crm.log(t, ActivityKind.quote, f"הצעת מחיר {deal_info.quote_number} נוצרה",
                         Actor.system, deal_id=deal.id, customer_id=cust.id,
                         meta={"quote_id": deal_info.quote_id})
        deal.value = deal_info.amount_total
        deal = self.crm.save_deal(deal)
        stage = STAGE_FOR_EVENT.get(event.type)
        if stage:
            reason = "הלקוח דחה את ההצעה" if stage == DealStage.lost else None
            deal = self.crm.move_stage(t, deal.id, stage, Actor.system, reason)
        if event.type == EventType.approved:
            self.crm.log(t, ActivityKind.quote,
                         f"ההצעה אושרה: חבילת {deal_info.tier}, ₪{deal_info.amount_total:,.0f}",
                         Actor.customer, deal_id=deal.id)
        return SyncResult(ok=True, detail=f"deal {deal.id}",
                          refs=ExternalRefs(deal_id=deal.id, contact_id=deal.customer_id))

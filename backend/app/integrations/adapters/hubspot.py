"""HubSpot CRM (v3 objects API, v4 default associations) with a private-app token.

Per sync:
  1. Contact: update the known one, else find by email/phone, else create.
  2. Deal: update the known one, else create; associate it with the contact.
  3. Line items: archive the ones we created last time, create the current ones, associate.

Settings: token_env, pipeline (default "default").
Mapping defaults below can be overridden per tenant (e.g. custom deal properties).
Required scopes: crm.objects.contacts.write, crm.objects.deals.write, crm.objects.line_items.write
"""

from __future__ import annotations

import httpx

from app.integrations.base import AdapterError, ExternalRefs, SyncResult, request_with_retry
from app.integrations.canonical import QuoteEvent
from app.integrations.config import IntegrationConfig, apply_mapping

BASE = "https://api.hubapi.com"

DEFAULT_CONTACT = {"firstname": "first_name", "lastname": "last_name", "email": "email",
                   "phone": "phone", "company": "company"}
DEFAULT_DEAL = {"dealname": "{title}", "amount": "amount_total", "closedate": "event_date",
                "description": "{quote_number} · {tier} · {notes}"}
DEFAULT_STAGES = {"new": "appointmentscheduled", "quoted": "presentationscheduled",
                  "won": "closedwon", "lost": "closedlost"}


class HubSpotAdapter:
    def __init__(self, config: IntegrationConfig, client: httpx.Client | None = None):
        self.config = config
        self.client = client or httpx.Client(base_url=BASE, timeout=15)

    def _h(self) -> dict:
        return {"Authorization": f"Bearer {self.config.secret('token')}",
                "Content-Type": "application/json"}

    def _call(self, method: str, path: str, json: dict | None = None) -> dict:
        r = request_with_retry(self.client, method, path, json=json, headers=self._h())
        return r.json() if r.content else {}

    # --- contact ---
    def _find_contact(self, props: dict) -> str | None:
        for key in ("email", "phone"):
            if props.get(key):
                body = {"filterGroups": [{"filters": [
                    {"propertyName": key, "operator": "EQ", "value": props[key]}]}],
                    "properties": ["email"], "limit": 1}
                res = self._call("POST", "/crm/v3/objects/contacts/search", body)
                if res.get("results"):
                    return res["results"][0]["id"]
        return None

    def _upsert_contact(self, event: QuoteEvent, refs: ExternalRefs) -> str | None:
        props = apply_mapping(event, self.config.mapping.contact or DEFAULT_CONTACT, "contact")
        if not props:
            return refs.contact_id
        cid = refs.contact_id or self._find_contact(props)
        if cid:
            self._call("PATCH", f"/crm/v3/objects/contacts/{cid}", {"properties": props})
            return cid
        return self._call("POST", "/crm/v3/objects/contacts", {"properties": props})["id"]

    # --- deal ---
    def _upsert_deal(self, event: QuoteEvent, refs: ExternalRefs) -> str:
        props = apply_mapping(event, self.config.mapping.deal or DEFAULT_DEAL, "deal")
        stages = self.config.mapping.stages or DEFAULT_STAGES
        props["dealstage"] = stages.get(event.deal.stage.value, event.deal.stage.value)
        props["pipeline"] = self.config.settings.get("pipeline", "default")
        if refs.deal_id:
            self._call("PATCH", f"/crm/v3/objects/deals/{refs.deal_id}", {"properties": props})
            return refs.deal_id
        return self._call("POST", "/crm/v3/objects/deals", {"properties": props})["id"]

    def _associate(self, from_type: str, from_id: str, to_type: str, to_id: str) -> None:
        self._call("PUT", f"/crm/v4/objects/{from_type}/{from_id}/associations/default/"
                          f"{to_type}/{to_id}")

    def _replace_line_items(self, event: QuoteEvent, deal_id: str, old: list[str]) -> list[str]:
        for lid in old:
            try:
                self._call("DELETE", f"/crm/v3/objects/line_items/{lid}")
            except AdapterError:
                pass  # already gone in HubSpot; not worth failing the sync
        ids = []
        for li in event.line_items:
            res = self._call("POST", "/crm/v3/objects/line_items", {"properties": {
                "name": li.name, "quantity": li.quantity, "price": li.unit_price, "hs_sku": li.sku,
            }})
            ids.append(res["id"])
            self._associate("line_items", res["id"], "deals", deal_id)
        return ids

    def sync(self, event: QuoteEvent, refs: ExternalRefs) -> SyncResult:
        try:
            contact_id = self._upsert_contact(event, refs)
            new_deal = refs.deal_id is None
            deal_id = self._upsert_deal(event, refs)
            if contact_id and (new_deal or contact_id != refs.contact_id):
                self._associate("deals", deal_id, "contacts", contact_id)
            old = refs.extra.get("line_item_ids", [])
            line_ids = self._replace_line_items(event, deal_id, list(old))
        except AdapterError as e:
            return SyncResult(ok=False, detail=str(e), retryable=e.retryable, refs=refs)
        return SyncResult(ok=True, detail=f"deal {deal_id}", refs=ExternalRefs(
            contact_id=contact_id, deal_id=deal_id, extra={"line_item_ids": line_ids}))

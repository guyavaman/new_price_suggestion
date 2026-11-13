"""Generic signed webhook: works with any CRM, directly or through Zapier / Make / n8n.

Delivery:
    POST <url>
    Content-Type: application/json
    X-QuoteAgent-Event:     quote.approved
    X-QuoteAgent-Delivery:  <event id>          (idempotency key — dedupe on it)
    X-QuoteAgent-Timestamp: <unix seconds>
    X-QuoteAgent-Signature: sha256=<hex HMAC-SHA256(secret, f"{timestamp}.{raw_body}")>

Body: the canonical QuoteEvent, plus "mapped": {"contact": {...}, "deal": {...}} when the
tenant configured a field mapping, so the receiver can forward fields as-is.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import httpx

from app.integrations.base import AdapterError, ExternalRefs, SyncResult, request_with_retry
from app.integrations.canonical import QuoteEvent
from app.integrations.config import IntegrationConfig, apply_mapping

SIGNATURE_TOLERANCE_SECONDS = 300


def sign(secret: str, timestamp: str, body: bytes) -> str:
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256)
    return "sha256=" + mac.hexdigest()


def verify_signature(secret: str, timestamp: str, body: bytes, signature: str,
                     now: float | None = None) -> bool:
    """For receivers: constant-time check plus replay protection."""
    try:
        age = abs((now or time.time()) - int(timestamp))
    except ValueError:
        return False
    if age > SIGNATURE_TOLERANCE_SECONDS:
        return False
    return hmac.compare_digest(sign(secret, timestamp, body), signature)


class WebhookAdapter:
    def __init__(self, config: IntegrationConfig, client: httpx.Client | None = None):
        self.config = config
        self.client = client or httpx.Client(timeout=10)

    def build_body(self, event: QuoteEvent) -> bytes:
        payload = event.model_dump(mode="json")
        m = self.config.mapping
        if m.contact or m.deal:
            payload["mapped"] = {
                "contact": apply_mapping(event, m.contact, "contact"),
                "deal": apply_mapping(event, m.deal, "deal"),
            }
            if m.stages:
                payload["mapped"]["deal"]["stage"] = m.stages.get(event.deal.stage.value,
                                                                  event.deal.stage.value)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()

    def sync(self, event: QuoteEvent, refs: ExternalRefs) -> SyncResult:
        url = self.config.settings.get("url")
        if not url:
            return SyncResult(ok=False, detail="webhook url missing")
        body = self.build_body(event)
        ts = str(int(time.time()))
        headers = {
            "Content-Type": "application/json",
            "X-QuoteAgent-Event": event.type.value,
            "X-QuoteAgent-Delivery": event.id,
            "X-QuoteAgent-Timestamp": ts,
            "X-QuoteAgent-Signature": sign(self.config.secret("secret"), ts, body),
            "User-Agent": "AIQuoteAgent-Webhook/1.0",
        }
        try:
            r = request_with_retry(self.client, "POST", url, content=body, headers=headers,
                                   attempts=int(self.config.settings.get("attempts", 3)))
        except AdapterError as e:
            return SyncResult(ok=False, detail=str(e), retryable=e.retryable)
        # receivers may return their own ids, e.g. {"deal_id": "...", "contact_id": "..."}
        try:
            data = r.json() if r.content else {}
        except ValueError:
            data = {}
        return SyncResult(ok=True, detail=f"HTTP {r.status_code}", refs=ExternalRefs(
            contact_id=data.get("contact_id") or refs.contact_id,
            deal_id=data.get("deal_id") or refs.deal_id,
        ))

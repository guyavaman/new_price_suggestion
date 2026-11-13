"""Delivers quote events to every integration a tenant configured.

- Idempotent: an event already delivered to an integration is never sent again.
- Remembers CRM ids per (quote, integration), so later events update instead of duplicating.
- Every attempt is logged; failed retryable deliveries can be retried with `retry_failed`.

It runs inline today. Because it only needs (tenant_id, quote_id, event), the same `deliver`
call can be moved into a queue worker (RQ/Celery/Cloud Tasks) without changing adapters.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from app.integrations.adapters import build_adapter
from app.integrations.base import ExternalRefs, SyncResult
from app.integrations.canonical import EventType, QuoteEvent, build_event
from app.integrations.config import IntegrationConfig, TenantConfig
from app.repositories.quotes import StoredQuote

DEFAULT_LOG = Path(__file__).resolve().parents[3] / "data" / "store" / "sync_log.json"


class SyncRecord(BaseModel):
    event_id: str
    event_type: EventType
    tenant_id: str
    quote_id: str
    integration_id: str
    ok: bool
    retryable: bool = False
    detail: str = ""
    refs: ExternalRefs = Field(default_factory=ExternalRefs)
    attempts: int = 1
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    event: QuoteEvent | None = Field(None, description="Kept for failed deliveries, for retry")


class _Log(BaseModel):
    records: list[SyncRecord] = Field(default_factory=list)


class SyncLog:
    def __init__(self, path: Path = DEFAULT_LOG):
        self.path = path
        self._lock = threading.RLock()

    def _load(self) -> _Log:
        if not self.path.exists():
            return _Log()
        return _Log.model_validate_json(self.path.read_text(encoding="utf-8"))

    def _write(self, log: _Log) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(log.model_dump_json(indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def append(self, rec: SyncRecord) -> None:
        with self._lock:
            log = self._load()
            log.records.append(rec)
            self._write(log)

    def delivered(self, event_id: str, integration_id: str) -> bool:
        return any(r.ok and r.event_id == event_id and r.integration_id == integration_id
                   for r in self._load().records)

    def refs(self, quote_id: str, integration_id: str) -> ExternalRefs:
        for r in reversed(self._load().records):
            if r.ok and r.quote_id == quote_id and r.integration_id == integration_id:
                return r.refs
        return ExternalRefs()

    def for_quote(self, tenant_id: str, quote_id: str) -> list[SyncRecord]:
        return [r for r in self._load().records
                if r.tenant_id == tenant_id and r.quote_id == quote_id]

    def pending_retries(self) -> list[SyncRecord]:
        recs = self._load().records
        done = {(r.event_id, r.integration_id) for r in recs if r.ok}
        latest: dict[tuple[str, str], SyncRecord] = {}
        for r in recs:
            if not r.ok and r.retryable and (r.event_id, r.integration_id) not in done:
                latest[(r.event_id, r.integration_id)] = r
        return list(latest.values())


AdapterFactory = Callable[[IntegrationConfig], object]


class SyncService:
    def __init__(self, log: SyncLog, adapter_factory: AdapterFactory = build_adapter,
                 max_attempts: int = 5):
        self.log = log
        self.adapter_factory = adapter_factory
        self.max_attempts = max_attempts

    def deliver(self, tenant: TenantConfig, quote: StoredQuote,
                event_type: EventType) -> list[SyncRecord]:
        event = build_event(quote, event_type)
        return [self._deliver_one(tenant, quote.id, integ, event)
                for integ in tenant.integrations
                if integ.enabled and event_type in integ.events]

    def _deliver_one(self, tenant: TenantConfig, quote_id: str, integ: IntegrationConfig,
                     event: QuoteEvent, attempts: int = 1) -> SyncRecord:
        if self.log.delivered(event.id, integ.id):
            return SyncRecord(event_id=event.id, event_type=event.type, tenant_id=tenant.tenant_id,
                              quote_id=quote_id, integration_id=integ.id, ok=True,
                              detail="already delivered", attempts=0)
        refs = self.log.refs(quote_id, integ.id)
        try:
            result: SyncResult = self.adapter_factory(integ).sync(event, refs)
        except Exception as e:  # config errors, missing secrets: log, don't crash the request
            result = SyncResult(ok=False, detail=f"{type(e).__name__}: {e}")
        rec = SyncRecord(
            event_id=event.id, event_type=event.type, tenant_id=tenant.tenant_id,
            quote_id=quote_id, integration_id=integ.id, ok=result.ok,
            retryable=result.retryable and attempts < self.max_attempts, detail=result.detail,
            refs=result.refs if result.ok else refs, attempts=attempts,
            event=None if result.ok else event,
        )
        self.log.append(rec)
        return rec

    def retry_failed(self, tenants: Callable[[str], TenantConfig | None]) -> list[SyncRecord]:
        out = []
        for rec in self.log.pending_retries():
            tenant = tenants(rec.tenant_id)
            integ = next((i for i in (tenant.integrations if tenant else [])
                          if i.id == rec.integration_id), None)
            if tenant and integ and rec.event:
                out.append(self._deliver_one(tenant, rec.quote_id, integ, rec.event,
                                             attempts=rec.attempts + 1))
        return out

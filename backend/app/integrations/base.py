"""The adapter contract. A new CRM = one class implementing `sync`.

Adapters receive the canonical event plus the CRM ids from earlier syncs of the same quote
(`ExternalRefs`), so they update the existing contact/deal instead of creating duplicates.
They return the ids they used, which the sync service stores for next time.
"""

from __future__ import annotations

import time
from typing import Protocol

import httpx
from pydantic import BaseModel, Field

from app.integrations.canonical import QuoteEvent
from app.integrations.config import IntegrationConfig


class ExternalRefs(BaseModel):
    contact_id: str | None = None
    deal_id: str | None = None
    extra: dict[str, list[str] | str] = Field(default_factory=dict)


class SyncResult(BaseModel):
    ok: bool
    refs: ExternalRefs = Field(default_factory=ExternalRefs)
    detail: str = ""
    retryable: bool = False


class CRMAdapter(Protocol):
    config: IntegrationConfig

    def sync(self, event: QuoteEvent, refs: ExternalRefs) -> SyncResult: ...


class AdapterError(Exception):
    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


def request_with_retry(client: httpx.Client, method: str, url: str, *, attempts: int = 3,
                       backoff: float = 0.5, **kw) -> httpx.Response:
    """Retry on network errors, 429 and 5xx. 4xx (bad mapping, auth) fail fast."""
    last: Exception | None = None
    for i in range(attempts):
        try:
            r = client.request(method, url, **kw)
            if r.status_code == 429 or r.status_code >= 500:
                last = AdapterError(f"{method} {url} -> {r.status_code}", retryable=True)
            elif r.status_code >= 400:
                raise AdapterError(f"{method} {url} -> {r.status_code}: {r.text[:300]}")
            else:
                return r
        except httpx.TransportError as e:
            last = AdapterError(f"{method} {url} network error: {e}", retryable=True)
        if i < attempts - 1:
            wait = backoff * (2 ** i)
            if last and isinstance(last, AdapterError) and "429" in str(last):
                wait = max(wait, 1.0)
            time.sleep(wait)
    assert last is not None
    raise last

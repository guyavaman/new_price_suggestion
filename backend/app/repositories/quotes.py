"""Quote persistence behind a small interface.

`QuoteRepository` is what the services depend on. `JsonQuoteRepository` keeps the demo
dependency-free; a SQLAlchemy implementation can replace it without touching any service,
adapter or route.
"""

from __future__ import annotations

import secrets
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, Field

from app.schemas.extraction import ExtractedRequest
from app.schemas.quote import MenuPlan, QuoteStatus, TierQuote

DEFAULT_PATH = Path(__file__).resolve().parents[3] / "data" / "store" / "quotes.json"


def _now() -> datetime:
    return datetime.now(UTC)


class StatusChange(BaseModel):
    status: QuoteStatus
    at: datetime = Field(default_factory=_now)
    note: str | None = None


class StoredQuote(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    public_token: str = Field(default_factory=lambda: secrets.token_urlsafe(16),
                              description="Secret for the customer's quote page link")
    tenant_id: str
    number: str
    status: QuoteStatus = QuoteStatus.draft
    selected_tier: str = "recommended"
    source_message: str = ""
    request: ExtractedRequest
    plan: MenuPlan
    tiers: list[TierQuote]
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
    history: list[StatusChange] = Field(default_factory=list)

    def tier(self, key: str | None = None) -> TierQuote:
        key = key or self.selected_tier
        for t in self.tiers:
            if t.key == key:
                return t
        raise KeyError(f"Unknown tier {key}")


class QuoteRepository(Protocol):
    def add(self, quote: StoredQuote) -> StoredQuote: ...
    def get(self, tenant_id: str, quote_id: str) -> StoredQuote | None: ...
    def save(self, quote: StoredQuote) -> StoredQuote: ...
    def find_by_token(self, token: str) -> StoredQuote | None: ...
    def list(self, tenant_id: str) -> list[StoredQuote]: ...
    def next_number(self, tenant_id: str) -> str: ...


class _Data(BaseModel):
    quotes: dict[str, StoredQuote] = Field(default_factory=dict)
    counters: dict[str, int] = Field(default_factory=dict)


class JsonQuoteRepository:
    def __init__(self, path: Path = DEFAULT_PATH):
        self.path = path
        self._lock = threading.RLock()

    def _load(self) -> _Data:
        if not self.path.exists():
            return _Data()
        return _Data.model_validate_json(self.path.read_text(encoding="utf-8"))

    def _write(self, data: _Data) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(data.model_dump_json(indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def next_number(self, tenant_id: str) -> str:
        with self._lock:
            d = self._load()
            n = d.counters.get(tenant_id, 1000) + 1
            d.counters[tenant_id] = n
            self._write(d)
            return f"Q-{_now().year}-{n}"

    def add(self, quote: StoredQuote) -> StoredQuote:
        with self._lock:
            d = self._load()
            d.quotes[quote.id] = quote
            self._write(d)
            return quote

    def save(self, quote: StoredQuote) -> StoredQuote:
        quote.updated_at = _now()
        return self.add(quote)

    def get(self, tenant_id: str, quote_id: str) -> StoredQuote | None:
        q = self._load().quotes.get(quote_id)
        return q if q and q.tenant_id == tenant_id else None  # tenant isolation

    def find_by_token(self, token: str) -> StoredQuote | None:
        return next((q for q in self._load().quotes.values()
                     if secrets.compare_digest(q.public_token, token)), None)

    def list(self, tenant_id: str) -> list[StoredQuote]:
        return sorted((q for q in self._load().quotes.values() if q.tenant_id == tenant_id),
                      key=lambda q: q.created_at, reverse=True)

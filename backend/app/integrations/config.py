"""Per-tenant integration settings, loaded from data/tenants/<tenant_id>.json.

Secrets are never stored in the file: settings reference an environment variable by name
(e.g. "token_env": "ACME_HUBSPOT_TOKEN"), so the config can live in git.

Field mapping turns the canonical model into CRM fields without code:
    "deal": {"dealname": "{title}", "amount": "amount_total", "closedate": "event_date"}
A value is either a canonical field path (`deal.amount_total`, `contact.phone`) or a template
with {placeholders}. Inside "deal"/"contact" mappings the prefix is implied.
"""

from __future__ import annotations

import os
import string
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.integrations.canonical import EventType, QuoteEvent

TENANTS_DIR = Path(__file__).resolve().parents[3] / "data" / "tenants"


class AdapterType(StrEnum):
    webhook = "webhook"
    hubspot = "hubspot"
    monday = "monday"
    internal = "internal"  # our own CRM


class FieldMapping(BaseModel):
    contact: dict[str, str] = Field(default_factory=dict)
    deal: dict[str, str] = Field(default_factory=dict)
    stages: dict[str, str] = Field(
        default_factory=dict, description="Canonical stage (new/quoted/won/lost) -> CRM value"
    )


class IntegrationConfig(BaseModel):
    id: str
    type: AdapterType
    enabled: bool = True
    events: list[EventType] = Field(default_factory=lambda: list(EventType))
    settings: dict[str, Any] = Field(default_factory=dict)
    mapping: FieldMapping = Field(default_factory=FieldMapping)

    def secret(self, key: str) -> str:
        env = self.settings.get(f"{key}_env")
        value = os.environ.get(env, "") if env else ""
        if not value:
            raise RuntimeError(f"Integration {self.id}: set env var {env or key + '_env'}")
        return value


class TenantConfig(BaseModel):
    tenant_id: str
    name: str
    api_key_env: str | None = Field(None, description="Env var holding this tenant's API key")
    integrations: list[IntegrationConfig] = Field(default_factory=list)


def load_tenant(tenant_id: str, directory: Path = TENANTS_DIR) -> TenantConfig | None:
    if not tenant_id.replace("-", "").replace("_", "").isalnum():
        return None  # no path tricks
    path = directory / f"{tenant_id}.json"
    if not path.exists():
        return None
    return TenantConfig.model_validate_json(path.read_text(encoding="utf-8"))


# ---------- mapping engine ----------

def _jsonable(v: Any) -> Any:
    if isinstance(v, datetime | date):
        return v.isoformat()
    if isinstance(v, StrEnum):
        return v.value
    return v


def resolve(event: QuoteEvent, expr: str, scope: str | None = None) -> Any:
    """Resolve a mapping expression against an event."""
    flat = flatten(event)
    if "{" in expr:
        fields = [f for _, f, _, _ in string.Formatter().parse(expr) if f]
        values = {}
        for f in fields:
            key = f if "." in f or scope is None else f"{scope}.{f}"
            v = flat.get(key)
            values[f] = "" if v is None else v
        return expr.format(**values).strip(" ·-")
    key = expr if "." in expr or scope is None else f"{scope}.{expr}"
    if key not in flat:
        raise KeyError(f"Unknown canonical field '{key}'")
    return flat[key]


def flatten(event: QuoteEvent) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for section in ("contact", "deal"):
        for k, v in getattr(event, section).model_dump().items():
            out[f"{section}.{k}"] = _jsonable(v)
    out["event.type"] = event.type.value
    out["event.id"] = event.id
    return out


def apply_mapping(event: QuoteEvent, mapping: dict[str, str], scope: str) -> dict[str, Any]:
    """Return {crm_field: value}, skipping empty values so we never blank out CRM data."""
    result = {}
    for crm_field, expr in mapping.items():
        value = resolve(event, expr, scope)
        if value not in (None, ""):
            result[crm_field] = value
    return result

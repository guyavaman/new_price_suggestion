"""The owner's menu and price list, per business.

A new business starts from the demo catalog (data/catalog.jsonl) without anything being
written; the first edit copies it into the tenant's own store (copy-on-write), so the owner
can then change prices, add dishes and mark items unavailable from the Menu & Prices screen.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from pydantic import Field

from app.catalog.loader import load_catalog
from app.repositories.store import STORE_DIR, Collection
from app.schemas.catalog import CatalogItem


class TenantCatalogItem(CatalogItem):
    id: str
    tenant_id: str
    active: bool = True
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CatalogService:
    def __init__(self, base: Path = STORE_DIR):
        self.col = Collection(TenantCatalogItem, base / "catalog.json")

    def _seed(self, tenant: str) -> list[TenantCatalogItem]:
        return [TenantCatalogItem(**i.model_dump(), id=f"{tenant}:{i.sku}", tenant_id=tenant)
                for i in load_catalog()]

    def all(self, tenant: str) -> list[TenantCatalogItem]:
        items = self.col.list(tenant)
        items = items or self._seed(tenant)
        return sorted(items, key=lambda i: (i.category.value, i.name_he))

    def items(self, tenant: str) -> list[CatalogItem]:
        """What engines and the AI may use: active items only."""
        return [i for i in self.all(tenant) if i.active]

    def _materialize(self, tenant: str) -> None:
        if not self.col.list(tenant):
            for i in self._seed(tenant):
                self.col.put(i)

    def get(self, tenant: str, sku: str) -> TenantCatalogItem | None:
        return next((i for i in self.all(tenant) if i.sku == sku), None)

    def upsert(self, tenant: str, item: CatalogItem, active: bool = True) -> TenantCatalogItem:
        self._materialize(tenant)
        obj = TenantCatalogItem(**item.model_dump(), id=f"{tenant}:{item.sku}", tenant_id=tenant,
                                active=active)
        return self.col.put(obj)

    def update(self, tenant: str, sku: str, patch: dict) -> TenantCatalogItem:
        self._materialize(tenant)
        cur = self.col.get(tenant, f"{tenant}:{sku}")
        if cur is None:
            raise KeyError(sku)
        data = cur.model_dump()
        data.update({k: v for k, v in patch.items() if k not in ("id", "tenant_id", "sku")})
        data["updated_at"] = datetime.now(UTC)
        return self.col.put(TenantCatalogItem.model_validate(data))

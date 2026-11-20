"""Suppliers and ingredients per business, copy-on-write from the demo data like the menu:
a new business sees the demo lists; its first edit copies them into its own store."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from app.purchasing.models import Ingredient, Supplier
from app.repositories.store import STORE_DIR, Collection

DATA = Path(__file__).resolve().parents[3] / "data"


class TenantSupplier(Supplier):
    id: str
    tenant_id: str


class TenantIngredient(Ingredient):
    id: str
    tenant_id: str


class OrderMark(BaseModel):
    """The owner placed the order for a supplier's delivery day."""
    id: str
    tenant_id: str
    supplier: str
    deliver_on: date
    ordered_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


def _load(name: str, model):
    path = DATA / name
    if not path.exists():
        return []
    return [model.model_validate(json.loads(line)) for line in path.read_text(encoding="utf-8")
            .splitlines() if line.strip()]


class PurchasingService:
    def __init__(self, base: Path = STORE_DIR):
        self.sup = Collection(TenantSupplier, base / "suppliers.json")
        self.ing = Collection(TenantIngredient, base / "ingredients.json")
        self.state = base / "purchasing_tenants.json"  # tenants whose lists are their own
        self.marks = Collection(OrderMark, base / "purchase_orders.json")

    # ---- copy-on-write ----
    def _own(self, tenant: str) -> bool:
        return self.state.exists() and tenant in json.loads(self.state.read_text())

    def _materialize(self, tenant: str) -> None:
        if self._own(tenant):
            return
        for s in _load("suppliers.jsonl", Supplier):
            self.sup.put(TenantSupplier(**s.model_dump(), id=f"{tenant}:{s.code}",
                                        tenant_id=tenant))
        for i in _load("ingredients.jsonl", Ingredient):
            self.ing.put(TenantIngredient(**i.model_dump(), id=f"{tenant}:{i.code}",
                                          tenant_id=tenant))
        owned = json.loads(self.state.read_text()) if self.state.exists() else []
        self.state.parent.mkdir(parents=True, exist_ok=True)
        self.state.write_text(json.dumps(sorted({*owned, tenant})))

    # ---- reads ----
    def suppliers(self, tenant: str) -> list[TenantSupplier]:
        if self._own(tenant):
            items = self.sup.list(tenant)
        else:
            items = [TenantSupplier(**s.model_dump(), id=f"{tenant}:{s.code}", tenant_id=tenant)
                     for s in _load("suppliers.jsonl", Supplier)]
        return sorted(items, key=lambda s: s.name)

    def ingredients(self, tenant: str) -> list[TenantIngredient]:
        if self._own(tenant):
            items = self.ing.list(tenant)
        else:
            items = [TenantIngredient(**i.model_dump(), id=f"{tenant}:{i.code}", tenant_id=tenant)
                     for i in _load("ingredients.jsonl", Ingredient)]
        return sorted(items, key=lambda i: i.name_he)

    # ---- writes ----
    def put_supplier(self, tenant: str, s: Supplier) -> TenantSupplier:
        self._materialize(tenant)
        return self.sup.put(TenantSupplier(**s.model_dump(), id=f"{tenant}:{s.code}",
                                           tenant_id=tenant))

    def put_ingredient(self, tenant: str, i: Ingredient, old: Ingredient | None = None
                       ) -> TenantIngredient:
        self._materialize(tenant)
        data = i.model_dump()
        if old is None or old.price != i.price:
            data["price_updated_at"] = datetime.now(UTC) if i.price is not None else None
        return self.ing.put(TenantIngredient(**data, id=f"{tenant}:{i.code}", tenant_id=tenant))

    def delete_supplier(self, tenant: str, code: str) -> bool:
        self._materialize(tenant)
        for i in self.ing.list(tenant, lambda x: x.supplier == code):  # keep the ingredients
            self.ing.put(i.model_copy(update={"supplier": None}))
        return self.sup.delete(tenant, f"{tenant}:{code}")

    def ordered(self, tenant: str) -> dict[tuple[str, date], datetime]:
        return {(m.supplier, m.deliver_on): m.ordered_at for m in self.marks.list(tenant)}

    def mark_ordered(self, tenant: str, supplier: str, deliver_on: date, ordered: bool) -> None:
        mid = f"{tenant}:{supplier}:{deliver_on.isoformat()}"
        if ordered:
            self.marks.put(OrderMark(id=mid, tenant_id=tenant, supplier=supplier,
                                     deliver_on=deliver_on))
        else:
            self.marks.delete(tenant, mid)

    def delete_ingredient(self, tenant: str, code: str) -> bool:
        self._materialize(tenant)
        return self.ing.delete(tenant, f"{tenant}:{code}")

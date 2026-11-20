"""Data migrations for the JSON store.

Adding a field with a default needs nothing (Pydantic fills it on read). A migration is needed
when existing records need a *value* derived from what's already there. Each migration runs
once, in order, and is recorded in STORE_DIR/schema_version.json. Migrations must be
idempotent and never drop data: they only fill in what's missing.

    python -m app.migrations          # also runs automatically on server start
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from app.repositories.store import STORE_DIR


def _read(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def _write(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    tmp.replace(path)


def m001_deal_won_at_and_net_value(base: Path) -> int:
    """Stage 0: deals get `won_at` (first booking) and `value_net` (before VAT).

    won_at: the first stage change to 'won' in the activity log; else the first paid payment;
    else the last stage change. value_net: the linked quote's selected tier net; else derived
    from the total with the tenant's VAT rate (default 18%)."""
    deals_p = base / "crm_deals.json"
    deals = _read(deals_p)
    if not deals:
        return 0
    acts = _read(base / "crm_activities.json").values()
    won_moves: dict[str, str] = {}
    for a in acts:
        to_won = (a.get("meta") or {}).get("to") == "won"
        if a.get("kind") == "stage" and to_won and a.get("deal_id"):
            prev = won_moves.get(a["deal_id"])
            won_moves[a["deal_id"]] = min(prev, a["created_at"]) if prev else a["created_at"]
    quotes = _read(base / "quotes.json")
    vat_by_tenant = {v.get("tenant_id"): v.get("vat_rate", 0.18)
                     for v in _read(base / "settings.json").values()}
    changed = 0
    for d in deals.values():
        touched = False
        if d.get("stage") in ("won", "completed") and not d.get("won_at"):
            paid = sorted(p["paid_at"] for p in d.get("payments", [])
                          if p.get("status") == "paid" and p.get("paid_at"))
            first_paid = paid[0] if paid else None
            d["won_at"] = won_moves.get(d["id"]) or first_paid or d.get("stage_changed_at")
            touched = True
        if d.get("value") is not None and d.get("value_net") is None:
            net = None
            for qid in reversed(d.get("quote_ids", [])):
                q = quotes.get(qid)
                if q:
                    tier = next((t for t in q.get("tiers", [])
                                 if t.get("key") == q.get("selected_tier")), None)
                    net = tier and tier.get("quote", {}).get("net")
                    break
            vat = vat_by_tenant.get(d.get("tenant_id"), 0.18)
            d["value_net"] = net if net is not None else round(d["value"] / (1 + vat), 2)
            touched = True
        changed += touched
    if changed:
        _write(deals_p, deals)
    return changed


def m002_catalog_roles_and_costs(base: Path) -> int:
    """Stage 1: tenant catalogs copied before stage 1 lack roles, defaults, tier links, costs and
    package components. Fill each missing field from the base catalog item with the same SKU;
    never overwrite what the business already set."""
    from app.catalog.loader import load_catalog  # late import: migrations stay light
    path = base / "catalog.json"
    items = _read(path)
    if not items:
        return 0
    ref = {i.sku: i.model_dump(mode="json") for i in load_catalog()}
    fields = ("role", "includes_bartender", "default_use", "upgrade_to", "downgrade_to",
              "basic_drop", "components", "cost", "cost_updated_at", "cost_source")
    changed = 0
    for it in items.values():
        src = ref.get(it.get("sku"))
        if not src:
            continue
        touched = False
        for f in fields:
            if it.get(f) in (None, [], False) and src.get(f) not in (None, [], False):
                it[f] = src[f]
                touched = True
        changed += touched
    if changed:
        _write(path, items)
    return changed


CATEGORY_LABEL = {"salad": "סלטים", "starter": "ראשונות", "main": "עיקריות", "side": "תוספות",
                  "canape": "קבלת פנים", "breakfast": "מאפים ובוקר", "dessert": "קינוחים",
                  "drink": "שתייה", "bar": "בר"}


def m003_package_slots_and_yields(base: Path) -> int:
    """Stage 2: packages become slots ("3 salads out of…") and food items get a yield per unit.
    Fill `yield_amount` and `slots` from the base catalog by SKU where missing. A package the
    business built itself from stage-1 components becomes one fixed slot per category (the same
    dishes, nothing lost); the old components are then cleared."""
    from app.catalog.loader import load_catalog  # late import
    path = base / "catalog.json"
    items = _read(path)
    if not items:
        return 0
    ref = {i.sku: i.model_dump(mode="json") for i in load_catalog()}
    cat_of = {it.get("sku"): it.get("category") for it in items.values()}
    changed = 0
    for it in items.values():
        src = ref.get(it.get("sku")) or {}
        touched = False
        for f in ("yield_amount", "slots"):
            if not it.get(f) and src.get(f):
                it[f] = src[f]
                touched = True
        comps = it.get("components") or []
        if comps and not it.get("slots"):
            groups: dict[str, list[str]] = {}
            for c in comps:
                groups.setdefault(cat_of.get(c["sku"]) or "other", []).append(c["sku"])
            it["slots"] = [{"id": cat, "label_he": CATEGORY_LABEL.get(cat, "מנות"),
                            "choose": len(skus), "options": skus, "customer_choice": False}
                           for cat, skus in groups.items()]
            touched = True
        if comps and it.get("slots"):
            it["components"] = []
            touched = True
        changed += touched
    if changed:
        _write(path, items)
    return changed


MIGRATIONS: list[tuple[str, Callable[[Path], int]]] = [
    ("001_deal_won_at_and_net_value", m001_deal_won_at_and_net_value),
    ("002_catalog_roles_and_costs", m002_catalog_roles_and_costs),
    ("003_package_slots_and_yields", m003_package_slots_and_yields),
]


def run(base: Path = STORE_DIR) -> list[str]:
    """Apply pending migrations; returns the names applied now."""
    base.mkdir(parents=True, exist_ok=True)
    state_p = base / "schema_version.json"
    state = _read(state_p) or {"applied": []}
    done = []
    for name, fn in MIGRATIONS:
        if name in state["applied"]:
            continue
        n = fn(base)
        state["applied"].append(name)
        state.setdefault("log", []).append({"name": name, "records": n,
                                            "at": datetime.now().isoformat(timespec="seconds")})
        done.append(name)
    state["version"] = len(state["applied"])
    _write(state_p, state)
    return done


if __name__ == "__main__":
    print(run() or "up to date")

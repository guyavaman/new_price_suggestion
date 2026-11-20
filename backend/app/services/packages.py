"""A package broken down into dishes, quantities and cost: the one place this is computed.

A package is a set of slots ("3 salads out of these 8"). For an event the owner (or the
customer, within the slots they may choose) picks the dishes; until then each slot uses its
first options. Each chosen dish gets a per-guest amount from the business's portion rule for
its category, shared by variety (more dishes of a category → less of each), or the slot's
fixed per-guest amount. Amount × guests ÷ what one catalog unit yields = units to make
(rounded up), and units × unit cost = the dish's cost.

Missing data is a normal state: a dish with no portion rule, no yield or no cost has no
quantity or no cost, says why, and the package has no cost until it's filled in.
Owner-only numbers; `customer_view` is the only thing a customer may see.
"""

from __future__ import annotations

import math
from collections import Counter

from pydantic import BaseModel, Field

from app.schemas.catalog import CatalogItem, Measure, PortionRule
from app.schemas.extraction import MealType

Choice = dict[str, list[str]]  # slot id -> chosen SKUs

MEASURE_HE = {Measure.g: "גרם", Measure.unit: "מנות"}
KASHRUT_OK = {MealType.meat: {MealType.meat, MealType.pareve},
              MealType.dairy: {MealType.dairy, MealType.pareve},
              MealType.pareve: {MealType.pareve}}


class DishRow(BaseModel):
    slot_id: str
    slot_label: str
    sku: str
    name_he: str
    category: str
    measure: Measure | None = None
    per_guest: float | None = None      # amount of this dish per guest
    total_amount: float | None = None   # for all guests
    units: int | None = None            # catalog units to make (trays, cakes, portions…)
    unit: str = ""
    unit_cost: float | None = None
    cost: float | None = None
    problem: str | None = None          # why quantity or cost is missing


class Breakdown(BaseModel):
    sku: str
    name_he: str
    guests: int
    rows: list[DishRow]
    status: str                         # "complete" | "missing"
    total_cost: float | None = None
    cost_per_guest: float | None = None
    missing: list[str] = Field(default_factory=list)  # "<dish>: <what's missing>"


def default_choice(pkg: CatalogItem) -> Choice:
    return {s.id: s.options[: s.choose] for s in pkg.slots}


def resolve_choice(pkg: CatalogItem, choice: Choice | None) -> Choice:
    """The event's choice where it's valid, the slot's default where it isn't given."""
    out = default_choice(pkg)
    for s in pkg.slots:
        picked = (choice or {}).get(s.id)
        if picked and not slot_errors(s, picked):
            out[s.id] = list(picked)
    return out


def slot_errors(slot, picked: list[str]) -> list[str]:
    errs = []
    if len(picked) != slot.choose:
        errs.append(f"ב{slot.label_he} צריך לבחור {slot.choose} (נבחרו {len(picked)})")
    if len(set(picked)) != len(picked):
        errs.append(f"ב{slot.label_he} מנה נבחרה פעמיים")
    bad = [p for p in picked if p not in slot.options]
    if bad:
        errs.append(f"ב{slot.label_he} יש מנה שאינה ברשימה: {', '.join(bad)}")
    return errs


def choice_errors(pkg: CatalogItem, choice: Choice, only_customer: bool = False) -> list[str]:
    errs = []
    slots = {s.id: s for s in pkg.slots}
    for sid, picked in choice.items():
        s = slots.get(sid)
        if s is None:
            errs.append(f"אין בחבילה חלק בשם {sid}")
        elif only_customer and not s.customer_choice:
            errs.append(f"את {s.label_he} קובע בעל העסק")
        else:
            errs.extend(slot_errors(s, picked))
    return errs


def package_errors(pkg: CatalogItem, by_sku: dict[str, CatalogItem]) -> list[str]:
    """Problems that make a package definition invalid (checked when it's saved/imported)."""
    errs = []
    ids = [s.id for s in pkg.slots]
    if len(set(ids)) != len(ids):
        errs.append("מזהה חלק מופיע פעמיים בחבילה")
    for s in pkg.slots:
        if s.choose > len(s.options):
            errs.append(f"ב{s.label_he} צריך לבחור {s.choose} אבל יש רק {len(s.options)} אפשרויות")
        for sku in s.options:
            it = by_sku.get(sku)
            if it is None:
                errs.append(f"ב{s.label_he}: {sku} לא קיים בתפריט")
            elif it.category.value == "package":
                errs.append(f"ב{s.label_he}: {it.name_he} היא חבילה, לא מנה")
            elif it.meal_type not in KASHRUT_OK[pkg.meal_type]:
                errs.append(f"ב{s.label_he}: {it.name_he} ({it.meal_type.value}) "
                            f"לא מתאים לחבילה {pkg.meal_type.value}")
    return errs


def breakdown(pkg: CatalogItem, by_sku: dict[str, CatalogItem], guests: int,
              rules: dict[str, PortionRule], choice: Choice | None = None) -> Breakdown:
    chosen = resolve_choice(pkg, choice)
    slots = {s.id: s for s in pkg.slots}
    picks = [(slots[sid], sku) for sid in chosen for sku in chosen[sid]]
    variety = Counter(by_sku[sku].category.value for s, sku in picks
                      if s.per_guest is None and sku in by_sku)
    rows: list[DishRow] = []
    for slot, sku in picks:
        it = by_sku.get(sku)
        if it is None:
            rows.append(DishRow(slot_id=slot.id, slot_label=slot.label_he, sku=sku, name_he=sku,
                                category="", problem="לא קיים בתפריט"))
            continue
        row = DishRow(slot_id=slot.id, slot_label=slot.label_he, sku=sku, name_he=it.name_he,
                      category=it.category.value, unit=it.unit.value, unit_cost=it.cost)
        rule = rules.get(it.category.value)
        row.measure = rule.measure if rule else (Measure.unit if slot.per_guest else None)
        if slot.per_guest is not None:
            per = slot.per_guest
        elif rule is not None:
            per = rule.per_dish(variety[it.category.value])
        else:
            row.problem = "אין כלל כמויות לקטגוריה"
            rows.append(row)
            continue
        row.per_guest = round(per, 1 if row.measure == Measure.g else 2)
        row.total_amount = round(per * guests, 1)
        if it.yield_amount is None:
            row.problem = "חסרה תפוקה ליחידה"
        else:
            row.units = max(1, math.ceil(per * guests / it.yield_amount - 1e-9))
            if it.cost is None:
                row.problem = "עלות חסרה"
            else:
                row.cost = round(row.units * it.cost, 2)
        rows.append(row)
    missing = [f"{r.name_he}: {r.problem}" for r in rows if r.problem]
    complete = bool(rows) and not missing and guests > 0
    total = round(sum(r.cost or 0 for r in rows), 2) if complete else None
    if not rows:
        missing = [f"{pkg.name_he}: אין בחבילה מנות"]
    return Breakdown(sku=pkg.sku, name_he=pkg.name_he, guests=guests, rows=rows,
                     status="complete" if complete else "missing", total_cost=total,
                     cost_per_guest=round(total / guests, 2) if total is not None else None,
                     missing=missing)


class CustomerSlot(BaseModel):
    """What a customer sees of a slot: names only, never amounts or costs."""
    id: str
    label_he: str
    choose: int
    can_choose: bool
    options: list[dict]  # [{sku, name_he, description_he}]
    chosen: list[str]


def customer_view(pkg: CatalogItem, by_sku: dict[str, CatalogItem],
                  choice: Choice | None) -> list[CustomerSlot]:
    chosen = resolve_choice(pkg, choice)
    return [CustomerSlot(
        id=s.id, label_he=s.label_he, choose=s.choose, can_choose=s.customer_choice,
        options=[{"sku": o, "name_he": by_sku[o].name_he,
                  "description_he": by_sku[o].description_he}
                 for o in s.options if o in by_sku],
        chosen=chosen[s.id]) for s in pkg.slots]

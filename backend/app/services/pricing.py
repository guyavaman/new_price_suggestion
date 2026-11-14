"""Deterministic pricing. No LLM here — same input, same quote, every time.

The LLM decides *what* goes on the quote (SKUs, which guest group a line serves).
This module decides *how much*: quantities, staff, delivery, supervision, discounts, VAT,
and enforces business guards (kashrut meat/dairy separation, unknown SKUs, minimums).
"""

from __future__ import annotations

import math

from app.business.settings import BusinessSettings
from app.schemas.catalog import CatalogItem
from app.schemas.extraction import ExtractedRequest, Kashrut, MealType
from app.schemas.quote import (
    BudgetCheck,
    Confidence,
    LineSource,
    MenuPlan,
    PricedQuote,
    QuoteLine,
)

BUDGET_TOLERANCE = 1.05
DEFAULT_RULES = BusinessSettings(id="default", tenant_id="default")

ALLOWED_MEAL = {
    MealType.meat: {MealType.meat, MealType.pareve},
    MealType.dairy: {MealType.dairy, MealType.pareve},
    MealType.pareve: {MealType.pareve},
}

MEAL_HE = {MealType.meat: "בשרי", MealType.dairy: "חלבי", MealType.pareve: "פרווה"}


def _r2(x: float) -> float:
    return round(x + 1e-9, 2)


def compute_quantity(item: CatalogItem, for_guests: int | None, quantity: float | None,
                     guests: int | None,
                     rules: BusinessSettings | None = None) -> tuple[float | None, str]:
    rules = rules or DEFAULT_RULES
    if quantity is not None and quantity > 0:
        return quantity, "כמות שביקש הלקוח"
    g = for_guests or guests
    if not g:
        return None, "חסר מספר אורחים"
    if item.serves:
        return math.ceil(g / item.serves), f"{g} סועדים ÷ {item.serves} ליחידה"
    if item.unit.value == "per_guest":
        return g, f"{g} סועדים"
    if item.category.value == "canape":
        return g * rules.canapes_per_guest, f"{rules.canapes_per_guest} יח' לסועד"
    if item.unit.value == "hour":
        return rules.staff_hours, f"{rules.staff_hours} שעות"
    return g, f"{g} סועדים"


class PricingEngine:
    def __init__(self, catalog: list[CatalogItem], vat_rate: float | None = None,
                 rules: BusinessSettings | None = None):
        self.by_sku = {i.sku: i for i in catalog}
        self.rules = rules or DEFAULT_RULES
        self.vat_rate = self.rules.vat_rate if vat_rate is None else vat_rate

    def _line(self, item: CatalogItem, qty: float, note: str, source: LineSource,
              confidence: Confidence, reason: str = "") -> QuoteLine:
        return QuoteLine(
            sku=item.sku, name_he=item.name_he, unit=item.unit.value, unit_price=item.price,
            quantity=qty, total=_r2(qty * item.price), note=note, source=source,
            confidence=confidence, reason=reason,
        )

    def price(self, req: ExtractedRequest, plan: MenuPlan) -> PricedQuote:
        R = self.rules
        guests = req.guest_count
        guards: list[str] = []
        lines: list[QuoteLine] = []
        allowed = ALLOWED_MEAL.get(req.meal_type) if req.meal_type else None

        # 1. menu lines from the plan, validated
        for ml in plan.lines:
            item = self.by_sku.get(ml.sku)
            if item is None:
                guards.append(f"הוסר פריט שלא קיים בקטלוג ({ml.sku})")
                continue
            if item.category.value in ("staff", "logistics"):
                continue  # rules own these; ignore if the LLM added them anyway
            if allowed and item.meal_type not in allowed:
                guards.append(f'הוסר "{item.name_he}": לא מתאים לאירוע {MEAL_HE[req.meal_type]}')
                continue
            qty, note = compute_quantity(item, ml.for_guests, ml.quantity, guests, self.rules)
            if qty is None:
                guards.append(f'"{item.name_he}" ללא כמות: חסר מספר אורחים')
                continue
            if item.min_qty and qty < item.min_qty:
                qty, note = item.min_qty, f"מינימום הזמנה {item.min_qty}"
            source = (LineSource.requested if ml.source == LineSource.requested
                      else LineSource.suggested)
            lines.append(self._line(item, qty, note, source, ml.confidence, ml.reason))

        # 2. kashrut: never mix meat and dairy at a kosher event
        if req.kashrut in (Kashrut.kosher, Kashrut.mehadrin):
            used = {self.by_sku[ln.sku].meal_type for ln in lines}
            if MealType.meat in used and MealType.dairy in used:
                drop = MealType.meat if req.meal_type == MealType.dairy else MealType.dairy
                kept = []
                for ln in lines:
                    if self.by_sku[ln.sku].meal_type == drop:
                        guards.append(f'הוסר "{ln.name_he}": אין ערבוב בשרי וחלבי באירוע כשר')
                    else:
                        kept.append(ln)
                lines = kept

        # 3. business rules
        def add(sku: str, qty: float, note: str) -> None:
            lines.append(self._line(self.by_sku[sku], qty, note, LineSource.rule, Confidence.rule))

        sv = req.service
        has_meal = any(self.by_sku[ln.sku].category.value in ("package", "main") for ln in lines)
        if guests:
            want_waiters = sv.waiters is True or (
                sv.waiters is None and guests >= R.auto_waiters_from and has_meal
            )
            if want_waiters:
                n = math.ceil(guests / R.waiter_ratio)
                add("STF-WAITER", n * R.staff_hours,
                    f"{n} מלצרים × {R.staff_hours} ש' (מלצר לכל {R.waiter_ratio})")
                if guests >= R.head_waiter_from:
                    add("STF-HEAD-WAITER", R.staff_hours, f"מנהל אירוע × {R.staff_hours} ש'")
            has_bar = any(self.by_sku[ln.sku].category.value == "bar" for ln in lines)
            has_open_bar = any(ln.sku == "BAR-OPEN" for ln in lines)  # includes a bartender
            if (sv.bar is True or has_bar) and not has_open_bar:
                n = math.ceil(guests / R.bartender_ratio)
                add("STF-BARTENDER", n * R.staff_hours, f"{n} ברמנים × {R.staff_hours} ש'")
            if req.kashrut == Kashrut.mehadrin:
                add("LOG-MEHADRIN", guests, f"{guests} סועדים")
        if sv.equipment is True or any(
            self.by_sku[ln.sku].category.value == "equipment" for ln in lines
        ):
            add("LOG-SETUP", 1, "")
        if lines:
            loc = (req.location or "").lower()
            remote = any(k in loc for k in R.remote_areas)
            add("LOG-DELIVERY-F" if remote else "LOG-DELIVERY-C", 1,
                f"ל{req.location}" if req.location else "אזור מרכז (ברירת מחדל)")

        # 4. totals
        subtotal = _r2(sum(ln.total for ln in lines))
        rate = next((d.rate for d in sorted(R.volume_discounts, key=lambda d: -d.min_subtotal)
                     if subtotal >= d.min_subtotal), 0.0)
        discount = _r2(subtotal * rate)
        net = _r2(subtotal - discount)
        vat = _r2(net * self.vat_rate)
        total = _r2(net + vat)
        per_guest = _r2(total / guests) if guests else None

        budget = None
        if req.budget:
            amt = req.budget.amount
            if req.budget.scope.value == "per_guest" and per_guest is not None:
                budget = BudgetCheck(ok=per_guest <= amt * BUDGET_TOLERANCE,
                                     text=f"₪{per_guest:,.2f} לסועד מול תקציב ₪{amt:,.0f} לסועד")
            elif req.budget.scope.value == "total":
                budget = BudgetCheck(ok=total <= amt * BUDGET_TOLERANCE,
                                     text=f"₪{total:,.2f} מול תקציב כולל ₪{amt:,.0f}")
        if req.suspicious_instructions:
            guards.append("זוהתה הוראה למערכת בתוך ההודעה: לא בוצעה")

        return PricedQuote(
            lines=lines, subtotal=subtotal, discount_rate=rate, discount=discount, net=net,
            vat=vat, total=total, per_guest=per_guest, budget=budget, guards=guards,
        )

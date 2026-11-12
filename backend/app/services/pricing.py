"""Deterministic pricing. No LLM here — same input, same quote, every time.

The LLM decides *what* goes on the quote (SKUs, which guest group a line serves).
This module decides *how much*: quantities, staff, delivery, supervision, discounts, VAT,
and enforces business guards (kashrut meat/dairy separation, unknown SKUs, minimums).
"""

from __future__ import annotations

import math

from app.config import get_settings
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

WAITER_RATIO = 15  # one waiter per N guests
BARTENDER_RATIO = 75
HEAD_WAITER_FROM = 80  # add an event manager from this many guests
AUTO_WAITERS_FROM = 60  # suggest waiters for full meals from this many guests
STAFF_HOURS = 5
CANAPES_PER_GUEST = 3
VOLUME_DISCOUNTS = [(50_000, 0.08), (20_000, 0.05)]  # (subtotal threshold, rate)
BUDGET_TOLERANCE = 1.05

REMOTE_AREAS = [
    "ירושלים", "חיפה", "צפון", "גליל", "עמק", "באר שבע", "אילת", "נגב", "גולן",
    "jerusalem", "haifa", "north", "galilee", "beer sheva", "eilat",
]

ALLOWED_MEAL = {
    MealType.meat: {MealType.meat, MealType.pareve},
    MealType.dairy: {MealType.dairy, MealType.pareve},
    MealType.pareve: {MealType.pareve},
}

MEAL_HE = {MealType.meat: "בשרי", MealType.dairy: "חלבי", MealType.pareve: "פרווה"}


def _r2(x: float) -> float:
    return round(x + 1e-9, 2)


def compute_quantity(item: CatalogItem, for_guests: int | None, quantity: float | None,
                     guests: int | None) -> tuple[float | None, str]:
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
        return g * CANAPES_PER_GUEST, f"{CANAPES_PER_GUEST} יח' לסועד"
    if item.unit.value == "hour":
        return STAFF_HOURS, f"{STAFF_HOURS} שעות"
    return g, f"{g} סועדים"


class PricingEngine:
    def __init__(self, catalog: list[CatalogItem], vat_rate: float | None = None):
        self.by_sku = {i.sku: i for i in catalog}
        self.vat_rate = get_settings().vat_rate if vat_rate is None else vat_rate

    def _line(self, item: CatalogItem, qty: float, note: str, source: LineSource,
              confidence: Confidence, reason: str = "") -> QuoteLine:
        return QuoteLine(
            sku=item.sku, name_he=item.name_he, unit=item.unit.value, unit_price=item.price,
            quantity=qty, total=_r2(qty * item.price), note=note, source=source,
            confidence=confidence, reason=reason,
        )

    def price(self, req: ExtractedRequest, plan: MenuPlan) -> PricedQuote:
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
            qty, note = compute_quantity(item, ml.for_guests, ml.quantity, guests)
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
                sv.waiters is None and guests >= AUTO_WAITERS_FROM and has_meal
            )
            if want_waiters:
                n = math.ceil(guests / WAITER_RATIO)
                add("STF-WAITER", n * STAFF_HOURS,
                    f"{n} מלצרים × {STAFF_HOURS} ש' (מלצר לכל {WAITER_RATIO})")
                if guests >= HEAD_WAITER_FROM:
                    add("STF-HEAD-WAITER", STAFF_HOURS, f"מנהל אירוע × {STAFF_HOURS} ש'")
            has_bar = any(self.by_sku[ln.sku].category.value == "bar" for ln in lines)
            has_open_bar = any(ln.sku == "BAR-OPEN" for ln in lines)  # includes a bartender
            if (sv.bar is True or has_bar) and not has_open_bar:
                n = math.ceil(guests / BARTENDER_RATIO)
                add("STF-BARTENDER", n * STAFF_HOURS, f"{n} ברמנים × {STAFF_HOURS} ש'")
            if req.kashrut == Kashrut.mehadrin:
                add("LOG-MEHADRIN", guests, f"{guests} סועדים")
        if sv.equipment is True or any(
            self.by_sku[ln.sku].category.value == "equipment" for ln in lines
        ):
            add("LOG-SETUP", 1, "")
        if lines:
            loc = (req.location or "").lower()
            remote = any(k in loc for k in REMOTE_AREAS)
            add("LOG-DELIVERY-F" if remote else "LOG-DELIVERY-C", 1,
                f"ל{req.location}" if req.location else "אזור מרכז (ברירת מחדל)")

        # 4. totals
        subtotal = _r2(sum(ln.total for ln in lines))
        rate = next((r for t, r in VOLUME_DISCOUNTS if subtotal >= t), 0.0)
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

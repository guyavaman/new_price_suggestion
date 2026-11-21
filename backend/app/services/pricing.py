"""Deterministic pricing. No LLM here — same input, same quote, every time.

The LLM decides *what* goes on the quote (SKUs, which guest group a line serves).
This module decides *how much*: quantities, staff, delivery, supervision, discounts, VAT,
and enforces business guards (kashrut meat/dairy separation, unknown SKUs, minimums).
"""

from __future__ import annotations

import math

from app.business.settings import BusinessSettings
from app.schemas.catalog import CatalogItem, ItemRole
from app.schemas.extraction import ExtractedRequest, Kashrut, MealType
from app.schemas.quote import (
    BudgetCheck,
    Confidence,
    LineSource,
    MenuPlan,
    PricedQuote,
    QuoteLine,
)
from app.services.costing import default_context, unit_cost

STYLE_HE = {"buffet": "מזנון", "plated": "הגשה לשולחן", "finger": "פינגר פוד",
            "chef_station": "שף במקום"}
ROLE_HE = {ItemRole.waiter: "מלצר", ItemRole.head_waiter: "מנהל אירוע", ItemRole.chef: "שף במקום",
           ItemRole.bartender: "ברמן", ItemRole.supervision: "השגחת מהדרין",
           ItemRole.setup: "הקמה ופירוק", ItemRole.delivery_center: "משלוח מרכז",
           ItemRole.delivery_remote: "משלוח מרוחק"}
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


def pick_zone(rules: BusinessSettings, location: str | None, km: float | None):
    """→ (zone, why). By distance when known (the smallest max_km that covers it), else by a
    word in the location, else the default zone. None when the business has no zones."""
    zones = rules.delivery_zones
    if not zones:
        return None, ""
    if km is not None:
        fits = sorted((z for z in zones if z.max_km and km <= z.max_km), key=lambda z: z.max_km)
        if fits:
            return fits[0], f"{km:g} ק\"מ"
        far = [z for z in zones if z.max_km]
        if far:  # beyond every distance band: the widest one
            return max(far, key=lambda z: z.max_km), f"{km:g} ק\"מ"
    loc = (location or "").lower()
    for z in zones:
        if loc and any(k.strip() and k.strip().lower() in loc for k in z.keywords):
            return z, location or ""
    z = next((z for z in zones if z.default), zones[0])
    return z, location or "מיקום לא ידוע: ברירת מחדל"


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def windows_for(rules: BusinessSettings, event_date, event_time: str | None) -> list:
    """Surcharge windows the delivery time falls in. No time known → none (not a guess)."""
    if not event_time:
        return []
    t = _minutes(event_time)
    day = (event_date.weekday() + 1) % 7 if event_date else None  # 0 = Sunday
    out = []
    for w in rules.delivery_windows:
        a, b = _minutes(w.start), _minutes(w.end)
        inside = a <= t < b if a < b else (t >= a or t < b)
        if inside and (not w.days or (day is not None and day in w.days)):
            out.append(w)
    return out


class PricingEngine:
    def __init__(self, catalog: list[CatalogItem], vat_rate: float | None = None,
                 rules: BusinessSettings | None = None, choices: dict | None = None):
        self.by_sku = {i.sku: i for i in catalog}
        self.choices = choices or {}  # package sku -> slot -> chosen dishes (the event's)
        self.by_role: dict[ItemRole, CatalogItem] = {}
        for i in catalog:
            if i.role and i.role not in self.by_role:
                self.by_role[i.role] = i
        self.rules = rules or DEFAULT_RULES
        self.vat_rate = self.rules.vat_rate if vat_rate is None else vat_rate

    def _unit_cost(self, item: CatalogItem, qty: float) -> float | None:
        ctx = None
        if item.category.value == "package":
            guests = int(qty) if item.unit.value == "per_guest" and qty else None
            ctx = default_context(self.rules, guests, self.choices.get(item.sku))
        return unit_cost(item, self.by_sku, ctx)

    def _line(self, item: CatalogItem, qty: float, note: str, source: LineSource,
              confidence: Confidence, reason: str = "") -> QuoteLine:
        return QuoteLine(
            sku=item.sku, name_he=item.name_he, unit=item.unit.value, unit_price=item.price,
            quantity=qty, total=_r2(qty * item.price), note=note, source=source,
            confidence=confidence, reason=reason,
            unit_cost=self._unit_cost(item, qty), cost_group=item.cost_group.value,
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
        def add(role: ItemRole, qty: float, note: str) -> None:
            item = self.by_role.get(role)
            if item is None:  # the business's catalog has no item for this rule: say so
                guards.append(f"חסר בקטלוג פריט בתפקיד '{ROLE_HE[role]}': השורה לא נוספה")
                return
            lines.append(self._line(item, qty, note, LineSource.rule, Confidence.rule))

        sv = req.service
        has_meal = any(self.by_sku[ln.sku].category.value in ("package", "main") for ln in lines)
        if guests:
            want_waiters = sv.waiters is True or (
                sv.waiters is None and guests >= R.auto_waiters_from and has_meal
            )
            style = sv.style.value if sv.style else None
            staffing = R.style_staffing.get(style) if style else None
            ratio = staffing.waiter_ratio if staffing else R.waiter_ratio
            if want_waiters or style:
                n = math.ceil(guests / ratio)
                how = f" · {STYLE_HE.get(style, style)}" if style else ""
                add(ItemRole.waiter, n * R.staff_hours,
                    f"{n} מלצרים × {R.staff_hours} ש' · מלצר לכל {ratio}{how}")
                if guests >= R.head_waiter_from:
                    add(ItemRole.head_waiter, R.staff_hours, f"מנהל אירוע × {R.staff_hours} ש'")
            if staffing and staffing.chef_ratio:
                n = math.ceil(guests / staffing.chef_ratio)
                add(ItemRole.chef, n * R.staff_hours, f"{n} שפים במקום × {R.staff_hours} ש'")
            has_bar = any(self.by_sku[ln.sku].category.value == "bar" for ln in lines)
            bar_staffed = any(self.by_sku[ln.sku].includes_bartender for ln in lines)
            if (sv.bar is True or has_bar) and not bar_staffed:
                n = math.ceil(guests / R.bartender_ratio)
                add(ItemRole.bartender, n * R.staff_hours, f"{n} ברמנים × {R.staff_hours} ש'")
            if req.kashrut == Kashrut.mehadrin:
                add(ItemRole.supervision, guests, f"{guests} סועדים")
        if sv.equipment is True or any(
            self.by_sku[ln.sku].category.value == "equipment" for ln in lines
        ):
            add(ItemRole.setup, 1, "")
        if lines:
            zone, why = pick_zone(R, req.location, req.distance_km)
            item = None
            if zone is not None:
                item = (self.by_sku.get(zone.sku) if zone.sku
                        else self.by_role.get(ItemRole(zone.role)) if zone.role else None)
                if item is None:
                    guards.append(f"לאזור המשלוח '{zone.name}' אין פריט בקטלוג: השורה לא נוספה")
                else:
                    lines.append(self._line(item, 1, f"אזור {zone.name} · {why}",
                                            LineSource.rule, Confidence.rule))
            else:  # no zones configured at all: the older two-role rule
                loc = (req.location or "").lower()
                remote = any(k in loc for k in R.remote_areas)
                add(ItemRole.delivery_remote if remote else ItemRole.delivery_center, 1,
                    f"ל{req.location}" if req.location else "אזור מרכז (ברירת מחדל)")
            for w in windows_for(R, req.event_date, req.event_time):
                lines.append(QuoteLine(
                    sku=f"DLV-{w.id}", name_he=f"תוספת משלוח: {w.name}", unit="unit",
                    unit_price=_r2(w.price), quantity=1, total=_r2(w.price),
                    note=f"הגעה ב-{req.event_time}", source=LineSource.rule,
                    confidence=Confidence.rule, unit_cost=w.cost, cost_group="logistics"))

        # 4. approved adjustments (late changes): a fixed amount, no cost behind it
        for a in plan.adjustments:
            lines.append(QuoteLine(sku=f"ADJ-{a.key}", name_he=a.label, unit="unit",
                                   unit_price=_r2(a.amount), quantity=1, total=_r2(a.amount),
                                   note="", source=LineSource.rule, confidence=Confidence.rule,
                                   unit_cost=0.0, cost_group="food"))

        # 5. totals
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

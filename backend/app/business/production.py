"""What the kitchen makes, buys and when: the one place it's computed.

`production()` turns every booked event in a date range into production lines: one per dish,
with the units to make (packages broken into their chosen dishes, packages.py), the weight or
portions, the work station and the prep day (event day − the dish's prep days). The kitchen
sheet, the purchase list and the prep schedule are three views of these lines.

Kashrut: the kitchen is split by the event's kind (meat / dairy / pareve), because that decides
utensils, staff shifts and transport. A day with both a meat and a dairy event gets a warning.

Missing data is normal: a dish without a yield has no weight, without a recipe it adds nothing
to the purchase list but is listed as "no recipe"; an ingredient without a supplier or a price
is listed as such. Nothing is guessed.
"""

from __future__ import annotations

import math
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from app.business.messages import whatsapp_url
from app.business.settings import BusinessSettings
from app.crm.models import Deal
from app.crm.service import CrmService, _booked
from app.purchasing.models import UNIT_HE as ING_UNIT_HE
from app.purchasing.models import WEEKDAYS_HE, Ingredient, Supplier
from app.schemas.catalog import CatalogItem
from app.services.packages import breakdown

NON_FOOD = {"staff", "logistics", "equipment"}
KASHRUT_ORDER = ["meat", "dairy", "pareve", ""]
KASHRUT_HE = {"meat": "בשרי", "dairy": "חלבי", "pareve": "פרווה", "": "לא צוין בשרי/חלבי"}
CATEGORY_HE = {"salad": "סלטים", "starter": "ראשונות", "main": "עיקריות", "side": "תוספות",
               "canape": "קבלת פנים", "breakfast": "מאפים ובוקר", "dessert": "קינוחים",
               "drink": "שתייה", "bar": "בר", "package": "חבילות"}
UNIT_HE = {"per_guest": "מנות", "unit": "יח'", "tray": "מגשים", "kg": 'ק"ג', "hour": "שעות"}


class ProdLine(BaseModel):
    deal_id: str
    title: str
    event_date: date
    event_meal: str              # "meat" | "dairy" | "pareve" | "" (not set)
    sku: str
    name_he: str
    category: str
    station: str
    measure: str | None = None   # "g" | "unit"
    total_amount: float | None = None
    units: float | None = None   # catalog units to make
    unit: str = ""
    prep_days: int = 0
    prep_date: date
    package: str | None = None
    problem: str | None = None


class EventInfo(BaseModel):
    deal_id: str
    title: str
    event_date: date
    guests: int | None
    location: str | None
    meal_type: str | None
    dietary: list[str]
    staff: list[str]
    equipment: list[str]
    tier: str | None


class Production(BaseModel):
    lines: list[ProdLine]
    events: list[EventInfo]
    missing_quotes: list[dict] = Field(default_factory=list)  # [{deal_id, title, event_date}]


def _latest_quote(repo, deal: Deal):
    for qid in reversed(deal.quote_ids):
        q = repo.get(deal.tenant_id, qid)
        if q:
            return q
    return None


def production(crm: CrmService, repo, catalog: list[CatalogItem], rules: BusinessSettings,
               tenant: str, start: date, end: date) -> Production:
    by_sku = {i.sku: i for i in catalog}
    deals = sorted(crm.deals.list(tenant, lambda d: d.event_date is not None
                                  and start <= d.event_date <= end and _booked(d)),
                   key=lambda d: (d.event_date, d.title))
    lines: list[ProdLine] = []
    events: list[EventInfo] = []
    missing: list[dict] = []
    for d in deals:
        q = _latest_quote(repo, d)
        staff: list[str] = []
        equipment: list[str] = []
        if q is None:
            missing.append({"deal_id": d.id, "title": d.title, "event_date": d.event_date})
        else:
            meal = d.meal_type or (q.request.meal_type.value if q.request.meal_type else "")
            for ln in q.tier().quote.lines:
                item = by_sku.get(ln.sku)
                cat = item.category.value if item else "other"
                if cat == "staff":
                    staff.append(f"{ln.name_he}: {ln.note or ln.quantity}")
                    continue
                if cat in NON_FOOD:
                    if cat == "equipment":
                        equipment.append(f"{ln.name_he} × {ln.quantity:g}")
                    continue
                if item is None:
                    continue
                if cat == "package" and item.slots:
                    guests = int(ln.quantity) if item.unit.value == "per_guest" else (
                        d.final_guest_count or d.guest_count or 0)
                    b = breakdown(item, by_sku, guests, rules.portion_rules,
                                  q.menu_choices.get(item.sku))
                    for r in b.rows:
                        dish = by_sku.get(r.sku)
                        lines.append(_line(d, meal, dish, r.sku, r.name_he, r.category, r.units,
                                           r.unit, r.measure.value if r.measure else None,
                                           r.total_amount, item.name_he,
                                           r.problem if r.units is None else None))
                    continue
                rule = rules.portion_rules.get(cat)
                amount = (ln.quantity * item.yield_amount
                          if rule and item.yield_amount else None)
                lines.append(_line(d, meal, item, item.sku, item.name_he, cat, ln.quantity,
                                   item.unit.value, rule.measure.value if rule else None,
                                   amount, None, None))
        events.append(EventInfo(
            deal_id=d.id, title=d.title, event_date=d.event_date,
            guests=d.final_guest_count or d.guest_count, location=d.location,
            meal_type=d.meal_type, dietary=d.dietary, staff=staff, equipment=equipment,
            tier=q.tier().name if q else None))
    return Production(lines=lines, events=events, missing_quotes=missing)


def _line(d: Deal, meal: str, dish: CatalogItem | None, sku: str, name: str, cat: str,
          units, unit: str, measure, amount, package, problem) -> ProdLine:
    prep = dish.prep_days if dish else 0
    return ProdLine(
        deal_id=d.id, title=d.title, event_date=d.event_date, event_meal=meal or "",
        sku=sku, name_he=name, category=cat,
        station=(dish.station if dish and dish.station else CATEGORY_HE.get(cat, cat)),
        measure=measure, total_amount=round(amount, 1) if amount is not None else None,
        units=units, unit=unit, prep_days=prep, prep_date=d.event_date - timedelta(days=prep),
        package=package, problem=problem)


# ------------------------------------------------------------------ kitchen sheet

class KitchenRow(BaseModel):
    sku: str
    name: str
    category: str
    units: float
    unit: str                      # Hebrew label
    measure: str | None = None
    total_amount: float | None = None
    events: list[dict] = Field(default_factory=list)  # [{deal_id, title, units, package}]
    problem: str | None = None


class KitchenGroup(BaseModel):
    station: str
    rows: list[KitchenRow]


class KitchenSection(BaseModel):
    kashrut: str                   # meat | dairy | pareve | ""
    label: str
    events: list[str]
    groups: list[KitchenGroup]


class KitchenSheet(BaseModel):
    date: date
    sections: list[KitchenSection]
    warnings: list[str]
    events: list[EventInfo]
    total_guests: int
    missing_quotes: list[str] = Field(default_factory=list)


def kitchen_day(p: Production, day: date) -> KitchenSheet:
    events = [e for e in p.events if e.event_date == day]
    lines = [ln for ln in p.lines if ln.event_date == day]
    sections = []
    for k in KASHRUT_ORDER:
        sec_lines = [ln for ln in lines if ln.event_meal == k]
        if not sec_lines:
            continue
        rows: dict[str, KitchenRow] = {}
        station_of: dict[str, str] = {}
        for ln in sec_lines:
            r = rows.setdefault(ln.sku, KitchenRow(
                sku=ln.sku, name=ln.name_he, category=ln.category, units=0,
                unit=UNIT_HE.get(ln.unit, ln.unit), measure=ln.measure,
                total_amount=0 if ln.total_amount is not None else None))
            station_of[ln.sku] = ln.station
            r.units += ln.units or 0
            if ln.total_amount is None:
                r.total_amount = None
            elif r.total_amount is not None:
                r.total_amount = round(r.total_amount + ln.total_amount, 1)
            if ln.problem:
                r.problem = ln.problem
            r.events.append({"deal_id": ln.deal_id, "title": ln.title, "units": ln.units,
                             "package": ln.package})
        groups: dict[str, list[KitchenRow]] = {}
        for sku, r in rows.items():
            groups.setdefault(station_of[sku], []).append(r)
        sections.append(KitchenSection(
            kashrut=k, label=KASHRUT_HE[k],
            events=sorted({ln.title for ln in sec_lines}),
            groups=[KitchenGroup(station=s, rows=sorted(g, key=lambda r: r.name))
                    for s, g in sorted(groups.items())]))
    return KitchenSheet(date=day, sections=sections, warnings=kashrut_warnings(events),
                        events=events, total_guests=sum(e.guests or 0 for e in events),
                        missing_quotes=[m["title"] for m in p.missing_quotes
                                        if m["event_date"] == day])


def kashrut_warnings(events: list[EventInfo]) -> list[str]:
    meat = [e.title for e in events if e.meal_type == "meat"]
    dairy = [e.title for e in events if e.meal_type == "dairy"]
    out = []
    if meat and dairy:
        out.append(f"באותו יום יש אירוע בשרי ({', '.join(meat)}) ואירוע חלבי "
                   f"({', '.join(dairy)}): להפריד כלים, משמרות במטבח ושינוע.")
    unknown = [e.title for e in events if not e.meal_type]
    if unknown:
        out.append(f"לא צוין בשרי/חלבי: {', '.join(unknown)}")
    return out


# ------------------------------------------------------------------ prep schedule

class PrepTask(BaseModel):
    sku: str
    name: str
    station: str
    units: float | None
    unit: str
    measure: str | None = None
    total_amount: float | None = None
    deal_id: str
    title: str
    event_date: date
    event_meal: str
    days_before: int
    problem: str | None = None


class PrepDay(BaseModel):
    date: date
    tasks: list[PrepTask]


def prep_schedule(p: Production, start: date, end: date) -> list[PrepDay]:
    """What to make each day in [start, end], for events up to two weeks later."""
    days: dict[date, list[PrepTask]] = {}
    for ln in p.lines:
        if not (start <= ln.prep_date <= end):
            continue
        days.setdefault(ln.prep_date, []).append(PrepTask(
            sku=ln.sku, name=ln.name_he, station=ln.station, units=ln.units,
            unit=UNIT_HE.get(ln.unit, ln.unit), measure=ln.measure, total_amount=ln.total_amount,
            deal_id=ln.deal_id, title=ln.title, event_date=ln.event_date,
            event_meal=ln.event_meal, days_before=ln.prep_days, problem=ln.problem))
    return [PrepDay(date=d, tasks=sorted(t, key=lambda x: (x.event_date, x.station, x.name)))
            for d, t in sorted(days.items())]


# ------------------------------------------------------------------ purchase list

class PurchaseItem(BaseModel):
    code: str
    name: str
    unit: str
    quantity: float
    price: float | None
    cost: float | None
    needed_by: date
    dishes: list[str]
    events: list[str]


class OrderBatch(BaseModel):
    deliver_on: date
    order_by: datetime | None   # None: no supplier, or no delivery day found
    late: bool = False
    items: list[PurchaseItem]
    total: float | None
    text: str
    whatsapp_url: str | None = None


class SupplierOrders(BaseModel):
    code: str | None
    name: str
    phone: str = ""
    lead_days: int | None = None
    delivery_days: list[str] = Field(default_factory=list)
    batches: list[OrderBatch]
    total: float | None


class PurchaseList(BaseModel):
    start: date
    end: date
    suppliers: list[SupplierOrders]
    missing_recipes: list[dict] = Field(default_factory=list)      # [{sku, name, events}]
    unknown_ingredients: list[dict] = Field(default_factory=list)  # [{code, dishes}]
    missing_quantities: list[dict] = Field(default_factory=list)   # [{name, problem, events}]
    missing_prices: list[str] = Field(default_factory=list)


def _qty(q: float, unit: str) -> float:
    if unit == "unit":
        return float(math.ceil(q - 1e-9))
    return math.ceil(q * 10 - 1e-9) / 10  # kg / liter: up to the next 100 g / 100 ml


def delivery_day(need: date, s: Supplier, buffer_days: int) -> date | None:
    """The latest day the supplier delivers that's at least `buffer_days` before `need`."""
    d = need - timedelta(days=buffer_days)
    for _ in range(15):
        if d.weekday() in s.delivery_days:
            return d
        d -= timedelta(days=1)
    return None


def order_deadline(deliver_on: date, s: Supplier, tz: ZoneInfo) -> datetime:
    h, m = (int(x) for x in s.order_cutoff.split(":"))
    return datetime.combine(deliver_on - timedelta(days=s.lead_days), time(h, m), tzinfo=tz)


def purchase_list(p: Production, catalog: list[CatalogItem], ingredients: list[Ingredient],
                  suppliers: list[Supplier], rules: BusinessSettings, start: date, end: date,
                  now: datetime | None = None) -> PurchaseList:
    tz = ZoneInfo(rules.timezone)
    now = now or datetime.now(tz)
    by_sku = {i.sku: i for i in catalog}
    ing = {i.code: i for i in ingredients}
    sup = {s.code: s for s in suppliers}
    need: dict[tuple[str | None, date, str], dict] = {}
    no_recipe: dict[str, dict] = {}
    unknown: dict[str, set] = {}
    no_qty: dict[str, dict] = {}
    for ln in p.lines:
        dish = by_sku.get(ln.sku)
        if dish is None:
            continue
        if ln.units is None:
            e = no_qty.setdefault(ln.sku, {"name": ln.name_he, "problem": ln.problem,
                                           "events": []})
            e["events"].append(ln.title)
            continue
        if not dish.recipe:
            e = no_recipe.setdefault(ln.sku, {"sku": ln.sku, "name": ln.name_he, "events": []})
            if ln.title not in e["events"]:
                e["events"].append(ln.title)
            continue
        for r in dish.recipe:
            i = ing.get(r.ingredient)
            if i is None:
                unknown.setdefault(r.ingredient, set()).add(dish.name_he)
                continue
            s = sup.get(i.supplier) if i.supplier else None
            deliver = delivery_day(ln.prep_date, s, rules.delivery_buffer_days) if s else (
                ln.prep_date - timedelta(days=rules.delivery_buffer_days))
            deliver = deliver or ln.prep_date
            key = (s.code if s else None, deliver, i.code)
            e = need.setdefault(key, {"q": 0.0, "need": ln.prep_date, "dishes": set(),
                                      "events": set()})
            e["q"] += r.quantity * ln.units
            e["need"] = min(e["need"], ln.prep_date)
            e["dishes"].add(dish.name_he)
            e["events"].add(ln.title)

    batches: dict[str | None, dict[date, list[PurchaseItem]]] = {}
    for (scode, deliver, code), e in need.items():
        i = ing[code]
        q = _qty(e["q"], i.unit.value)
        batches.setdefault(scode, {}).setdefault(deliver, []).append(PurchaseItem(
            code=code, name=i.name_he, unit=ING_UNIT_HE[i.unit.value], quantity=q,
            price=i.price, cost=round(q * i.price, 2) if i.price is not None else None,
            needed_by=e["need"], dishes=sorted(e["dishes"]), events=sorted(e["events"])))

    out: list[SupplierOrders] = []
    for scode, by_day in batches.items():
        s = sup.get(scode) if scode else None
        bl = []
        for deliver, items in sorted(by_day.items()):
            items.sort(key=lambda x: x.name)
            deadline = order_deadline(deliver, s, tz) if s else None
            text = _order_text(rules.business_name, s, deliver, items)
            bl.append(OrderBatch(
                deliver_on=deliver, order_by=deadline, late=bool(deadline and deadline < now),
                items=items, total=_sum(x.cost for x in items), text=text,
                whatsapp_url=whatsapp_url(s.phone, text) if s else None))
        out.append(SupplierOrders(
            code=scode, name=s.name if s else "בלי ספק", phone=s.phone if s else "",
            lead_days=s.lead_days if s else None,
            delivery_days=[WEEKDAYS_HE[d] for d in s.delivery_days] if s else [],
            batches=bl, total=_sum(b.total for b in bl)))
    out.sort(key=lambda o: (o.code is None, min((b.order_by or datetime.max.replace(tzinfo=tz))
                                                 for b in o.batches), o.name))
    prices = sorted({it.name for o in out for b in o.batches for it in b.items
                     if it.price is None})
    return PurchaseList(
        start=start, end=end, suppliers=out,
        missing_recipes=sorted(no_recipe.values(), key=lambda x: x["name"]),
        unknown_ingredients=[{"code": c, "dishes": sorted(d)} for c, d in sorted(unknown.items())],
        missing_quantities=sorted(no_qty.values(), key=lambda x: x["name"]),
        missing_prices=prices)


def _sum(values) -> float | None:
    vals = list(values)
    return None if any(v is None for v in vals) or not vals else round(sum(vals), 2)


def _order_text(business: str, s: Supplier | None, deliver: date,
                items: list[PurchaseItem]) -> str:
    head = (f"שלום {s.name}, הזמנה מ{business}" if s else f"רשימת קנייה ({business})")
    lines = [f"{head} לאספקה ביום {WEEKDAYS_HE[deliver.weekday()]} "
             f"{deliver.day}.{deliver.month}:"]
    lines += [f"• {it.name}: {it.quantity:g} {it.unit}" for it in items]
    lines.append("תודה!")
    return "\n".join(lines)

"""An event's menu: which dishes go into each package on a quote, and who may change them.

The owner can change dishes at any time (from the quote or the event card). The customer can
pick, in their link, only in slots the package lets customers choose, only while the quote is
live (sent or approved, not expired) and until `menu_lock_days` before the event. Every change
re-snapshots the package lines' cost, since the dishes (and so the cost) changed.
"""

from __future__ import annotations

from datetime import date, timedelta

from pydantic import BaseModel

from app.business.settings import BusinessSettings
from app.repositories.quotes import StoredQuote
from app.schemas.catalog import CatalogItem
from app.schemas.quote import QuoteStatus
from app.services.costing import refresh_package_costs
from app.services.packages import (
    Breakdown,
    CustomerSlot,
    breakdown,
    choice_errors,
    customer_view,
)


class PackageMenu(BaseModel):
    """Owner view: the slots and the breakdown with quantities and cost."""
    sku: str
    name_he: str
    tiers: list[str]
    guests: int
    slots: list[CustomerSlot]
    breakdown: Breakdown


class PublicPackageMenu(BaseModel):
    """Customer view: dish names and what they may choose. No amounts, no costs."""
    sku: str
    name_he: str
    tiers: list[str]
    slots: list[CustomerSlot]


class MenuLock(BaseModel):
    customer_can_choose: bool
    lock_date: date | None   # last day the customer can change dishes without approval
    reason: str | None = None
    needs_approval: bool = False  # after the lock: a change is a request for the owner


def _packages(q: StoredQuote, by_sku: dict[str, CatalogItem], only_selected: bool = False
              ) -> list[tuple[CatalogItem, list[str], int]]:
    """Distinct packages on the quote, in tier order: (package, names of the tiers using it,
    guests it's for). Guests come from the selected tier's line when it has the package."""
    found: dict[str, list] = {}
    for t in [q.tier()] if only_selected else q.tiers:
        for ln in t.quote.lines:
            item = by_sku.get(ln.sku)
            if item is None or item.category.value != "package" or not item.slots:
                continue
            guests = int(ln.quantity) if item.unit.value == "per_guest" else (
                q.request.guest_count or 0)
            entry = found.setdefault(ln.sku, [item, [], guests])
            entry[1].append(t.name)
            if t.key == q.selected_tier:
                entry[2] = guests
    return [tuple(v) for v in found.values()]


def owner_menu(q: StoredQuote, by_sku: dict[str, CatalogItem], rules: BusinessSettings,
               only_selected: bool = False) -> list[PackageMenu]:
    out = []
    for pkg, tiers, guests in _packages(q, by_sku, only_selected):
        choice = q.menu_choices.get(pkg.sku)
        out.append(PackageMenu(
            sku=pkg.sku, name_he=pkg.name_he, tiers=tiers, guests=guests,
            slots=customer_view(pkg, by_sku, choice),
            breakdown=breakdown(pkg, by_sku, guests, rules.portion_rules, choice)))
    return out


def customer_menu(q: StoredQuote, by_sku: dict[str, CatalogItem]) -> list[PublicPackageMenu]:
    return [PublicPackageMenu(sku=pkg.sku, name_he=pkg.name_he, tiers=tiers,
                              slots=customer_view(pkg, by_sku, q.menu_choices.get(pkg.sku)))
            for pkg, tiers, _ in _packages(q, by_sku)]


def lock(q: StoredQuote, rules: BusinessSettings, today: date, expired: bool) -> MenuLock:
    d = q.request.event_date
    lock_date = d - timedelta(days=rules.menu_lock_days) if d else None
    if q.status not in (QuoteStatus.sent, QuoteStatus.approved) or expired:
        return MenuLock(customer_can_choose=False, lock_date=lock_date,
                        reason="ההצעה לא פתוחה לבחירה")
    if d and today > d:
        return MenuLock(customer_can_choose=False, lock_date=lock_date, reason="האירוע עבר")
    if lock_date and today > lock_date:
        return MenuLock(customer_can_choose=True, lock_date=lock_date, needs_approval=True,
                        reason=f"בחירת המנות ננעלה {rules.menu_lock_days} ימים לפני האירוע: "
                               "שינוי יישלח לאישור")
    return MenuLock(customer_can_choose=True, lock_date=lock_date)


def apply_choice(q: StoredQuote, package: str, choice: dict[str, list[str]],
                 by_sku: dict[str, CatalogItem], rules: BusinessSettings,
                 by_customer: bool) -> list[str]:
    """Validate and store the chosen dishes for one package; returns errors (nothing changes
    when there are any). Slots not mentioned keep their current choice."""
    pkg = by_sku.get(package)
    if pkg is None or pkg.category.value != "package" or package not in {
            p.sku for p, _, _ in _packages(q, by_sku)}:
        return ["החבילה לא נמצאת בהצעה"]
    errs = choice_errors(pkg, choice, only_customer=by_customer)
    if errs:
        return errs
    q.menu_choices = {**q.menu_choices, package: {**q.menu_choices.get(package, {}), **choice}}
    for t in q.tiers:
        t.quote = refresh_package_costs(t.quote, by_sku, rules, q.menu_choices)
    return []


def describe(pkg: CatalogItem, choice: dict[str, list[str]], by_sku: dict[str, CatalogItem]
             ) -> str:
    """One line for the event timeline: "סלטים: X, Y; עיקרית: Z"."""
    labels = {s.id: s.label_he for s in pkg.slots}
    return "; ".join(f"{labels.get(sid, sid)}: "
                     + ", ".join(by_sku[s].name_he if s in by_sku else s for s in picked)
                     for sid, picked in choice.items())

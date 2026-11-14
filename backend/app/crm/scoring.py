"""Deterministic, explainable lead score (0-100). No LLM: a salesperson can see exactly why."""

from __future__ import annotations

from datetime import date

from app.crm.models import Customer, Deal

RULES = [
    # (points, reason, predicate(deal, customer, today))
    (20, "יש טלפון או מייל", lambda d, c, t: bool(c and (c.phone or c.email))),
    (15, "תאריך אירוע ידוע", lambda d, c, t: d.event_date is not None),
    (15, "מספר אורחים ידוע", lambda d, c, t: bool(d.guest_count)),
    (10, "ציין תקציב", lambda d, c, t: d.budget is not None),
    (10, "אירוע בתוך 60 יום",
     lambda d, c, t: bool(d.event_date and 0 <= (d.event_date - t).days <= 60)),
    (10, "אירוע גדול (80+ אורחים)", lambda d, c, t: (d.guest_count or 0) >= 80),
    (10, "ביקש הצעת מחיר", lambda d, c, t: bool(d.quote_ids)),
    (10, "כשרות וסוג ארוחה ידועים", lambda d, c, t: bool(d.kashrut and d.meal_type)),
]


def score(deal: Deal, customer: Customer | None,
          today: date | None = None) -> tuple[int, list[str]]:
    today = today or date.today()
    if deal.event_date and deal.event_date < today:
        return 0, ["תאריך האירוע עבר"]
    pts, reasons = 0, []
    for points, reason, pred in RULES:
        if pred(deal, customer, today):
            pts += points
            reasons.append(f"+{points} {reason}")
    return min(pts, 100), reasons

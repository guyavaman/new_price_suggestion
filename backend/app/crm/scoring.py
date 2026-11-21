"""Deterministic, explainable lead score (0-100). No LLM: a salesperson can see exactly why.

Stage 7: what the customer *did* weighs more than what they *filled in*. Opening the quote
(again and again), printing it, asking about price or the date, and asking for a person are
intent; knowing the date and guest count is only information. The points per signal are the
owner's (settings.score_weights); a key missing there counts as 0.
"""

from __future__ import annotations

from datetime import date

from app.crm.models import Customer, Deal

RULES = [
    # (weight key, reason, predicate(deal, customer, today))
    ("contact", "יש טלפון או מייל", lambda d, c, t: bool(c and (c.phone or c.email))),
    ("date", "תאריך אירוע ידוע", lambda d, c, t: d.event_date is not None),
    ("guests", "מספר אורחים ידוע", lambda d, c, t: bool(d.guest_count)),
    ("budget", "ציין תקציב", lambda d, c, t: d.budget is not None),
    ("details", "כשרות וסוג ארוחה ידועים", lambda d, c, t: bool(d.kashrut and d.meal_type)),
    ("soon", "אירוע בתוך 60 יום",
     lambda d, c, t: bool(d.event_date and 0 <= (d.event_date - t).days <= 60)),
    ("big", "אירוע גדול (80+ אורחים)", lambda d, c, t: (d.guest_count or 0) >= 80),
    ("quote", "ביקש הצעת מחיר", lambda d, c, t: bool(d.quote_ids)),
    ("opened", "פתח את ההצעה", lambda d, c, t: d.signals.quote_opens >= 1),
    ("opened_again", "חזר להצעה 3 פעמים או יותר", lambda d, c, t: d.signals.quote_opens >= 3),
    ("pdf", "הוריד את ההצעה כ-PDF", lambda d, c, t: d.signals.pdf_views >= 1),
    ("asked_human", "ביקש לדבר עם נציג", lambda d, c, t: d.signals.asked_human),
    ("asked_price", "שאל על מחיר", lambda d, c, t: d.signals.price_questions >= 1),
    ("asked_date", "שאל על תאריך או זמינות", lambda d, c, t: d.signals.date_questions >= 1),
]


def score(deal: Deal, customer: Customer | None, today: date | None = None,
          weights: dict[str, int] | None = None) -> tuple[int, list[str]]:
    if weights is None:
        from app.business.settings import _default_score  # late: settings imports crm models
        weights = _default_score()
    today = today or date.today()
    if deal.event_date and deal.event_date < today:
        return 0, ["תאריך האירוע עבר"]
    pts, reasons = 0, []
    for key, reason, pred in RULES:
        points = weights.get(key, 0)
        if points and pred(deal, customer, today):
            pts += points
            reasons.append(f"+{points} {reason}")
    return min(pts, 100), reasons

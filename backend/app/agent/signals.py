"""Cheap, deterministic signals about the customer's mood.

Runs on every message, even when the AI is silent because a salesperson took over, so a lead
that is about to walk away always raises an alarm in the CRM.
"""

from __future__ import annotations

import re

FRUSTRATION = [
    r"לא רציני", r"לא אחזור", r"לא נחזור", r"מאוכזב", r"מבאס", r"בזבוז זמן", r"עזבו",
    r"שכחו ממני", r"אף אחד לא (עונה|חוזר)", r"נמאס", r"אלך למקום אחר", r"ספק אחר",
    r"מתחרים", r"אתם (לא )?עונים", r"כבר שעות", r"לא מקצועי", r"מגוחך", r"חוצפה",
    r"\bnot serious\b", r"\bwaste of time\b", r"\bnever (mind|coming back)\b", r"\bdisappoint",
    r"\bgo (somewhere|elsewhere)\b", r"\bno one (answers|replies)\b", r"\bfrustrat",
]
_RE = re.compile("|".join(FRUSTRATION), re.I)


def is_frustrated(text: str) -> bool:
    return bool(_RE.search(text))


# ---- intent (stage 7): what the customer asks shows how close they are to booking ----
PRICE = [r"כמה (זה )?(עולה|יעלה|יוצא|עולים)", r"מחיר", r"עלות", r"תקציב", r"הנחה", r"לאורח",
         r"לסועד", r"\bprice", r"\bcost", r"how much", r"\bquote\b", r"discount"]
DATE = [r"פנוי", r"פנויים", r"תאריך", r"זמינ", r"יש לכם מקום", r"אפשר (ב|ל)?(יום|שבת|שישי)",
        r"available", r"\bdate\b", r"free on"]
HUMAN = [r"נציג", r"בן אדם", r"אדם אמיתי", r"מישהו (ש)?יחזור", r"תתקשרו", r"להתקשר",
         r"לדבר עם", r"בעל העסק", r"מנהל", r"\bhuman\b", r"real person", r"call me",
         r"speak (to|with)", r"\bagent\b"]
_P, _D, _H = (re.compile("|".join(x), re.I) for x in (PRICE, DATE, HUMAN))


def intent_of(text: str) -> tuple[bool, bool, bool]:
    """(asks about price, asks about date/availability, asks for a person)."""
    return bool(_P.search(text)), bool(_D.search(text)), bool(_H.search(text))


def chat_signals(customer_texts: list[str], handed_off: bool) -> dict:
    """Counts over the whole conversation (idempotent: recomputed every turn)."""
    hits = [intent_of(t) for t in customer_texts]
    return {"price_questions": sum(h[0] for h in hits),
            "date_questions": sum(h[1] for h in hits),
            "asked_human": handed_off or any(h[2] for h in hits)}

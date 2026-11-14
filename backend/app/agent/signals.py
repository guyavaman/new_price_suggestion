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

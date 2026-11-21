"""The order terms the customer accepts on the quote page before paying the deposit (stage 7).

The text is built from the same settings the system enforces (lock days, surcharge, deposit,
cancellation steps), so what the customer accepts is always what will actually happen. The
version is a hash of the exact lines: an acceptance records the lines it was shown.
"""

from __future__ import annotations

import hashlib

from app.business.settings import BusinessSettings


def _pct(x: float) -> str:
    return f"{round(x * 100):g}%"


def cancellation_lines(rules: BusinessSettings) -> list[str]:
    steps = sorted(rules.cancellation_policy, key=lambda c: -c.days_before)
    out = []
    for i, c in enumerate(steps):
        if c.refund_rate >= 1:
            refund = "המקדמה מוחזרת במלואה"
        elif c.refund_rate <= 0:
            refund = "המקדמה לא מוחזרת"
        else:
            refund = f"מוחזרים {_pct(c.refund_rate)} מהמקדמה"
        if c.days_before == 0:
            when = ("ביטול בפחות מ-" + str(steps[i - 1].days_before) + " ימים לפני האירוע"
                    if i else "ביטול בכל מועד")
        else:
            when = (f"ביטול {c.days_before} עד {steps[i - 1].days_before - 1} ימים לפני האירוע"
                    if i else f"ביטול {c.days_before} ימים או יותר לפני האירוע")
        out.append(f"{when}: {refund}.")
    return out


def terms_lines(rules: BusinessSettings) -> list[str]:
    lines = []
    if rules.deposit_rate > 0:
        lines.append(f"ההזמנה מאושרת בתשלום מקדמה של {_pct(rules.deposit_rate)} מהמחיר. "
                     f"היתרה משולמת עד {rules.balance_reminder_days} ימים לפני האירוע.")
    lines += cancellation_lines(rules)
    late = (f"אחרי המועד הזה הוספת אורחים כרוכה בתוספת של {_pct(rules.late_guest_surcharge)} "
            "למחיר לאורח ובאישור שלנו" if rules.late_guest_surcharge
            else "אחרי המועד הזה הוספת אורחים באישור שלנו")
    fewer = ("והפחתה לא מוזילה את המחיר" if rules.late_decrease_charged
             else "והפחתה מעדכנת את המחיר")
    lines.append(f"את מספר האורחים הסופי מאשרים עד {rules.guest_lock_days} ימים לפני האירוע. "
                 f"{late}, {fewer}.")
    lines.append(f"בחירת המנות ננעלת {rules.menu_lock_days} ימים לפני האירוע. "
                 "שינוי אחר כך בכפוף לאישור שלנו.")
    lines.append(f"המחירים בהצעה תקפים {rules.quote_valid_days} ימים ממועד ההצעה.")
    lines += [x.strip() for x in rules.terms_extra if x.strip()]
    return lines


def terms_version(lines: list[str]) -> str:
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()[:12]

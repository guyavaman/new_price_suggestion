"""Ready-to-send customer messages, each carrying the customer's personal link.

The personal quote page is where the customer picks a package, pays, updates the guest count and
talks to Noa (customer service). It only works if customers get there, so every message the
business sends at an important moment ends with that link. The owner sends them from the deal
page on WhatsApp in one tap (wa.me with the text filled in), from their own phone.
"""

from __future__ import annotations

from datetime import date, timedelta
from urllib.parse import quote as urlquote

from pydantic import BaseModel

from app.business.settings import BusinessSettings
from app.crm.models import Customer, Deal, DealStage
from app.repositories.quotes import StoredQuote
from app.schemas.quote import QuoteStatus

FINAL_COUNT_CLOSES_DAYS_BEFORE = 2
NOA = "יש שאלה? אפשר לכתוב לנועה בעמוד, בכל שעה."
EVENT_HE = {
    "wedding": "החתונה", "bar_bat_mitzvah": "בר/בת המצווה", "brit": "הברית",
    "birthday": "יום ההולדת", "corporate": "האירוע", "conference": "הכנס", "holiday": "האירוע",
    "private": "האירוע", "other": "האירוע",
}


class CustomerMessage(BaseModel):
    kind: str
    label: str
    text: str
    recommended: bool = False
    whatsapp_url: str | None = None


def _ils(x: float) -> str:
    return f"₪{x:,.0f}"


def _date(d: date) -> str:
    return d.strftime("%d/%m")


def personal_link(rules: BusinessSettings, q: StoredQuote) -> str:
    return f"{rules.public_base_url.rstrip('/')}/q/{q.public_token}"


def whatsapp_url(phone: str | None, text: str) -> str | None:
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    if digits.startswith("0"):
        digits = "972" + digits[1:]
    return f"https://wa.me/{digits}?text={urlquote(text)}" if len(digits) >= 11 else None


def followup_text(link: str) -> str:
    return (f"היי, רציתי לוודא שההצעה הגיעה 🙂 אפשר לבחור חבילה ולאשר כאן: {link}\n"
            f"ואם משהו לא מתאים, נשמח להתאים. {NOA}")


def final_count_text(link: str, deadline: date) -> str:
    return (f"היי! האירוע מתקרב 🎉 אפשר לאשר מספר אורחים סופי עד {_date(deadline)}, "
            f"והמחיר יתעדכן לבד: {link}\n{NOA}")


def customer_messages(deal: Deal, q: StoredQuote | None, customer: Customer | None,
                      rules: BusinessSettings, today: date | None = None) -> list[CustomerMessage]:
    """The messages that make sense for this deal right now, the most relevant first."""
    if q is None:
        return []
    today = today or date.today()
    link = personal_link(rules, q)
    first = ((customer.name if customer else None) or q.request.contact.name or "").split(" ")[0]
    hi = f"היי {first}" if first else "היי"
    event = EVENT_HE.get(deal.event_type or "other", "האירוע")
    total = q.tier().quote.total
    out: list[tuple[str, str, str]] = []  # kind, label, text

    if q.status in (QuoteStatus.draft, QuoteStatus.sent) and deal.stage != DealStage.lost:
        out.append(("quote", "שליחת ההצעה",
                    f"{hi}, ההצעה ל{event} מוכנה 🙂 שלוש חבילות לבחירה, מאשרים ומשלמים מקדמה "
                    f"ישר מהעמוד: {link}\n{NOA}"))
        out.append(("followup", "תזכורת על ההצעה", followup_text(link)))

    if q.status == QuoteStatus.approved and deal.stage in (DealStage.won, DealStage.quoted):
        balance = max(total - deal.deposit_paid, 0)
        when = f" ל-{_date(deal.event_date)}" if deal.event_date else ""
        paid = f"המקדמה של {_ils(deal.deposit_paid)} התקבלה. " if deal.deposit_paid else ""
        out.append(("confirmed", "אישור הזמנה",
                    f"תודה {first}! ההזמנה{when} אושרה ✔️ {paid}כל הפרטים נמצאים כאן, "
                    f"ושם גם מאשרים מספר אורחים סופי: {link}\n{NOA}"))
        if deal.event_date:
            days_left = (deal.event_date - today).days
            deadline = deal.event_date - timedelta(days=FINAL_COUNT_CLOSES_DAYS_BEFORE)
            if days_left >= FINAL_COUNT_CLOSES_DAYS_BEFORE and deal.final_guest_count is None:
                out.append(("final_count", "בקשת מספר אורחים סופי",
                            final_count_text(link, deadline)))
            if balance > 0 and days_left >= 0:
                out.append(("balance", "תזכורת יתרה",
                            f"{hi}, תזכורת קטנה לקראת {event}: נשארה יתרה של {_ils(balance)}. "
                            f"הפירוט המלא כאן: {link}\n{NOA}"))

    if deal.stage == DealStage.completed:
        out.append(("thanks", "תודה אחרי האירוע",
                    f"{hi}, תודה שבחרתם בנו ל{event}! נשמח לשמוע איך היה 🙏 "
                    f"ואם תרצו להזמין שוב, הכל כאן: {link}"))

    out.append(("service", "קישור לשירות לקוחות",
                f"{hi}, כל פרטי ההזמנה נמצאים בעמוד האישי שלך: {link}\n"
                f"שם אפשר גם לשאול את נועה כל שאלה, בכל שעה."))

    recommended = _recommended(deal, q, [k for k, _, _ in out], today)
    phone = customer.phone if customer else q.request.contact.phone
    msgs = [CustomerMessage(kind=k, label=lab, text=t, recommended=k == recommended,
                            whatsapp_url=whatsapp_url(phone, t)) for k, lab, t in out]
    return sorted(msgs, key=lambda m: not m.recommended)


def _recommended(deal: Deal, q: StoredQuote, kinds: list[str], today: date) -> str:
    def first(*options: str) -> str:
        return next((k for k in options if k in kinds), kinds[0])
    if "quote" in kinds:
        age = (today - q.created_at.date()).days
        return first("followup" if age >= 2 else "quote")
    if "final_count" in kinds and deal.event_date and (deal.event_date - today).days <= 7:
        return "final_count"
    if "confirmed" in kinds and "confirmed" not in deal.sent_messages:
        return "confirmed"
    return first("balance", "thanks", "service")

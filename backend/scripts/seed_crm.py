# ruff: noqa: E501
"""Fill the demo tenant's CRM with realistic sample data (customers, deals in every stage,
activities, tasks and agent conversations), so the UI has something to show.

Usage (from backend/):  python -m scripts.seed_crm [--reset]
"""

from __future__ import annotations

import argparse
import random
from datetime import date, timedelta

from app.catalog.loader import load_catalog
from app.crm.models import (
    Activity,
    ActivityKind,
    Actor,
    ChatMessage,
    ChatRole,
    Conversation,
    ConversationStatus,
    Deal,
    DealStage,
    Invoice,
    Payment,
    Source,
    now,
)
from app.crm.service import CrmService
from app.repositories.quotes import JsonQuoteRepository, StatusChange
from app.repositories.store import STORE_DIR
from app.schemas.extraction import ContactInfo, ExtractedRequest
from app.schemas.quote import QuoteStatus
from app.services.pricing import PricingEngine
from app.services.quotes import create_quote, standard_plan

QUOTE_STATUS_FOR_STAGE = {"quoted": QuoteStatus.sent, "won": QuoteStatus.approved,
                          "completed": QuoteStatus.approved, "lost": QuoteStatus.rejected}

TENANT = "demo"
SAMPLES = [
    # name, phone, event_type, days_ahead, guests, meal, kashrut, stage, ready_to_book, source
    ("מיכל לוי", "0501234567", "bar_bat_mitzvah", 19, 120, "meat", "kosher", "quoted", False, "web_chat"),
    ("יוסי כהן", "0529876543", "wedding", 45, 220, "meat", "mehadrin", "quoted", True, "phone"),
    ("נטע אברהם", "0541112233", "brit", 3, 60, "dairy", "kosher", "won", False, "web_chat"),
    ("דנה שפירא", "0587654321", "corporate", 3, 180, "meat", "kosher", "won", False, "email"),
    ("Amir Tech Ltd", "0533334444", "conference", 33, 90, "pareve", "kosher", "new", False, "web_chat"),
    ("רונית גל", "0502223344", "birthday", 14, 35, "dairy", None, "new", False, "web_chat"),
    ("אבי מזרחי", "0545556677", "wedding", 80, 300, "meat", "mehadrin", "quoted", False, "referral"),
    ("שירה בן דוד", "0526667788", "private", 21, 30, "dairy", "kosher", "lost", False, "web_chat"),
    ("עומר פרץ", "0508889900", "corporate", 6, 25, "meat", None, "won", False, "email"),
    ("ליאת רוזן", "0521212121", "bar_bat_mitzvah", 60, 140, "meat", "kosher", "new", False, "whatsapp"),
    ("גיא שמש", "0543434343", "holiday", -4, 70, "dairy", "kosher", "completed", False, "web_chat"),
    ("הדס יעקב", "0505656565", "birthday", 11, 40, "pareve", "kosher", "quoted", True, "web_chat"),
]

CHAT = [
    ("user", "היי, אני מתכננת בר מצווה לבן שלי, בערך 120 איש"),
    ("assistant", "מזל טוב! 🎉 באיזה תאריך ובשרי או חלבי?"),
    ("user", "בשרי כשר, 8 טבעונים. בתחילת דצמבר"),
    ("assistant", "בדקתי, התאריך פנוי. ההערכה לחבילה המומלצת היא בערך ₪370 לאורח כולל הכל. איך קוראים לך?"),
    ("user", "מיכל, 050-1234567. תשלחי הצעה"),
    ("assistant", "שלחתי לך הצעה מסודרת עם 3 חבילות 🙂 רוצה שנציג יחזור אלייך?"),
]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--reset", action="store_true")
    args = p.parse_args()
    if args.reset:
        for f in [*STORE_DIR.glob("crm_*.json"), STORE_DIR / "quotes.json"]:
            f.unlink(missing_ok=True)
    crm = CrmService()
    repo = JsonQuoteRepository()
    catalog = load_catalog()
    engine = PricingEngine(catalog)
    rnd = random.Random(7)
    today = date.today()
    for i, (name, phone, etype, days, guests, meal, kashrut, stage, ready, src) in enumerate(SAMPLES):
        value = None
        company = name if "Ltd" in name else None
        c = crm.upsert_customer(TENANT, name=None if company else name, phone=phone,
                                company=company, source=Source(src))
        d = crm.save_deal(Deal(
            tenant_id=TENANT, customer_id=c.id, title="", source=Source(src), value=value,
            event_type=etype, event_date=today + timedelta(days=days), guest_count=guests,
            meal_type=meal, kashrut=kashrut, budget=rnd.choice([None, None, 250, 300]),
            budget_scope="per_guest", ready_to_book=ready,
        ))
        src_he = {"web_chat": "צ'אט באתר", "phone": "טלפון", "email": "מייל", "referral": "המלצה",
                  "whatsapp": "וואטסאפ"}[src]
        crm.log(TENANT, ActivityKind.system, f"פנייה חדשה ({src_he})", Actor.system, deal_id=d.id,
                customer_id=c.id)
        if stage in QUOTE_STATUS_FOR_STAGE:  # a real stored quote behind every quoted deal
            req = ExtractedRequest(language="he", event_type=etype, guest_count=guests,
                                   event_date=d.event_date, kashrut=kashrut, meal_type=meal,
                                   contact=ContactInfo(name=c.name, phone=c.phone,
                                                       company=c.company),
                                   service={"waiters": guests >= 60})
            q = create_quote(repo, TENANT, req, standard_plan(req), catalog, engine,
                             f"פנייה של {c.name or c.company} ל{guests} אורחים")
            q.status = QUOTE_STATUS_FOR_STAGE[stage]
            q.history.append(StatusChange(status=q.status))
            repo.save(q)
            d.quote_ids, d.value = [q.id], q.tier().quote.total
            if stage in ("won", "completed"):
                deposit = round(d.value * 0.3, 2)
                d.payments = [Payment(amount=deposit, status="paid", paid_at=now())]
                if stage == "completed":
                    d.invoice = Invoice(provider="manual", number="INV-1001", amount=d.value)
            d = crm.save_deal(d)
            crm.log(TENANT, ActivityKind.quote, f"הצעת מחיר {q.number} נוצרה", Actor.system,
                    deal_id=d.id, meta={"quote_id": q.id})
        if stage != "new":
            crm.move_stage(TENANT, d.id, DealStage(stage), Actor.agent if src == "web_chat"
                           else Actor.user, "המחיר גבוה מהתקציב" if stage == "lost" else None)
        if src == "web_chat":
            conv = Conversation(tenant_id=TENANT, customer_id=c.id, deal_id=d.id,
                                status=ConversationStatus.handed_off if ready
                                else ConversationStatus.active,
                                messages=[ChatMessage(role=ChatRole(r), text=t) for r, t in CHAT]
                                if i == 0 else [ChatMessage(role=ChatRole.user,
                                                            text=f"שלום, צריך הצעה ל-{guests} איש"),
                                                ChatMessage(role=ChatRole.assistant,
                                                            text="בשמחה! באיזה תאריך מדובר?")])
            conv = crm.conversations.put(conv)
            d = crm.deals.get(TENANT, d.id)  # reload: move_stage saved a newer copy
            d.conversation_id = conv.id
            crm.save_deal(d)
        if stage in ("quoted", "new"):
            crm.add_task(TENANT, "שיחת מעקב על ההצעה" if stage == "quoted" else "לחזור ללקוח",
                         deal_id=d.id, due_at=now() + timedelta(hours=rnd.choice([-5, 3, 26])),
                         priority="high" if ready else "normal",
                         created_by=Actor.agent)
        crm.activities.put(Activity(tenant_id=TENANT, deal_id=d.id, kind=ActivityKind.note,
                                    text=rnd.choice(["מעדיפים הגשה למזנון", "שאלו על מגדל קינוחים",
                                                     "האולם מספק כלים", "צריך הגעה עד 17:00"]),
                                    actor=Actor.user))
    print(f"Seeded {len(SAMPLES)} deals for tenant '{TENANT}'.")


if __name__ == "__main__":
    main()

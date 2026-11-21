# ruff: noqa: E501
"""Fill the demo tenant's CRM with realistic sample data (customers, deals in every stage,
activities, tasks and agent conversations), so the UI has something to show.

Usage (from backend/):  python -m scripts.seed_crm [--reset]
"""

from __future__ import annotations

import argparse
import random
from datetime import UTC, date, datetime, timedelta

from app.business.changes import request_change
from app.business.settings import BusinessSettings
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
    DishOutcome,
    EventClosing,
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
from app.services.event_menu import apply_choice, describe
from app.services.pricing import PricingEngine
from app.services.quotes import create_quote, standard_plan

QUOTE_STATUS_FOR_STAGE = {"quoted": QuoteStatus.sent, "won": QuoteStatus.approved,
                          "completed": QuoteStatus.approved, "lost": QuoteStatus.rejected}

TENANT = "demo"
SAMPLES = [
    # name, phone, event_type, days_ahead, guests, meal, kashrut, stage, ready_to_book, source
    ("מיכל לוי", "0501234567", "bar_bat_mitzvah", 19, 120, "meat", "kosher", "quoted", False, "web_chat"),
    ("יוסי כהן", "0529876543", "wedding", 45, 220, "meat", "mehadrin", "quoted", True, "phone"),
    ("נטע אברהם", "0541112233", "brit", 2, 60, "dairy", "kosher", "won", False, "web_chat"),
    ("דנה שפירא", "0587654321", "corporate", 2, 180, "meat", "kosher", "won", False, "email"),
    ("Amir Tech Ltd", "0533334444", "conference", 33, 90, "pareve", "kosher", "new", False, "web_chat"),
    ("רונית גל", "0502223344", "birthday", 14, 35, "dairy", None, "new", False, "web_chat"),
    ("אבי מזרחי", "0545556677", "wedding", 80, 300, "meat", "mehadrin", "quoted", False, "referral"),
    ("שירה בן דוד", "0526667788", "private", 21, 30, "dairy", "kosher", "lost", False, "web_chat"),
    ("עומר פרץ", "0508889900", "corporate", 6, 25, "meat", None, "won", False, "email"),
    ("ליאת רוזן", "0521212121", "bar_bat_mitzvah", 60, 140, "meat", "kosher", "new", False, "whatsapp"),
    ("גיא שמש", "0543434343", "holiday", -4, 70, "dairy", "kosher", "completed", False, "web_chat"),
    ("הדס יעקב", "0505656565", "birthday", 11, 40, "pareve", "kosher", "quoted", True, "web_chat"),
]

# events that already happened, with a closing form each (stage 6: planned vs actual, learning)
HISTORY = [
    ("משפחת אורן", "0501010101", "bar_bat_mitzvah", -18, 110, "meat", "kosher", "completed", False, "phone"),
    ("רחל דוד", "0502020202", "brit", -29, 50, "dairy", "kosher", "completed", False, "referral"),
    ("Nova Systems Ltd", "0503030303", "corporate", -41, 80, "meat", "kosher", "completed", False, "email"),
    ("תמר וייס", "0504040404", "birthday", -55, 45, "dairy", "kosher", "completed", False, "whatsapp"),
]
# per event: guests who came, leftover mark by category (default "ok"), purchasing vs plan, notes
CLOSINGS = {
    "משפחת אורן": (104, {"salad": "lot", "main": "out"}, 1.06, "הסלטים חזרו כמעט מלאים. השניצלים נגמרו מוקדם."),
    "רחל דוד": (50, {"salad": "lot"}, 0.97, ""),
    "Nova Systems Ltd": (72, {"salad": "lot", "main": "out", "dessert": "ok"}, 1.12, "הגיעו פחות ממה שאישרו."),
    "תמר וייס": (45, {"salad": "ok", "main": "out"}, 1.0, ""),
    "גיא שמש": (66, {"salad": "lot"}, 1.04, "חם מאוד, שתו הרבה."),
}

# how long ago each booked deal was closed: some this month, some earlier (month KPIs)
# dishes picked per event: by the customer in their link, or by the owner. One owner pick uses a
# salad with no yield per unit, so that quote shows "חסרה תפוקה ליחידה" (missing data demo).
MENU_CHOICES = {
    "מיכל לוי": ("PKG-MEAT-STD", {"salads": ["SAL-TABULE", "SAL-HUMMUS", "SAL-MATBUCHA"],
                                  "main": ["MAIN-KEBAB"]}, "customer"),
    "אבי מזרחי": ("PKG-MEAT-STD", {"salads": ["SAL-ISR", "SAL-EGGPLANT", "SAL-CABBAGE"]},
                  "owner"),
}
# serving style per event (sets the waiter ratio)
STYLE = {"דנה שפירא": "buffet", "נטע אברהם": "plated", "יוסי כהן": "plated",
         "עומר פרץ": "buffet", "מיכל לוי": "buffet"}
# event readiness: a fully ready event, events with gaps, one without a venue at all
READY = {
    "עומר פרץ": {"location": "משרדי החברה, רחוב הברזל 30 תל אביב", "contact": ("שני", "052-7001122"),
                 "site": dict(electricity=True, kitchenette=True, fridge=True, parking=False),
                 "final": True, "paid": True, "marks": ["staff", "equipment"], "menu": True},
    "דנה שפירא": {"location": "גן אירועים השקמה, רעננה", "contact": ("מאיר", "054-3300112"),
                  "site": dict(electricity=True, kitchenette=True, fridge=None, parking=True),
                  "final": True, "paid": False, "marks": ["staff"], "menu": False},
    "נטע אברהם": {"location": None, "contact": None, "site": {}, "final": False, "paid": False,
                  "marks": [], "menu": False, "change": 72},
}
BOOKED_DAYS_AGO = {"נטע אברהם": 2, "דנה שפירא": 9, "עומר פרץ": 40, "גיא שמש": 55,
                   "משפחת אורן": 70, "רחל דוד": 60, "Nova Systems Ltd": 95, "תמר וייס": 100}

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
    seed(reset=p.parse_args().reset)


def seed(reset: bool = False) -> None:
    if reset:
        for f in [*STORE_DIR.glob("crm_*.json"), STORE_DIR / "quotes.json",
                  *(STORE_DIR / n for n in ("staff.json", "staff_assignments.json",
                                            "equipment.json", "event_equipment.json",
                                            "purchase_orders.json"))]:
            f.unlink(missing_ok=True)
    crm = CrmService()
    repo = JsonQuoteRepository()
    catalog = load_catalog()
    _add_samples(crm, repo, catalog, SAMPLES + HISTORY)
    seed_team(crm, repo, catalog)
    seed_closings(crm, repo, catalog)
    print(f"Seeded {len(SAMPLES)} deals for tenant '{TENANT}'.")


def _add_samples(crm, repo, catalog, samples) -> None:
    """Customers, deals, quotes and chats for each sample row."""
    engine = PricingEngine(catalog)
    rules = BusinessSettings(id=TENANT, tenant_id=TENANT)
    by_sku = {i.sku: i for i in catalog}
    rnd = random.Random(7)
    today = date.today()
    for i, (name, phone, etype, days, guests, meal, kashrut, stage, ready, src) in enumerate(samples):
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
                                   service={"waiters": guests >= 60, "style": STYLE.get(name)})
            q = create_quote(repo, TENANT, req, standard_plan(req, catalog), catalog, engine,
                             f"פנייה של {c.name or c.company} ל{guests} אורחים")
            q.status = QUOTE_STATUS_FOR_STAGE[stage]
            q.history.append(StatusChange(status=q.status))
            picked = MENU_CHOICES.get(name)
            if picked:
                pkg, choice, who = picked
                errs = apply_choice(q, pkg, choice, by_sku, rules, by_customer=who == "customer")
                assert not errs, errs
            repo.save(q)
            d.quote_ids = [q.id]
            d.set_value(q.tier().quote.total, q.tier().quote.net)
            if stage in ("won", "completed"):
                deposit = round(d.value * 0.3, 2)
                d.payments = [Payment(amount=deposit, status="paid", paid_at=now())]
                if stage == "completed":
                    d.invoice = Invoice(provider="manual", number="INV-1001", amount=d.value)
            d = crm.save_deal(d)
            crm.log(TENANT, ActivityKind.quote, f"הצעת מחיר {q.number} נוצרה", Actor.system,
                    deal_id=d.id, meta={"quote_id": q.id})
            if picked:
                crm.log(TENANT, ActivityKind.note,
                        ("הלקוח בחר מנות ב" if who == "customer" else "עודכנו מנות ב")
                        + f"{by_sku[pkg].name_he}: {describe(by_sku[pkg], choice, by_sku)}",
                        Actor.customer if who == "customer" else Actor.user, deal_id=d.id,
                        meta={"quote_id": q.id, "menu_choice": pkg})
        if stage != "new":
            crm.move_stage(TENANT, d.id, DealStage(stage), Actor.agent if src == "web_chat"
                           else Actor.user, "המחיר גבוה מהתקציב" if stage == "lost" else None)
        if stage in ("won", "completed"):  # booked some time ago, deposit paid that day
            d = crm.deals.get(TENANT, d.id)
            d.won_at = now() - timedelta(days=BOOKED_DAYS_AGO.get(name, 5))
            for p in d.payments:
                p.paid_at = d.won_at
            crm.save_deal(d)
        r = READY.get(name)
        if r:
            d = crm.deals.get(TENANT, d.id)
            d.service_style = STYLE.get(name)
            d.location = r["location"]
            if r["contact"]:
                d.site_contact_name, d.site_contact_phone = r["contact"]
            d.site = d.site.model_copy(update=r["site"])
            if r["final"]:
                d.final_guest_count = d.guest_count
            for m in r["marks"]:
                d.ready_marks[m] = now().isoformat(timespec="minutes")
            if r["paid"]:
                d.payments.append(Payment(amount=round(d.value - d.deposit_paid, 2),
                                          status="paid", paid_at=now()))
            q = repo.get(TENANT, d.quote_ids[0])
            if r["menu"]:
                for ln in q.tier().quote.lines:
                    if ln.sku in by_sku and by_sku[ln.sku].slots:
                        q.menu_choices[ln.sku] = {s.id: s.options[: s.choose]
                                                  for s in by_sku[ln.sku].slots}
                repo.save(q)
            crm.save_deal(d)
            if r.get("change"):
                request_change(crm, TENANT, d, "guests",
                               {"old": d.guest_count, "new": r["change"]},
                               f"מספר אורחים {d.guest_count} ← {r['change']}")
        elif name in STYLE:
            d = crm.deals.get(TENANT, d.id)
            d.service_style = STYLE[name]
            crm.save_deal(d)
        if src == "web_chat":
            if i == 0:
                script = CHAT
            elif ready:  # a handoff only ever follows a reason: here, a customer ready to book
                script = [("user", f"שלום, צריך הצעה ל-{guests} איש"),
                          ("assistant", "בשמחה! שלחתי הצעה עם שלוש חבילות לבחירה 🙂"),
                          ("user", "נראה מצוין, אנחנו רוצים לסגור. אפשר שמישהו יחזור אליי?"),
                          ("assistant", "מעולה! 🎉 העברתי לצוות, נציג יחזור אלייך היום כדי "
                                        "לסגור את כל הפרטים.")]
            else:
                script = [("user", f"שלום, צריך הצעה ל-{guests} איש"),
                          ("assistant", "בשמחה! באיזה תאריך מדובר?")]
            conv = Conversation(tenant_id=TENANT, customer_id=c.id, deal_id=d.id,
                                status=ConversationStatus.handed_off if ready
                                else ConversationStatus.active,
                                handoff_reason="הלקוח מוכן להזמין" if ready else None,
                                messages=[ChatMessage(role=ChatRole(r), text=t,
                                                      by="customer" if r == "user" else "ai")
                                          for r, t in script])
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


STAFF = [  # name, phone, roles, rate, days (0=Mon … 6=Sun; None = every day)
    ("יוסי אברג'ל", "050-7100001", ["head_waiter", "waiter"], 85, None),
    ("מירב לוי", "050-7100002", ["head_waiter"], 85, [6, 0, 1, 2, 3]),
    ("אורי בן חיים", "050-7100003", ["waiter"], 50, None),
    ("נועה פרידמן", "050-7100004", ["waiter"], 50, [6, 0, 1, 2, 3]),
    ("איתי שגיא", "050-7100005", ["waiter", "bartender"], 55, None),
    ("שחר מזרחי", "050-7100006", ["waiter"], 50, [3, 4, 5, 6]),
    ("רותם כץ", "050-7100007", ["waiter"], 50, None),
    ("עדי גולן", "050-7100008", ["waiter"], 48, [6, 0, 1, 2, 3, 4]),
    ("ליאור דהן", "050-7100009", ["waiter"], 50, None),
    ("תמר אלון", "050-7100010", ["waiter"], None, None),          # no rate yet
    ("בן עזרא", "050-7100011", ["bartender"], 60, [3, 4, 5]),
    ("שף אלי חדד", "050-7100012", ["chef"], 150, None),
    ("מאיה ששון", "050-7100013", ["waiter"], 50, None),
    ("דור נחום", "050-7100014", ["waiter"], 50, None),
]
STOCK = [("EQP-TABLE-ROUND", "שולחן עגול ל-10", 20), ("EQP-TABLE-RECT", "שולחן מלבני", 30),
         ("EQP-CHAIR", "כיסא אירועים", 200), ("EQP-CLOTH", "מפת שולחן בד", 60),
         ("EQP-HEATERS", "חימום שאפינג", 25), ("EQP-DISH-PREM", "סט כלי הגשה פרימיום", 150),
         ("TRAY", "מגש הגשה", 80), ("COOLER", "צידנית גדולה", 12), ("URN", "מיחם", 6)]
# what goes out per event (code, quantity, returned); "packed" marks it ready
EQUIPMENT = {
    "דנה שפירא": ([("EQP-HEATERS", 14, None), ("TRAY", 40, None), ("COOLER", 6, None)], False),
    "נטע אברהם": ([("EQP-HEATERS", 14, None), ("TRAY", 20, None), ("URN", 2, None)], False),
    "גיא שמש": ([("EQP-HEATERS", 8, 6), ("TRAY", 25, 25), ("EQP-CHAIR", 70, 65)], True),
}


def backfill() -> list[str]:
    """For a demo business seeded before a later stage: add only what that stage brought, once,
    and only when the demo customers are there (never touches a real business's data)."""
    from app.team.service import TeamService
    crm = CrmService()
    names = {c.name or c.company for c in crm.customers.list(TENANT)}
    if not {"דנה שפירא", "גיא שמש"} <= names:
        return []
    repo, catalog, done = JsonQuoteRepository(), load_catalog(), []
    if not TeamService().staff(TENANT):
        seed_team(crm, repo, catalog)
        done.append("team")
    new = [h for h in HISTORY if h[0] not in names]
    if new and not any(d.closing for d in crm.deals.list(TENANT)):
        _add_samples(crm, repo, catalog, new)
        seed_closings(crm, repo, catalog)
        done.append("closings")
    return done


def seed_team_if_missing() -> bool:
    return "team" in backfill()


def seed_closings(crm, repo, catalog) -> None:
    """A closing form for each past demo event (planned vs actual, and learning data)."""
    from app.business import closing
    from app.business.settings import SettingsService
    from app.team.service import TeamService
    rules = SettingsService().get(TENANT)
    team = TeamService()
    for d in crm.deals.list(TENANT):
        cust = crm.customers.get(TENANT, d.customer_id)
        plan = CLOSINGS.get((cust.name or cust.company) if cust else "")
        if not plan or d.closing:
            continue
        came, marks, spend, notes = plan
        dishes = closing.planned_dishes(crm, repo, catalog, rules, d)
        report = closing.report(d, closing._latest(repo, d), catalog, rules, dishes, team)
        food = next((g.planned for g in report.groups if g.group == "food"), None)
        body = EventClosing(
            actual_guests=came, notes=notes,
            purchasing_cost=round(food * spend) if food else None,
            dishes=[DishOutcome(sku=x.sku, leftover=marks.get(x.category, "ok"))
                    for x in dishes if x.category in rules.portion_rules])
        d.closing = closing.save(d, body, rules, dishes)
        d.closing.closed_at = datetime.combine(d.event_date + timedelta(days=1),
                                               datetime.min.time(), tzinfo=UTC)
        crm.save_deal(d)


def seed_team(crm, repo, catalog) -> None:
    """Staff, equipment stock, scheduling and equipment lists for the demo events."""
    from app.business.settings import SettingsService
    from app.team.models import EquipmentLine, EquipmentType, StaffMember
    from app.team.planning import auto_assign, save_event_list
    from app.team.service import TeamService
    team = TeamService()
    rules = SettingsService().get(TENANT)
    for name, phone, roles, rate, days in STAFF:
        team.members.put(StaffMember(tenant_id=TENANT, name=name, phone=phone, roles=roles,
                                     hourly_rate=rate,
                                     **({"available_days": days} if days else
                                        {"available_days": list(range(7))})))
    for code, name, owned in STOCK:
        team.put_type(TENANT, EquipmentType(code=code, name=name, owned=owned))
    names = {e.code: e.name for e in team.stock(TENANT)}
    for d in crm.deals.list(TENANT):
        cust = crm.customers.get(TENANT, d.customer_id)
        who = cust.name if cust else ""
        if who not in ("דנה שפירא", "עומר פרץ", "גיא שמש") or not d.quote_ids:
            continue
        q = repo.get(TENANT, d.quote_ids[-1])
        new = auto_assign(team, crm, d, q, catalog, rules)
        for i, a in enumerate(new):
            if who == "דנה שפירא":   # most confirmed, one still waiting, one cancelled
                a.status = "declined" if i == 1 else "invited" if i == 2 else "confirmed"
            else:
                a.status = "confirmed"
            if who == "גיא שמש":     # past event: actual hours entered
                a.actual_hours = a.planned_hours + (1 if i % 2 else 0.5)
            team.assignments.put(a)
        if who == "דנה שפירא" and len(new) > 1:
            m = team.members.get(TENANT, new[1].member_id)
            crm.add_task(TENANT, f"{m.name} ביטל/ה: לשבץ מלצר אחר", deal_id=d.id,
                         priority="high", created_by=Actor.system, kind="staff_declined")
    for d in crm.deals.list(TENANT):
        cust = crm.customers.get(TENANT, d.customer_id)
        plan = EQUIPMENT.get(cust.name if cust else "")
        if not plan:
            continue
        lines, packed = plan
        save_event_list(team, d, [EquipmentLine(code=c, name=names[c], quantity=n, returned=r)
                                  for c, n, r in lines],
                        packed=packed, returned=any(r is not None for _, _, r in lines) or None)



if __name__ == "__main__":
    main()

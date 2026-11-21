"""The Today screen (stage 4): it opens with what could go wrong this week, then one list of
leads and tasks.

"What could go wrong": for every booked event in the next `WATCH_DAYS` days, each red item of
its readiness checklist; supplier orders whose deadline is in that window (or already passed)
and that weren't marked as ordered; and customer change requests waiting for approval. Every
row carries the action that fixes it (a WhatsApp message to the customer or supplier, a link,
an approve button).

Leads and tasks: one row per deal (its open tasks merged in) plus tasks without a deal, sorted
by overdue first, then priority and value. A task that a "what could go wrong" row already
covers (final count, balance, a change request) is not repeated. A lead without a quote gets
the action "create a quote".
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from app.business import kpis
from app.business.messages import customer_messages
from app.business.production import production, purchase_list
from app.business.readiness import Action, readiness
from app.business.settings import BusinessSettings
from app.crm.models import Deal, DealStage
from app.crm.service import CrmService
from app.purchasing.service import PurchasingService
from app.team.planning import equipment_state, missing_returns, staff_plan

WATCH_DAYS = 7
COVERED_TASK_KINDS = {"final_count", "balance", "change_request", "menu", "staff_declined",
                      "closing"}
WEEKDAY_HE = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]


class WatchRow(BaseModel):
    kind: str                     # readiness | order | change
    key: str                      # readiness item key / supplier code / request id
    severity: str                 # high | normal
    deal_id: str | None = None
    title: str
    text: str
    when: date | None = None
    actions: list[Action] = Field(default_factory=list)
    meta: dict = Field(default_factory=dict)


class AgendaRow(BaseModel):
    deal_id: str | None
    title: str
    value: float | None = None
    stage: str | None = None
    temperature: str | None = None
    event_date: date | None = None
    tasks: list[dict] = Field(default_factory=list)  # {id, title, due_at, overdue, priority}
    overdue: bool = False
    priority: str = "normal"
    action: Action | None = None


class Reminder(BaseModel):
    at: datetime
    deal_id: str | None
    text: str
    rule: str


class TodayView(BaseModel):
    watch: list[WatchRow]
    agenda: list[AgendaRow]
    waiting_chats: list[dict]
    events_this_week: list[dict]
    reminders: list[Reminder]
    automation_last_run: str | None = None
    kpis: kpis.Kpis


def _when(d: datetime) -> str:
    return f"{WEEKDAY_HE[d.weekday()]} {d.day}.{d.month} {d:%H:%M}"


def today_view(crm: CrmService, repo, catalog, rules: BusinessSettings, ps: PurchasingService,
               tenant: str, today: date | None = None,
               now: datetime | None = None, team=None) -> TodayView:
    tz = ZoneInfo(rules.timezone)
    now = now or datetime.now(tz)
    today = today or now.date()
    deals = crm.deals.list(tenant)
    by_id = {d.id: d for d in deals}
    watch: list[WatchRow] = []

    # --- events this week: what's missing
    week = sorted([d for d in deals if d.stage == DealStage.won and d.event_date
                   and today <= d.event_date <= today + timedelta(days=WATCH_DAYS)],
                  key=lambda d: d.event_date)
    events = []
    for d in week:
        q = _latest(repo, d)
        cust = crm.customers.get(tenant, d.customer_id)
        msgs = customer_messages(d, q, cust, rules, today)
        extra = {}
        if team is not None:
            extra = {"staff": staff_plan(team, d, q, catalog, rules),
                     "equipment": equipment_state(team, crm, d, q, catalog, today)}
        r = readiness(d, q, catalog, rules, msgs, today, **extra)
        events.append({"id": d.id, "title": d.title, "event_date": d.event_date,
                       "guests": d.final_guest_count or d.guest_count, "done": r.done,
                       "total": r.total, "ready": r.ready})
        days = (d.event_date - today).days
        for it in r.items:
            if it.ok:
                continue
            watch.append(WatchRow(
                kind="readiness", key=it.key, deal_id=d.id, title=d.title, when=d.event_date,
                severity="high" if days <= 2 or it.key in ("final_count", "balance") and days <= 4
                else "normal",
                text=f"{it.label}: {it.detail}",
                actions=[a for a in [it.action, Action(kind="link", label="לאירוע",
                                                       url=f"/deals/{d.id}")] if a]))

    # --- supplier orders due this week (for events up to two weeks ahead)
    try:
        p = production(crm, repo, catalog, rules, tenant, today,
                       today + timedelta(days=WATCH_DAYS * 2))
        pl = purchase_list(p, catalog, ps.ingredients(tenant), ps.suppliers(tenant), rules,
                           today, today + timedelta(days=WATCH_DAYS * 2), now=now,
                           ordered=ps.ordered(tenant))
        horizon = now + timedelta(days=WATCH_DAYS)
        for o in pl.suppliers:
            for b in o.batches:
                if (o.code is None or b.ordered_at or b.order_by is None or b.order_by > horizon
                        or b.deliver_on < today):  # a delivery day that passed can't be fixed
                    continue
                acts = [Action(kind="mark", label="סימון כהוזמן", target="order")]
                if b.whatsapp_url:
                    acts.insert(0, Action(kind="whatsapp", label="הזמנה בוואטסאפ",
                                          url=b.whatsapp_url))
                watch.append(WatchRow(
                    kind="order", key=o.code, severity="high" if b.late or
                    b.order_by - now < timedelta(hours=24) else "normal",
                    title=o.name, when=b.deliver_on,
                    text=(f"{'עבר המועד להזמנה' if b.late else 'להזמין עד'} "
                          f"{_when(b.order_by)} · {len(b.items)} פריטים לאספקה "
                          f"{WEEKDAY_HE[b.deliver_on.weekday()]} {b.deliver_on.day}."
                          f"{b.deliver_on.month}"),
                    actions=acts + [Action(kind="link", label="לרשימת הרכש",
                                           url="/purchasing")],
                    meta={"supplier": o.code, "deliver_on": b.deliver_on.isoformat()}))
    except Exception:  # noqa: BLE001 — Today must open even if purchasing data is broken
        pass

    # --- equipment that didn't come back, and staff who cancelled
    if team is not None:
        for m in missing_returns(team, crm, tenant, today):
            what = ", ".join(f"{i['name']} ({i['missing']})" for i in m["items"][:4])
            watch.append(WatchRow(
                kind="equipment", key=m["deal_id"], deal_id=m["deal_id"], title=m["title"],
                severity="normal", when=m["event_date"],
                text=("ציוד שלא חזר: " + what) if m["counted"] else
                "הציוד עוד לא נספר אחרי האירוע",
                actions=[Action(kind="link", label="לספירת הציוד",
                                url=f"/deals/{m['deal_id']}#equipment")]))

    # --- events that happened and weren't summed up yet (planned vs actual needs the form)
    for d in deals:
        if (d.stage in (DealStage.won, DealStage.completed) and d.event_date and d.closing is None
                and today - timedelta(days=rules.closing_window_days) <= d.event_date < today):
            watch.append(WatchRow(
                kind="closing", key="closing", deal_id=d.id, title=d.title, severity="normal",
                when=d.event_date,
                text="סיכום אירוע: כמה הגיעו, מה נשאר, כמה עלה בפועל (שתי דקות)",
                actions=[Action(kind="link", label="למילוי הסיכום",
                                url=f"/deals/{d.id}#closing")]))

    # --- customer change requests waiting
    for d in deals:
        for r in d.change_requests:
            if r.status == "pending":
                watch.append(WatchRow(
                    kind="change", key=r.id, deal_id=d.id, title=d.title, severity="high",
                    when=d.event_date, text=f"הלקוח ביקש אחרי הנעילה: {r.summary}",
                    actions=[Action(kind="approve", label="אישור", target=r.id),
                             Action(kind="link", label="לאירוע", url=f"/deals/{d.id}")]))

    watch.sort(key=lambda w: (w.severity != "high", w.when or date.max, w.title))

    # --- leads and tasks, merged
    covered = {(w.deal_id, w.key) for w in watch if w.kind != "order"}
    covered_deals = {w.deal_id for w in watch if w.kind in ("readiness", "change")}
    rows: dict[str | None, AgendaRow] = {}
    loose: list[AgendaRow] = []
    for t in crm.tasks.list(tenant, lambda t: not t.done):
        if t.kind in COVERED_TASK_KINDS and t.deal_id in covered_deals:
            continue
        if t.deal_id and (t.deal_id, t.kind) in covered:
            continue
        overdue = bool(t.due_at and t.due_at < now)
        item = {"id": t.id, "title": t.title, "due_at": t.due_at, "overdue": overdue,
                "priority": t.priority}
        d = by_id.get(t.deal_id) if t.deal_id else None
        if d is None:
            loose.append(AgendaRow(deal_id=None, title=t.title, tasks=[item], overdue=overdue,
                                   priority=t.priority))
            continue
        row = rows.setdefault(d.id, _deal_row(d))
        row.tasks.append(item)
        row.overdue |= overdue
        if t.priority == "high":
            row.priority = "high"
    for d in deals:
        if d.id in rows or d.stage not in (DealStage.new, DealStage.quoted):
            continue
        if d.temperature.value == "hot" or (d.stage == DealStage.new and not d.quote_ids):
            rows[d.id] = _deal_row(d)
    agenda = list(rows.values()) + loose
    for r in agenda:
        d = by_id.get(r.deal_id) if r.deal_id else None
        if d and not d.quote_ids and d.stage in (DealStage.new, DealStage.quoted):
            r.action = Action(kind="quote", label="לשלוח הצעה", target=d.id)
        r.tasks.sort(key=lambda x: (not x["overdue"], x["due_at"] or datetime.max.replace(
            tzinfo=tz)))
    agenda.sort(key=lambda r: (not r.overdue, r.priority != "high",
                               -(r.value or 0), r.event_date or date.max))

    # --- what the automation did lately
    since = now - timedelta(days=7)
    reminders = [Reminder(at=a.at, deal_id=a.deal_id, text=a.text,
                          rule=(a.meta or {}).get("automation", ""))
                 for a in crm.activities.list(tenant, lambda a: bool((a.meta or {}).get(
                     "automation")) and a.at >= since)]
    reminders.sort(key=lambda r: r.at, reverse=True)

    convs = crm.conversations.list(tenant, lambda c: c.status in ("handed_off", "human"))
    waiting = sorted(convs, key=lambda c: (not c.escalated, c.updated_at))
    return TodayView(
        watch=watch, agenda=agenda[:40],
        waiting_chats=[{"id": c.id, "deal_id": c.deal_id, "escalated": c.escalated,
                        "status": c.status.value, "reason": c.handoff_reason,
                        "last": next((m.text for m in reversed(c.messages)
                                      if m.role == "user"), ""), "updated_at": c.updated_at}
                       for c in waiting],
        events_this_week=events, reminders=reminders[:20],
        automation_last_run=crm.settings.get(tenant).automation_last_run,
        kpis=kpis.compute(crm, tenant, rules, today))


def _deal_row(d: Deal) -> AgendaRow:
    return AgendaRow(deal_id=d.id, title=d.title, value=d.value, stage=d.stage.value,
                     temperature=d.temperature.value, event_date=d.event_date)


def _latest(repo, deal: Deal):
    for qid in reversed(deal.quote_ids):
        q = repo.get(deal.tenant_id, qid)
        if q:
            return q
    return None

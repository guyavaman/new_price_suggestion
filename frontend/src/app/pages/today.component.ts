import { Component, computed, inject, signal } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { ApiService } from '../core/api.service';
import { HeDatePipe, IlsPipe, RelativePipe } from '../core/format';
import { TEMP } from '../core/labels';
import { TodayView, UiAction, WatchRow } from '../core/models';

interface EventGroup { deal_id: string; title: string; when: string | null; rows: WatchRow[]; done: number; total: number; high: boolean }

@Component({
  selector: 'app-today',
  standalone: true,
  imports: [RouterLink, IlsPipe, HeDatePipe, RelativePipe],
  template: `
    <div class="page-head">
      <div><h1>{{ greeting }}</h1><p>מה עלול להשתבש השבוע, ומה מחכה לך</p></div>
      <div class="row">
        <a class="btn" routerLink="/inbox">+ פנייה חדשה</a>
      </div>
    </div>
    @if (msg()) { <p class="note" [class.bad]="msgBad()" role="status">{{ msg() }}</p> }
    @if (error()) { <div class="err">{{ error() }}</div> }
    @if (v(); as v) {
      <section class="watch" aria-labelledby="w-h">
        <div class="sec-h">
          <h2 id="w-h">מה עלול להשתבש השבוע</h2>
          <small class="muted">{{ v.watch.length ? v.watch.length + ' דברים לטפל בהם' : '' }}</small>
        </div>

        @for (g of groups(); track g.deal_id) {
          <article class="card evt" [class.hot]="g.high" [attr.aria-label]="g.title">
            <header>
              <a [routerLink]="['/deals', g.deal_id]"><b>{{ g.title }}</b></a>
              @if (g.total) {
                <span class="meter" [attr.aria-label]="g.done + ' מתוך ' + g.total + ' מוכנים'"><i [style.width.%]="g.done / g.total * 100"></i></span>
                <small class="muted num">{{ g.done }}/{{ g.total }} מוכן</small>
              }
              @if (g.when) { <small class="muted">· {{ g.when | rel }}</small> }
            </header>
            <ul>
              @for (r of g.rows; track r.kind + r.key) {
                <li [class.high]="r.severity === 'high'">
                  <span class="dot" aria-hidden="true"></span>
                  <span class="txt">{{ r.text }}</span>
                  <span class="acts">
                    @for (a of mainActions(r); track a.label) {
                      @switch (a.kind) {
                        @case ('whatsapp') { <a class="btn sm" [href]="a.url" target="_blank" rel="noopener" (click)="sent(r)">{{ a.label }}</a> }
                        @case ('link') { <a class="btn ghost sm" [routerLink]="a.url">{{ a.label }}</a> }
                        @case ('edit') { <a class="btn ghost sm" [routerLink]="['/deals', r.deal_id]" fragment="readiness">{{ a.label }}</a> }
                        @case ('mark') { <button class="btn ghost sm" type="button" [disabled]="busy()" (click)="mark(r)">{{ a.label }}</button> }
                        @case ('approve') {
                          <button class="btn sm" type="button" [disabled]="busy()" (click)="decide(r, 'approve')">אישור</button>
                          <button class="btn ghost sm" type="button" [disabled]="busy()" (click)="decide(r, 'decline')">דחייה</button>
                        }
                      }
                    }
                  </span>
                </li>
              }
            </ul>
          </article>
        }

        @if (orders().length) {
          <article class="card evt orders" aria-label="הזמנות מספקים">
            <header><b>הזמנות מספקים</b><a class="more" routerLink="/purchasing">לרשימת הרכש ←</a></header>
            <ul>
              @for (r of shownOrders(); track r.key + r.meta['deliver_on']) {
                <li [class.high]="r.severity === 'high'">
                  <span class="dot" aria-hidden="true"></span>
                  <span class="txt"><b>{{ r.title }}</b> · {{ r.text }}</span>
                  <span class="acts">
                    @for (a of r.actions; track a.label) {
                      @if (a.kind === 'whatsapp') { <a class="btn sm" [href]="a.url" target="_blank" rel="noopener">{{ a.label }}</a> }
                      @if (a.kind === 'mark') { <button class="btn ghost sm" type="button" [disabled]="busy()" (click)="markOrder(r)">{{ a.label }}</button> }
                    }
                  </span>
                </li>
              }
            </ul>
            @if (orders().length > 5) {
              <button class="linkish" type="button" (click)="allOrders.set(!allOrders())">{{ allOrders() ? 'פחות' : 'עוד ' + (orders().length - 5) + ' הזמנות' }}</button>
            }
          </article>
        }

        @for (e of readyEvents(); track e.id) {
          <a class="card evt ok" [routerLink]="['/deals', e.id]"><b>{{ e.title }}</b> <span class="okc">✓ מוכן ({{ e.done }}/{{ e.total }})</span></a>
        }
        @if (!v.watch.length && !readyEvents().length) { <p class="card calm">אין אירועים השבוע ואין הזמנות שמחכות. שבוע רגוע.</p> }
      </section>

      <section class="card agenda" aria-labelledby="a-h">
        <div class="sec-h"><h2 id="a-h">לידים ומשימות</h2><small class="muted">לפי איחור, דחיפות ושווי</small></div>
        @for (r of v.agenda; track $index) {
          <div class="arow" [class.late]="r.overdue">
            <div class="ahead">
              @if (r.deal_id) { <a [routerLink]="['/deals', r.deal_id]"><b>{{ r.title }}</b></a> } @else { <b>{{ r.title }}</b> }
              @if (r.temperature && r.stage !== 'won') { <span class="temp temp-{{ r.temperature }}">{{ temp[r.temperature] }}</span> }
              @if (r.overdue) { <span class="late-tag">באיחור</span> }
              @if (r.value) { <span class="num muted">{{ r.value | ils }}</span> }
              @if (r.action?.kind === 'quote') { <button class="btn sm" type="button" [disabled]="busy()" (click)="makeQuote(r.deal_id!)">{{ r.action!.label }}</button> }
            </div>
            @if (r.deal_id ? r.tasks.length : false) {
              <ul class="tasks">
                @for (t of r.tasks; track t.id) {
                  <li [class.late]="t.overdue"><label><input type="checkbox" (change)="done(t.id)" [attr.aria-label]="'בוצע: ' + t.title"> {{ t.title }}</label>
                    @if (t.due_at) { <small class="muted">{{ t.due_at | rel }}</small> }</li>
                }
              </ul>
            } @else if (!r.deal_id) {
              <ul class="tasks"><li [class.late]="r.overdue"><label><input type="checkbox" (change)="done(r.tasks[0].id)" [attr.aria-label]="'בוצע: ' + r.title"> סמן כבוצע</label>
                @if (r.tasks[0].due_at) { <small class="muted">{{ r.tasks[0].due_at | rel }}</small> }</li></ul>
            }
          </div>
        } @empty { <p class="muted">אין לידים או משימות פתוחים 🎉</p> }
      </section>

      @if (v.waiting_chats.length) {
        <section class="card">
          <h2>לקוחות שמחכים לך בצ'אט</h2>
          @for (c of v.waiting_chats; track c.id) {
            <a class="item" [class.urgent]="c.escalated" [routerLink]="['/inbox']" [queryParams]="{ id: c.id }">
              <span>@if (c.escalated) { <b class="temp temp-hot">🔥 מתוסכל</b> } {{ c.last }}</span>
              <small class="muted">{{ c.reason }} · {{ c.updated_at | rel }}</small>
            </a>
          }
        </section>
      }

      <section class="card auto" aria-labelledby="r-h">
        <div class="sec-h">
          <h2 id="r-h">תזכורות אוטומטיות</h2>
          <button class="btn ghost sm" (click)="automate()" [disabled]="running()">{{ running() ? 'בודק…' : 'הרץ תזכורות עכשיו' }}</button>
        </div>
        <p class="muted small">רצות לבד כל יום (בקשת כמות סופית, תזכורת יתרה, מעקב על הצעות). ההודעה מוכנה, והשליחה בוואטסאפ היא בקליק מהשורה למעלה.
          @if (v.automation_last_run) { הרצה אחרונה: {{ v.automation_last_run | heDate }}. }</p>
        @for (r of v.reminders; track $index) {
          <div class="rem"><small class="muted">{{ r.at | rel }}</small> @if (r.deal_id) { <a [routerLink]="['/deals', r.deal_id]">{{ r.text }}</a> } @else { {{ r.text }} }</div>
        } @empty { <p class="muted small">לא נוצרו תזכורות בשבוע האחרון.</p> }
      </section>

      <div class="money">
        <div class="card"><span>מקדמות שנכנסו החודש</span><b class="num" data-kpi="deposits_this_month">{{ v.kpis.deposits_this_month | ils }}</b></div>
        <div class="card"><span>נסגר החודש</span><b class="num" data-kpi="booked_this_month_value">{{ v.kpis.booked_this_month_value | ils }}</b><small class="muted">{{ v.kpis.booked_this_month_count }} אירועים · לפני מע"מ</small></div>
        <a class="card" routerLink="/events"><span>הצעות שמחכות לתשובה</span><b class="num">{{ v.kpis.quotes_waiting }}</b><small class="muted num" data-kpi="quotes_waiting_value">{{ v.kpis.quotes_waiting_value | ils }} לפני מע"מ</small></a>
      </div>
    }
  `,
  styles: [`
    .row { display: flex; gap: 8px; flex-wrap: wrap; }
    .note { background: var(--ok-soft); color: var(--ok); border-radius: 8px; padding: 8px 12px; } .note.bad { background: var(--bad-soft); color: var(--bad); }
    .sec-h { display: flex; justify-content: space-between; align-items: baseline; gap: 10px; flex-wrap: wrap; margin-bottom: 8px; }
    .sec-h h2 { margin: 0; }
    .watch { display: grid; gap: 10px; margin-bottom: 16px; }
    .watch > .sec-h h2 { font-size: 1.35rem; }
    .evt { padding: 12px 14px; display: grid; gap: 8px; border-inline-start: 5px solid var(--warn); }
    .evt.hot { border-inline-start-color: var(--bad); }
    .evt.orders { border-inline-start-color: var(--olive); }
    .evt.ok { border-inline-start-color: var(--ok); display: flex; gap: 10px; align-items: center; text-decoration: none; color: inherit; padding: 9px 14px; }
    .okc { color: var(--ok); font-weight: 700; }
    .evt header { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
    .evt header a { color: inherit; } .more { margin-inline-start: auto; font-size: .88rem; }
    .meter { width: 90px; height: 7px; background: var(--paper); border-radius: 99px; overflow: hidden; display: inline-block; }
    .meter i { display: block; height: 100%; background: var(--ok); }
    .evt ul { list-style: none; margin: 0; padding: 0; display: grid; gap: 6px; }
    .evt li { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
    .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--warn); flex: none; }
    li.high .dot { background: var(--bad); }
    .txt { flex: 1 1 260px; }
    .acts { display: flex; gap: 6px; flex-wrap: wrap; }
    .btn.sm { padding: 4px 10px; font-size: .84rem; text-decoration: none; }
    .calm { color: var(--ok); }
    .linkish { background: none; border: 0; padding: 0; color: var(--olive); text-decoration: underline; font: inherit; font-weight: 600; cursor: pointer; justify-self: start; }
    .agenda { margin-bottom: 14px; }
    .arow { padding: 9px 0; border-top: 1px solid var(--line); }
    .arow.late .ahead b { color: var(--bad); }
    .ahead { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
    .ahead a { color: inherit; }
    .late-tag { background: var(--bad-soft); color: var(--bad); font-weight: 700; font-size: .75rem; border-radius: 6px; padding: 1px 7px; }
    .tasks { list-style: none; margin: 4px 0 0; padding: 0 18px 0 0; display: grid; gap: 3px; font-size: .92rem; }
    .tasks li { display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; } .tasks li.late label { color: var(--bad); }
    .tasks label { display: flex; gap: 6px; align-items: center; }
    .item { display: grid; gap: 2px; padding: 9px 10px; border-radius: 8px; border: 1px solid var(--line); margin-bottom: 6px; text-decoration: none; color: inherit; }
    .item.urgent { border-color: var(--bad); background: var(--bad-soft); }
    .auto { margin: 14px 0; } .small { font-size: .84rem; } .rem { padding: 4px 0; border-top: 1px solid var(--line); font-size: .9rem; }
    .money { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
    @media (max-width: 700px) { .money { grid-template-columns: 1fr; } }
    .money .card { display: grid; text-decoration: none; color: inherit; }
    .money span { color: var(--muted); font-size: .85rem; }
    .money b { font-family: var(--display); font-size: 1.5rem; color: var(--olive); }
  `],
})
export class TodayComponent {
  private api = inject(ApiService);
  private router = inject(Router);
  v = signal<TodayView | null>(null);
  error = signal(''); msg = signal(''); msgBad = signal(false);
  running = signal(false); busy = signal(false);
  temp = TEMP;
  greeting = new Date().getHours() < 12 ? 'בוקר טוב ☀️' : new Date().getHours() < 18 ? 'צהריים טובים' : 'ערב טוב';

  groups = computed<EventGroup[]>(() => {
    const v = this.v();
    if (!v) return [];
    const out = new Map<string, EventGroup>();
    for (const r of v.watch) {
      if (r.kind === 'order' || !r.deal_id) continue;
      const ev = v.events_this_week.find((e) => e.id === r.deal_id);
      const g = out.get(r.deal_id) ?? { deal_id: r.deal_id, title: r.title, when: r.when, rows: [], done: ev?.done ?? 0, total: ev?.total ?? 0, high: false };
      g.rows.push(r); g.high ||= r.severity === 'high';
      out.set(r.deal_id, g);
    }
    return [...out.values()].sort((a, b) => (a.when ?? '9').localeCompare(b.when ?? '9'));
  });
  orders = computed(() => (this.v()?.watch ?? []).filter((r) => r.kind === 'order'));
  allOrders = signal(false);
  shownOrders = computed(() => this.allOrders() ? this.orders() : this.orders().slice(0, 5));
  readyEvents = computed(() => (this.v()?.events_this_week ?? []).filter((e) => e.ready));

  constructor() { this.load(); }
  load() { this.api.today().subscribe({ next: (v) => this.v.set(v), error: () => this.error.set('השרת לא זמין כרגע. נסו לרענן בעוד רגע.') }); }
  flash(m: string, bad = false) { this.msg.set(m); this.msgBad.set(bad); setTimeout(() => this.msg.set(''), 3500); }
  mainActions(r: WatchRow): UiAction[] { return r.actions.filter((a) => !(a.kind === 'link' && a.label === 'לאירוע')); }
  done(id: string) { this.api.doneTask(id).subscribe(() => this.load()); }
  sent(r: WatchRow) { this.flash('ההודעה נפתחה בוואטסאפ'); void r; }

  mark(r: WatchRow) {
    if (!r.deal_id) return;
    this.busy.set(true);
    this.api.patchReadiness(r.deal_id, { marks: { [r.key]: true } }).subscribe({
      next: () => { this.busy.set(false); this.flash('סומן כבוצע'); this.load(); },
      error: () => { this.busy.set(false); this.flash('הסימון נכשל', true); },
    });
  }
  markOrder(r: WatchRow) {
    this.busy.set(true);
    this.api.markOrder(r.meta['supplier'], r.meta['deliver_on']).subscribe({
      next: () => { this.busy.set(false); this.flash(`ההזמנה מ${r.title} סומנה כהוזמנה`); this.load(); },
      error: () => { this.busy.set(false); this.flash('הסימון נכשל', true); },
    });
  }
  decide(r: WatchRow, d: 'approve' | 'decline') {
    if (!r.deal_id) return;
    this.busy.set(true);
    this.api.decideChange(r.deal_id, r.key, d).subscribe({
      next: () => { this.busy.set(false); this.flash(d === 'approve' ? 'הבקשה אושרה והמחיר עודכן' : 'הבקשה נדחתה'); this.load(); },
      error: (e) => { this.busy.set(false); this.flash(e.error?.detail ?? 'הפעולה נכשלה', true); },
    });
  }
  makeQuote(dealId: string) {
    this.busy.set(true);
    this.api.quoteFromDeal(dealId).subscribe({
      next: (q) => { this.busy.set(false); this.router.navigate(['/quotes', q.quote_id]); },
      error: (e) => { this.busy.set(false); this.flash(e.error?.detail ?? 'לא ניתן לבנות הצעה', true); },
    });
  }
  automate() {
    this.running.set(true);
    this.api.runAutomation().subscribe({
      next: (a) => { this.running.set(false); this.flash(a.length ? `נוצרו ${a.length} תזכורות` : 'הכל מעודכן, אין תזכורות חדשות'); this.load(); },
      error: () => this.running.set(false),
    });
  }
}

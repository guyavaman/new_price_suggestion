import { Component, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { ApiService } from '../core/api.service';
import { HeDatePipe, IlsPipe, RelativePipe } from '../core/format';
import { TEMP } from '../core/labels';
import { TodayView } from '../core/models';

@Component({
  selector: 'app-today',
  standalone: true,
  imports: [RouterLink, IlsPipe, HeDatePipe, RelativePipe],
  template: `
    <div class="page-head">
      <div><h1>{{ greeting }}</h1><p>מה צריך ממך היום</p></div>
      <div class="row">
        <button class="btn ghost" (click)="automate()" [disabled]="running()">{{ running() ? 'בודק…' : 'הרץ תזכורות עכשיו' }}</button>
        <a class="btn" routerLink="/inbox">+ פנייה חדשה</a>
      </div>
    </div>
    @if (autoMsg()) { <p class="note">{{ autoMsg() }}</p> }
    @if (error()) { <div class="err">{{ error() }}</div> }
    @if (v(); as v) {
      <div class="money">
        <div class="card"><span>מקדמות שנכנסו החודש</span><b class="num">{{ v.deposits_this_month | ils }}</b></div>
        <div class="card"><span>נסגר החודש</span><b class="num">{{ v.won_this_month | ils }}</b></div>
        <a class="card" routerLink="/events"><span>הצעות שמחכות לתשובה</span><b class="num">{{ v.quotes_waiting }}</b><small class="muted num">{{ v.open_quotes_value | ils }}</small></a>
      </div>

      <div class="cols">
        <section class="card">
          <h2>לקוחות שמחכים לך</h2>
          @for (c of v.waiting_chats; track c.id) {
            <a class="item" [class.urgent]="c.escalated" [routerLink]="['/inbox']" [queryParams]="{ id: c.id }">
              <span>@if (c.escalated) { <b class="temp temp-hot">🔥 מתוסכל</b> } {{ c.last }}</span>
              <small class="muted">{{ c.reason }} · {{ c.updated_at | rel }}</small>
            </a>
          } @empty { <p class="muted">אף אחד לא מחכה. הסוכנת מטפלת בכל השיחות.</p> }

          <h2 class="mt">משימות להיום</h2>
          @for (t of v.tasks_due; track t.id) {
            <div class="item task" [class.urgent]="t.priority === 'high'">
              <label><input type="checkbox" (change)="done(t.id)" [attr.aria-label]="t.title"> {{ t.title }}</label>
              <small class="muted">@if (t.deal_id) { <a [routerLink]="['/deals', t.deal_id]">{{ t.deal_title }}</a> · } {{ t.due_at | rel }}</small>
            </div>
          } @empty { <p class="muted">אין משימות להיום 🎉</p> }
        </section>

        <section class="card">
          <h2>אירועים השבוע</h2>
          @for (e of v.events_this_week; track e.id) {
            <a class="item" [routerLink]="['/deals', e.id]">
              <span><b>{{ e.title }}</b></span>
              <small class="muted">{{ e.event_date | heDate }} · {{ e.event_date | rel }} · {{ e.guests }} אורחים
                · מקדמה {{ e.deposit_paid | ils }}
                @if (!e.final_count_confirmed) { · <span class="warnc">מספר אורחים לא אושר</span> }</small>
            </a>
          } @empty { <p class="muted">אין אירועים השבוע</p> }
          <a routerLink="/kitchen" class="more">לדף המטבח ←</a>

          <h2 class="mt">לידים חמים להתקשר אליהם</h2>
          @for (l of v.hot_leads; track l.id) {
            <a class="item" [routerLink]="['/deals', l.id]">
              <span><span class="temp temp-{{ l.temperature }}">{{ temp[l.temperature] }}</span> {{ l.title }}</span>
              <small class="muted num">{{ l.value | ils }}</small>
            </a>
          } @empty { <p class="muted">אין לידים חמים פתוחים</p> }
        </section>
      </div>
    }
  `,
  styles: [`
    .row { display: flex; gap: 8px; flex-wrap: wrap; }
    .note { background: var(--olive-soft); border-radius: 8px; padding: 8px 12px; }
    .money { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 14px; }
    @media (max-width: 700px) { .money { grid-template-columns: 1fr; } }
    .money .card { display: grid; text-decoration: none; color: inherit; }
    .money span { color: var(--muted); font-size: .85rem; }
    .money b { font-family: var(--display); font-size: 1.6rem; color: var(--olive); }
    .cols { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; align-items: start; }
    @media (max-width: 900px) { .cols { grid-template-columns: 1fr; } }
    h2 { margin-bottom: 8px; } .mt { margin-top: 18px; }
    .item { display: grid; gap: 2px; padding: 9px 10px; border-radius: 8px; border: 1px solid var(--line); margin-bottom: 6px; text-decoration: none; color: inherit; }
    a.item:hover { border-color: var(--olive); }
    .item.urgent { border-color: var(--bad); background: var(--bad-soft); }
    .task label { display: flex; gap: 8px; align-items: center; }
    .warnc { color: var(--warn); font-weight: 700; }
    .more { font-size: .9rem; }
  `],
})
export class TodayComponent {
  private api = inject(ApiService);
  v = signal<TodayView | null>(null);
  error = signal('');
  running = signal(false);
  autoMsg = signal('');
  temp = TEMP;
  greeting = new Date().getHours() < 12 ? 'בוקר טוב ☀️' : new Date().getHours() < 18 ? 'צהריים טובים' : 'ערב טוב';

  constructor() { this.load(); }
  load() { this.api.today().subscribe({ next: (v) => this.v.set(v), error: () => this.error.set('השרת לא זמין. הפעילו את ה-backend על פורט 8000.') }); }
  done(id: string) { this.api.doneTask(id).subscribe(() => this.load()); }
  automate() {
    this.running.set(true);
    this.api.runAutomation().subscribe({
      next: (a) => { this.running.set(false); this.autoMsg.set(a.length ? `נוצרו ${a.length} תזכורות: ${a.map((x) => x.title).join(' · ')}` : 'הכל מעודכן, אין תזכורות חדשות'); this.load(); },
      error: () => this.running.set(false),
    });
  }
}

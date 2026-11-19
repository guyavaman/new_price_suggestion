import { Component, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { ApiService } from '../core/api.service';
import { HeDatePipe, IlsPipe, RelativePipe } from '../core/format';
import { EVENT_TYPE, SOURCE, STAGE_LABEL } from '../core/labels';
import { Dashboard, ProfitReport } from '../core/models';

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [RouterLink, IlsPipe, HeDatePipe, RelativePipe],
  template: `
    <div class="page-head">
      <div><h1>דשבורד מכירות</h1><p>מה קורה ב-pipeline ומה דורש תשומת לב היום</p></div>
      <a class="btn" routerLink="/pipeline">ל-Pipeline</a>
    </div>
    @if (error()) { <div class="err">{{ error() }}</div> }
    @if (d(); as d) {
      <div class="alerts">
        @if (d.kpis.escalated_chats) { <a routerLink="/conversations" class="alert bad">🔥 {{ d.kpis.escalated_chats }} לקוחות מתוסכלים מחכים למענה</a> }
        @if (d.kpis.handed_off_chats) { <a routerLink="/conversations" class="alert bad">{{ d.kpis.handed_off_chats }} שיחות מהסוכן ממתינות לנציג</a> }
        @if (d.kpis.overdue_tasks) { <a routerLink="/tasks" class="alert warn">{{ d.kpis.overdue_tasks }} משימות באיחור</a> }
        @if (d.kpis.hot_leads) { <a routerLink="/pipeline" class="alert hot">{{ d.kpis.hot_leads }} לידים חמים (ציון 70+)</a> }
      </div>
      <div class="kpis">
        <div class="card kpi"><span>Pipeline פתוח</span><b class="num">{{ d.kpis.open_pipeline_value | ils }}</b></div>
        <div class="card kpi"><span>נסגר החודש</span><b class="num" data-kpi="booked_this_month_value">{{ d.kpis.booked_this_month_value | ils }}</b><small>{{ d.kpis.booked_this_month_count }} אירועים · לפני מע"מ</small></div>
        <div class="card kpi"><span>אחוז סגירה</span><b class="num">{{ pct(d.kpis.win_rate) }}</b><small>מתוך עסקאות שהסתיימו</small></div>
        <div class="card kpi"><span>עסקה ממוצעת</span><b class="num">{{ d.kpis.avg_booked_value | ils }}</b></div>
        <div class="card kpi"><span>המרת צ'אט לליד</span><b class="num">{{ pct(d.kpis.chat_conversion) }}</b><small>שיחות סוכן AI</small></div>
      </div>
      <div class="cols">
        <section class="card">
          <h2>לפי שלב</h2>
          <div class="funnel">
            @for (s of d.kpis.stages; track s.stage) {
              <a class="row stage-{{ s.stage }}" routerLink="/pipeline">
                <span class="lbl">{{ stageLabel[s.stage] }}</span>
                <span class="bar"><i [style.width.%]="(s.count / maxCount()) * 100"></i></span>
                <span class="num cnt">{{ s.count }}</span>
                <span class="num val muted">{{ s.value | ils }}</span>
              </a>
            }
          </div>
        </section>
        <section class="card">
          <h2>אירועים ב-30 הימים הקרובים</h2>
          @if (d.upcoming_events.length) {
            <table>
              <tbody>
                @for (e of d.upcoming_events; track e.id) {
                  <tr class="link" [routerLink]="['/deals', e.id]">
                    <td><b>{{ e.title }}</b><div class="muted">{{ e.event_date | rel }}</div></td>
                    <td><span class="pill stage-{{ e.stage }}" [style.background]="'color-mix(in srgb, var(--st) 15%, white)'" [style.color]="'var(--st)'">{{ stageLabel[e.stage] }}</span></td>
                    <td class="num">{{ e.event_date | heDate }}</td>
                  </tr>
                }
              </tbody>
            </table>
          } @else { <p class="empty">אין אירועים מתוכננים</p> }
        </section>
        <section class="card">
          <h2>מקורות לידים</h2>
          <div class="funnel">
            @for (s of sources(); track s.key) {
              <div class="row"><span class="lbl">{{ sourceLabel[s.key] || s.key }}</span>
                <span class="bar src"><i [style.width.%]="(s.n / maxSource()) * 100"></i></span><span class="num cnt">{{ s.n }}</span></div>
            }
          </div>
        </section>
      </div>
    }
    @if (pr(); as pr) {
      <section class="card profit-rep" aria-labelledby="pr-h">
        <div class="pr-head">
          <h2 id="pr-h">רווחיות (אירועים שנסגרו)</h2>
          <small class="muted">לפני מע"מ · רווח גולמי = הכנסה אחרי הנחה פחות עלויות ישירות · רצפה {{ pct(pr.floor) }}</small>
        </div>
        <div class="pr-tabs" role="tablist">
          @for (t of prTabs; track t.key) {
            <button role="tab" [attr.aria-selected]="prTab() === t.key" [class.on]="prTab() === t.key" (click)="prTab.set(t.key)">{{ t.label }}</button>
          }
        </div>
        @if (prTab() !== 'events') {
          <table class="pr-table">
            <thead><tr><th></th><th>אירועים</th><th>הכנסה</th><th>רווח גולמי</th><th>רווחיות</th></tr></thead>
            <tbody>
              @for (r of prRows(); track r.key) {
                <tr>
                  <td>{{ prTab() === 'by_month' ? month(r.key) : r.label }}</td><td class="num">{{ r.events }}</td><td class="num">{{ r.revenue | ils }}</td>
                  <td class="num">@if (r.profit !== null) { {{ r.profit | ils }} } @else { — }</td>
                  <td><div class="mcell"><span class="num" [class.low]="r.margin !== null && r.margin < pr.floor">{{ pct(r.margin) }}</span>
                    @if (r.missing_cost) { <span class="miss-tag" title="אירועים בלי עלות מלאה לא נכללים ברווח">{{ r.missing_cost }} בלי עלות</span> }</div></td>
                </tr>
              } @empty { <tr><td colspan="5" class="empty">אין עדיין אירועים סגורים בתקופה</td></tr> }
            </tbody>
          </table>
        } @else {
          <table class="pr-table">
            <thead><tr><th>אירוע</th><th>תאריך</th><th>הכנסה</th><th>עלות</th><th>רווח</th></tr></thead>
            <tbody>
              @for (e of pr.events; track e.deal_id) {
                <tr>
                  <td><a [routerLink]="['/deals', e.deal_id]">{{ e.title }}</a></td>
                  <td>{{ e.event_date ? (e.event_date | heDate) : '—' }}</td>
                  <td class="num">{{ e.revenue | ils }}</td>
                  <td class="num">@if (e.cost !== null) { {{ e.cost | ils }} } @else { <span class="miss-tag" [title]="e.missing.join(', ')">עלות חסרה</span> }</td>
                  <td class="num">@if (e.profit !== null) { <span [class.low]="e.margin! < pr.floor">{{ e.profit | ils }} · {{ pct(e.margin) }}</span> } @else { — }</td>
                </tr>
              } @empty { <tr><td colspan="5" class="empty">אין אירועים סגורים</td></tr> }
            </tbody>
          </table>
        }
        <p class="muted note">אירוע בלי עלות מלאה מוצג בנפרד ולא נכנס לחישוב הרווח, כדי שלא יוצג רווח שלא באמת ידוע.</p>
      </section>
    }
  `,
  styles: [`
    .alerts { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 14px; }
    .alert { text-decoration: none; border-radius: 8px; padding: 8px 12px; font-weight: 700; }
    .alert.bad { background: var(--bad-soft); color: var(--bad); }
    .alert.warn { background: var(--warn-soft); color: var(--warn); }
    .alert.hot { background: var(--honey-soft); color: #8a5c06; }
    .kpis { display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: 12px; margin-bottom: 14px; }
    .kpi { display: grid; gap: 2px; }
    .kpi span { color: var(--muted); font-size: .85rem; }
    .kpi b { font-family: var(--display); font-size: 1.6rem; color: var(--olive); }
    .kpi small { color: var(--muted); }
    .cols { display: grid; grid-template-columns: 1.1fr 1.3fr .9fr; gap: 14px; align-items: start; }
    @media (max-width: 1100px) { .cols { grid-template-columns: 1fr; } }
    h2 { margin-bottom: 10px; }
    .funnel { display: grid; gap: 6px; }
    .row { display: grid; grid-template-columns: 90px 1fr 28px 90px; align-items: center; gap: 8px; text-decoration: none; color: inherit; }
    .row .bar { height: 10px; background: var(--bg); border-radius: 99px; overflow: hidden; }
    .row .bar i { display: block; height: 100%; background: var(--st, var(--olive)); border-radius: 99px; }
    .row .bar.src i { background: var(--honey); }
    .cnt { text-align: end; font-weight: 700; }
    .val { text-align: end; font-size: .85rem; }
    .profit-rep { margin-top: 14px; display: grid; gap: 10px; }
    .pr-head { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; flex-wrap: wrap; }
    .pr-tabs { display: flex; gap: 6px; flex-wrap: wrap; }
    .pr-tabs button { border: 1px solid var(--line); background: var(--surface); border-radius: 99px; padding: 4px 12px; cursor: pointer; font: inherit; }
    .pr-tabs button.on { background: var(--olive); color: #fff; border-color: var(--olive); }
    .pr-table { width: 100%; border-collapse: collapse; }
    .pr-table th { text-align: start; font-size: .8rem; color: var(--muted); font-weight: 600; padding: 4px 6px; }
    .pr-table td { padding: 6px; border-top: 1px solid var(--line); }
    .low { color: var(--bad); font-weight: 700; }
    .miss-tag { margin-inline-start: 6px; font-size: .75rem; color: var(--warn); background: var(--warn-soft); border-radius: 6px; padding: 1px 6px; white-space: nowrap; }
    .note { margin: 0; font-size: .8rem; }
    .mcell { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; } .mcell .miss-tag { margin: 0; }
    @media (max-width: 640px) { .pr-table th:nth-child(2), .pr-table td:nth-child(2) { display: none; } }
  `],
})
export class DashboardComponent {
  private api = inject(ApiService);
  d = signal<Dashboard | null>(null);
  error = signal('');
  stageLabel = STAGE_LABEL;
  sourceLabel = SOURCE;
  eventType = EVENT_TYPE;
  maxCount = computed(() => Math.max(1, ...(this.d()?.kpis.stages.map((s) => s.count) ?? [1])));
  sources = computed(() => Object.entries(this.d()?.kpis.sources ?? {}).map(([key, n]) => ({ key, n })).sort((a, b) => b.n - a.n));
  maxSource = computed(() => Math.max(1, ...this.sources().map((s) => s.n)));

  pr = signal<ProfitReport | null>(null);
  prTabs = [{ key: 'by_month', label: 'לפי חודש' }, { key: 'by_event_type', label: 'לפי סוג אירוע' }, { key: 'by_package', label: 'לפי חבילה' }, { key: 'events', label: 'לפי אירוע' }] as const;
  prTab = signal<'by_month' | 'by_event_type' | 'by_package' | 'events'>('by_month');
  prRows = computed(() => { const r = this.pr(); const t = this.prTab(); return r && t !== 'events' ? r[t] : []; });

  constructor() {
    this.api.profitReport(6).subscribe({ next: (r) => this.pr.set(r), error: () => this.pr.set(null) });
    this.api.dashboard().subscribe({
      next: (d) => this.d.set(d),
      error: () => this.error.set('השרת לא זמין. הפעילו את ה-backend על פורט 8000.'),
    });
  }
  month(key: string) { const [y, m] = key.split('-').map(Number); return new Date(y, m - 1, 1).toLocaleDateString('he-IL', { month: 'long', year: 'numeric' }); }
  pct(v: number | null) { return v == null ? '—' : Math.round(v * 100) + '%'; }
}

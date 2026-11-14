import { Component, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { ApiService } from '../core/api.service';
import { HeDatePipe, IlsPipe, RelativePipe } from '../core/format';
import { EVENT_TYPE, SOURCE, STAGE_LABEL } from '../core/labels';
import { Dashboard } from '../core/models';

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
        @if (d.escalated_chats) { <a routerLink="/conversations" class="alert bad">🔥 {{ d.escalated_chats }} לקוחות מתוסכלים מחכים למענה</a> }
        @if (d.handed_off_chats) { <a routerLink="/conversations" class="alert bad">{{ d.handed_off_chats }} שיחות מהסוכן ממתינות לנציג</a> }
        @if (d.overdue_tasks) { <a routerLink="/tasks" class="alert warn">{{ d.overdue_tasks }} משימות באיחור</a> }
        @if (d.hot_leads) { <a routerLink="/pipeline" class="alert hot">{{ d.hot_leads }} לידים חמים (ציון 70+)</a> }
      </div>
      <div class="kpis">
        <div class="card kpi"><span>Pipeline פתוח</span><b class="num">{{ d.open_pipeline_value | ils }}</b></div>
        <div class="card kpi"><span>נסגר החודש</span><b class="num">{{ d.won_value_this_month | ils }}</b><small>{{ d.won_count_this_month }} עסקאות</small></div>
        <div class="card kpi"><span>אחוז סגירה</span><b class="num">{{ pct(d.win_rate) }}</b><small>מתוך עסקאות שהסתיימו</small></div>
        <div class="card kpi"><span>עסקה ממוצעת</span><b class="num">{{ d.avg_won_value | ils }}</b></div>
        <div class="card kpi"><span>המרת צ'אט לליד</span><b class="num">{{ pct(d.chat_conversion) }}</b><small>שיחות סוכן AI</small></div>
      </div>
      <div class="cols">
        <section class="card">
          <h2>לפי שלב</h2>
          <div class="funnel">
            @for (s of d.stages; track s.stage) {
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
  `],
})
export class DashboardComponent {
  private api = inject(ApiService);
  d = signal<Dashboard | null>(null);
  error = signal('');
  stageLabel = STAGE_LABEL;
  sourceLabel = SOURCE;
  eventType = EVENT_TYPE;
  maxCount = computed(() => Math.max(1, ...(this.d()?.stages.map((s) => s.count) ?? [1])));
  sources = computed(() => Object.entries(this.d()?.sources ?? {}).map(([key, n]) => ({ key, n })).sort((a, b) => b.n - a.n));
  maxSource = computed(() => Math.max(1, ...this.sources().map((s) => s.n)));

  constructor() {
    this.api.dashboard().subscribe({
      next: (d) => this.d.set(d),
      error: () => this.error.set('השרת לא זמין. הפעילו את ה-backend על פורט 8000.'),
    });
  }
  pct(v: number | null) { return v == null ? '—' : Math.round(v * 100) + '%'; }
}

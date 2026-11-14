import { Component, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { ApiService } from '../core/api.service';
import { STAGE_LABEL } from '../core/labels';
import { CalendarDay } from '../core/models';

const MONTHS = ['ינואר', 'פברואר', 'מרץ', 'אפריל', 'מאי', 'יוני', 'יולי', 'אוגוסט', 'ספטמבר', 'אוקטובר', 'נובמבר', 'דצמבר'];

@Component({
  selector: 'app-calendar',
  standalone: true,
  imports: [RouterLink],
  template: `
    <div class="page-head">
      <div><h1>לוח שנה</h1><p>מה סגור, מה בהמתנה, ואיפה היומן כבר מלא</p></div>
      <div class="nav">
        <button class="btn ghost" (click)="shift(1)" aria-label="חודש הבא">→</button>
        <b>{{ title() }}</b>
        <button class="btn ghost" (click)="shift(-1)" aria-label="חודש קודם">←</button>
        <button class="btn ghost" (click)="goToday()">היום</button>
      </div>
    </div>
    <div class="legend"><span class="d won"></span>נסגר <span class="d quoted"></span>הצעה נשלחה <span class="d new"></span>פנייה <span class="full-l">מלא</span> = הגעתם לקיבולת היומית</div>
    <div class="cal card">
      @for (w of weekdays; track w) { <div class="wd">{{ w }}</div> }
      @for (b of blanks(); track $index) { <div class="cell empty"></div> }
      @for (d of days(); track d.date) {
        <div class="cell" [class.today]="d.date === todayIso" [class.full]="d.full">
          <div class="dn"><span>{{ +d.date.slice(8) }}</span>@if (d.full) { <span class="full-l">מלא</span> } @else if (d.guests_booked) { <small class="muted">{{ d.guests_booked }} אורחים</small> }</div>
          @for (e of d.deals; track e.id) {
            <a class="ev {{ e.stage }}" [routerLink]="['/deals', e.id]" [title]="stage[e.stage]">{{ e.title }}</a>
          }
          @if (d.events_booked) { <a class="kitchen" [routerLink]="['/kitchen']" [queryParams]="{ day: d.date }">דף מטבח</a> }
        </div>
      }
    </div>
  `,
  styles: [`
    .nav { display: flex; gap: 8px; align-items: center; } .nav b { min-width: 120px; text-align: center; font-family: var(--display); font-size: 1.2rem; }
    .legend { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; margin-bottom: 10px; font-size: .85rem; color: var(--muted); }
    .d { width: 10px; height: 10px; border-radius: 3px; display: inline-block; margin-inline-start: 8px; }
    .d.won { background: var(--ok); } .d.quoted { background: var(--honey); } .d.new { background: #8a9580; }
    .cal { display: grid; grid-template-columns: repeat(7, 1fr); gap: 4px; padding: 10px; }
    .wd { text-align: center; font-size: .8rem; color: var(--muted); padding: 4px 0; }
    .cell { min-height: 110px; border: 1px solid var(--line); border-radius: 8px; padding: 6px; display: flex; flex-direction: column; gap: 3px; min-width: 0; }
    .cell.empty { border: 0; }
    .cell.today { border: 2px solid var(--olive); }
    .cell.full { background: var(--bad-soft); }
    .dn { display: flex; justify-content: space-between; align-items: center; font-weight: 700; }
    .full-l { font-size: .7rem; background: var(--bad); color: #fff; border-radius: 99px; padding: 0 6px; }
    .ev { font-size: .75rem; border-radius: 4px; padding: 2px 5px; text-decoration: none; color: var(--ink); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; border-inline-start: 3px solid; }
    .ev.won { background: var(--ok-soft); border-color: var(--ok); } .ev.quoted { background: var(--honey-soft); border-color: var(--honey); }
    .ev.new { background: var(--bg); border-color: #8a9580; } .ev.completed { background: var(--bg); border-color: #5b6b8c; color: var(--muted); }
    .kitchen { margin-top: auto; font-size: .72rem; }
    @media (max-width: 700px) { .cell { min-height: 70px; } .ev { font-size: .65rem; } }
  `],
})
export class CalendarComponent {
  private api = inject(ApiService);
  weekdays = ['א', 'ב', 'ג', 'ד', 'ה', 'ו', 'ש'];
  stage = STAGE_LABEL;
  todayIso = new Date().toISOString().slice(0, 10);
  month = signal(this.todayIso.slice(0, 7));
  days = signal<CalendarDay[]>([]);
  title = computed(() => { const [y, m] = this.month().split('-'); return `${MONTHS[+m - 1]} ${y}`; });
  blanks = computed(() => Array(new Date(this.month() + '-01T12:00:00').getDay()).fill(0));

  constructor() { this.load(); }
  load() { this.api.calendar(this.month()).subscribe((d) => this.days.set(d)); }
  shift(n: number) {
    const [y, m] = this.month().split('-').map(Number);
    const d = new Date(y, m - 1 + n, 1);
    this.month.set(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`);
    this.load();
  }
  goToday() { this.month.set(this.todayIso.slice(0, 7)); this.load(); }
}

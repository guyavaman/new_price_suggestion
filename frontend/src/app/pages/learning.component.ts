import { Component, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { ApiService } from '../core/api.service';
import { HeDatePipe, IlsPipe } from '../core/format';
import { LearningView, PortionSuggestion } from '../core/models';

/** What past events teach: suggested base amounts per guest (applied only by the owner),
 *  planned vs actual per closed event, and events still waiting for their summary. */
@Component({
  selector: 'app-learning',
  standalone: true,
  imports: [RouterLink, IlsPipe, HeDatePipe],
  template: `
    <h1>סגירה ולמידה</h1>
    @if (msg()) { <p class="flash" role="status">{{ msg() }}</p> }
    @if (v(); as v) {
      @if (v.to_close.length) {
        <section class="card todo" aria-labelledby="tc-h">
          <h2 id="tc-h">אירועים שמחכים לסיכום</h2>
          <ul>@for (e of v.to_close; track e.deal_id) { <li><a [routerLink]="['/deals', e.deal_id]" fragment="closing">{{ e.title }}</a> <small class="muted">{{ e.event_date | heDate }}</small></li> }</ul>
        </section>
      }

      <section class="card" aria-labelledby="sg-h">
        <h2 id="sg-h">הצעות לכמות בסיס לסועד</h2>
        <p class="muted small">מחושב מסיכומי האירועים: כמה אורחים הגיעו וכמה נשאר מכל מנה. שום דבר לא משתנה עד שמאשרים.</p>
        <div class="sugs">
          @for (s of active(v); track s.category) {
            <article class="sug" [class.up]="(s.change ?? 0) > 0">
              <h3>{{ s.label }}</h3>
              <p class="nums"><span class="num old">{{ fmt(s.current, s.measure) }}</span><span aria-hidden="true">←</span><b class="num">{{ fmt(s.suggested!, s.measure) }}</b>
                <span class="chg">{{ (s.change! > 0 ? '+' : '') + pctv(s.change!) }}</span></p>
              <p class="why">{{ s.reason }}</p>
              <div class="bar" aria-label="סימוני שאריות">
                @if (s.marks.out) { <span class="b-out" [style.flex]="s.marks.out">נגמר {{ s.marks.out }}</span> }
                @if (s.marks.ok) { <span class="b-ok" [style.flex]="s.marks.ok">סביר {{ s.marks.ok }}</span> }
                @if (s.marks.lot) { <span class="b-lot" [style.flex]="s.marks.lot">נשאר הרבה {{ s.marks.lot }}</span> }
              </div>
              <button class="btn sm" type="button" [disabled]="busy()" (click)="apply(s)">עדכון ל-{{ fmt(s.suggested!, s.measure) }}</button>
            </article>
          } @empty { <p class="muted">אין כרגע הצעות לשינוי.</p> }
        </div>
        <details class="rest"><summary>שאר הקטגוריות</summary>
          <ul>@for (s of quiet(v); track s.category) { <li><b>{{ s.label }}</b> ({{ fmt(s.current, s.measure) }}): {{ s.reason }}</li> }</ul>
        </details>
      </section>

      <section class="card" aria-labelledby="ev-h">
        <h2 id="ev-h">מתוכנן מול בפועל</h2>
        <div class="tw"><table>
          <thead><tr><th>אירוע</th><th class="end">אורחים</th><th class="end">רווח מתוכנן</th><th class="end">רווח בפועל</th><th class="end">שולי רווח</th></tr></thead>
          <tbody>
            @for (e of v.events; track e.deal_id) {
              <tr><td><a [routerLink]="['/deals', e.deal_id]" fragment="closing">{{ e.title }}</a></td>
                <td class="end num">{{ e.actual_guests ?? '—' }} / {{ e.planned_guests ?? '?' }}</td>
                <td class="end">{{ e.planned_profit !== null ? (e.planned_profit | ils) : 'לא ידוע' }}</td>
                <td class="end" [class.bad]="e.actual_profit !== null && e.planned_profit !== null && e.actual_profit < e.planned_profit">{{ e.actual_profit !== null ? (e.actual_profit | ils) : 'לא ידוע' }}</td>
                <td class="end">{{ e.actual_margin !== null ? pctv(e.actual_margin) : '—' }}</td></tr>
            } @empty { <tr><td colspan="5" class="muted">עוד אין אירועים עם סיכום.</td></tr> }
          </tbody>
        </table></div>
      </section>
    } @else { <p class="muted">טוען…</p> }
  `,
  styles: [`
    .card { display: grid; gap: 10px; min-width: 0; margin-bottom: 14px; } h2 { margin: 0; }
    .small { font-size: .86rem; margin: 0; }
    .todo { border-inline-start: 4px solid var(--warn); } .todo ul { margin: 0; padding-inline-start: 18px; }
    .sugs { display: grid; gap: 12px; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); }
    .sug { border: 1px solid var(--line); border-radius: 12px; padding: 12px 14px; display: grid; gap: 8px; align-content: start; }
    .sug h3 { margin: 0; font-size: 1rem; }
    .nums { margin: 0; display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; }
    .nums .old { color: var(--muted); text-decoration: line-through; } .nums b { font-size: 1.5rem; color: var(--olive); }
    .chg { font-size: .8rem; font-weight: 700; border-radius: 99px; padding: 1px 8px; background: var(--warn-soft); color: var(--warn); }
    .sug.up .chg { background: var(--bad-soft); color: var(--bad); }
    .why { margin: 0; font-size: .86rem; color: var(--muted); }
    .bar { display: flex; height: 22px; border-radius: 6px; overflow: hidden; font-size: .7rem; font-weight: 700; }
    .bar span { display: flex; align-items: center; justify-content: center; white-space: nowrap; overflow: hidden; min-width: 0; }
    .b-out { background: var(--bad-soft); color: var(--bad); } .b-ok { background: var(--ok-soft); color: var(--ok); } .b-lot { background: var(--warn-soft); color: var(--warn); }
    .btn.sm { padding: 5px 12px; font-size: .86rem; justify-self: start; }
    .rest summary { cursor: pointer; color: var(--muted); } .rest ul { margin: 6px 0 0; padding-inline-start: 18px; font-size: .86rem; }
    .tw { overflow-x: auto; } table { width: 100%; border-collapse: collapse; }
    th { text-align: start; font-size: .78rem; color: var(--muted); font-weight: 600; padding: 6px; }
    td { padding: 7px 6px; border-top: 1px solid var(--line); } .end { text-align: end; } .bad { color: var(--bad); }
    .flash { background: var(--ok-soft); color: var(--ok); padding: 6px 12px; border-radius: 8px; }
  `],
})
export class LearningComponent {
  private api = inject(ApiService);
  v = signal<LearningView | null>(null);
  busy = signal(false); msg = signal('');
  constructor() { this.load(); }
  load() { this.api.learning().subscribe((v) => this.v.set(v)); }
  active(v: LearningView) { return v.suggestions.filter((s) => s.suggested !== null); }
  quiet(v: LearningView) { return v.suggestions.filter((s) => s.suggested === null); }
  fmt(v: number, m: string) { return m === 'g' ? `${v} גרם` : `${v} מנות`; }
  pctv(v: number) { return `${Math.round(v * 100)}%`; }
  apply(s: PortionSuggestion) {
    if (!confirm(`לעדכן את כמות הבסיס ל${s.label} מ-${this.fmt(s.current, s.measure)} ל-${this.fmt(s.suggested!, s.measure)} לסועד? ההצעות הבאות ייבנו לפי הכמות החדשה.`)) return;
    this.busy.set(true);
    this.api.applyPortion(s.category, s.suggested!).subscribe({
      next: () => { this.busy.set(false); this.msg.set(`עודכן: ${s.label} ${this.fmt(s.suggested!, s.measure)} לסועד`); this.load(); setTimeout(() => this.msg.set(''), 4000); },
      error: () => { this.busy.set(false); this.msg.set('העדכון נכשל'); },
    });
  }
}

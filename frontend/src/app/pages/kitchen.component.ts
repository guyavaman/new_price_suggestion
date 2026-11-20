import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { ApiService } from '../core/api.service';
import { HeDatePipe } from '../core/format';
import { MEAL, dietLabel } from '../core/labels';
import { KitchenSheet, PrepDay } from '../core/models';

const iso = (d: Date) => d.toISOString().slice(0, 10);
const plus = (day: string, n: number) => { const d = new Date(day + 'T12:00:00'); d.setDate(d.getDate() + n); return iso(d); };

@Component({
  selector: 'app-kitchen',
  standalone: true,
  imports: [FormsModule, RouterLink, HeDatePipe],
  template: `
    <div class="page-head no-print">
      <div><h1>מטבח</h1><p>מה מכינים, בכמה, באיזו תחנה ומתי. חבילות מפורקות למנות.</p></div>
      <div class="tabs" role="tablist">
        <button role="tab" [attr.aria-selected]="tab() === 'day'" [class.on]="tab() === 'day'" (click)="tab.set('day')">דף מטבח יומי</button>
        <button role="tab" [attr.aria-selected]="tab() === 'prep'" [class.on]="tab() === 'prep'" (click)="tab.set('prep'); loadPrep()">לו"ז הכנה</button>
      </div>
    </div>

    @if (tab() === 'day') {
      <div class="row no-print">
        <button class="btn ghost" (click)="shift(-1)" aria-label="יום קודם">→</button>
        <input type="date" [(ngModel)]="day" (ngModelChange)="load()" aria-label="תאריך">
        <button class="btn ghost" (click)="shift(1)" aria-label="יום הבא">←</button>
        <button class="btn" (click)="print()">הדפסה</button>
      </div>
      @if (s(); as s) {
        <h2 class="print-title">דף מטבח · {{ s.date | heDate }} · {{ s.events.length }} אירועים · {{ s.total_guests }} אורחים</h2>
        @if (!s.events.length) { <p class="card empty">אין אירועים סגורים בתאריך הזה</p> }
        @else {
          @for (w of s.warnings; track w) { <div class="kwarn" role="alert"><b>שימו לב:</b> {{ w }}</div> }
          @if (s.missing_quotes.length) { <div class="err">אירועים בלי הצעת מחיר (לא נכללו): {{ s.missing_quotes.join(', ') }}</div> }
          @for (sec of s.sections; track sec.kashrut) {
            <section class="card ksec k-{{ sec.kashrut || 'none' }}" [attr.aria-label]="sec.label">
              <header class="ksec-h"><h2>{{ sec.label }}</h2><small>{{ shortList(sec.events) }}</small></header>
              @for (g of sec.groups; track g.station) {
                <h3 class="station">{{ g.station }}</h3>
                <table class="krows">
                  <thead><tr><th>מנה</th><th class="end">להכין</th><th class="end">כמות</th><th>לפי אירוע</th></tr></thead>
                  <tbody>
                    @for (r of g.rows; track r.sku) {
                      <tr>
                        <td><b>{{ r.name }}</b></td>
                        <td class="end num"><b>{{ n(r.units) }}</b> {{ r.unit }}</td>
                        <td class="end num">{{ amount(r.total_amount, r.measure) }}@if (r.problem) { <span class="kprob">{{ r.problem }}</span> }</td>
                        <td class="small">@for (e of r.events; track $index) { <span>{{ short(e.title) }}: {{ e.units === null ? '?' : n(e.units) }}@if (e.package) { <i class="muted"> ({{ e.package }})</i> }</span> }</td>
                      </tr>
                    }
                  </tbody>
                </table>
              }
            </section>
          }
          <div class="events">
            @for (e of s.events; track e.deal_id) {
              <section class="card">
                <h3><a [routerLink]="['/deals', e.deal_id]">{{ e.title }}</a></h3>
                <p>{{ e.guests }} אורחים · {{ meal[e.meal_type ?? ''] || 'לא צוין בשרי/חלבי' }} @if (e.location) { · {{ e.location }} }</p>
                @if (e.dietary.length) { <p class="diet">⚠ {{ diets(e.dietary) }}</p> }
                @if (e.staff.length) { <p><b>צוות:</b> {{ e.staff.join(' · ') }}</p> }
                @if (e.equipment.length) { <p><b>ציוד:</b> {{ e.equipment.join(' · ') }}</p> }
              </section>
            }
          </div>
        }
      }
    } @else {
      <div class="row no-print">
        <label>מ-<input type="date" [(ngModel)]="from" (ngModelChange)="loadPrep()"></label>
        <label>עד<input type="date" [(ngModel)]="to" (ngModelChange)="loadPrep()"></label>
        <button class="btn" (click)="print()">הדפסה</button>
      </div>
      @if (prep(); as days) {
        @for (d of days; track d.date) {
          <section class="card pday">
            <h2>{{ weekday(d.date) }} · {{ d.date | heDate }} <small class="muted">{{ d.tasks.length }} משימות</small></h2>
            @for (e of byEvent(d); track e.deal_id) {
              <div class="pev k-{{ e.meal || 'none' }}">
                <h3><a [routerLink]="['/deals', e.deal_id]">{{ short(e.title) }}</a>
                  <small class="muted">· {{ meal[e.meal] || 'לא צוין' }} · האירוע {{ e.event_date | heDate }}@if (e.ahead) { · {{ e.ahead === 1 ? 'מחר' : 'בעוד ' + e.ahead + ' ימים' }} }</small></h3>
                <ul>
                  @for (t of e.tasks; track t.sku) {
                    <li><b>{{ t.name }}</b> <span class="num">{{ t.units === null ? '?' : n(t.units) }} {{ t.unit }}</span>
                      <span class="muted">· {{ t.station }}</span>@if (t.problem) { <span class="kprob inline">{{ t.problem }}</span> }</li>
                  }
                </ul>
              </div>
            }
          </section>
        } @empty { <p class="card empty">אין הכנות בטווח הזה</p> }
      }
    }
  `,
  styles: [`
    .tabs { display: flex; gap: 6px; }
    .tabs button { border: 1px solid var(--line); background: var(--surface); border-radius: 99px; padding: 6px 14px; font: inherit; cursor: pointer; }
    .tabs button.on { background: var(--olive); color: #fff; border-color: var(--olive); }
    .row { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; margin-bottom: 12px; }
    .row label { display: flex; gap: 6px; align-items: center; }
    .print-title { margin: 0 0 12px; }
    .kwarn { background: var(--bad-soft); color: var(--bad); border: 2px solid var(--bad); border-radius: 10px; padding: 10px 14px; margin-bottom: 12px; font-weight: 600; }
    .ksec { margin-bottom: 14px; border-top: 6px solid var(--k); --k: var(--olive); }
    .k-meat { --k: #8a3b2e; } .k-dairy { --k: #2f5d8a; } .k-pareve { --k: var(--olive); } .k-none { --k: var(--warn); }
    .ksec-h { display: flex; justify-content: space-between; align-items: baseline; gap: 10px; flex-wrap: wrap; }
    .ksec-h h2 { margin: 0; color: var(--k); }
    .station { font-size: .95rem; margin: 14px 0 4px; color: var(--muted); }
    .krows { width: 100%; border-collapse: collapse; }
    .krows th { text-align: start; font-size: .76rem; color: var(--muted); font-weight: 600; padding: 4px 6px; }
    .krows td { padding: 6px; border-top: 1px solid var(--line); vertical-align: top; }
    .end { text-align: end; } .small { font-size: .82rem; } .small span { display: inline-block; margin-inline-end: 10px; color: var(--muted); }
    .kprob { display: block; font-size: .72rem; color: var(--warn); font-weight: 600; } .kprob.inline { display: inline; margin-inline-start: 6px; }
    .events { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; margin-top: 14px; }
    .events p { margin: 4px 0; } .diet { color: var(--bad); font-weight: 700; }
    .pday { margin-bottom: 12px; } .pday h2 { margin: 0 0 8px; font-size: 1.1rem; }
    .pev { border-inline-start: 4px solid var(--k); padding-inline-start: 10px; margin: 10px 0; --k: var(--olive); }
    .pev h3 { margin: 0 0 4px; font-size: .98rem; } .pev ul { margin: 0; padding-inline-start: 18px; } .pev li { margin: 2px 0; }
    @media (max-width: 640px) {
      .krows thead { display: none; }
      .krows tr { display: grid; grid-template-columns: 1fr auto; gap: 2px 10px; padding: 8px 0; border-top: 1px solid var(--line); }
      .krows td { border: 0; padding: 0; } .krows td:nth-child(4) { grid-column: 1 / -1; }
    }
    @media print { .no-print { display: none !important; } .card { border: 0; padding: 0; break-inside: avoid; } .kwarn { border-width: 3px; } }
  `],
})
export class KitchenComponent {
  private api = inject(ApiService);
  day = inject(ActivatedRoute).snapshot.queryParamMap.get('day') ?? iso(new Date());
  tab = signal<'day' | 'prep'>('day');
  s = signal<KitchenSheet | null>(null);
  prep = signal<PrepDay[] | null>(null);
  from = iso(new Date()); to = plus(iso(new Date()), 7);
  meal: Record<string, string> = MEAL;
  constructor() { this.load(); }
  load() { this.api.kitchen(this.day).subscribe((s) => this.s.set(s)); }
  loadPrep() { this.api.prepSchedule(this.from, this.to).subscribe((d) => this.prep.set(d)); }
  shift(n: number) { this.day = plus(this.day, n); this.load(); }
  short(t: string) { return t.split(' · ').slice(0, 2).join(' · '); }
  shortList(t: string[]) { return t.map((x) => this.short(x)).join(' | '); }
  diets(d: string[]) { return d.map(dietLabel).join(', '); }
  print() { window.print(); }
  n(v: number) { return v.toLocaleString('he-IL', { maximumFractionDigits: 1 }); }
  amount(v: number | null, m: 'g' | 'unit' | null) {
    if (v === null || m === null) return '—';
    return m === 'g' ? `${(v / 1000).toLocaleString('he-IL', { maximumFractionDigits: 1 })} ק"ג` : `${this.n(v)} מנות`;
  }
  weekday(d: string) { return new Date(d + 'T12:00:00').toLocaleDateString('he-IL', { weekday: 'long' }); }
  byEvent(d: PrepDay) {
    const out = new Map<string, { deal_id: string; title: string; meal: string; event_date: string; ahead: number; tasks: PrepDay['tasks'] }>();
    for (const t of d.tasks) {
      const e = out.get(t.deal_id) ?? { deal_id: t.deal_id, title: t.title, meal: t.event_meal, event_date: t.event_date, ahead: t.days_before, tasks: [] };
      e.tasks.push(t); out.set(t.deal_id, e);
    }
    return [...out.values()];
  }
}

import { Component, computed, effect, inject, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiService } from './api.service';
import { IlsPipe } from './format';
import { ClosingView, EventClosing, Leftover, PlannedDish } from './models';

const MARKS: { id: Leftover; he: string }[] = [{ id: 'lot', he: 'נשאר הרבה' }, { id: 'ok', he: 'סביר' }, { id: 'out', he: 'נגמר' }];
const CAT_HE: Record<string, string> = {
  salad: 'סלטים', side: 'תוספות', starter: 'ראשונות', main: 'עיקריות', canape: 'קנאפה', breakfast: 'ארוחת בוקר',
  dessert: 'קינוחים', drink: 'שתייה', bar: 'בר',
};

/** After the event: a short form (who came, what was left, what it really cost) and the
 *  planned-vs-actual report built from it. */
@Component({
  selector: 'app-event-closing',
  standalone: true,
  imports: [FormsModule, IlsPipe],
  template: `
    @if (v(); as v) {
      @if (editing()) {
        <form class="form" (ngSubmit)="save()">
          <div class="nums">
            <label>אורחים שהגיעו בפועל
              <input type="number" min="0" [(ngModel)]="f.actual_guests" name="g" [placeholder]="'אושרו ' + (v.planned_guests ?? '?')"></label>
            <label>רכש בפועל (₪)
              <input type="number" min="0" [(ngModel)]="f.purchasing_cost" name="p" [placeholder]="v.planned_food_cost !== null ? 'מתוכנן ' + (v.planned_food_cost | ils) : 'לא ידוע'"></label>
            <label>תשלום לצוות (₪)
              <input type="number" min="0" [(ngModel)]="f.staff_cost" name="s" [placeholder]="v.staff_cost_from_hours !== null ? 'לפי השעות ' + (v.staff_cost_from_hours | ils) : 'לא ידוע'"></label>
            <label>הוצאות לא מתוכננות (₪)
              <input type="number" min="0" [(ngModel)]="f.other_cost" name="o" placeholder="0"></label>
          </div>
          @if (v.staff_cost_from_hours !== null && f.staff_cost === null) {
            <p class="hint">תשלום לצוות שלא הוזן יחושב לפי שעות הצוות שבכרטיס "צוות לאירוע".</p>
          }
          @if (v.dishes.length) {
            <fieldset class="dishes"><legend>כמה נשאר מכל מנה</legend>
              <div class="allbar"><span class="muted">לכל המנות:</span>
                @for (m of marks; track m.id) { <button type="button" class="chip" (click)="markAll(m.id)">{{ m.he }}</button> }</div>
              @for (g of groups(); track g.cat) {
                <div class="cat">{{ g.label }}</div>
                @for (d of g.dishes; track d.sku) {
                  <div class="dish" role="radiogroup" [attr.aria-label]="d.name">
                    <span class="dn">{{ d.name }} <small class="muted">{{ amount(d) }}</small></span>
                    <span class="seg">
                      @for (m of marks; track m.id) {
                        <button type="button" role="radio" [attr.aria-checked]="mark(d.sku) === m.id" [class]="'m-' + m.id"
                                [class.on]="mark(d.sku) === m.id" (click)="setMark(d.sku, m.id)">{{ m.he }}</button>
                      }
                    </span>
                  </div>
                }
              }
            </fieldset>
          }
          <label class="notes">הערות<textarea [(ngModel)]="f.notes" name="n" rows="2" placeholder="מה למדנו מהאירוע הזה"></textarea></label>
          <div class="row">
            <button class="btn" type="submit" [disabled]="busy()">{{ v.closing ? 'שמירת השינויים' : 'שמירת הסיכום' }}</button>
            @if (v.closing) { <button class="btn ghost" type="button" (click)="editing.set(false)">ביטול</button> }
          </div>
          @if (err()) { <p class="err" role="alert">{{ err() }}</p> }
        </form>
      } @else {
        <button class="linkish edit" type="button" (click)="startEdit()">עריכת הסיכום</button>
      }

      @if (v.closing) {
        @let r = v.report;
        <div class="cmp" aria-label="מתוכנן מול בפועל">
          <div class="kpi"><span class="lbl">אורחים</span><b class="num">{{ r.actual_guests ?? '—' }}</b><small>מתוך {{ r.planned_guests ?? '?' }} שאושרו</small></div>
          <div class="kpi"><span class="lbl">רווח בפועל</span>
            <b class="num" [class.bad]="r.actual_profit !== null && r.planned_profit !== null && r.actual_profit < r.planned_profit">{{ r.actual_profit !== null ? (r.actual_profit | ils) : '—' }}</b>
            <small>מתוכנן {{ r.planned_profit !== null ? (r.planned_profit | ils) : 'לא ידוע' }}</small></div>
          <div class="kpi"><span class="lbl">שולי רווח</span><b class="num">{{ pct(r.actual_margin) }}</b><small>מתוכנן {{ pct(r.planned_margin) }}</small></div>
        </div>
        @if (r.missing.length) { <p class="miss">כדי להשוות עד הסוף חסר: {{ r.missing.join(' · ') }}</p> }

        <div class="tw"><table class="t">
          <caption>עלויות</caption>
          <thead><tr><th>סעיף</th><th class="end">מתוכנן</th><th class="end">בפועל</th><th class="end">הפרש</th><th>מקור</th></tr></thead>
          <tbody>
            @for (g of r.groups; track g.group) {
              <tr><td>{{ g.label }}</td><td class="end">{{ money(g.planned) }}</td><td class="end">{{ money(g.actual) }}</td>
                <td class="end" [class.bad]="diff(g.planned, g.actual) > 0" [class.ok]="diff(g.planned, g.actual) < 0">{{ signed(g.planned, g.actual) }}</td>
                <td class="muted">{{ g.source }}</td></tr>
            }
          </tbody>
          <tfoot><tr><td>סה"כ עלות</td><td class="end">{{ money(r.planned_cost) }}</td><td class="end">{{ money(r.actual_cost) }}</td><td class="end">{{ signed(r.planned_cost, r.actual_cost) }}</td><td></td></tr>
            <tr><td>הכנסה (לפני מע"מ)</td><td class="end">{{ r.revenue | ils }}</td><td class="end">{{ r.revenue | ils }}</td><td></td><td></td></tr></tfoot>
        </table></div>

        @if (r.dishes.length) {
          <div class="tw"><table class="t">
            <caption>כמויות לסועד</caption>
            <thead><tr><th>מנה</th><th class="end">הוכן</th><th class="end">לסועד שאושר</th><th class="end">לסועד שהגיע</th><th>נשאר</th></tr></thead>
            <tbody>
              @for (d of r.dishes; track d.sku) {
                <tr><td>{{ d.name }}</td><td class="end">{{ amount(d) }}</td>
                  <td class="end num">{{ per(d.per_guest_planned, d.measure) }}</td><td class="end num">{{ per(d.per_guest_actual, d.measure) }}</td>
                  <td>@if (d.leftover) { <span class="mk m-{{ d.leftover }}">{{ markHe(d.leftover) }}</span> }</td></tr>
              }
            </tbody>
          </table></div>
        }

        @if (r.staff.length) {
          <div class="tw"><table class="t">
            <caption>צוות</caption>
            <thead><tr><th>תפקיד</th><th class="end">נדרשו</th><th class="end">הגיעו</th><th class="end">שעות מתוכננות</th><th class="end">שעות בפועל</th></tr></thead>
            <tbody>
              @for (s of r.staff; track s.role) {
                <tr><td>{{ s.label }}</td><td class="end num">{{ s.needed }}</td><td class="end num" [class.bad]="s.came !== null && s.came < s.needed">{{ s.came ?? 'לא שובץ במערכת' }}</td>
                  <td class="end num">{{ s.planned_hours }}</td><td class="end num">{{ s.actual_hours ?? 'לא הוזן' }}</td></tr>
              }
            </tbody>
          </table></div>
        }
        @if (r.notes) { <p class="note">“{{ r.notes }}”</p> }
      }
    } @else { <p class="muted">טוען…</p> }
  `,
  styles: [`
    :host { display: grid; gap: 12px; min-width: 0; }
    .form { display: grid; gap: 12px; }
    .nums { display: grid; gap: 10px; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); }
    .nums label, .notes { display: grid; gap: 4px; font-size: .86rem; }
    .hint { margin: 0; font-size: .82rem; color: var(--muted); }
    .dishes { border: 1px solid var(--line); border-radius: 10px; padding: 8px 12px 12px; display: grid; gap: 6px; min-width: 0; }
    legend { font-weight: 600; padding: 0 4px; }
    .allbar { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; font-size: .84rem; }
    .chip { border: 1px solid var(--line); background: var(--surface); border-radius: 99px; padding: 2px 10px; font: inherit; font-size: .8rem; cursor: pointer; }
    .cat { font-size: .78rem; color: var(--muted); font-weight: 700; margin-top: 6px; }
    .dish { display: flex; gap: 8px; align-items: center; justify-content: space-between; flex-wrap: wrap; padding: 3px 0; border-top: 1px dashed var(--line); }
    .dn { flex: 1 1 140px; }
    .seg { display: inline-flex; border: 1px solid var(--line); border-radius: 8px; overflow: hidden; }
    .seg button { border: 0; background: var(--surface); font: inherit; font-size: .82rem; padding: 5px 10px; cursor: pointer; }
    .seg button + button { border-inline-start: 1px solid var(--line); }
    .seg button.on.m-lot { background: var(--warn-soft); color: var(--warn); font-weight: 700; }
    .seg button.on.m-ok { background: var(--ok-soft); color: var(--ok); font-weight: 700; }
    .seg button.on.m-out { background: var(--bad-soft); color: var(--bad); font-weight: 700; }
    .row { display: flex; gap: 8px; flex-wrap: wrap; }
    .edit { justify-self: start; }
    .linkish { background: none; border: 0; padding: 0; color: var(--olive); text-decoration: underline; font: inherit; cursor: pointer; }
    .cmp { display: grid; gap: 10px; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); }
    .kpi { display: grid; gap: 2px; border: 1px solid var(--line); border-radius: 10px; padding: 10px 12px; }
    .kpi .lbl { font-size: .8rem; color: var(--muted); } .kpi b { font-size: 1.35rem; } .kpi small { color: var(--muted); font-size: .8rem; }
    .miss { margin: 0; background: var(--warn-soft); color: var(--warn); border-radius: 8px; padding: 6px 10px; font-size: .86rem; }
    .tw { overflow-x: auto; } .t { width: 100%; border-collapse: collapse; }
    caption { text-align: start; font-weight: 700; padding: 4px 0; }
    .t th { text-align: start; font-size: .76rem; color: var(--muted); font-weight: 600; padding: 4px 6px; }
    .t td { padding: 6px; border-top: 1px solid var(--line); } .t tfoot td { font-weight: 700; }
    .end { text-align: end; } .bad { color: var(--bad); } .ok { color: var(--ok); }
    .mk { font-size: .76rem; border-radius: 99px; padding: 1px 8px; font-weight: 700; }
    .mk.m-lot { background: var(--warn-soft); color: var(--warn); } .mk.m-ok { background: var(--ok-soft); color: var(--ok); } .mk.m-out { background: var(--bad-soft); color: var(--bad); }
    .note { margin: 0; font-style: italic; color: var(--muted); }
  `],
})
export class EventClosingComponent {
  private api = inject(ApiService);
  dealId = input.required<string>();
  changed = output<void>();
  marks = MARKS;
  v = signal<ClosingView | null>(null);
  editing = signal(true);
  busy = signal(false); err = signal('');
  f: EventClosing = this.blank();
  private picks = signal<Record<string, Leftover | null>>({});
  groups = computed(() => {
    const out: { cat: string; label: string; dishes: PlannedDish[] }[] = [];
    for (const d of this.v()?.dishes ?? []) {
      let g = out.find((x) => x.cat === d.category);
      if (!g) out.push(g = { cat: d.category, label: CAT_HE[d.category] ?? d.category, dishes: [] });
      g.dishes.push(d);
    }
    return out;
  });
  constructor() { effect(() => this.load(this.dealId())); }
  private blank(): EventClosing { return { actual_guests: null, dishes: [], purchasing_cost: null, staff_cost: null, other_cost: null, notes: '' }; }
  load(id: string) {
    this.api.closing(id).subscribe((v) => {
      this.v.set(v);
      this.editing.set(!v.closing);
      this.fill(v);
    });
  }
  private fill(v: ClosingView) {
    const c = v.closing;
    this.f = c ? { ...c } : this.blank();
    this.picks.set(Object.fromEntries((c?.dishes ?? []).map((d) => [d.sku, d.leftover])));
  }
  startEdit() { const v = this.v(); if (v) this.fill(v); this.editing.set(true); }
  mark(sku: string) { return this.picks()[sku] ?? null; }
  setMark(sku: string, m: Leftover) { this.picks.update((p) => ({ ...p, [sku]: p[sku] === m ? null : m })); }
  markAll(m: Leftover) { this.picks.set(Object.fromEntries((this.v()?.dishes ?? []).map((d) => [d.sku, m]))); }
  markHe(m: string) { return MARKS.find((x) => x.id === m)?.he ?? m; }
  private num(x: unknown): number | null { return x === null || x === undefined || x === '' ? null : Math.max(0, +x); }
  save() {
    const body: EventClosing = {
      actual_guests: this.num(this.f.actual_guests) === null ? null : Math.round(this.num(this.f.actual_guests)!),
      purchasing_cost: this.num(this.f.purchasing_cost), staff_cost: this.num(this.f.staff_cost), other_cost: this.num(this.f.other_cost),
      notes: (this.f.notes ?? '').trim(),
      dishes: (this.v()?.dishes ?? []).map((d) => ({ sku: d.sku, leftover: this.mark(d.sku) })),
    };
    this.busy.set(true); this.err.set('');
    this.api.saveClosing(this.dealId(), body).subscribe({
      next: (v) => { this.busy.set(false); this.v.set(v); this.editing.set(false); this.changed.emit(); },
      error: (e) => { this.busy.set(false); this.err.set(typeof e.error?.detail === 'string' ? e.error.detail : 'השמירה נכשלה. בדקו שהמספרים תקינים.'); },
    });
  }
  amount(d: PlannedDish) {
    if (d.total_amount !== null && d.measure === 'g') return d.total_amount >= 1000 ? `${(d.total_amount / 1000).toFixed(1)} ק"ג` : `${d.total_amount} גרם`;
    if (d.units !== null) return `${+d.units.toFixed(1)} ${d.unit}`;
    return '';
  }
  per(v: number | null, m: string | null) { return v === null ? '—' : m === 'g' ? `${Math.round(v)} גרם` : `${+v.toFixed(2)}`; }
  pct(v: number | null) { return v === null ? '—' : `${Math.round(v * 100)}%`; }
  money(v: number | null) { return v === null ? 'לא ידוע' : `₪${Math.round(v).toLocaleString('he-IL')}`; }
  diff(a: number | null, b: number | null) { return a === null || b === null ? 0 : b - a; }
  signed(a: number | null, b: number | null) {
    if (a === null || b === null) return '';
    const d = Math.round(b - a);
    return d === 0 ? '0' : `${d > 0 ? '+' : '−'}₪${Math.abs(d).toLocaleString('he-IL')}`;
  }
}

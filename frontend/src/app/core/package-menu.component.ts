import { Component, computed, effect, input, output, signal } from '@angular/core';
import { DishRow, PackageMenu } from './models';
import { IlsPipe } from './format';

const UNIT_HE: Record<string, [string, string]> = {
  tray: ['מגש', 'מגשים'], unit: ['יחידה', 'יחידות'], per_guest: ['מנה', 'מנות'], hour: ['שעה', 'שעות'], kg: ['ק"ג', 'ק"ג'],
};

/** Owner view of an event's packages: pick the dishes per slot, and see what that means in
 *  quantities to make and cost. Customers never get this component (no amounts, no costs). */
@Component({
  selector: 'app-package-menu',
  standalone: true,
  imports: [IlsPipe],
  template: `
    @for (p of packages(); track p.sku; let first = $first) {
      <details class="pm" [open]="first" [attr.aria-label]="'הרכב ' + p.name_he">
        <summary class="pm-head">
          <div>
            <h3>{{ p.name_he }}</h3>
            <small class="muted">ל-{{ p.guests }} סועדים · {{ p.tiers.join(', ') }}</small>
          </div>
          @if (p.breakdown.status === 'complete') {
            <div class="pm-cost"><b class="num">{{ p.breakdown.total_cost | ils }}</b><small class="muted">עלות · {{ p.breakdown.cost_per_guest | ils:1 }} לסועד</small></div>
          } @else {
            <span class="miss-tag">חסרים נתונים</span>
          }
        </summary>

        <div class="slots">
          @for (s of p.slots; track s.id) {
            <fieldset class="slot" [class.bad]="count(p.sku, s.id) !== s.choose">
              <legend>
                {{ s.label_he }}
                <span class="muted">· {{ s.choose === 1 ? 'אחת' : s.choose }} מתוך {{ s.options.length }}</span>
                @if (editable() && s.options.length > 1) { <span class="counter num">{{ count(p.sku, s.id) }}/{{ s.choose }}</span> }
                @if (!s.can_choose) { <span class="owner-tag" title="הלקוח לא בוחר בחלק הזה">רק אתה</span> }
              </legend>
              <div class="chips">
                @for (o of s.options; track o.sku) {
                  <button type="button" class="dish" [class.on]="picked(p.sku, s.id, o.sku)" [attr.aria-pressed]="picked(p.sku, s.id, o.sku)"
                          [disabled]="!editable() || s.options.length === 1" (click)="toggle(p.sku, s.id, o.sku, s.choose)">{{ o.name_he }}</button>
                }
              </div>
            </fieldset>
          }
        </div>

        @if (dirty(p.sku)) {
          <div class="savebar" role="status">
            <span>{{ ready(p) ? 'הבחירה השתנתה. הכמויות והעלות יחושבו מחדש בשמירה.' : 'צריך לבחור בדיוק את מספר המנות בכל חלק' }}</span>
            <button class="btn" [disabled]="!ready(p) || busy()" (click)="commit(p)">שמירת המנות</button>
            <button class="btn ghost" (click)="reset(p.sku)">ביטול</button>
          </div>
        }

        <div class="tbl-wrap">
          <table class="dishes">
            <thead><tr><th>מנה</th><th>לסועד</th><th>סה"כ</th><th>להכנה</th><th>עלות</th></tr></thead>
            <tbody>
              @for (r of p.breakdown.rows; track r.slot_id + r.sku) {
                <tr [class.problem]="r.problem">
                  <td>{{ r.name_he }}<small class="muted slot-of">{{ r.slot_label }}</small></td>
                  <td class="num">{{ amount(r.per_guest, r) }}</td>
                  <td class="num">{{ amount(r.total_amount, r) }}</td>
                  <td class="num">@if (r.units !== null) { {{ units(r) }} } @else { <span class="miss-tag">{{ r.problem }}</span> }</td>
                  <td class="num">@if (r.cost !== null) { {{ r.cost | ils }} } @else if (r.units !== null) { <span class="miss-tag">{{ r.problem }}</span> } @else { — }</td>
                </tr>
              }
            </tbody>
          </table>
        </div>
      </details>
    } @empty {
      <p class="muted">אין בהצעה חבילה עם מנות לבחירה.</p>
    }
  `,
  styles: [`
    :host { display: grid; gap: 14px; }
    .pm { padding-top: 4px; }
    .pm[open] > :not(summary) { margin-top: 12px; }
    .pm > .slots, .pm > .tbl-wrap, .pm > .savebar { display: grid; }
    .pm + .pm { border-top: 1px solid var(--line); padding-top: 14px; }
    .pm-head { cursor: pointer; list-style: none; }
    .pm-head::-webkit-details-marker { display: none; }
    .pm-head h3::before { content: '◂'; display: inline-block; margin-inline-end: 6px; transition: transform .15s; color: var(--muted); }
    .pm[open] .pm-head h3::before { transform: rotate(-90deg); }
    .pm-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 10px; flex-wrap: wrap; }
    .pm-head h3 { margin: 0; font-size: 1.05rem; }
    .pm-cost { display: grid; text-align: end; }
    .pm-cost b { font-family: var(--display); font-size: 1.2rem; }
    .slots { display: grid; gap: 10px; }
    .slot { border: 0; margin: 0; padding: 0; min-width: 0; }
    .slot legend { padding: 0; font-weight: 600; margin-bottom: 6px; display: flex; gap: 6px; align-items: baseline; flex-wrap: wrap; }
    .counter { font-size: .8rem; background: var(--paper); border-radius: 99px; padding: 0 8px; }
    .slot.bad .counter { background: var(--warn-soft); color: var(--warn); }
    .owner-tag { font-size: .72rem; color: var(--muted); border: 1px solid var(--line); border-radius: 99px; padding: 0 7px; }
    .chips { display: flex; gap: 6px; flex-wrap: wrap; }
    .dish { font: inherit; font-size: .88rem; border: 1px solid var(--line); background: var(--surface); color: var(--ink); border-radius: 8px; padding: 5px 10px; cursor: pointer; }
    .dish.on { background: var(--olive); border-color: var(--olive); color: #fff; }
    .dish:disabled { cursor: default; }
    .dish:disabled:not(.on) { opacity: .55; }
    .dish:focus-visible { outline: 2px solid var(--olive); outline-offset: 2px; }
    .savebar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; background: var(--paper); border-radius: 8px; padding: 8px 10px; font-size: .88rem; }
    .savebar span { flex: 1 1 200px; }
    .tbl-wrap { overflow-x: auto; }
    .dishes { width: 100%; border-collapse: collapse; font-size: .9rem; }
    .dishes th { text-align: start; font-size: .78rem; color: var(--muted); font-weight: 600; padding: 4px 6px; white-space: nowrap; }
    .dishes td { padding: 6px; border-top: 1px solid var(--line); vertical-align: top; }
    .dishes tr.problem td:first-child { box-shadow: inset -3px 0 0 var(--warn); }
    .slot-of { display: block; font-size: .74rem; }
    .miss-tag { font-size: .75rem; color: var(--warn); background: var(--warn-soft); border-radius: 6px; padding: 1px 6px; white-space: nowrap; }
    @media (max-width: 640px) {
      .dishes th:nth-child(3), .dishes td:nth-child(3) { display: none; }
    }
  `],
})
export class PackageMenuComponent {
  packages = input.required<PackageMenu[]>();
  editable = input(true);
  busy = input(false);
  save = output<{ pkg: string; choice: Record<string, string[]> }>();

  private draft = signal<Record<string, Record<string, string[]>>>({});
  private saved = computed(() => Object.fromEntries(this.packages().map((p) => [p.sku, Object.fromEntries(p.slots.map((s) => [s.id, s.chosen]))])));

  constructor() {
    effect(() => this.draft.set(structuredClone(this.saved())), { allowSignalWrites: true });
  }

  picked(pkg: string, slot: string, sku: string) { return this.draft()[pkg]?.[slot]?.includes(sku) ?? false; }
  count(pkg: string, slot: string) { return this.draft()[pkg]?.[slot]?.length ?? 0; }

  toggle(pkg: string, slot: string, sku: string, choose: number) {
    this.draft.update((d) => {
      const cur = [...(d[pkg]?.[slot] ?? [])];
      const i = cur.indexOf(sku);
      if (i >= 0) cur.splice(i, 1);
      else if (choose === 1) cur.splice(0, cur.length, sku); // single choice: swap
      else cur.push(sku);
      return { ...d, [pkg]: { ...d[pkg], [slot]: cur } };
    });
  }

  dirty(pkg: string) { return JSON.stringify(this.draft()[pkg]) !== JSON.stringify(this.saved()[pkg]); }
  ready(p: PackageMenu) { return p.slots.every((s) => this.count(p.sku, s.id) === s.choose); }
  reset(pkg: string) { this.draft.update((d) => ({ ...d, [pkg]: structuredClone(this.saved()[pkg]) })); }

  commit(p: PackageMenu) {
    const before = this.saved()[p.sku];
    const now = this.draft()[p.sku];
    const changed = Object.fromEntries(Object.entries(now).filter(([k, v]) => JSON.stringify(v) !== JSON.stringify(before[k])));
    this.save.emit({ pkg: p.sku, choice: changed });
  }

  amount(v: number | null, r: DishRow): string {
    if (v === null) return '—';
    if (r.measure === 'g') return v >= 1000 ? `${(v / 1000).toLocaleString('he-IL', { maximumFractionDigits: 1 })} ק"ג` : `${Math.round(v)} גרם`;
    const n = v.toLocaleString('he-IL', { maximumFractionDigits: 2 });
    return `${n} ${v === 1 ? 'מנה' : 'מנות'}`;
  }

  units(r: DishRow): string {
    const [one, many] = UNIT_HE[r.unit] ?? ['', ''];
    return `${r.units!.toLocaleString('he-IL')} ${r.units === 1 ? one : many}`;
  }
}

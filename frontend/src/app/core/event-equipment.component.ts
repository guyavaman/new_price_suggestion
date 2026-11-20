import { Component, effect, inject, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiService } from './api.service';
import { EquipmentLine, EquipmentState, EquipmentType } from './models';

/** What goes out to the event (from the quote + what the owner adds), same-day stock check,
 *  packed mark, and after the event: what came back. */
@Component({
  selector: 'app-event-equipment',
  standalone: true,
  imports: [FormsModule],
  template: `
    @if (st(); as st) {
      @if (st.from_quote && st.lines.length) { <p class="muted small">הרשימה מבוססת על הציוד בהצעה. שמירה קובעת אותה.</p> }
      @for (s of st.shortages; track s) { <p class="short" role="alert">⚠ {{ s }} (באותו יום יוצא גם לאירועים אחרים)</p> }
      <table class="eq">
        <thead><tr><th>ציוד</th><th class="end">יוצא</th><th class="end">במלאי</th>@if (past()) { <th class="end">חזר</th> }<th></th></tr></thead>
        <tbody>
          @for (l of draft(); track l.code; let i = $index) {
            <tr [class.miss]="past() && l.returned !== null && l.returned < l.quantity">
              <td>{{ l.name }}</td>
              <td class="end"><input type="number" min="0" [ngModel]="l.quantity" (ngModelChange)="setQty(i, $event)" [name]="'q' + i" [attr.aria-label]="'כמות ' + l.name"></td>
              <td class="end num muted">{{ owned(l.code) ?? '—' }}</td>
              @if (past()) {
                <td class="end"><input type="number" min="0" [max]="l.quantity" [ngModel]="l.returned" (ngModelChange)="setRet(i, $event)" [name]="'r' + i" placeholder="?" [attr.aria-label]="'חזר ' + l.name"></td>
              }
              <td><button class="linkish" type="button" (click)="remove(i)" [attr.aria-label]="'הסרת ' + l.name">הסרה</button></td>
            </tr>
          } @empty { <tr><td colspan="5" class="muted">אין ציוד לאירוע</td></tr> }
        </tbody>
      </table>
      <div class="row">
        <select [ngModel]="''" (ngModelChange)="addType($event)" name="add" aria-label="הוספת ציוד">
          <option value="">+ הוספת ציוד מהמלאי</option>
          @for (e of stock(); track e.code) { @if (!has(e.code)) { <option [value]="e.code">{{ e.name }} ({{ e.owned }})</option> } }
        </select>
        <button class="btn ghost sm" type="button" [disabled]="busy()" (click)="save()">שמירה</button>
        @if (!past()) {
          @if (st.packed) { <span class="okc">✓ נארז ונבדק</span> <button class="linkish" type="button" (click)="save({ packed: false })">ביטול</button> }
          @else { <button class="btn sm" type="button" [disabled]="busy() || !draft().length" (click)="save({ packed: true })">סימון: נארז ונבדק</button> }
        } @else {
          <button class="btn sm" type="button" [disabled]="busy() || !draft().length" (click)="countAllBack()">הכל חזר</button>
          <button class="btn ghost sm" type="button" [disabled]="busy() || !countable()" (click)="save({ returned: true })">שמירת הספירה</button>
        }
      </div>
      @if (past() && st.missing.length) { <p class="short">לא חזרו: {{ st.missing.join(', ') }}</p> }
      @if (err()) { <p class="err" role="alert">{{ err() }}</p> }
    }
  `,
  styles: [`
    :host { display: grid; gap: 8px; }
    .small { font-size: .84rem; margin: 0; }
    .short { margin: 0; background: var(--bad-soft); color: var(--bad); border-radius: 8px; padding: 6px 10px; font-weight: 600; }
    .eq { width: 100%; border-collapse: collapse; }
    .eq th { text-align: start; font-size: .76rem; color: var(--muted); font-weight: 600; padding: 4px 6px; }
    .eq td { padding: 5px 6px; border-top: 1px solid var(--line); }
    .eq input { width: 80px; } .end { text-align: end; }
    tr.miss td { background: var(--bad-soft); }
    .row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
    .btn.sm { padding: 4px 10px; font-size: .84rem; }
    .okc { color: var(--ok); font-weight: 700; }
    .linkish { background: none; border: 0; padding: 0; color: var(--bad); text-decoration: underline; font: inherit; font-size: .84rem; cursor: pointer; }
  `],
})
export class EventEquipmentComponent {
  private api = inject(ApiService);
  dealId = input.required<string>();
  past = input(false);
  changed = output<void>();
  st = signal<EquipmentState | null>(null);
  draft = signal<EquipmentLine[]>([]);
  stock = signal<EquipmentType[]>([]);
  busy = signal(false); err = signal('');
  constructor() {
    effect(() => this.load(this.dealId()));
    this.api.stock().subscribe((s) => this.stock.set(s));
  }
  load(id = this.dealId()) {
    this.api.dealEquipment(id).subscribe((st) => { this.st.set(st); this.draft.set(st.lines.map(({ code, name, quantity, returned }) => ({ code, name, quantity, returned }))); });
  }
  owned(code: string) { return this.stock().find((e) => e.code === code)?.owned ?? null; }
  has(code: string) { return this.draft().some((l) => l.code === code); }
  countable() { return this.draft().every((l) => l.returned !== null && l.returned !== undefined); }
  setQty(i: number, v: number) { this.draft.update((d) => d.map((l, j) => j === i ? { ...l, quantity: Math.max(0, Math.round(+v || 0)) } : l)); }
  setRet(i: number, v: number | string) { this.draft.update((d) => d.map((l, j) => j === i ? { ...l, returned: v === '' || v === null ? null : Math.max(0, Math.round(+v)) } : l)); }
  remove(i: number) { this.draft.update((d) => d.filter((_, j) => j !== i)); }
  addType(code: string) {
    const e = this.stock().find((x) => x.code === code);
    if (e) this.draft.update((d) => [...d, { code: e.code, name: e.name, quantity: 1, returned: null }]);
  }
  countAllBack() { this.draft.update((d) => d.map((l) => ({ ...l, returned: l.quantity }))); this.save({ returned: true }); }
  save(flags: { packed?: boolean; returned?: boolean } = {}) {
    this.busy.set(true); this.err.set('');
    this.api.putDealEquipment(this.dealId(), this.draft(), flags).subscribe({
      next: (st) => { this.busy.set(false); this.st.set(st); this.changed.emit(); },
      error: (e) => { this.busy.set(false); this.err.set(e.error?.detail ?? 'השמירה נכשלה'); },
    });
  }
}

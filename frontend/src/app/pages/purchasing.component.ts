import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../core/api.service';
import { HeDatePipe, IlsPipe } from '../core/format';
import { ImportReport, Ingredient, PurchaseList, Supplier } from '../core/models';

const iso = (d: Date) => d.toISOString().slice(0, 10);
const plus = (n: number) => { const d = new Date(); d.setDate(d.getDate() + n); return iso(d); };
// Hebrew day letters, Sunday first; values are Python weekdays (0 = Monday)
const DAYS: [number, string][] = [[6, 'א'], [0, 'ב'], [1, 'ג'], [2, 'ד'], [3, 'ה'], [4, 'ו'], [5, 'ש']];
const UNITS: [Ingredient['unit'], string][] = [['kg', 'ק"ג'], ['liter', 'ליטר'], ['unit', "יח'"]];
const KASHRUT: [Ingredient['kashrut'], string][] = [['pareve', 'פרווה'], ['meat', 'בשרי'], ['dairy', 'חלבי']];

@Component({
  selector: 'app-purchasing',
  standalone: true,
  imports: [FormsModule, IlsPipe, HeDatePipe],
  template: `
    <div class="page-head">
      <div><h1>רכש וספקים</h1><p>מה להזמין, מאיזה ספק ועד מתי, לכל האירועים הסגורים בטווח. מחירים לפני מע"מ, רק לך.</p></div>
      <div class="tabs" role="tablist">
        @for (t of tabs; track t[0]) { <button role="tab" [attr.aria-selected]="tab() === t[0]" [class.on]="tab() === t[0]" (click)="tab.set(t[0])">{{ t[1] }}</button> }
      </div>
    </div>
    @if (msg()) { <p class="note" [class.bad]="msgBad()" role="status">{{ msg() }}</p> }

    <!-- purchase list -->
    @if (tab() === 'list') {
      <div class="row">
        <label>אירועים מ-<input type="date" [(ngModel)]="start" (ngModelChange)="loadList()"></label>
        <label>עד<input type="date" [(ngModel)]="end" (ngModelChange)="loadList()"></label>
        <button class="btn ghost" (click)="exportXlsx()">ייצוא לאקסל</button>
      </div>
      @if (pl(); as list) {
        @if (list.missing_recipes.length || list.unknown_ingredients.length || list.missing_quantities.length || list.missing_prices.length) {
          <section class="card gaps" aria-label="חסרים נתונים">
            <h2>חסרים נתונים, לכן הרשימה לא מלאה</h2>
            @if (list.missing_recipes.length) { <p><b>מנות בלי מתכון</b> (לא נכנסו לרשימה): {{ names(list.missing_recipes) }}</p> }
            @if (list.missing_quantities.length) { <p><b>מנות בלי כמות</b>: @for (m of list.missing_quantities; track m.name) { {{ m.name }} ({{ m.problem }}) } </p> }
            @if (list.unknown_ingredients.length) { <p><b>חומרי גלם שלא קיימים</b>: @for (u of list.unknown_ingredients; track u.code) { {{ u.code }} ב{{ u.dishes.join(', ') }} } </p> }
            @if (list.missing_prices.length) { <p><b>בלי מחיר</b> (אין סכום משוער): {{ list.missing_prices.join(', ') }}</p> }
          </section>
        }
        @for (o of list.suppliers; track $index) {
          <section class="card sup" [class.nosup]="!o.code">
            <header class="sup-h">
              <div><h2>{{ o.name }}</h2>
                @if (o.code) { <small class="muted">{{ o.phone }} · אספקה תוך {{ o.lead_days }} ימים · ימי אספקה: {{ o.delivery_days.join(', ') }}</small> }
                @else { <small class="muted">חומרי גלם שלא שויכו לספק. אפשר לשייך בלשונית חומרי גלם.</small> }</div>
              @if (o.total !== null) { <b class="num">{{ o.total | ils }}</b> }
            </header>
            @for (b of o.batches; track b.deliver_on) {
              <div class="batch">
                <div class="batch-h">
                  <span>אספקה {{ weekday(b.deliver_on) }} {{ b.deliver_on | heDate }}</span>
                  @if (b.order_by) {
                    <span class="due" [class.late]="b.late">להזמין עד: {{ weekday(b.order_by) }} {{ b.order_by | heDate:true }}@if (b.late) { · עבר המועד }</span>
                  }
                  <span class="acts">
                    @if (b.whatsapp_url) { <a class="btn sm" [href]="b.whatsapp_url" target="_blank" rel="noopener">שליחה בוואטסאפ</a> }
                    <button class="btn ghost sm" type="button" (click)="copy(b.text)">העתקת ההזמנה</button>
                  </span>
                </div>
                <table class="items">
                  <thead><tr><th>חומר גלם</th><th class="end">כמות</th><th class="end">מחיר</th><th class="end">סה"כ</th><th>עבור</th></tr></thead>
                  <tbody>
                    @for (it of b.items; track it.code) {
                      <tr>
                        <td><b>{{ it.name }}</b></td>
                        <td class="end num">{{ it.quantity }} {{ it.unit }}</td>
                        <td class="end num">@if (it.price !== null) { {{ it.price | ils:2 }} } @else { <span class="miss">אין מחיר</span> }</td>
                        <td class="end num">{{ it.cost | ils }}</td>
                        <td class="small muted">{{ it.dishes.join(', ') }}</td>
                      </tr>
                    }
                  </tbody>
                </table>
              </div>
            }
          </section>
        } @empty { <p class="card empty">אין אירועים סגורים עם מתכונים בטווח הזה.</p> }
      }
    }

    <!-- suppliers -->
    @if (tab() === 'suppliers') {
      <div class="row"><button class="btn" (click)="addSupplier()">+ ספק חדש</button><button class="btn ghost" (click)="importing.set(!importing())">ייבוא מאקסל</button></div>
      <div class="card list">
        <table class="edit">
          <thead><tr><th>ספק</th><th>טלפון</th><th>ימים לאספקה</th><th>ימי אספקה</th><th>סגירת הזמנות</th><th></th></tr></thead>
          <tbody>
            @for (s of sups(); track s.code) {
              <tr>
                <td data-l="ספק"><input [(ngModel)]="s.name" [name]="'sn' + s.code" (change)="saveSupplier(s)" [attr.aria-label]="'שם ' + s.code"><small class="muted">{{ s.code }}</small></td>
                <td data-l="טלפון"><input [(ngModel)]="s.phone" [name]="'sp' + s.code" (change)="saveSupplier(s)" inputmode="tel" [attr.aria-label]="'טלפון ' + s.name"></td>
                <td data-l="ימים לאספקה"><input class="n" type="number" min="0" max="60" [(ngModel)]="s.lead_days" [name]="'sl' + s.code" (change)="saveSupplier(s)" [attr.aria-label]="'ימים לאספקה ' + s.name"></td>
                <td data-l="ימי אספקה"><span class="days">@for (d of days; track d[0]) {
                  <button type="button" class="day" [class.on]="s.delivery_days.includes(d[0])" [attr.aria-pressed]="s.delivery_days.includes(d[0])" (click)="toggleDay(s, d[0])" [attr.aria-label]="'יום ' + d[1] + ' ' + s.name">{{ d[1] }}</button> }</span></td>
                <td data-l="סגירת הזמנות"><input type="time" [(ngModel)]="s.order_cutoff" [name]="'sc' + s.code" (change)="saveSupplier(s)" [attr.aria-label]="'שעת סגירה ' + s.name"></td>
                <td><button class="linkish bad" type="button" (click)="removeSupplier(s)">מחיקה</button></td>
              </tr>
            }
          </tbody>
        </table>
      </div>
    }

    <!-- ingredients -->
    @if (tab() === 'ingredients') {
      <div class="row">
        <input type="search" placeholder="חיפוש" [ngModel]="q()" (ngModelChange)="q.set($event)" aria-label="חיפוש חומר גלם">
        <button class="chip" [class.on]="onlyGaps()" (click)="onlyGaps.set(!onlyGaps())">בלי ספק או מחיר ({{ gaps() }})</button>
        <button class="btn" (click)="addIngredient()">+ חומר גלם</button>
        <button class="btn ghost" (click)="importing.set(!importing())">ייבוא מאקסל</button>
      </div>
      <div class="card list">
        <table class="edit">
          <thead><tr><th>חומר גלם</th><th>יחידה</th><th>כשרות</th><th>ספק</th><th>מחיר ליחידה ₪</th><th></th></tr></thead>
          <tbody>
            @for (i of shownIngs(); track i.code) {
              <tr>
                <td data-l="חומר גלם"><input [(ngModel)]="i.name_he" [name]="'in' + i.code" (change)="saveIngredient(i)" [attr.aria-label]="'שם ' + i.code"><small class="muted">{{ i.code }}</small></td>
                <td data-l="יחידה"><select [(ngModel)]="i.unit" [name]="'iu' + i.code" (change)="saveIngredient(i)" [attr.aria-label]="'יחידה ' + i.name_he">@for (u of units; track u[0]) { <option [value]="u[0]">{{ u[1] }}</option> }</select></td>
                <td data-l="כשרות"><select [(ngModel)]="i.kashrut" [name]="'ik' + i.code" (change)="saveIngredient(i)" [attr.aria-label]="'כשרות ' + i.name_he">@for (k of kashrut; track k[0]) { <option [value]="k[0]">{{ k[1] }}</option> }</select></td>
                <td data-l="ספק"><select [(ngModel)]="i.supplier" [name]="'is' + i.code" (change)="saveIngredient(i)" [class.empty]="!i.supplier" [attr.aria-label]="'ספק ' + i.name_he">
                  <option [ngValue]="null">בלי ספק</option>@for (s of sups(); track s.code) { <option [ngValue]="s.code">{{ s.name }}</option> }</select></td>
                <td data-l="מחיר"><input class="n" type="number" min="0" step="0.01" [ngModel]="i.price" (ngModelChange)="i.price = $event === '' || $event === null ? null : +$event"
                       [name]="'ip' + i.code" (change)="saveIngredient(i)" placeholder="לא ידוע" [class.empty]="i.price === null" [attr.aria-label]="'מחיר ' + i.name_he"></td>
                <td><button class="linkish bad" type="button" (click)="removeIngredient(i)">מחיקה</button></td>
              </tr>
            }
          </tbody>
        </table>
      </div>
    }

    @if (importing() && tab() !== 'list') {
      <section class="card import">
        <h2>ייבוא ספקים, חומרי גלם ומתכונים</h2>
        <ol>
          <li><button class="linkish" type="button" (click)="template()">הורדת קובץ אקסל</button> עם הספקים, חומרי הגלם והמתכונים הנוכחיים, למילוי.</li>
          <li>מעלים את הקובץ ורואים מה ישתנה, לפני שמשהו נשמר.</li>
        </ol>
        <input type="file" accept=".xlsx,.csv" (change)="pick($any($event.target).files?.[0])" aria-label="קובץ לייבוא">
        @if (report(); as r) {
          <div class="report">
            <p><b>{{ r.creates.length }} חדשים · {{ r.updates.length }} עדכונים · {{ r.unchanged }} ללא שינוי</b>@if (r.errors.length) { · <span class="bad">{{ r.errors.length }} שורות נדחו</span> }</p>
            @if (r.errors.length) {
              <table class="errs"><thead><tr><th>גיליון</th><th>שורה</th><th>עמודה</th><th>בעיה</th></tr></thead>
                <tbody>@for (e of r.errors; track $index) { <tr><td>{{ e.sheet }}</td><td>{{ e.row }}</td><td>{{ e.column }}</td><td>{{ e.message }}</td></tr> }</tbody></table>
            }
            @if (!r.applied && (r.creates.length || r.updates.length)) {
              <button class="btn" [disabled]="busy()" (click)="applyImport()">שמירת {{ r.creates.length + r.updates.length }} השינויים</button>
            }
            @if (r.applied) { <p class="ok">הייבוא נשמר</p> }
          </div>
        }
      </section>
    }
  `,
  styles: [`
    .tabs { display: flex; gap: 6px; flex-wrap: wrap; }
    .tabs button { border: 1px solid var(--line); background: var(--surface); border-radius: 99px; padding: 6px 14px; font: inherit; cursor: pointer; }
    .tabs button.on { background: var(--olive); color: #fff; border-color: var(--olive); }
    .row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 12px; }
    .row label { display: flex; gap: 6px; align-items: center; }
    .note { background: var(--ok-soft); color: var(--ok); border-radius: 8px; padding: 6px 12px; } .note.bad { background: var(--bad-soft); color: var(--bad); }
    .gaps { border-color: var(--warn); margin-bottom: 12px; } .gaps h2 { font-size: 1rem; margin: 0 0 6px; color: var(--warn); } .gaps p { margin: 4px 0; font-size: .9rem; }
    .sup { margin-bottom: 12px; display: grid; gap: 10px; } .sup.nosup { border-style: dashed; }
    .sup-h { display: flex; justify-content: space-between; align-items: flex-start; gap: 10px; }
    .sup-h h2 { margin: 0; font-size: 1.1rem; } .sup-h b { font-family: var(--display); font-size: 1.2rem; }
    .batch { border-top: 1px solid var(--line); padding-top: 8px; }
    .batch-h { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; margin-bottom: 6px; font-weight: 600; }
    .due { background: var(--paper); border-radius: 8px; padding: 2px 10px; }
    .due.late { background: var(--bad-soft); color: var(--bad); }
    .acts { display: flex; gap: 6px; margin-inline-start: auto; }
    .btn.sm { padding: 4px 10px; font-size: .85rem; text-decoration: none; }
    table { width: 100%; border-collapse: collapse; }
    th { text-align: start; font-size: .76rem; color: var(--muted); font-weight: 600; padding: 4px 6px; }
    td { padding: 6px; border-top: 1px solid var(--line); vertical-align: top; }
    .end { text-align: end; } .small { font-size: .8rem; }
    .miss { font-size: .75rem; color: var(--warn); background: var(--warn-soft); border-radius: 6px; padding: 1px 6px; }
    .edit input:not(.n) { width: 100%; min-width: 120px; box-sizing: border-box; } .edit input.n { width: 90px; }
    .edit td small { display: block; font-size: .7rem; }
    .empty { border-style: dashed; border-color: var(--warn); }
    .days { display: inline-flex; gap: 3px; }
    .day { width: 28px; height: 28px; border-radius: 50%; border: 1px solid var(--line); background: var(--surface); font: inherit; font-size: .82rem; cursor: pointer; padding: 0; }
    .day.on { background: var(--olive); color: #fff; border-color: var(--olive); }
    .chip.on { background: var(--olive); color: #fff; border-color: var(--olive); }
    .linkish { background: none; border: 0; padding: 0; color: var(--olive); text-decoration: underline; font: inherit; font-weight: 700; cursor: pointer; } .linkish.bad, .bad { color: var(--bad); }
    .import { margin-top: 14px; display: grid; gap: 10px; } .import ol { margin: 0; padding-inline-start: 20px; color: var(--muted); }
    .report { border-top: 1px solid var(--line); padding-top: 10px; display: grid; gap: 8px; } .errs td { color: var(--bad); font-size: .88rem; } .ok { color: var(--ok); }
    @media (max-width: 760px) {
      table.edit thead, table.items thead { display: none; }
      table.edit tr, table.items tr { display: grid; grid-template-columns: 1fr 1fr; gap: 4px 10px; padding: 8px 0; border-top: 1px solid var(--line); }
      table.edit td, table.items td { border: 0; padding: 2px 0; }
      table.edit td:first-child, table.items td:first-child { grid-column: 1 / -1; }
      table.edit td[data-l]:not(:first-child)::before { content: attr(data-l); display: block; font-size: .72rem; color: var(--muted); }
      .acts { margin-inline-start: 0; }
    }
  `],
})
export class PurchasingComponent {
  private api = inject(ApiService);
  tabs: ['list' | 'suppliers' | 'ingredients', string][] = [['list', 'רשימת רכש'], ['suppliers', 'ספקים'], ['ingredients', 'חומרי גלם']];
  tab = signal<'list' | 'suppliers' | 'ingredients'>('list');
  start = plus(0); end = plus(7);
  pl = signal<PurchaseList | null>(null);
  sups = signal<Supplier[]>([]);
  ings = signal<Ingredient[]>([]);
  q = signal(''); onlyGaps = signal(false);
  msg = signal(''); msgBad = signal(false); busy = signal(false);
  importing = signal(false); report = signal<ImportReport | null>(null);
  private file: File | null = null;
  days = DAYS; units = UNITS; kashrut = KASHRUT;
  gaps = computed(() => this.ings().filter((i) => !i.supplier || i.price === null).length);
  shownIngs = computed(() => this.ings().filter((i) => (!this.q() || i.name_he.includes(this.q()) || i.code.includes(this.q().toUpperCase()))
    && (!this.onlyGaps() || !i.supplier || i.price === null)));

  constructor() { this.loadList(); this.loadLists(); }
  loadList() { this.api.purchaseList(this.start, this.end).subscribe({ next: (p) => this.pl.set(p), error: (e) => this.flash(e.error?.detail ?? 'לא ניתן לטעון', true) }); }
  loadLists() { this.api.suppliers().subscribe((s) => this.sups.set(s)); this.api.ingredients().subscribe((i) => this.ings.set(i)); }
  flash(m: string, bad = false) { this.msg.set(m); this.msgBad.set(bad); setTimeout(() => this.msg.set(''), 3500); }
  names(x: { name: string }[]) { return x.map((m) => m.name).join(', '); }
  weekday(d: string) { return new Date(d.length === 10 ? d + 'T12:00:00' : d).toLocaleDateString('he-IL', { weekday: 'short' }); }
  copy(text: string) { navigator.clipboard?.writeText(text).then(() => this.flash('ההזמנה הועתקה'), () => this.flash('לא הצלחנו להעתיק', true)); }
  exportXlsx() { this.api.purchaseXlsx(this.start, this.end).subscribe((b) => this.download(b, `purchase-${this.start}.xlsx`)); }
  template() { this.api.purchasingTemplate().subscribe((b) => this.download(b, 'suppliers-and-recipes.xlsx')); }
  private download(b: Blob, name: string) {
    const a = document.createElement('a'); a.href = URL.createObjectURL(b); a.download = name; a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  // suppliers
  saveSupplier(s: Supplier) {
    this.api.putSupplier(s).subscribe({ next: () => { this.flash(`${s.name} נשמר`); this.loadList(); }, error: (e) => this.flash(this.err(e), true) });
  }
  toggleDay(s: Supplier, d: number) {
    const next = s.delivery_days.includes(d) ? s.delivery_days.filter((x) => x !== d) : [...s.delivery_days, d];
    if (!next.length) { this.flash('צריך לפחות יום אספקה אחד', true); return; }
    s.delivery_days = next; this.saveSupplier(s);
  }
  addSupplier() {
    const code = 'SUP-' + Date.now().toString(36).toUpperCase();
    const s: Supplier = { code, name: 'ספק חדש', phone: '', email: '', lead_days: 1, delivery_days: [6, 0, 1, 2, 3], order_cutoff: '12:00', notes: '' };
    this.api.putSupplier(s).subscribe({ next: () => { this.loadLists(); this.flash('ספק נוסף. אפשר לערוך את הפרטים בטבלה.'); }, error: (e) => this.flash(this.err(e), true) });
  }
  removeSupplier(s: Supplier) {
    if (!confirm(`למחוק את ${s.name}? חומרי הגלם שלו יישארו בלי ספק.`)) return;
    this.api.deleteSupplier(s.code).subscribe({ next: () => { this.loadLists(); this.loadList(); this.flash(`${s.name} נמחק`); } });
  }

  // ingredients
  saveIngredient(i: Ingredient) {
    if (i.price !== null && !(i.price >= 0)) { this.flash('מחיר לא יכול להיות שלילי', true); return; }
    this.api.putIngredient(i).subscribe({ next: () => { this.flash(`${i.name_he} נשמר`); this.loadList(); }, error: (e) => this.flash(this.err(e), true) });
  }
  addIngredient() {
    const code = 'ING-' + Date.now().toString(36).toUpperCase();
    const i: Ingredient = { code, name_he: 'חומר גלם חדש', unit: 'kg', kashrut: 'pareve', supplier: null, price: null };
    this.api.putIngredient(i).subscribe({ next: () => { this.q.set(''); this.loadLists(); this.flash('נוסף. אפשר לערוך בטבלה.'); } });
  }
  removeIngredient(i: Ingredient) {
    if (!confirm(`למחוק את ${i.name_he}?`)) return;
    this.api.deleteIngredient(i.code).subscribe({ next: () => { this.loadLists(); this.flash(`${i.name_he} נמחק`); }, error: (e) => this.flash(this.err(e), true) });
  }

  // import
  pick(f: File | undefined) {
    if (!f) return;
    this.file = f; this.report.set(null); this.busy.set(true);
    this.api.importPurchasing(f).subscribe({ next: (r) => { this.report.set(r); this.busy.set(false); }, error: (e) => { this.busy.set(false); this.flash(this.err(e), true); } });
  }
  applyImport() {
    if (!this.file) return;
    this.busy.set(true);
    this.api.importPurchasing(this.file, true).subscribe({
      next: (r) => { this.report.set(r); this.busy.set(false); this.loadLists(); this.loadList(); this.flash('הייבוא נשמר'); },
      error: () => { this.busy.set(false); this.flash('השמירה נכשלה', true); },
    });
  }
  private err(e: { error?: { detail?: unknown } }) {
    const d = e.error?.detail;
    return typeof d === 'string' ? d : Array.isArray(d) ? 'ערך לא תקין' : 'השמירה נכשלה';
  }
}

import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { ApiService } from '../core/api.service';
import { HeDatePipe, IlsPipe } from '../core/format';
import { CATEGORY, MEAL, UNIT } from '../core/labels';
import { CatalogItem, ImpactRow, ImportReport } from '../core/models';

const SOURCE: Record<string, string> = { manual: 'ידני', supplier: 'ספק', recipe: 'מתכון', components: 'מהרכיבים' };
const FIELD: Record<string, string> = { name_he: 'שם', category: 'קטגוריה', unit: 'יחידה', price: 'מחיר', cost: 'עלות', cost_source: 'מקור עלות', meal_type: 'סוג', serves: 'סועדים ליחידה', components: 'רכיבים', active: 'פעיל' };

@Component({
  selector: 'app-menu',
  standalone: true,
  imports: [FormsModule, IlsPipe, HeDatePipe, RouterLink],
  template: `
    <div class="page-head">
      <div><h1>תפריט ומחירים</h1><p>מחיר ועלות לפני מע"מ. העלות והרווח מוצגים רק לך, אף פעם לא ללקוח.</p></div>
      <div class="head-actions">
        <button class="btn ghost" (click)="importing.set(!importing())">ייבוא מאקסל</button>
        <button class="btn" (click)="adding.set(!adding())">+ פריט חדש</button>
      </div>
    </div>

    @if (importing()) {
      <section class="card import">
        <h2>ייבוא תפריט ועלויות</h2>
        <ol>
          <li><button class="linkish" type="button" (click)="downloadTemplate()">הורדת קובץ אקסל</button> עם התפריט הנוכחי ועמודת עלות למילוי. אפשר גם קובץ CSV משלך עם עמודות מק"ט ועלות.</li>
          <li>מעלים את הקובץ ורואים מה ישתנה, לפני שמשהו נשמר.</li>
        </ol>
        <input type="file" accept=".xlsx,.csv" (change)="pick($any($event.target).files?.[0])" aria-label="קובץ לייבוא">
        @if (report(); as r) {
          <div class="report">
            <p><b>{{ r.rows }} שורות:</b> {{ r.creates.length }} פריטים חדשים · {{ r.updates.length }} עדכונים · {{ r.unchanged }} ללא שינוי · <span [class.bad]="r.errors.length">{{ r.errors.length }} שורות עם שגיאה</span></p>
            @if (r.errors.length) {
              <table class="errs">
                <thead><tr><th>גיליון</th><th>שורה</th><th>עמודה</th><th>מה לא תקין</th></tr></thead>
                <tbody>@for (e of r.errors; track $index) { <tr><td>{{ e.sheet }}</td><td class="num">{{ e.row }}</td><td>{{ e.column }}</td><td>{{ e.message }}</td></tr> }</tbody>
              </table>
            }
            @if (r.updates.length || r.creates.length) {
              <details [open]="r.updates.length + r.creates.length <= 12">
                <summary>מה ישתנה</summary>
                <ul class="changes">
                  @for (c of r.creates; track c.sku) { <li><span class="pill ok">חדש</span> {{ c.name }}</li> }
                  @for (u of r.updates; track u.sku) { <li><b>{{ u.name }}</b>: @for (f of fields(u.fields); track f.k) { <span class="chg">{{ f.label }} {{ f.from }} ← {{ f.to }}</span> }</li> }
                </ul>
              </details>
            }
            @if (r.applied) { <p class="note">הייבוא נשמר.</p> }
            @else if (r.updates.length || r.creates.length) {
              <button class="btn" (click)="applyImport()" [disabled]="busy()">שמירת {{ r.updates.length + r.creates.length }} השינויים התקינים</button>
              @if (r.errors.length) { <small class="muted"> השורות עם שגיאה לא יישמרו. אפשר לתקן בקובץ ולהעלות שוב.</small> }
            }
          </div>
        }
      </section>
    }

    @if (adding()) {
      <form class="card add" (ngSubmit)="add()">
        <input name="n" [(ngModel)]="nw.name_he" placeholder="שם הפריט" required aria-label="שם">
        <select name="c" [(ngModel)]="nw.category" aria-label="קטגוריה">@for (c of cats; track c[0]) { <option [value]="c[0]">{{ c[1] }}</option> }</select>
        <select name="u" [(ngModel)]="nw.unit" aria-label="יחידה">@for (u of units; track u[0]) { <option [value]="u[0]">{{ u[1] }}</option> }</select>
        <select name="m" [(ngModel)]="nw.meal_type" aria-label="בשרי/חלבי">@for (m of meals; track m[0]) { <option [value]="m[0]">{{ m[1] }}</option> }</select>
        <input name="p" type="number" min="1" step="0.5" [(ngModel)]="nw.price" placeholder="מחיר ₪" aria-label="מחיר">
        <input name="k" type="number" min="0" step="0.5" [(ngModel)]="nw.cost" placeholder="עלות ₪ (אם ידועה)" aria-label="עלות">
        <input name="s" type="number" min="1" [(ngModel)]="nw.serves" placeholder="מספיק ל-X אורחים" aria-label="מספיק ל">
        <input name="d" [(ngModel)]="nw.description_he" placeholder="תיאור קצר" aria-label="תיאור" class="wide">
        <button class="btn" [disabled]="!nw.name_he || !nw.price">הוספה</button>
      </form>
    }
    @if (msg()) { <p class="note" [class.bad]="msgBad()" role="status">{{ msg() }}</p> }

    @if (impact().length) {
      <section class="card impact" role="alert">
        <div class="impact-head"><h2>ההתייקרות של {{ impactName() }} פוגעת ברווח</h2><button class="linkish" (click)="impact.set([])">סגירה</button></div>
        <table>
          <thead><tr><th></th><th>אירוע</th><th>תאריך</th><th>רווח לפני</th><th>רווח עכשיו</th><th>שינוי</th></tr></thead>
          <tbody>
            @for (r of impact(); track r.quote_id) {
              <tr>
                <td><span class="pill" [class.warn]="r.kind === 'open_quote'" [class.ok]="r.kind === 'booked_event'">{{ r.kind === 'open_quote' ? 'הצעה פתוחה' : 'אירוע סגור' }}</span></td>
                <td><a [routerLink]="['/quotes', r.quote_id]">{{ r.title }}</a></td>
                <td>{{ r.event_date | heDate }}</td>
                <td class="num">{{ r.profit_before | ils }} @if (r.margin_before !== null) { <small class="muted">({{ pct(r.margin_before) }})</small> }</td>
                <td class="num">{{ r.profit_after | ils }} @if (r.margin_after !== null) { <small class="muted">({{ pct(r.margin_after) }})</small> }</td>
                <td class="num bad">{{ r.delta | ils }}</td>
              </tr>
            }
          </tbody>
        </table>
        <p class="muted small">בהצעה פתוחה אפשר לעדכן מחיר לפני שהלקוח מאשר. באירוע סגור המחיר ללקוח נשאר כפי שסוכם.</p>
      </section>
    }

    <div class="filters">
      <input type="search" placeholder="חיפוש" [ngModel]="q()" (ngModelChange)="q.set($event)" aria-label="חיפוש">
      <button class="chip" [class.on]="!cat() && !onlyMissing()" (click)="cat.set(''); onlyMissing.set(false)">הכל</button>
      <button class="chip miss" [class.on]="onlyMissing()" (click)="onlyMissing.set(!onlyMissing())">עלות חסרה ({{ missingCount() }})</button>
      @for (c of usedCats(); track c) { <button class="chip" [class.on]="cat() === c" (click)="cat.set(c)">{{ catLabel[c] || c }}</button> }
    </div>

    <div class="card list">
      <table class="items">
        <thead><tr><th>פריט</th><th>קטגוריה</th><th>יחידה</th><th>מחיר ₪</th><th>עלות ₪</th><th>רווח לפריט</th><th>זמין</th></tr></thead>
        <tbody>
          @for (i of shown(); track i.sku) {
            <tr [class.off]="!i.active">
              <td data-l="פריט"><b>{{ i.name_he }}</b><div class="muted small">{{ i.description_he }}</div></td>
              <td data-l="קטגוריה">{{ catLabel[i.category] || i.category }}</td>
              <td data-l="יחידה">{{ unitLabel[i.unit] }}@if (i.serves) { <small class="muted"> · ל-{{ i.serves }}</small> }</td>
              <td data-l="מחיר"><input class="money" type="number" min="1" step="0.5" [value]="i.price" (change)="setPrice(i, $any($event.target).value)" [attr.aria-label]="'מחיר ' + i.name_he"></td>
              <td data-l="עלות" class="cost">
                @if (isPackage(i)) {
                  @if (i.unit_cost !== null && i.unit_cost !== undefined) { <span class="num">{{ i.unit_cost | ils: 1 }}</span><small class="muted">מחושב מ-{{ i.components?.length }} רכיבים</small> }
                  @else { <span class="missing" [title]="'חסרה עלות: ' + (i.cost_missing ?? []).join(', ')">עלות חסרה</span><small class="muted">{{ (i.cost_missing ?? []).join(', ') }}</small> }
                } @else {
                  <input class="money" type="number" min="0" step="0.5" [value]="i.cost ?? ''" placeholder="לא ידוע" [class.empty]="i.cost == null"
                         (change)="setCost(i, $any($event.target).value)" [attr.aria-label]="'עלות ' + i.name_he">
                  @if (i.cost == null) { <span class="missing">עלות חסרה</span> }
                  @else if (i.cost_updated_at) { <small class="muted">{{ source[i.cost_source || 'manual'] }} · {{ i.cost_updated_at | heDate }}</small> }
                }
              </td>
              <td data-l="רווח לפריט" class="num">@if (i.item_margin != null) { <span [class.low]="i.item_margin < floor()">{{ pct(i.item_margin) }}</span> } @else { <span class="muted">—</span> }</td>
              <td data-l="זמין"><label class="sw"><input type="checkbox" [checked]="i.active" (change)="toggle(i)" [attr.aria-label]="'זמין ' + i.name_he"> {{ i.active ? 'כן' : 'לא' }}</label></td>
            </tr>
          } @empty { <tr><td colspan="7" class="muted">אין פריטים שמתאימים לסינון.</td></tr> }
        </tbody>
      </table>
    </div>
  `,
  styles: [`
    .head-actions { display: flex; gap: 8px; }
    .add { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; } .add .wide { flex: 1; min-width: 200px; }
    .filters { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; margin-bottom: 10px; }
    .chip.on { background: var(--olive); color: #fff; border-color: var(--olive); }
    .chip.miss { border-color: var(--warn); color: var(--warn); } .chip.miss.on { background: var(--warn); color: #fff; }
    .money { width: 92px; font-variant-numeric: tabular-nums; }
    .money.empty { border-style: dashed; border-color: var(--warn); }
    .cost { display: flex; flex-direction: column; gap: 3px; align-items: flex-start; }
    .missing { display: inline-block; background: var(--warn-soft); color: var(--warn); font-weight: 700; font-size: .78rem; border-radius: 6px; padding: 1px 7px; }
    .low { color: var(--bad); font-weight: 700; }
    tr.off td { opacity: .5; } .small, small { font-size: .78rem; }
    .note { background: var(--ok-soft); color: var(--ok); border-radius: 8px; padding: 6px 12px; } .note.bad { background: var(--bad-soft); color: var(--bad); }
    .sw { display: flex; gap: 6px; align-items: center; }
    .bad { color: var(--bad); }
    .linkish { background: none; border: 0; padding: 0; color: var(--olive); text-decoration: underline; font-weight: 700; }
    .import { margin-bottom: 14px; display: grid; gap: 10px; } .import ol { margin: 0; padding-inline-start: 20px; color: var(--muted); }
    .report { border-top: 1px solid var(--line); padding-top: 10px; display: grid; gap: 8px; }
    .errs td { color: var(--bad); font-size: .88rem; } .changes { margin: 6px 0; padding-inline-start: 18px; } .chg { margin-inline-end: 10px; color: var(--muted); }
    .impact { border-color: var(--bad); margin-bottom: 14px; } .impact-head { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 8px; }
    @media (max-width: 760px) {
      table.items thead { display: none; }
      table.items tr { display: grid; grid-template-columns: 1fr 1fr; gap: 4px 12px; padding: 10px 0; border-bottom: 1px solid var(--line); }
      table.items td { border: 0; padding: 2px 0; }
      table.items td:first-child { grid-column: 1 / -1; }
      table.items td[data-l]:not(:first-child)::before { content: attr(data-l); display: block; font-size: .72rem; color: var(--muted); }
      .impact table { font-size: .85rem; }
    }
  `],
})
export class MenuComponent {
  private api = inject(ApiService);
  items = signal<CatalogItem[]>([]);
  q = signal(''); cat = signal(''); onlyMissing = signal(false);
  adding = signal(false); importing = signal(false); busy = signal(false);
  msg = signal(''); msgBad = signal(false);
  impact = signal<ImpactRow[]>([]); impactName = signal('');
  report = signal<ImportReport | null>(null);
  floor = signal(0.3);
  private file: File | null = null;
  catLabel = CATEGORY; unitLabel = UNIT; mealLabel = MEAL; source = SOURCE;
  cats = Object.entries(CATEGORY).filter(([k]) => !['staff', 'logistics'].includes(k));
  units = Object.entries(UNIT); meals = Object.entries(MEAL);
  nw: Partial<CatalogItem> = { category: 'main', unit: 'per_guest', meal_type: 'meat', tags: [], description_he: '' };
  usedCats = computed(() => [...new Set(this.items().map((i) => i.category))]);
  missingCount = computed(() => this.items().filter((i) => i.active && i.unit_cost == null).length);
  shown = computed(() => this.items().filter((i) =>
    (!this.cat() || i.category === this.cat()) && (!this.q() || i.name_he.includes(this.q()))
    && (!this.onlyMissing() || i.unit_cost == null)));

  constructor() {
    this.load();
    this.api.settings().subscribe((s) => this.floor.set(s.profit_floor));
  }
  load() { this.api.catalog().subscribe((i) => this.items.set(i)); }
  isPackage(i: CatalogItem) { return i.category === 'package'; }
  pct(x: number) { return `${Math.round(x * 100)}%`; }
  flash(m: string, bad = false) { this.msg.set(m); this.msgBad.set(bad); setTimeout(() => this.msg.set(''), 3000); }

  setPrice(i: CatalogItem, v: string) {
    const price = +v;
    if (!(price > 0)) { this.flash('מחיר חייב להיות חיובי', true); return; }
    this.api.patchItem(i.sku, { price }).subscribe({ next: (r) => { this.load(); this.flash(`המחיר של ${r.item.name_he} עודכן ל-₪${r.item.price}`); } });
  }
  setCost(i: CatalogItem, v: string) {
    const cost = v === '' ? null : +v;
    if (cost !== null && !(cost >= 0)) { this.flash('עלות לא יכולה להיות שלילית', true); return; }
    this.api.patchItem(i.sku, { cost }).subscribe({
      next: (r) => {
        this.load();
        this.flash(cost === null ? `העלות של ${r.item.name_he} סומנה כלא ידועה` : `העלות של ${r.item.name_he} עודכנה`);
        this.impact.set(r.cost_impact); this.impactName.set(r.item.name_he);
      },
      error: (e) => this.flash(e.error?.detail ?? 'העדכון נכשל', true),
    });
  }
  toggle(i: CatalogItem) {
    this.api.patchItem(i.sku, { active: !i.active }).subscribe((r) => { this.load(); this.flash(r.item.active ? `${r.item.name_he} זמין שוב` : `${r.item.name_he} לא יוצע ללקוחות`); });
  }
  add() {
    const sku = 'CUS-' + Date.now().toString(36).toUpperCase();
    this.api.addItem({ ...this.nw, sku, name_en: this.nw.name_he ?? '', serves: this.nw.serves || null, cost: this.nw.cost ?? null,
                       cost_source: this.nw.cost != null ? 'manual' : null }).subscribe({
      next: () => { this.adding.set(false); this.flash('הפריט נוסף'); this.load(); this.nw = { category: 'main', unit: 'per_guest', meal_type: 'meat', tags: [], description_he: '' }; },
      error: () => this.flash('לא הצלחנו להוסיף את הפריט', true),
    });
  }

  downloadTemplate() {
    this.api.importTemplate().subscribe((b) => {
      const a = document.createElement('a');
      a.href = URL.createObjectURL(b); a.download = 'menu-and-costs.xlsx'; a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    });
  }
  pick(f: File | undefined) {
    if (!f) return;
    this.file = f; this.report.set(null); this.busy.set(true);
    this.api.importCatalog(f).subscribe({
      next: (r) => { this.report.set(r); this.busy.set(false); },
      error: (e) => { this.busy.set(false); this.flash(e.error?.detail ?? 'הקובץ לא נקלט', true); },
    });
  }
  applyImport() {
    if (!this.file) return;
    this.busy.set(true);
    this.api.importCatalog(this.file, true).subscribe({
      next: (r) => { this.report.set(r); this.busy.set(false); this.load(); this.flash('הייבוא נשמר'); },
      error: () => { this.busy.set(false); this.flash('השמירה נכשלה', true); },
    });
  }
  fields(f: Record<string, [unknown, unknown]>) {
    const show = (v: unknown) => v == null ? 'ריק' : Array.isArray(v) ? `${v.length} רכיבים` : String(v);
    return Object.entries(f).map(([k, [a, b]]) => ({ k, label: FIELD[k] ?? k, from: show(a), to: show(b) }));
  }
}

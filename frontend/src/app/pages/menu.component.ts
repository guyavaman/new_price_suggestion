import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../core/api.service';
import { CATEGORY, MEAL, UNIT } from '../core/labels';
import { CatalogItem } from '../core/models';

@Component({
  selector: 'app-menu',
  standalone: true,
  imports: [FormsModule],
  template: `
    <div class="page-head">
      <div><h1>תפריט ומחירים</h1><p>מה שמופיע כאן הוא מה שהסוכנת מציעה ומה שנכנס להצעות. מחירים לפני מע"מ.</p></div>
      <button class="btn" (click)="adding.set(!adding())">+ פריט חדש</button>
    </div>
    @if (adding()) {
      <form class="card add" (ngSubmit)="add()">
        <input name="n" [(ngModel)]="nw.name_he" placeholder="שם הפריט" required aria-label="שם">
        <select name="c" [(ngModel)]="nw.category" aria-label="קטגוריה">@for (c of cats; track c[0]) { <option [value]="c[0]">{{ c[1] }}</option> }</select>
        <select name="u" [(ngModel)]="nw.unit" aria-label="יחידה">@for (u of units; track u[0]) { <option [value]="u[0]">{{ u[1] }}</option> }</select>
        <select name="m" [(ngModel)]="nw.meal_type" aria-label="בשרי/חלבי">@for (m of meals; track m[0]) { <option [value]="m[0]">{{ m[1] }}</option> }</select>
        <input name="p" type="number" min="1" step="0.5" [(ngModel)]="nw.price" placeholder="מחיר ₪" aria-label="מחיר">
        <input name="s" type="number" min="1" [(ngModel)]="nw.serves" placeholder="מספיק ל-X אורחים" aria-label="מספיק ל">
        <input name="d" [(ngModel)]="nw.description_he" placeholder="תיאור קצר" aria-label="תיאור" class="wide">
        <button class="btn" [disabled]="!nw.name_he || !nw.price">הוספה</button>
      </form>
    }
    @if (msg()) { <p class="note" [class.bad]="msgBad()">{{ msg() }}</p> }
    <div class="filters">
      <input type="search" placeholder="חיפוש" [ngModel]="q()" (ngModelChange)="q.set($event)" aria-label="חיפוש">
      <button class="chip" [class.on]="!cat()" (click)="cat.set('')">הכל</button>
      @for (c of usedCats(); track c) { <button class="chip" [class.on]="cat() === c" (click)="cat.set(c)">{{ catLabel[c] || c }}</button> }
    </div>
    <div class="card">
      <table>
        <thead><tr><th>פריט</th><th>קטגוריה</th><th>יחידה</th><th>ארוחה</th><th>מחיר ₪</th><th>זמין</th></tr></thead>
        <tbody>
          @for (i of shown(); track i.sku) {
            <tr [class.off]="!i.active">
              <td><b>{{ i.name_he }}</b><div class="muted small">{{ i.description_he }}</div></td>
              <td>{{ catLabel[i.category] || i.category }}</td>
              <td>{{ unitLabel[i.unit] }}@if (i.serves) { <small class="muted"> · ל-{{ i.serves }}</small> }</td>
              <td>{{ mealLabel[i.meal_type] }}</td>
              <td><input class="price" type="number" min="1" step="0.5" [value]="i.price" (change)="setPrice(i, $any($event.target).value)" [attr.aria-label]="'מחיר ' + i.name_he"></td>
              <td><label class="sw"><input type="checkbox" [checked]="i.active" (change)="toggle(i)" [attr.aria-label]="'זמין ' + i.name_he"> {{ i.active ? 'כן' : 'לא' }}</label></td>
            </tr>
          }
        </tbody>
      </table>
    </div>
  `,
  styles: [`
    .add { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; } .add .wide { flex: 1; min-width: 200px; }
    .filters { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; margin-bottom: 10px; }
    .chip { border: 1px solid var(--line); background: var(--surface); border-radius: 99px; padding: 3px 11px; font-size: .85rem; }
    .chip.on { background: var(--olive); color: #fff; border-color: var(--olive); }
    .price { width: 90px; font-variant-numeric: tabular-nums; }
    tr.off td { opacity: .5; } .small { font-size: .8rem; }
    .note { background: var(--ok-soft); color: var(--ok); border-radius: 8px; padding: 6px 12px; } .note.bad { background: var(--bad-soft); color: var(--bad); }
    .sw { display: flex; gap: 6px; align-items: center; }
  `],
})
export class MenuComponent {
  private api = inject(ApiService);
  items = signal<CatalogItem[]>([]);
  q = signal(''); cat = signal('');
  adding = signal(false);
  msg = signal(''); msgBad = signal(false);
  catLabel = CATEGORY; unitLabel = UNIT; mealLabel = MEAL;
  cats = Object.entries(CATEGORY).filter(([k]) => !['staff', 'logistics'].includes(k));
  units = Object.entries(UNIT); meals = Object.entries(MEAL);
  nw: Partial<CatalogItem> = { category: 'main', unit: 'per_guest', meal_type: 'meat', tags: [], description_he: '' };
  usedCats = computed(() => [...new Set(this.items().map((i) => i.category))]);
  shown = computed(() => this.items().filter((i) => (!this.cat() || i.category === this.cat()) && (!this.q() || i.name_he.includes(this.q()))));

  constructor() { this.load(); }
  load() { this.api.catalog().subscribe((i) => this.items.set(i)); }
  flash(m: string, bad = false) { this.msg.set(m); this.msgBad.set(bad); setTimeout(() => this.msg.set(''), 2500); }
  setPrice(i: CatalogItem, v: string) {
    const price = +v;
    if (!(price > 0)) { this.flash('מחיר חייב להיות חיובי', true); return; }
    this.api.patchItem(i.sku, { price }).subscribe({ next: (u) => { this.items.update((l) => l.map((x) => (x.sku === u.sku ? u : x))); this.flash(`המחיר של ${u.name_he} עודכן ל-₪${u.price}`); } });
  }
  toggle(i: CatalogItem) {
    this.api.patchItem(i.sku, { active: !i.active }).subscribe((u) => { this.items.update((l) => l.map((x) => (x.sku === u.sku ? u : x))); this.flash(u.active ? `${u.name_he} זמין שוב` : `${u.name_he} לא יוצע ללקוחות`); });
  }
  add() {
    const sku = 'CUS-' + Date.now().toString(36).toUpperCase();
    this.api.addItem({ ...this.nw, sku, name_en: this.nw.name_he ?? '', serves: this.nw.serves || null }).subscribe({
      next: () => { this.adding.set(false); this.flash('הפריט נוסף'); this.load(); this.nw = { category: 'main', unit: 'per_guest', meal_type: 'meat', tags: [], description_he: '' }; },
      error: () => this.flash('לא הצלחנו להוסיף את הפריט', true),
    });
  }
}

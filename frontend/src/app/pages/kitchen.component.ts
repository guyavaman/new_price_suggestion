import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { ApiService } from '../core/api.service';
import { HeDatePipe } from '../core/format';
import { CATEGORY, MEAL, dietLabel } from '../core/labels';
import { KitchenSheet } from '../core/models';

@Component({
  selector: 'app-kitchen',
  standalone: true,
  imports: [FormsModule, RouterLink, HeDatePipe],
  template: `
    <div class="page-head no-print">
      <div><h1>דף מטבח</h1><p>כמה להכין מכל דבר, לכל האירועים של היום ביחד</p></div>
      <div class="row">
        <button class="btn ghost" (click)="shift(-1)" aria-label="יום קודם">→</button>
        <input type="date" [(ngModel)]="day" (ngModelChange)="load()" aria-label="תאריך">
        <button class="btn ghost" (click)="shift(1)" aria-label="יום הבא">←</button>
        <button class="btn" (click)="print()">הדפסה</button>
      </div>
    </div>
    @if (s(); as s) {
      <h2 class="print-title">דף מטבח · {{ s.date | heDate }} · {{ s.events.length }} אירועים · {{ s.total_guests }} אורחים</h2>
      @if (!s.events.length) { <p class="card empty">אין אירועים סגורים בתאריך הזה</p> }
      @else {
        @if (s.missing_quotes.length) { <div class="err">אירועים בלי הצעת מחיר (לא נכללו בחישוב): {{ s.missing_quotes.join(', ') }}</div> }
        <section class="card">
          <h2>להכנה</h2>
          <table>
            <thead><tr><th>פריט</th><th>קטגוריה</th><th class="end">סה"כ</th><th>לפי אירוע</th></tr></thead>
            <tbody>
              @for (f of s.food; track f.sku) {
                <tr>
                  <td><b>{{ f.name }}</b>@if (f.serves) { <small class="muted"> · מגש ל-{{ f.serves }}</small> }</td>
                  <td>{{ cat[f.category] || f.category }}</td>
                  <td class="end num"><b>{{ f.quantity }}</b> {{ f.unit }}</td>
                  <td class="small">@for (e of f.events; track e.deal_id) { <span>{{ short(e.title) }}: {{ e.quantity }}</span> }</td>
                </tr>
              }
            </tbody>
          </table>
        </section>
        <div class="events">
          @for (e of s.events; track e.deal_id) {
            <section class="card">
              <h3><a [routerLink]="['/deals', e.deal_id]">{{ e.title }}</a></h3>
              <p>{{ e.guests }} אורחים · {{ meal[e.meal_type ?? ''] || '' }} @if (e.location) { · {{ e.location }} }</p>
              @if (e.dietary.length) { <p class="diet">⚠ {{ diets(e.dietary) }}</p> }
              @if (e.staff.length) { <p><b>צוות:</b> {{ e.staff.join(' · ') }}</p> }
              @if (e.equipment.length) { <p><b>ציוד:</b> {{ e.equipment.join(' · ') }}</p> }
            </section>
          }
        </div>
      }
    }
  `,
  styles: [`
    .row { display: flex; gap: 6px; align-items: center; }
    .print-title { margin: 0 0 12px; }
    .end { text-align: end; } .small { font-size: .82rem; } .small span { display: inline-block; margin-inline-end: 10px; color: var(--muted); }
    .events { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; margin-top: 14px; }
    .events p { margin: 4px 0; } .diet { color: var(--bad); font-weight: 700; }
    @media print { .no-print { display: none !important; } .card { border: 0; padding: 0; } }
  `],
})
export class KitchenComponent {
  private api = inject(ApiService);
  day = inject(ActivatedRoute).snapshot.queryParamMap.get('day') ?? new Date().toISOString().slice(0, 10);
  s = signal<KitchenSheet | null>(null);
  cat = CATEGORY; meal = MEAL;
  constructor() { this.load(); }
  load() { this.api.kitchen(this.day).subscribe((s) => this.s.set(s)); }
  shift(n: number) { const d = new Date(this.day + 'T12:00:00'); d.setDate(d.getDate() + n); this.day = d.toISOString().slice(0, 10); this.load(); }
  short(t: string) { return t.split(' · ').slice(0, 2).join(' · '); }
  diets(d: string[]) { return d.map(dietLabel).join(', '); }
  print() { window.print(); }
}

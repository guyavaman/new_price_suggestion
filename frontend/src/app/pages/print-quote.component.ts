import { Component, computed, effect, inject, input, signal } from '@angular/core';
import { ApiService } from '../core/api.service';
import { HeDatePipe, IlsPipe } from '../core/format';
import { KASHRUT, MEAL, UNIT } from '../core/labels';
import { PublicQuote } from '../core/models';

/** Printable quote: A4, RTL. The browser's print dialog saves it as a PDF ("Save as PDF"), with
 *  Hebrew shaped correctly and no server-side PDF engine. Reached by the same secret link. */
@Component({
  selector: 'app-print-quote',
  standalone: true,
  imports: [IlsPipe, HeDatePipe],
  template: `
    @if (error()) { <p class="err">{{ error() }}</p> }
    @if (q(); as q) {
      <div class="toolbar no-print">
        <div class="tiers" role="radiogroup" aria-label="חבילה להדפסה">
          @for (t of q.tiers; track t.key) {
            <button type="button" role="radio" [attr.aria-checked]="t.key === tierKey()" [class.on]="t.key === tierKey()" (click)="picked.set(t.key)">{{ t.name }}</button>
          }
        </div>
        <button class="btn" type="button" (click)="print()">הדפסה / שמירה כ-PDF</button>
        <span class="muted small">בחלון ההדפסה בחרו "שמירה כ-PDF" כדי לקבל קובץ</span>
      </div>

      @if (tier(); as t) {
        <article class="sheet">
          <header>
            <div>
              <h1 class="biz">{{ q.business_name }}</h1>
              <p>{{ q.business_phone }}@if (q.business_email) { · {{ q.business_email }} }</p>
              @if (q.business_id) { <p>ע.מ / ח.פ {{ q.business_id }}</p> }
            </div>
            <div class="doc">
              <h2>הצעת מחיר</h2>
              <p><bdi class="ref">{{ q.number }}</bdi></p>
              <p>תאריך: {{ q.created_at | heDate }}</p>
              <p>בתוקף עד: {{ q.valid_until | heDate }}</p>
            </div>
          </header>

          <section class="to">
            <p><b>לכבוד:</b> {{ q.customer_name || 'הלקוח' }}</p>
            <p><b>האירוע:</b> {{ q.event.type }} · {{ q.event.date | heDate }} · {{ q.final_guest_count ?? q.event.guests }} אורחים
              @if (q.event.meal_type) { · {{ meal[q.event.meal_type] }} } @if (q.event.kashrut) { · {{ kashrut[q.event.kashrut] }} }
              @if (q.event.location) { · {{ q.event.location }} }</p>
            @if (q.cover_note) { <p class="note">{{ q.cover_note }}</p> }
          </section>

          <h3>חבילת {{ t.name }}</h3>
          <table>
            <thead><tr><th>פריט</th><th class="qty">כמות</th></tr></thead>
            <tbody>
              @for (i of t.items; track $index) { <tr><td>{{ i.name }}</td><td class="qty">{{ i.quantity }} {{ unit[i.unit] || i.unit }}</td></tr> }
            </tbody>
          </table>
          @if (t.services.length) { <p class="svc"><b>כולל:</b> {{ t.services.join(' · ') }}</p> }

          <table class="sum">
            @if (t.discount) {
              <tr><td>סכום לפני הנחה</td><td>{{ t.subtotal | ils: 2 }}</td></tr>
              <tr><td>הנחת היקף {{ pct(t.discount_rate) }}%</td><td>−{{ t.discount | ils: 2 }}</td></tr>
            }
            <tr><td>סה"כ לפני מע"מ</td><td>{{ t.net | ils: 2 }}</td></tr>
            <tr><td>מע"מ {{ pct(q.vat_rate) }}%</td><td>{{ t.vat | ils: 2 }}</td></tr>
            <tr class="total"><td>סה"כ לתשלום</td><td>{{ t.total | ils: 2 }}</td></tr>
            @if (t.per_guest) { <tr class="pg"><td>לאורח</td><td>{{ t.per_guest | ils }}</td></tr> }
          </table>

          @if (others().length) {
            <p class="others"><b>חבילות נוספות:</b>
              @for (o of others(); track o.key; let last = $last) { {{ o.name }} {{ o.total | ils }}@if (!last) { · } }</p>
          }

          <section class="terms">
            <h3>תנאים</h3>
            <ul>
              <li>המחירים בשקלים וכוללים מע"מ, צוות ומשלוח כמפורט.</li>
              @if (q.deposit_rate) { <li>אישור ההזמנה בתשלום מקדמה של {{ pct(q.deposit_rate) }}% ({{ t.deposit | ils }}). היתרה עד לפני האירוע.</li> }
              <li>את מספר האורחים הסופי אפשר לעדכן עד יומיים לפני האירוע, והמחיר יתעדכן בהתאם.</li>
              <li>ההצעה בתוקף עד {{ q.valid_until | heDate }}.</li>
            </ul>
            <p class="link">לאישור ותשלום מקדמה אונליין: <span dir="ltr">{{ link() }}</span></p>
          </section>

          <footer>
            <div><span class="line"></span>חתימת הלקוח</div>
            <div><span class="line"></span>תאריך</div>
          </footer>
        </article>
      }
    }
  `,
  styles: [`
    :host { display: block; background: #e9eae4; min-height: 100vh; padding: 16px 0 40px; }
    .toolbar { max-width: 210mm; margin: 0 auto 12px; display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
    .tiers { display: flex; gap: 4px; } .tiers button { border: 1px solid var(--line); background: #fff; border-radius: 99px; padding: 5px 12px; cursor: pointer; font: inherit; }
    .tiers button.on { background: var(--olive); color: #fff; border-color: var(--olive); }
    .sheet { box-sizing: border-box; width: 210mm; min-height: 297mm; margin: 0 auto; background: #fff; color: #1d2318; padding: 16mm 15mm; box-shadow: 0 2px 16px rgba(0,0,0,.12); font-size: 11pt; line-height: 1.5; }
    header { display: flex; justify-content: space-between; gap: 20px; border-bottom: 2px solid var(--olive); padding-bottom: 10px; margin-bottom: 14px; }
    header p { margin: 0; color: #4b5446; font-size: 10pt; }
    .biz { font-size: 20pt; margin: 0 0 4px; } .doc { text-align: end; } .doc h2 { margin: 0 0 2px; font-size: 16pt; color: var(--olive); }
    .to p { margin: 0 0 4px; } .note { background: #f2f4ec; padding: 8px 10px; border-radius: 6px; margin-top: 8px !important; }
    h3 { font-size: 12.5pt; margin: 16px 0 6px; color: var(--olive); }
    table { width: 100%; border-collapse: collapse; } th, td { text-align: start; padding: 5px 6px; border-bottom: 1px solid #e3e5dc; }
    th { font-size: 9.5pt; color: #677061; font-weight: 600; } .qty { width: 30%; white-space: nowrap; }
    .svc { font-size: 10pt; color: #4b5446; margin: 6px 0 0; }
    .sum { width: 55%; margin-inline-start: auto; margin-top: 14px; } .sum td:last-child { text-align: end; white-space: nowrap; }
    .sum .total td { font-weight: 700; font-size: 13pt; border-top: 2px solid var(--olive); border-bottom: 0; color: var(--olive); }
    .sum .pg td { border: 0; color: #677061; font-size: 9.5pt; }
    .others { font-size: 10pt; color: #4b5446; }
    .terms ul { margin: 0; padding-inline-start: 18px; font-size: 10pt; } .link { font-size: 9.5pt; color: #4b5446; word-break: break-all; }
    footer { display: flex; gap: 40px; margin-top: 36px; font-size: 10pt; color: #677061; }
    footer div { flex: 1; } .line { display: block; border-bottom: 1px solid #9aa194; height: 28px; margin-bottom: 4px; }
    @media print {
      @page { size: A4; margin: 0; }
      :host { background: none; padding: 0; } .no-print { display: none !important; }
      .sheet { box-shadow: none; margin: 0; width: auto; min-height: auto; }
      tr { break-inside: avoid; }
    }
  `],
})
export class PrintQuoteComponent {
  private api = inject(ApiService);
  token = input.required<string>();
  tierParam = input<string | undefined>(undefined, { alias: 'tier' });
  q = signal<PublicQuote | null>(null);
  error = signal('');
  picked = signal<string | null>(null);
  meal = MEAL; kashrut = KASHRUT; unit = UNIT;

  tierKey = computed(() => this.picked() ?? this.tierParam() ?? this.q()?.selected_tier ?? 'recommended');
  tier = computed(() => this.q()?.tiers.find((t) => t.key === this.tierKey()));
  others = computed(() => (this.q()?.tiers ?? []).filter((t) => t.key !== this.tierKey()));
  link = computed(() => `${location.origin}/q/${this.token()}`);

  constructor() {
    effect(() => this.api.publicQuote(this.token()).subscribe({
      next: (q) => this.q.set(q),
      error: () => this.error.set('הקישור לא תקין'),
    }), { allowSignalWrites: true });
  }
  pct(r: number | undefined) { return Math.round((r ?? 0) * 100); }
  print() { window.print(); }
}

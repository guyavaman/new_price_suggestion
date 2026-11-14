import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { ApiService } from '../core/api.service';

@Component({
  selector: 'app-quote-new',
  standalone: true,
  imports: [FormsModule],
  template: `
    <div class="page-head"><div><h1>הצעת מחיר חדשה</h1>
      <p>הדביקו הודעה של לקוח כמו שהיא (מייל, וואטסאפ, תמלול שיחה). ה-AI מחלץ פרטים ובונה תפריט, וקוד רגיל מתמחר 3 חבילות.</p></div></div>
    <form class="card form" (ngSubmit)="submit()">
      <label for="msg">הודעת הלקוח</label>
      <textarea id="msg" name="msg" rows="9" [(ngModel)]="message" placeholder="למשל: שלום, בר מצווה ל-120 איש ב-3.12, בשרי כשר, 8 טבעונים. מיכל 050-1234567"></textarea>
      <div class="examples">
        @for (e of examples; track e.label) { <button type="button" class="chip" (click)="message = e.text">{{ e.label }}</button> }
      </div>
      <div class="row">
        <button class="btn" [disabled]="busy() || !message.trim()">{{ busy() ? 'יוצר הצעה…' : 'צור הצעת מחיר' }}</button>
        <span class="muted">ההצעה נשמרת ונכנסת ל-CRM אוטומטית</span>
      </div>
      @if (error()) { <div class="err">{{ error() }}</div> }
    </form>
    <section class="steps">
      @for (s of steps; track s.t) { <div class="card step"><span class="tag" [class.ai]="s.ai">{{ s.ai ? 'AI' : 'קוד' }}</span><b>{{ s.t }}</b><p class="muted">{{ s.d }}</p></div> }
    </section>
  `,
  styles: [`
    .form { display: grid; gap: 10px; max-width: 820px; }
    label { font-weight: 700; }
    textarea { width: 100%; resize: vertical; line-height: 1.6; }
    .examples { display: flex; gap: 6px; flex-wrap: wrap; }
    .chip { border: 1px solid var(--line); background: var(--surface); border-radius: 99px; padding: 3px 11px; font-size: .85rem; }
    .chip:hover { border-color: var(--olive); color: var(--olive); }
    .row { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
    .steps { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-top: 18px; max-width: 820px; }
    @media (max-width: 800px) { .steps { grid-template-columns: 1fr 1fr; } }
    .step { display: grid; gap: 4px; } .step p { margin: 0; font-size: .85rem; }
    .tag { justify-self: start; font-size: .72rem; font-weight: 700; border-radius: 99px; padding: 0 8px; background: var(--olive-soft); color: var(--olive); }
    .tag.ai { background: var(--honey-soft); color: #8a5c06; }
  `],
})
export class QuoteNewComponent {
  private api = inject(ApiService);
  private router = inject(Router);
  message = '';
  busy = signal(false);
  error = signal('');
  examples = [
    { label: 'בר מצווה', text: 'שלום, אני מארגנת בר מצווה לבן שלי ב-3 בדצמבר באולם בראשון לציון. יהיו בערך 120 אורחים. בשרי כשר, מתוכם 8 טבעונים. נשמח למלצרים ובר אלכוהול. תודה, מיכל 050-1234567' },
    { label: 'וואטסאפ קצר', text: 'היי צריך אוכל לאירוע חברה ביום חמישי הבא, 40 איש, חלבי. משהו קליל פינגר פוד' },
    { label: 'תקציב לראש', text: 'חתונה קטנה בגינה במושב בעמק, 80 איש, 24.12. התקציב בסביבות 250 ש"ח לראש. בשרי, כשר למהדרין. צריך גם שולחנות וכיסאות.' },
    { label: 'English', text: "Hi, we're planning our company year-end party on December 17th in Tel Aviv for about 180 employees. Kosher meat dinner, open bar and waiters. About 15 are vegetarian. Budget roughly 60,000 NIS. Dan, dan@acme.co.il" },
  ];
  steps = [
    { t: 'חילוץ', d: 'טקסט חופשי ל-JSON מובנה, כולל פרטי קשר', ai: true },
    { t: 'בחירת תפריט', d: 'רק מתוך הקטלוג, עם רמת ודאות', ai: true },
    { t: 'תמחור', d: 'כמויות, צוות, משלוח, הנחות, מע"מ', ai: false },
    { t: '3 חבילות', d: 'בסיס, מומלץ ופרימיום לפי כללים', ai: false },
  ];

  submit() {
    if (!this.message.trim() || this.busy()) return;
    this.busy.set(true);
    this.error.set('');
    this.api.createQuote(this.message).subscribe({
      next: (r) => this.router.navigate(['/quotes', r.quote.id]),
      error: (e) => {
        this.busy.set(false);
        this.error.set(e.status === 0 ? 'השרת לא זמין. הפעילו את ה-backend על פורט 8000.' : 'לא הצלחנו ליצור הצעה. בדקו שמפתח ה-API מוגדר ב-backend ונסו שוב.');
      },
    });
  }
}

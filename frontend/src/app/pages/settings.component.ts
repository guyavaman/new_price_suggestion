import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../core/api.service';
import { BusinessSettings } from '../core/models';

@Component({
  selector: 'app-settings',
  standalone: true,
  imports: [FormsModule],
  template: `
    <div class="page-head"><div><h1>הגדרות העסק</h1><p>הכללים שלפיהם המערכת מתמחרת, בודקת זמינות ושולחת תזכורות</p></div></div>
    @if (s(); as s) {
      <form class="grid" (ngSubmit)="save()">
        <section class="card">
          <h2>פרטי העסק</h2>
          <div class="fields">
            <label>שם העסק<input name="bn" [(ngModel)]="s.business_name"></label>
            <label>טלפון<input name="ph" [(ngModel)]="s.phone"></label>
            <label>מייל<input name="em" type="email" [(ngModel)]="s.email"></label>
            <label>ח.פ / עוסק מורשה<input name="bid" [(ngModel)]="s.business_id"></label>
          </div>
        </section>
        <section class="card">
          <h2>צוות ותמחור</h2>
          <div class="fields">
            <label>מלצר לכל X אורחים<input name="wr" type="number" min="1" [(ngModel)]="s.waiter_ratio"></label>
            <label>מלצרים אוטומטית מ-X אורחים<input name="aw" type="number" min="1" [(ngModel)]="s.auto_waiters_from"></label>
            <label>מנהל אירוע מ-X אורחים<input name="hw" type="number" min="1" [(ngModel)]="s.head_waiter_from"></label>
            <label>ברמן לכל X אורחים<input name="br" type="number" min="1" [(ngModel)]="s.bartender_ratio"></label>
            <label>שעות עבודה לאירוע<input name="sh" type="number" min="1" [(ngModel)]="s.staff_hours"></label>
            <label>יחידות קבלת פנים לאורח<input name="cp" type="number" min="1" [(ngModel)]="s.canapes_per_guest"></label>
            <label>מע"מ (%)<input name="vat" type="number" min="0" max="50" step="0.5" [ngModel]="pct(s.vat_rate)" (ngModelChange)="s.vat_rate = $event / 100"></label>
          </div>
          <h3>הנחות כמות</h3>
          @for (d of s.volume_discounts; track $index) {
            <div class="disc">מעל ₪<input [name]="'dm' + $index" type="number" min="1" [(ngModel)]="d.min_subtotal">
              הנחה של <input [name]="'dr' + $index" type="number" min="0" max="50" [ngModel]="pct(d.rate)" (ngModelChange)="d.rate = $event / 100">%
              <button type="button" class="btn ghost sm" (click)="s.volume_discounts.splice($index, 1)">הסר</button></div>
          }
          <button type="button" class="btn ghost sm" (click)="s.volume_discounts.push({ min_subtotal: 100000, rate: 0.1 })">+ הנחה</button>
          <h3>אזורי משלוח מרוחקים</h3>
          <input name="ra" class="wide" [ngModel]="s.remote_areas.join(', ')" (ngModelChange)="s.remote_areas = split($event)" aria-label="אזורים מרוחקים">
        </section>
        <section class="card">
          <h2>קיבולת</h2>
          <div class="fields">
            <label>מקסימום אירועים ביום<input name="me" type="number" min="1" [(ngModel)]="s.max_events_per_day"></label>
            <label>מקסימום אורחים ביום<input name="mg" type="number" min="1" [(ngModel)]="s.max_guests_per_day"></label>
          </div>
        </section>
        <section class="card">
          <h2>הצעות, מקדמה ותזכורות</h2>
          <div class="fields">
            <label>תוקף הצעה (ימים)<input name="qv" type="number" min="1" [(ngModel)]="s.quote_valid_days"></label>
            <label>מקדמה לאישור (%)<input name="dp" type="number" min="0" max="100" [ngModel]="pct(s.deposit_rate)" (ngModelChange)="s.deposit_rate = $event / 100"></label>
            <label>מעקב על הצעה שלא נענתה אחרי (ימים)<input name="fu" type="number" min="1" [(ngModel)]="s.followup_after_days"></label>
            <label>בקשת מספר אורחים סופי (ימים לפני)<input name="fc" type="number" min="1" [(ngModel)]="s.final_count_days_before"></label>
            <label>חשבוניות
              <select name="ip" [(ngModel)]="s.invoice_provider"><option value="manual">ידני (מזינים מספר)</option><option value="morning">חשבונית ירוקה (Morning)</option></select></label>
            <label>תשלומים
              <select name="pp" [(ngModel)]="s.payment_provider"><option value="demo">דמו (בלי חיוב אמיתי)</option></select></label>
            <label class="span">כתובת דף הלקוח<input name="pb" dir="ltr" [(ngModel)]="s.public_base_url"></label>
          </div>
        </section>
        <div class="bar"><button class="btn" [disabled]="saving()">{{ saving() ? 'שומר…' : 'שמירה' }}</button>
          @if (msg()) { <span [class.bad]="bad()">{{ msg() }}</span> }</div>
      </form>
    }
  `,
  styles: [`
    form.grid { max-width: 920px; }
    h2 { margin-bottom: 10px; } h3 { font-size: 1rem; margin: 14px 0 6px; }
    .fields { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 10px; }
    label { display: grid; gap: 4px; font-size: .88rem; color: var(--muted); } label.span { grid-column: 1 / -1; }
    label input, label select { color: var(--ink); }
    .disc { display: flex; gap: 6px; align-items: center; margin-bottom: 6px; } .disc input { width: 110px; }
    .wide { width: 100%; } .sm { padding: 4px 10px; font-size: .85rem; }
    .bar { position: sticky; bottom: 0; background: var(--bg); padding: 10px 0; display: flex; gap: 12px; align-items: center; }
    .bad { color: var(--bad); }
  `],
})
export class SettingsComponent {
  private api = inject(ApiService);
  s = signal<BusinessSettings | null>(null);
  saving = signal(false); msg = signal(''); bad = signal(false);
  constructor() { this.api.settings().subscribe((s) => this.s.set(structuredClone(s))); }
  pct(v: number) { return Math.round(v * 1000) / 10; }
  split(v: string) { return v.split(',').map((x) => x.trim()).filter(Boolean); }
  save() {
    const s = this.s();
    if (!s) return;
    this.saving.set(true);
    this.api.saveSettings(s).subscribe({
      next: (r) => { this.s.set(structuredClone(r)); this.saving.set(false); this.bad.set(false); this.msg.set('נשמר ✓ ההצעות הבאות יתומחרו לפי ההגדרות החדשות'); },
      error: (e) => { this.saving.set(false); this.bad.set(true); const d = e.error?.detail; this.msg.set('לא נשמר: ' + (typeof d === 'string' ? d.slice(0, 160) : 'ערך לא תקין')); },
    });
  }
}

import { Component, inject, input, signal } from '@angular/core';
import { ApiService } from '../core/api.service';
import { HeDatePipe } from '../core/format';
import { ShiftView } from '../core/models';

/** The page a staff member opens from the WhatsApp invite: when, where, what role, and two
 *  buttons. No customer details, no money. */
@Component({
  selector: 'app-shift',
  standalone: true,
  imports: [HeDatePipe],
  template: `
    <div class="wrap">
      @if (s(); as s) {
        <p class="biz">{{ s.business_name }}</p>
        <h1>היי {{ first(s.name) }}</h1>
        <p class="lead">שיבצנו אותך כ<b>{{ s.role }}</b> ב{{ s.event }}</p>
        <dl>
          <div><dt>מתי</dt><dd>{{ s.event_date ? (s.event_date | heDate) : 'יתואם' }} · {{ weekday(s.event_date) }}</dd></div>
          <div><dt>איפה</dt><dd>{{ s.location || 'נעדכן בהמשך' }}</dd></div>
          <div><dt>משמרת</dt><dd>{{ s.hours }} שעות · {{ s.guests || '?' }} אורחים</dd></div>
        </dl>
        @if (s.status === 'invited') {
          <div class="acts">
            <button class="btn yes" [disabled]="busy()" (click)="answer(true)">מגיע/ה ✓</button>
            <button class="btn ghost" [disabled]="busy()" (click)="answer(false)">לא אוכל להגיע</button>
          </div>
        } @else {
          <p class="done" [class.no]="s.status === 'declined'" role="status">
            {{ s.status === 'confirmed' ? 'תודה! רשמנו שאת/ה מגיע/ה 🙌' : 'רשמנו שלא תוכל/י להגיע. תודה שעדכנת.' }}
          </p>
          <button class="linkish" (click)="answer(s.status !== 'confirmed')">{{ s.status === 'confirmed' ? 'בעצם לא אוכל להגיע' : 'בעצם אני כן יכול/ה' }}</button>
        }
      } @else if (error()) {
        <p class="err">{{ error() }}</p>
      } @else { <p class="muted">טוען…</p> }
    </div>
  `,
  styles: [`
    .wrap { max-width: 440px; margin: 0 auto; padding: 32px 20px; display: grid; gap: 14px; }
    .biz { margin: 0; color: var(--olive); font-weight: 700; letter-spacing: .02em; }
    h1 { margin: 0; font-family: var(--display); font-size: 2rem; }
    .lead { margin: 0; font-size: 1.1rem; }
    dl { margin: 0; display: grid; gap: 10px; background: var(--surface); border: 1px solid var(--line); border-radius: 12px; padding: 14px 16px; }
    dl div { display: grid; grid-template-columns: 70px 1fr; gap: 8px; } dt { color: var(--muted); } dd { margin: 0; font-weight: 600; }
    .acts { display: grid; gap: 10px; } .btn { padding: 14px; font-size: 1.05rem; } .yes { background: var(--ok); border-color: var(--ok); }
    .done { margin: 0; background: var(--ok-soft); color: var(--ok); border-radius: 10px; padding: 12px 14px; font-weight: 600; }
    .done.no { background: var(--paper); color: var(--ink); }
    .linkish { background: none; border: 0; padding: 0; color: var(--muted); text-decoration: underline; font: inherit; cursor: pointer; justify-self: start; }
  `],
})
export class ShiftComponent {
  private api = inject(ApiService);
  token = input.required<string>();
  s = signal<ShiftView | null>(null);
  error = signal('');
  busy = signal(false);
  ngOnInit() { this.api.shift(this.token()).subscribe({ next: (s) => this.s.set(s), error: () => this.error.set('הקישור לא נמצא. בדקו את ההודעה או פנו אלינו.') }); }
  first(n: string) { return n.split(' ')[0]; }
  weekday(d: string | null) { return d ? new Date(d + 'T12:00:00').toLocaleDateString('he-IL', { weekday: 'long' }) : ''; }
  answer(coming: boolean) {
    this.busy.set(true);
    this.api.answerShift(this.token(), coming).subscribe({
      next: (s) => { this.busy.set(false); this.s.set(s); },
      error: (e) => { this.busy.set(false); this.error.set(e.error?.detail ?? 'לא הצלחנו לשמור. נסו שוב.'); },
    });
  }
}

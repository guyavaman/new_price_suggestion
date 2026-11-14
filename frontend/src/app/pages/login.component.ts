import { Component, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { AuthService } from '../core/auth';

@Component({
  selector: 'app-login',
  standalone: true,
  imports: [FormsModule],
  template: `
    <div class="box card">
      <b class="brand">זית ודבש</b>
      <h1>כניסה למערכת</h1>
      <form (ngSubmit)="submit()">
        <label for="pw">סיסמת בעל העסק</label>
        <input id="pw" name="pw" type="password" [(ngModel)]="password" autocomplete="current-password" required>
        <button class="btn" [disabled]="busy() || !password">{{ busy() ? 'נכנס…' : 'כניסה' }}</button>
      </form>
      @if (error()) { <p class="err" role="alert">{{ error() }}</p> }
      @if (guest()) {
        <div class="guest">
          <p>מגיעים מתיק העבודות? אפשר להסתכל על כל המערכת עם נתוני דמו, בלי לשנות כלום.</p>
          <button class="btn ghost" type="button" [disabled]="busy()" (click)="asGuest()">כניסה לדמו (צפייה בלבד)</button>
        </div>
      }
    </div>
  `,
  styles: [`
    .box { max-width: 380px; margin: 10vh auto; display: grid; gap: 14px; }
    .brand { font-family: var(--display); font-size: 1.6rem; color: var(--olive); }
    form { display: grid; gap: 8px; }
    .guest { border-top: 1px solid var(--line); padding-top: 14px; display: grid; gap: 8px; }
    .guest p { margin: 0; color: var(--muted); font-size: .9rem; }
  `],
})
export class LoginComponent {
  private auth = inject(AuthService);
  private router = inject(Router);
  next = input<string>('/today');
  password = '';
  busy = signal(false);
  error = signal('');
  guest = signal(false);

  constructor() { this.auth.serverStatus().then((s) => { this.guest.set(s.guest); if (!s.required) this.go(); }); }

  async submit() { await this.run({ password: this.password }); }
  async asGuest() { await this.run({ guest: true }); }

  private async run(body: { password?: string; guest?: boolean }) {
    this.busy.set(true); this.error.set('');
    try { await this.auth.login(body); this.go(); }
    catch (e: any) { this.error.set(e?.status === 429 ? 'יותר מדי ניסיונות. נסו שוב בעוד דקה.' : 'הסיסמה שגויה'); }
    finally { this.busy.set(false); }
  }
  private go() { this.router.navigateByUrl(this.next() || '/today'); }
}

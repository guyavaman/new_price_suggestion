import { Component, inject, input, signal, effect } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { ApiService } from '../core/api.service';
import { IlsPipe } from '../core/format';

/** Simulated checkout for the demo payment provider. A real provider hosts this page. */
@Component({
  selector: 'app-pay',
  standalone: true,
  imports: [IlsPipe],
  template: `
    <div class="box card">
      <span class="tag">דף תשלום לדוגמה · לא מתבצע חיוב</span>
      @if (info(); as i) {
        <h1>תשלום מקדמה</h1>
        <p>{{ i.business_name }} · הצעה <bdi class="ref">{{ i.quote_number }}</bdi> · חבילת {{ i.tier }}</p>
        <b class="amount num">{{ i.amount | ils: 2 }}</b>
        @if (i.status === 'paid') { <p class="ok">שולם ✓</p> }
        @else {
          <div class="fake"><input placeholder="מספר כרטיס" value="4580 0000 0000 0000" disabled aria-label="כרטיס"><input placeholder="תוקף" value="12/29" disabled aria-label="תוקף"></div>
          <button class="btn big" [disabled]="busy()" (click)="pay()">{{ busy() ? 'מעבד…' : 'תשלום' }}</button>
        }
      }
      @if (error()) { <p class="err">{{ error() }}</p> }
    </div>
  `,
  styles: [`
    .box { max-width: 420px; margin: 60px auto; display: grid; gap: 10px; text-align: center; }
    .tag { justify-self: center; font-size: .75rem; background: var(--honey-soft); color: #8a5c06; border-radius: 99px; padding: 2px 10px; }
    .amount { font-family: var(--display); font-size: 2.2rem; color: var(--olive); }
    .fake { display: grid; gap: 6px; } .big { padding: 12px; font-size: 1.05rem; } .ok { color: var(--ok); font-weight: 700; }
  `],
})
export class PayComponent {
  private api = inject(ApiService);
  private router = inject(Router);
  id = input.required<string>();
  token = inject(ActivatedRoute).snapshot.queryParamMap.get('t') ?? '';
  info = signal<{ amount: number; status: string; business_name: string; quote_number: string; tier: string } | null>(null);
  busy = signal(false);
  error = signal('');
  constructor() {
    effect(() => this.api.paymentInfo(this.token, this.id()).subscribe({
      next: (i) => this.info.set(i), error: () => this.error.set('התשלום לא נמצא'),
    }), { allowSignalWrites: true });
  }
  pay() {
    this.busy.set(true);
    this.api.demoConfirm(this.token, this.id()).subscribe({
      next: () => this.router.navigate(['/q', this.token]),
      error: () => { this.busy.set(false); this.error.set('התשלום נכשל'); },
    });
  }
}

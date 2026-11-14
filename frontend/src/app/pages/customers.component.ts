import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { ApiService } from '../core/api.service';
import { HeDatePipe, IlsPipe } from '../core/format';
import { SOURCE, STAGE_LABEL } from '../core/labels';
import { Customer, Deal } from '../core/models';

@Component({
  selector: 'app-customers',
  standalone: true,
  imports: [FormsModule, RouterLink, HeDatePipe, IlsPipe],
  template: `
    <div class="page-head">
      <div><h1>לקוחות</h1><p>לקוח אחד לכל טלפון או מייל, גם אם פנה כמה פעמים</p></div>
      <input type="search" placeholder="שם, טלפון או מייל" [(ngModel)]="q" (ngModelChange)="load()" aria-label="חיפוש לקוח">
    </div>
    <div class="cols">
      <div class="card">
        <table>
          <thead><tr><th>שם</th><th>טלפון</th><th>מקור</th><th>עודכן</th></tr></thead>
          <tbody>
            @for (c of list(); track c.id) {
              <tr class="link" [class.on]="sel()?.customer?.id === c.id" (click)="open(c.id)">
                <td><b>{{ c.name || c.company || '—' }}</b></td>
                <td dir="ltr" class="num">{{ c.phone || c.email || '—' }}</td>
                <td>{{ source[c.source] }}</td>
                <td class="muted">{{ c.updated_at | heDate }}</td>
              </tr>
            } @empty { <tr><td colspan="4" class="empty">לא נמצאו לקוחות</td></tr> }
          </tbody>
        </table>
      </div>
      @if (sel(); as s) {
        <aside class="card">
          <h2>{{ s.customer.name || s.customer.company }}</h2>
          <p dir="ltr" class="muted">{{ s.customer.phone }} {{ s.customer.email }}</p>
          <h3>עסקאות</h3>
          <ul>
            @for (d of s.deals; track d.id) {
              <li><a [routerLink]="['/deals', d.id]">{{ d.title }}</a> <span class="pill">{{ stage[d.stage] }}</span> <span class="num">{{ d.value | ils }}</span></li>
            }
          </ul>
        </aside>
      }
    </div>
  `,
  styles: [`
    .cols { display: grid; grid-template-columns: 1fr 340px; gap: 14px; align-items: start; }
    @media (max-width: 900px) { .cols { grid-template-columns: 1fr; } }
    tr.on td { background: var(--olive-soft); }
    ul { padding-inline-start: 18px; display: grid; gap: 6px; }
    h3 { font-size: 1rem; margin-top: 12px; }
  `],
})
export class CustomersComponent {
  private api = inject(ApiService);
  q = '';
  list = signal<Customer[]>([]);
  sel = signal<{ customer: Customer; deals: Deal[] } | null>(null);
  source = SOURCE; stage = STAGE_LABEL;
  constructor() { this.load(); }
  load() { this.api.customers(this.q || undefined).subscribe((l) => this.list.set(l)); }
  open(id: string) { this.api.customer(id).subscribe((s) => this.sel.set(s)); }
}

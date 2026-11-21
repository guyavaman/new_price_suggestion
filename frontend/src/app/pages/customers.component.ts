import { Component, effect, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { ApiService } from '../core/api.service';
import { HeDatePipe, IlsPipe } from '../core/format';
import { EVENT_TYPE, SOURCE, STAGE_LABEL } from '../core/labels';
import { Customer, CustomerHistory } from '../core/models';

/** Customers: one per phone/email. Type (private/business decides how prices are shown),
 *  order history with value and profit, and who's due for a "haven't heard from you" call. */
@Component({
  selector: 'app-customers',
  standalone: true,
  imports: [FormsModule, RouterLink, HeDatePipe, IlsPipe],
  template: `
    <div class="page-head">
      <div><h1>לקוחות</h1><p>לקוח אחד לכל טלפון או מייל, גם אם פנה כמה פעמים</p></div>
      <input type="search" placeholder="שם, חברה, טלפון או מייל" [(ngModel)]="q" (ngModelChange)="load()" aria-label="חיפוש לקוח">
    </div>
    <div class="cols">
      <div class="card tw">
        <table>
          <thead><tr><th>שם</th><th>סוג</th><th>טלפון</th><th>מקור</th><th>עודכן</th></tr></thead>
          <tbody>
            @for (c of list(); track c.id) {
              <tr class="link" [class.on]="cust()?.id === c.id" (click)="open(c.id)">
                <td><b>{{ c.name || c.company || '—' }}</b>@if (c.name && c.company) { <small class="muted"> · {{ c.company }}</small> }</td>
                <td><span class="kind" [class.biz]="isBiz(c)">{{ isBiz(c) ? 'עסקי' : 'פרטי' }}</span></td>
                <td dir="ltr" class="num">{{ c.phone || c.email || '—' }}</td>
                <td>{{ source[c.source] }}</td>
                <td class="muted">{{ c.updated_at | heDate }}</td>
              </tr>
            } @empty { <tr><td colspan="5" class="empty">לא נמצאו לקוחות</td></tr> }
          </tbody>
        </table>
      </div>
      @if (cust(); as c) {
        <aside class="card side" aria-labelledby="c-h">
          <h2 id="c-h">{{ c.name || c.company }}</h2>
          <p dir="ltr" class="muted contact">{{ c.phone }} {{ c.email }}</p>

          <fieldset class="kindset"><legend>סוג לקוח</legend>
            <div class="seg" role="radiogroup" aria-label="סוג לקוח">
              <button type="button" role="radio" [attr.aria-checked]="c.kind === 'private'" [class.on]="c.kind === 'private'" (click)="setKind('private')">פרטי</button>
              <button type="button" role="radio" [attr.aria-checked]="c.kind === 'business'" [class.on]="c.kind === 'business'" (click)="setKind('business')">עסקי</button>
              <button type="button" role="radio" [attr.aria-checked]="!c.kind" [class.on]="!c.kind" (click)="setKind(null)">לפי שם החברה</button>
            </div>
            <p class="muted small">{{ isBiz(c) ? 'מחירים בהצעה ובקישור לפני מע"מ, עם שורת מע"מ.' : 'מחירים בהצעה ובקישור כוללים מע"מ.' }}</p>
            <label class="company">שם החברה<input [(ngModel)]="company" name="co" maxlength="120" (change)="saveCompany()" placeholder="לא צוין"></label>
          </fieldset>

          @if (h(); as h) {
            @if (h.reorder_due) {
              <p class="due" role="status">לא הזמינו {{ h.days_since_last }} ימים. זה זמן טוב לחזור אליהם.</p>
            }
            <div class="stats">
              <div><span>אירועים</span><b class="num">{{ h.booked }}</b></div>
              <div><span>סה"כ (לפני מע"מ)</span><b class="num">{{ h.total_net | ils }}</b></div>
              <div><span>ממוצע לאירוע</span><b class="num">{{ h.avg_net !== null ? (h.avg_net | ils) : '—' }}</b></div>
              <div><span>אירוע אחרון</span><b class="num">{{ h.last_event ? (h.last_event | heDate) : '—' }}</b></div>
            </div>
            <h3>היסטוריית הזמנות</h3>
            <ul class="hist">
              @for (e of h.events; track e.deal_id) {
                <li>
                  <a [routerLink]="['/deals', e.deal_id]">{{ eventType[e.event_type ?? 'other'] || 'אירוע' }} · {{ e.event_date ? (e.event_date | heDate) : 'בלי תאריך' }}</a>
                  <span class="pill">{{ stage[e.stage] }}</span>
                  <div class="muted small">@if (e.guests) { {{ e.guests }} אורחים · }{{ e.value_net | ils }}@if (e.profit !== null) { · רווח {{ e.profit | ils }} }</div>
                </li>
              } @empty { <li class="muted">אין עדיין הזמנות</li> }
            </ul>
          }
          @if (msg()) { <p class="err" role="alert">{{ msg() }}</p> }
        </aside>
      }
    </div>
  `,
  styles: [`
    .cols { display: grid; grid-template-columns: 1fr 360px; gap: 14px; align-items: start; }
    @media (max-width: 900px) { .cols { grid-template-columns: 1fr; } }
    .tw { overflow-x: auto; min-width: 0; }
    tr.on td { background: var(--olive-soft); }
    .kind { font-size: .76rem; border-radius: 99px; padding: 1px 9px; background: var(--paper); color: var(--muted); font-weight: 600; }
    .kind.biz { background: var(--olive-soft); color: var(--olive); }
    .side { display: grid; gap: 10px; min-width: 0; }
    .side h2 { margin: 0; } .contact { margin: 0; }
    .kindset { border: 1px solid var(--line); border-radius: 10px; padding: 8px 12px 10px; display: grid; gap: 6px; }
    legend { font-size: .82rem; color: var(--muted); }
    .seg { display: inline-flex; border: 1px solid var(--line); border-radius: 8px; overflow: hidden; justify-self: start; flex-wrap: wrap; }
    .seg button { border: 0; background: var(--surface); font: inherit; font-size: .86rem; padding: 5px 12px; cursor: pointer; }
    .seg button + button { border-inline-start: 1px solid var(--line); }
    .seg button.on { background: var(--olive); color: #fff; font-weight: 700; }
    .company { display: grid; gap: 4px; font-size: .84rem; }
    .small { font-size: .82rem; margin: 0; }
    .due { margin: 0; background: var(--warn-soft); color: var(--warn); border-radius: 8px; padding: 8px 10px; font-weight: 600; }
    .stats { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
    .stats div { border: 1px solid var(--line); border-radius: 8px; padding: 6px 10px; display: grid; }
    .stats span { font-size: .76rem; color: var(--muted); } .stats b { font-size: 1.05rem; }
    h3 { font-size: 1rem; margin: 4px 0 0; }
    .hist { list-style: none; padding: 0; margin: 0; display: grid; gap: 8px; }
    .hist li { border-top: 1px solid var(--line); padding-top: 6px; }
  `],
})
export class CustomersComponent {
  private api = inject(ApiService);
  c = input<string | undefined>(undefined);  // ?c=<id> opens a customer
  q = '';
  company = '';
  list = signal<Customer[]>([]);
  cust = signal<Customer | null>(null);
  h = signal<CustomerHistory | null>(null);
  msg = signal('');
  source = SOURCE; stage = STAGE_LABEL; eventType = EVENT_TYPE as Record<string, string>;
  constructor() {
    this.load();
    effect(() => { const id = this.c(); if (id) this.open(id); });
  }
  isBiz(c: Customer) { return c.kind ? c.kind === 'business' : !!(c.company ?? '').trim(); }
  load() { this.api.customers(this.q || undefined).subscribe((l) => this.list.set(l)); }
  open(id: string) {
    this.msg.set('');
    this.api.customer(id).subscribe((s) => { this.cust.set(s.customer); this.company = s.customer.company ?? ''; });
    this.api.customerHistory(id).subscribe((h) => this.h.set(h));
  }
  private patch(body: Partial<Customer> & { clear_kind?: boolean }) {
    const c = this.cust();
    if (!c) return;
    this.api.patchCustomer(c.id, body).subscribe({
      next: (n) => { this.cust.set(n); this.list.update((l) => l.map((x) => x.id === n.id ? n : x)); this.api.customerHistory(n.id).subscribe((h) => this.h.set(h)); },
      error: () => this.msg.set('השמירה נכשלה'),
    });
  }
  setKind(kind: 'private' | 'business' | null) { this.patch(kind ? { kind } : { clear_kind: true }); }
  saveCompany() { this.patch({ company: this.company.trim() || null }); }
}

import { Component, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { ApiService } from '../core/api.service';
import { HeDatePipe, IlsPipe } from '../core/format';
import { EVENT_TYPE, QUOTE_STATUS } from '../core/labels';
import { StoredQuote } from '../core/models';

@Component({
  selector: 'app-quotes-list',
  standalone: true,
  imports: [RouterLink, IlsPipe, HeDatePipe],
  template: `
    <div class="page-head">
      <div><h1>הצעות מחיר</h1><p>כל ההצעות שנוצרו מהודעות, מהסוכן או ידנית</p></div>
      <a class="btn" routerLink="/quotes/new">+ הצעה חדשה</a>
    </div>
    @if (error()) { <div class="err">{{ error() }}</div> }
    <div class="card">
      <table>
        <thead><tr><th>מספר</th><th>אירוע</th><th>לקוח</th><th>תאריך אירוע</th><th>סטטוס</th><th class="end">חבילה נבחרת</th><th>נוצרה</th></tr></thead>
        <tbody>
          @for (q of quotes(); track q.id) {
            <tr class="link" [routerLink]="['/quotes', q.id]">
              <td class="num"><b>{{ q.number }}</b></td>
              <td>{{ eventType[q.request.event_type ?? ''] || 'אירוע' }}{{ q.request.guest_count ? ' · ' + q.request.guest_count + ' אורחים' : '' }}</td>
              <td>{{ q.request.contact.name || q.request.contact.company || '—' }}</td>
              <td class="num">{{ q.request.event_date | heDate }}</td>
              <td><span class="pill st-{{ q.status }}">{{ status[q.status] }}</span></td>
              <td class="num end">{{ selected(q) | ils }}</td>
              <td class="muted">{{ q.created_at | heDate }}</td>
            </tr>
          } @empty { <tr><td colspan="7" class="empty">עוד אין הצעות. <a routerLink="/quotes/new">צרו הצעה ראשונה</a></td></tr> }
        </tbody>
      </table>
    </div>
  `,
  styles: [`
    .end { text-align: end; }
    .st-approved { background: var(--ok-soft); color: var(--ok); }
    .st-rejected, .st-expired { background: var(--bad-soft); color: var(--bad); }
    .st-sent { background: var(--honey-soft); color: #8a5c06; }
  `],
})
export class QuotesListComponent {
  private api = inject(ApiService);
  quotes = signal<StoredQuote[]>([]);
  error = signal('');
  eventType = EVENT_TYPE;
  status = QUOTE_STATUS;
  constructor() {
    this.api.quotes().subscribe({ next: (q) => this.quotes.set(q), error: () => this.error.set('השרת לא זמין') });
  }
  selected(q: StoredQuote) { return q.tiers.find((t) => t.key === q.selected_tier)?.quote.total ?? null; }
}

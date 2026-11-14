import { Component, computed, effect, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { ApiService } from '../core/api.service';
import { HeDatePipe, IlsPipe } from '../core/format';
import { CONFIDENCE, EVENT_TYPE, KASHRUT, LINE_SOURCE, MEAL, QUOTE_STATUS, REJECT_REASONS, UNIT, dietLabel } from '../core/labels';
import { EditOut, QuoteStatus, StoredQuote, TierQuote } from '../core/models';

@Component({
  selector: 'app-quote-detail',
  standalone: true,
  imports: [FormsModule, RouterLink, IlsPipe, HeDatePipe],
  template: `
    <a routerLink="/quotes" class="back">→ כל ההצעות</a>
    @if (error()) { <div class="err">{{ error() }}</div> }
    @if (q(); as q) {
      <div class="page-head">
        <div>
          <h1>הצעת מחיר <bdi class="ref">{{ q.number }}</bdi></h1>
          <p><span class="pill">{{ status[q.status] }}</span> נוצרה {{ q.created_at | heDate: true }}
            @if (dealId()) { · <a [routerLink]="['/deals', dealId()]">לעסקה ב-CRM ←</a> }</p>
        </div>
        <div class="actions">
          @if (q.status === 'draft' || q.status === 'rejected' || q.status === 'expired') { <button class="btn ghost" (click)="setStatus('sent')">סמן כנשלחה</button> }
          @if (q.status !== 'approved') {
            <button class="btn" (click)="setStatus('approved')">הלקוח אישר את חבילת {{ tier()?.name }}</button>
            @if (q.status !== 'rejected') { <button class="btn danger" (click)="askReject.set(true)">הלקוח דחה</button> }
          }
        </div>
      </div>

      @if (askReject()) {
        <form class="card rejectbox" (ngSubmit)="reject()">
          <b>למה הלקוח דחה?</b>
          <div class="examples">@for (r of reasons; track r) { <button type="button" class="chip" [class.on]="rejectReason === r" (click)="rejectReason = r">{{ r }}</button> }</div>
          <div class="row">
            <input name="rr" [(ngModel)]="rejectReason" placeholder="או כתבו סיבה אחרת" aria-label="סיבת הדחייה">
            <button class="btn danger" [disabled]="!rejectReason.trim()">סמן כנדחתה</button>
            <button class="btn ghost" type="button" (click)="askReject.set(false)">ביטול</button>
          </div>
        </form>
      }
      @if (q.status === 'rejected' && rejectNote(); as why) { <div class="card rejected-why"><b>סיבת הדחייה:</b> {{ why }}</div> }

      @if (q.request.suspicious_instructions) {
        <div class="err">ההודעה כללה ניסיון לתת הוראות למערכת (למשל לשנות מחיר). ההוראה לא בוצעה.</div>
      }

      <section class="card facts">
        <div><span>אירוע</span><b>{{ eventType[q.request.event_type ?? ''] || '—' }}</b></div>
        <div><span>אורחים</span><b class="num">{{ q.request.guest_count ?? '—' }}</b></div>
        <div><span>תאריך</span><b>{{ q.request.event_date | heDate }}</b></div>
        <div><span>ארוחה</span><b>{{ meal[q.request.meal_type ?? ''] || '—' }} · {{ kashrut[q.request.kashrut ?? ''] || '—' }}</b></div>
        <div><span>מיקום</span><b>{{ q.request.location || '—' }}</b></div>
        <div><span>לקוח</span><b>{{ q.request.contact.name || q.request.contact.company || '—' }}</b><small dir="ltr" class="muted">{{ q.request.contact.phone || q.request.contact.email }}</small></div>
        @if (q.request.dietary_requirements.length) { <div><span>תזונה</span><b>{{ diets() }}</b></div> }
        @if (q.request.budget; as b) { <div><span>תקציב</span><b class="num">{{ b.amount | ils }} {{ b.scope === 'per_guest' ? 'לסועד' : 'סה"כ' }}</b></div> }
      </section>
      @if (q.request.missing_info.length) {
        <p class="missing">חסר: {{ q.request.missing_info.join(', ') }}</p>
      }

      <div class="tiers" role="group" aria-label="בחירת חבילה">
        @for (t of q.tiers; track t.key) {
          <button class="tier" [attr.aria-pressed]="t.key === view()" (click)="view.set(t.key)">
            <span class="tn">{{ t.name }} @if (t.key === q.selected_tier) { <span class="pill">נבחרה</span> }</span>
            <b class="num">{{ t.quote.total | ils }}</b>
            <small class="num muted">{{ t.quote.per_guest | ils }} לסועד כולל מע"מ</small>
            @if (t.changes.length) { <small class="muted">{{ t.changes.slice(0, 3).join(' · ') }}</small> }
          </button>
        }
      </div>

      @if (tier(); as t) {
        <section class="card doc">
          @if (t.quote.guards.length) { <div class="warnbox"><b>בקרות שהופעלו:</b> {{ t.quote.guards.join(' · ') }}</div> }
          <div class="table-wrap">
            <table>
              <thead><tr><th>פריט</th><th>מקור</th><th>ודאות</th><th class="end">כמות</th><th class="end">מחיר יח'</th><th class="end">סה"כ</th></tr></thead>
              <tbody>
                @for (l of t.quote.lines; track $index) {
                  <tr>
                    <td><b>{{ l.name_he }}</b><div class="sku">{{ l.sku }}</div>@if (l.reason) { <div class="muted small">{{ l.reason }}</div> }</td>
                    <td><span class="pill src-{{ l.source }}">{{ src[l.source] }}</span></td>
                    <td><span class="conf c-{{ l.confidence }}"><i></i>{{ conf[l.confidence] }}</span></td>
                    <td class="num end">{{ l.quantity }} {{ unit[l.unit] }}<div class="muted small">{{ l.note }}</div></td>
                    <td class="num end">{{ l.unit_price | ils: 2 }}</td>
                    <td class="num end"><b>{{ l.total | ils: 2 }}</b></td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
          @if (t.plan.unmatched.length) { <p class="missing">לא נמצאו בקטלוג: {{ t.plan.unmatched.join(', ') }}</p> }
          <div class="totals num">
            <span>סכום ביניים</span><span>{{ t.quote.subtotal | ils: 2 }}</span>
            @if (t.quote.discount) { <span class="ok">הנחת היקף {{ t.quote.discount_rate * 100 }}%</span><span class="ok">−{{ t.quote.discount | ils: 2 }}</span> }
            <span>מע"מ</span><span>{{ t.quote.vat | ils: 2 }}</span>
            <span class="grand">סה"כ לתשלום</span><span class="grand">{{ t.quote.total | ils: 2 }}</span>
          </div>
          @if (t.quote.budget; as b) { <p class="budget" [class.over]="!b.ok">{{ b.ok ? '✓ בתוך התקציב: ' : 'חורג מהתקציב: ' }}{{ b.text }}</p> }
        </section>
      }

      <div class="cols" [class.single]="q.status === 'approved'">
        @if (q.status !== 'approved') {
          <section class="card">
            <h2>שינוי בשפה חופשית <span class="pill ai">Claude + כלים</span></h2>
            <form class="edit" (ngSubmit)="edit()">
              <input name="ins" [(ngModel)]="instruction" placeholder="למשל: תחליף את השיפודים בסושי ותעלה ל-130 אורחים" aria-label="שינוי">
              <button class="btn" [disabled]="editing() || !instruction.trim()">{{ editing() ? 'מעדכן…' : 'עדכן' }}</button>
            </form>
            <div class="examples">@for (e of editExamples; track e) { <button type="button" class="chip" (click)="instruction = e">{{ e }}</button> }</div>
            @if (lastEdit(); as r) {
              @if (r.reply) { <p class="reply">{{ r.reply }}</p> }
              @if (r.flags.length) { <div class="warnbox"><b>הועבר לטיפולך:</b> {{ r.flags.join(' · ') }}</div> }
              <div class="log">@for (a of r.actions; track $index) { <code [class.bad]="a.error">{{ a.tool }}</code> }</div>
            }
          </section>
        }
        <section class="card">
          <h2>הודעה ללקוח</h2>
          <p class="mail">{{ email() }}</p>
          <button class="btn ghost" (click)="copy()">{{ copied() ? 'הועתק ✓' : 'העתק' }}</button>
        </section>
      </div>

      <details class="card src-msg"><summary>ההודעה המקורית של הלקוח</summary><p>{{ q.source_message }}</p></details>
    }
  `,
  styles: [`
    .back { display: inline-block; margin-bottom: 10px; text-decoration: none; }
    .page-head p { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
    .actions { display: flex; gap: 6px; flex-wrap: wrap; }
    .facts { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 10px; margin-bottom: 8px; }
    .facts div { display: grid; } .facts span { font-size: .78rem; color: var(--muted); }
    .missing { color: var(--warn); margin: 4px 0 10px; }
    .tiers { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin: 12px 0; }
    @media (max-width: 700px) { .tiers { grid-template-columns: 1fr; } }
    .tier { text-align: start; background: var(--surface); border: 1px solid var(--line); border-radius: var(--r); padding: 12px; display: grid; gap: 2px; color: var(--ink); }
    .tier[aria-pressed="true"] { border: 2px solid var(--olive); background: var(--olive-soft); padding: 11px; }
    .tn { font-weight: 700; display: flex; gap: 6px; align-items: center; }
    .tier b { font-family: var(--display); font-size: 1.4rem; color: var(--olive); }
    .doc { display: grid; gap: 12px; }
    .table-wrap { overflow-x: auto; } table { min-width: 640px; }
    .end { text-align: end; }
    .sku { font-size: .72rem; color: var(--muted); direction: ltr; text-align: start; font-family: ui-monospace, monospace; }
    .small { font-size: .78rem; }
    .src-requested { background: var(--olive-soft); } .src-suggested { background: var(--honey-soft); color: #8a5c06; } .src-rule { background: var(--bg); color: var(--muted); }
    .conf { display: inline-flex; gap: 5px; align-items: center; font-size: .8rem; }
    .conf i { width: 9px; height: 9px; border-radius: 50%; background: var(--muted); }
    .c-high i { background: var(--ok); } .c-medium i { background: var(--warn); } .c-low i { background: var(--bad); } .c-rule i { background: var(--olive); }
    .totals { justify-self: end; display: grid; grid-template-columns: 1fr auto; gap: 4px 24px; min-width: min(320px, 100%); }
    .grand { font-family: var(--display); font-size: 1.3rem; font-weight: 700; color: var(--olive); border-top: 2px solid var(--olive); padding-top: 4px; }
    .ok { color: var(--ok); }
    .budget { margin: 0; padding: 8px 12px; border-radius: 8px; background: var(--ok-soft); color: var(--ok); }
    .budget.over { background: var(--warn-soft); color: var(--warn); }
    .warnbox { background: var(--warn-soft); border: 1px solid var(--warn); border-radius: 8px; padding: 8px 12px; margin: 6px 0; }
    .cols { display: grid; grid-template-columns: 1.3fr 1fr; gap: 14px; margin-top: 14px; align-items: start; }
    .rejectbox { display: grid; gap: 10px; margin-top: 14px; border-color: var(--bad); }
    .rejectbox .row { display: flex; gap: 8px; flex-wrap: wrap; } .rejectbox input { flex: 1; min-width: 200px; }
    .chip.on { background: var(--bad-soft); border-color: var(--bad); color: var(--bad); }
    .rejected-why { margin-top: 14px; background: var(--bad-soft); color: var(--bad); }
    .cols.single { grid-template-columns: 1fr; }
    @media (max-width: 900px) { .cols { grid-template-columns: 1fr; } }
    h2 { display: flex; gap: 8px; align-items: center; margin-bottom: 10px; }
    .edit { display: flex; gap: 6px; } .edit input { flex: 1; min-width: 0; }
    .examples { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 8px; }
    .chip { border: 1px solid var(--line); background: var(--surface); border-radius: 99px; padding: 2px 10px; font-size: .82rem; }
    .reply { background: var(--olive-soft); border-radius: 8px; padding: 8px 12px; }
    .log { display: flex; gap: 4px; flex-wrap: wrap; }
    code { font-size: .75rem; border: 1px solid var(--line); border-radius: 4px; padding: 0 6px; direction: ltr; }
    code.bad { color: var(--bad); border-color: var(--bad); }
    .mail { white-space: pre-wrap; background: var(--bg); border-radius: 8px; padding: 10px; }
    .src-msg { margin-top: 14px; } .src-msg p { white-space: pre-wrap; }
  `],
})
export class QuoteDetailComponent {
  private api = inject(ApiService);
  id = input.required<string>();
  q = signal<StoredQuote | null>(null);
  view = signal<string>('recommended');
  dealId = signal<string | null>(null);
  error = signal('');
  editing = signal(false);
  lastEdit = signal<EditOut | null>(null);
  copied = signal(false);
  instruction = '';
  askReject = signal(false); rejectReason = ''; reasons = REJECT_REASONS;
  rejectNote = computed(() => [...(this.q()?.history ?? [])].reverse().find((h) => h.status === 'rejected')?.note ?? null);
  eventType = EVENT_TYPE; meal = MEAL; kashrut = KASHRUT; status = QUOTE_STATUS;
  unit = UNIT; src = LINE_SOURCE; conf = CONFIDENCE;
  editExamples = ['תחליף את השיפודים בסושי', 'תוריד ל-100 אורחים', 'תוסיף עמדת קפה ותה', 'תן ללקוח 15% הנחה'];

  tier = computed<TierQuote | undefined>(() => this.q()?.tiers.find((t) => t.key === this.view()));
  diets = computed(() => (this.q()?.request.dietary_requirements ?? []).map((d) => dietLabel(d.guest_count ? `${d.tag}:${d.guest_count}` : d.tag)).join(', '));
  email = computed(() => {
    const q = this.q(); const t = this.tier();
    if (!q || !t) return '';
    const name = q.request.contact.name ?? '';
    const total = '₪' + t.quote.total.toLocaleString('he-IL', { minimumFractionDigits: 2 });
    return [`שלום ${name}`.trim() + ',', t.plan.cover_note, `מצורפת הצעת מחיר מס' ${q.number}, חבילת ${t.name}, על סך ${total} כולל מע"מ, בתוקף ל-14 יום.`, 'בברכה,\nזית ודבש קייטרינג']
      .filter(Boolean).join('\n\n');
  });

  constructor() { effect(() => this.load(this.id()), { allowSignalWrites: true }); }

  load(id = this.id()) {
    this.api.quote(id).subscribe({
      next: (q) => { this.q.set(q); this.view.set(q.selected_tier); },
      error: () => this.error.set('ההצעה לא נמצאה או שהשרת לא זמין'),
    });
    this.api.deals().subscribe((ds) => this.dealId.set(ds.find((d) => d.quote_ids.includes(id))?.id ?? null));
  }
  reject() {
    this.api.setQuoteStatus(this.id(), 'rejected', undefined, this.rejectReason.trim()).subscribe({
      next: (r) => { this.askReject.set(false); this.rejectReason = ''; this.q.set(r.quote); this.load(); },
      error: (e) => this.error.set(e.error?.detail ?? 'לא ניתן לעדכן סטטוס'),
    });
  }
  setStatus(s: QuoteStatus) {
    this.api.setQuoteStatus(this.id(), s, s === 'approved' ? this.view() : undefined).subscribe({
      next: (r) => { this.q.set(r.quote); this.load(); },
      error: (e) => this.error.set(e.error?.detail ?? 'לא ניתן לעדכן סטטוס'),
    });
  }
  edit() {
    this.editing.set(true);
    this.api.editQuote(this.id(), this.instruction).subscribe({
      next: (r) => { this.lastEdit.set(r); this.q.set(r.quote); this.instruction = ''; this.editing.set(false); },
      error: () => { this.editing.set(false); this.error.set('העריכה נכשלה. בדקו שמפתח ה-API מוגדר ב-backend.'); },
    });
  }
  async copy() {
    try { await navigator.clipboard.writeText(this.email()); this.copied.set(true); setTimeout(() => this.copied.set(false), 2000); } catch { /* blocked */ }
  }
}

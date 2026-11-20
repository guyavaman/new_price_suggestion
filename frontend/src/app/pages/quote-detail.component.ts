import { PackageMenuComponent } from '../core/package-menu.component';
import { Component, computed, effect, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { ApiService } from '../core/api.service';
import { HeDatePipe, IlsPipe } from '../core/format';
import { CONFIDENCE, EVENT_TYPE, KASHRUT, LINE_SOURCE, MEAL, QUOTE_STATUS, REJECT_REASONS, UNIT, dietLabel } from '../core/labels';
import { EditOut, OwnerMenu, QuoteProfit, QuoteStatus, StoredQuote, TierQuote } from '../core/models';

@Component({
  selector: 'app-quote-detail',
  standalone: true,
  imports: [FormsModule, RouterLink, IlsPipe, HeDatePipe, PackageMenuComponent],
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
          <a class="btn ghost" [href]="'/print/' + q.public_token + '?tier=' + view()" target="_blank" rel="noopener">הדפסה / PDF</a>
          @if (q.status === 'draft' || q.status === 'rejected' || q.status === 'expired') { <button class="btn ghost" (click)="setStatus('sent')">סמן כנשלחה</button> }
          @if (q.status !== 'approved') {
            <button class="btn" (click)="setStatus('approved')">הלקוח אישר את חבילת {{ tier()?.name }}</button>
            @if (q.status !== 'rejected') { <button class="btn danger" (click)="askReject.set(true)">הלקוח דחה</button> }
          }
        </div>
      </div>

      @if (confirmSend()) {
        <section class="card confirm-send" role="alertdialog" aria-labelledby="cs-h">
          <h2 id="cs-h">לשלוח בכל זאת?</h2>
          <ul>@for (b of profit()?.send_blockers ?? []; track b) { <li>{{ b }}</li> }</ul>
          <p class="muted">אם תאשר, ההצעה תסומן כנשלחה וההחלטה תירשם בציר הזמן של האירוע.</p>
          <div class="row">
            <button class="btn danger" (click)="setStatus('sent', true)">שליחה באישורי</button>
            <button class="btn ghost" (click)="confirmSend.set(false)">ביטול</button>
          </div>
        </section>
      }

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

      @if (tierProfit(); as tp) {
        <section class="card profit" [class.alarm]="tp.summary.status === 'missing' || tp.summary.below_floor" aria-label="רווחיות החבילה">
          <div class="profit-head">
            <h2>רווח בחבילת {{ tp.name }}</h2>
            <small class="muted">רק לך · לפני מע"מ · רצפה {{ pct(profit()!.floor) }}</small>
          </div>
          @if (tp.summary.status === 'missing') {
            <div class="bar hatched" role="img" aria-label="עלות חסרה, אין חישוב רווח"><span>עלות חסרה</span></div>
            <p class="miss-line">אי אפשר לחשב רווח עד שתוזן עלות ל: <b>{{ tp.missing_detail.join(', ') }}</b>.
              <a routerLink="/menu">להזנת עלויות ←</a></p>
          } @else {
            <div class="bar" role="img" [attr.aria-label]="'רווח ' + pct(tp.summary.margin!)">
              @for (g of tp.summary.by_group; track g.group) {
                @if (g.cost) { <i class="seg g-{{ g.group }}" [style.flex-grow]="g.cost" [title]="g.label + ': ' + (g.cost | ils)"></i> }
              }
              <i class="seg profit-seg" [class.low]="tp.summary.below_floor" [style.flex-grow]="max0(tp.summary.gross_profit!)"></i>
              <b class="floor-mark" [style.inset-inline-end.%]="profit()!.floor * 100" aria-hidden="true"></b>
            </div>
            <div class="profit-figs">
              <div><span>מחיר לפני מע"מ</span><b class="num">{{ tp.summary.revenue_net | ils }}</b></div>
              <div><span>עלות</span><b class="num">{{ tp.summary.total_cost | ils }}</b></div>
              <div class="big" [class.low]="tp.summary.below_floor"><span>רווח גולמי</span><b class="num">{{ tp.summary.gross_profit | ils }} · {{ pct(tp.summary.margin!) }}</b></div>
            </div>
            @if (tp.summary.below_floor) { <p class="floor-warn">הרווח מתחת לרצפה שהגדרת ({{ pct(profit()!.floor) }}). שליחה תדרוש אישור מפורש.</p> }
          }
          <ul class="legend">
            @for (g of tp.summary.by_group; track g.group) {
              <li><i class="dot g-{{ g.group }}"></i>{{ g.label }} <span class="num">@if (g.cost !== null) { {{ g.cost | ils }} } @else { <em>חסר</em> }</span></li>
            }
          </ul>
          <details class="all-tiers"><summary>שלוש החבילות</summary>
            <table><tbody>
              @for (x of profit()!.tiers; track x.key) {
                <tr><td>{{ x.name }}</td><td class="num">{{ x.summary.revenue_net | ils }}</td>
                  <td class="num">@if (x.summary.margin !== null) { <span [class.low]="x.summary.below_floor">{{ x.summary.gross_profit | ils }} · {{ pct(x.summary.margin) }}</span> } @else { <span class="miss-tag">עלות חסרה</span> }</td></tr>
              }
            </tbody></table>
          </details>
        </section>
      }

      @if (menu(); as m) {
        @if (m.packages.length) {
          <section class="card qmenu" aria-labelledby="qm-h">
            <div class="profit-head">
              <h2 id="qm-h">מנות וכמויות</h2>
              <small class="muted">
                @if (m.lock.customer_can_choose) { הלקוח יכול לבחור בקישור @if (m.lock.lock_date) { עד {{ m.lock.lock_date | heDate }} } }
                @else { {{ m.lock.reason }} }
              </small>
            </div>
            <app-package-menu [packages]="m.packages" [busy]="menuBusy()" (save)="saveMenu($event)" />
            @if (menuError()) { <p class="err" role="alert">{{ menuError() }}</p> }
          </section>
        }
      }

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
    .qmenu { margin-top: 14px; display: grid; gap: 10px; min-width: 0; }
    .profit { margin-top: 14px; display: grid; gap: 10px; min-width: 0; }
    .profit > * { min-width: 0; }
    .profit.alarm { border-color: var(--warn); }
    .profit-head { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; flex-wrap: wrap; }
    .bar { position: relative; display: flex; height: 26px; border-radius: 6px; overflow: hidden; background: var(--paper); direction: rtl; }
    .seg { display: block; min-width: 2px; }
    .g-food { background: #8f9c6a; } .g-staff { background: #5d6e86; } .g-equipment { background: #a98c62; } .g-logistics { background: #7f6d8f; }
    .profit-seg { background: var(--ok); } .profit-seg.low { background: var(--bad); }
    .floor-mark { position: absolute; top: -3px; bottom: -3px; width: 0; border-inline-start: 2px dashed var(--ink); }
    .bar.hatched { align-items: center; justify-content: center; background: repeating-linear-gradient(-45deg, var(--warn-soft) 0 8px, #f6e4c3 8px 16px); color: var(--warn); font-weight: 700; font-size: .85rem; }
    .profit-figs { display: flex; gap: 22px; flex-wrap: wrap; }
    .profit-figs div { display: grid; } .profit-figs span { font-size: .78rem; color: var(--muted); }
    .profit-figs .big b { font-family: var(--display); font-size: 1.35rem; color: var(--ok); }
    .profit-figs .big.low b, .low { color: var(--bad); }
    .floor-warn { margin: 0; background: var(--bad-soft); color: var(--bad); border-radius: 8px; padding: 6px 10px; font-weight: 600; }
    .miss-line { margin: 0; color: var(--warn); }
    .legend { display: flex; gap: 14px; flex-wrap: wrap; list-style: none; padding: 0; margin: 0; font-size: .85rem; color: var(--muted); }
    .legend .dot { display: inline-block; width: 10px; height: 10px; border-radius: 3px; margin-inline-end: 5px; vertical-align: -1px; }
    .legend em { color: var(--warn); font-style: normal; font-weight: 700; }
    .miss-tag { color: var(--warn); font-weight: 700; font-size: .85rem; white-space: nowrap; }
    .all-tiers summary { cursor: pointer; color: var(--olive); font-weight: 600; }
    .all-tiers table { width: 100%; border-collapse: collapse; } .all-tiers td { padding: 4px 6px; border-top: 1px solid var(--line); }
    .confirm-send { margin-top: 14px; border-color: var(--bad); display: grid; gap: 6px; }
    .confirm-send ul { margin: 0; color: var(--bad); } .confirm-send .row { display: flex; gap: 8px; flex-wrap: wrap; }
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
    .cols > * { min-width: 0; } .mail { overflow-wrap: anywhere; }
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
    const link = `${location.origin}/q/${q.public_token}`;
    return [`שלום ${name}`.trim() + ',', t.plan.cover_note, `הצעת מחיר מס' ${q.number}: חבילת ${t.name} על סך ${total} כולל מע"מ, ועוד שתי חבילות לבחירה.`,
      `בוחרים, מאשרים ומשלמים מקדמה כאן: ${link}\nיש שאלה? אפשר לכתוב לנועה בעמוד, בכל שעה.`, 'בברכה,\nזית ודבש קייטרינג']
      .filter(Boolean).join('\n\n');
  });

  constructor() { effect(() => this.load(this.id()), { allowSignalWrites: true }); }

  profit = signal<QuoteProfit | null>(null);
  confirmSend = signal(false);
  tierProfit = computed(() => this.profit()?.tiers.find((t) => t.key === this.view()) ?? null);
  pct(x: number) { return `${Math.round(x * 100)}%`; }
  max0(x: number) { return Math.max(0, x); }

  menu = signal<OwnerMenu | null>(null);
  menuBusy = signal(false);
  menuError = signal('');
  saveMenu(e: { pkg: string; choice: Record<string, string[]> }) {
    this.menuBusy.set(true); this.menuError.set('');
    this.api.setQuoteMenu(this.id(), e.pkg, e.choice).subscribe({
      next: (m) => { this.menuBusy.set(false); this.menu.set(m); this.load(); },
      error: (err) => { this.menuBusy.set(false); this.menuError.set(err.error?.detail ?? 'לא ניתן לשמור את המנות'); },
    });
  }

  load(id = this.id()) {
    this.api.quoteMenu(id).subscribe({ next: (m) => this.menu.set(m), error: () => this.menu.set(null) });
    this.api.quoteProfit(id).subscribe({ next: (p) => this.profit.set(p), error: () => this.profit.set(null) });
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
  setStatus(s: QuoteStatus, overrideFloor = false) {
    if (s === 'sent' && !overrideFloor && this.profit()?.send_blockers.length) { this.confirmSend.set(true); return; }
    this.api.setQuoteStatus(this.id(), s, s === 'approved' ? this.view() : undefined, undefined, overrideFloor).subscribe({
      next: (r) => { this.confirmSend.set(false); this.q.set(r.quote); this.load(); },
      error: (e) => this.error.set(typeof e.error?.detail === 'string' ? e.error.detail : e.error?.detail?.message ?? 'לא ניתן לעדכן סטטוס'),
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

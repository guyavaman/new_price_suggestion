import { Component, ElementRef, computed, effect, inject, input, signal, viewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../core/api.service';
import { HeDatePipe, IlsPipe } from '../core/format';
import { CUSTOMER_REJECT_REASONS, KASHRUT, MEAL, UNIT } from '../core/labels';
import { PublicQuote, ServiceChat } from '../core/models';

/** What the customer sees from the link: pick a package, approve, pay the deposit. */
@Component({
  selector: 'app-customer-quote',
  standalone: true,
  imports: [FormsModule, IlsPipe, HeDatePipe],
  template: `
    <div class="wrap">
      @if (error()) { <div class="err">{{ error() }}</div> }
      @if (q(); as q) {
        <header>
          <div><b class="biz">{{ q.business_name }}</b><span class="muted">הצעת מחיר <bdi class="ref">{{ q.number }}</bdi></span></div>
          <a [href]="'tel:' + q.business_phone" class="muted" dir="ltr">{{ q.business_phone }}</a>
        </header>
        <h1>{{ q.customer_name ? 'שלום ' + q.customer_name + ',' : 'שלום,' }} הנה ההצעה ל{{ q.event.type }}</h1>
        <p class="ev">{{ q.event.date | heDate }} · {{ q.final_guest_count ?? q.event.guests }} אורחים
          @if (q.event.meal_type) { · {{ meal[q.event.meal_type] }} } @if (q.event.kashrut) { · {{ kashrut[q.event.kashrut] }} }
          @if (q.event.location) { · {{ q.event.location }} }</p>
        @if (q.cover_note) { <p class="note">{{ q.cover_note }}</p> }

        @if (q.status === 'approved') {
          <div class="done">
            <b>ההצעה אושרה 🎉</b> חבילת {{ chosen()?.name }} · {{ chosen()?.total | ils }} כולל מע"מ
            @if (q.deposit_paid) { · מקדמה של {{ q.deposit_paid | ils }} התקבלה }
          </div>
          @if (q.can_update_count) {
            <form class="card count" (ngSubmit)="updateCount()">
              <label for="g">מספר אורחים סופי</label>
              <input id="g" name="g" type="number" min="1" [(ngModel)]="guests">
              <button class="btn" [disabled]="busy() || !guests">עדכון</button>
              <small class="muted">אפשר לעדכן עד יומיים לפני האירוע. המחיר יתעדכן בהתאם.</small>
            </form>
          }
        } @else if (q.expired) {
          <div class="err">תוקף ההצעה פג ב-{{ q.valid_until | heDate }}. דברו איתנו ונעדכן אותה: {{ q.business_phone }}</div>
        }

        <div class="tiers" role="radiogroup" aria-label="בחירת חבילה">
          @for (t of q.tiers; track t.key) {
            <button class="tier" role="radio" [attr.aria-checked]="pick() === t.key" [disabled]="!q.can_accept && q.status !== 'approved'" (click)="q.can_accept && pick.set(t.key)">
              <span class="tn">{{ t.name }} @if (t.key === 'recommended') { <em>מומלץ</em> }</span>
              <b class="num">{{ t.total | ils }}</b>
              <small class="muted num">{{ t.per_guest | ils }} לאורח · כולל מע"מ</small>
              <ul>@for (i of t.items; track $index) { <li>{{ i.name }} <span class="muted">× {{ i.quantity }} {{ unit[i.unit] }}</span></li> }</ul>
              @if (t.services.length) { <p class="svc">כולל: {{ t.services.join(' · ') }}</p> }
            </button>
          }
        </div>

        @if (q.can_accept) {
          <div class="accept card">
            <div><b>בחרתם: {{ selected()?.name }}</b> · {{ selected()?.total | ils }}
              @if (q.deposit_rate > 0) { <div class="muted">לאישור משלמים מקדמה של {{ selected()?.deposit | ils }} ({{ q.deposit_rate * 100 }}%). היתרה לפני האירוע.</div> }</div>
            <button class="btn big" [disabled]="busy()" (click)="accept()">{{ busy() ? 'רגע…' : q.deposit_rate > 0 ? 'אישור ותשלום מקדמה' : 'אישור ההצעה' }}</button>
          </div>
          <p class="muted small">ההצעה בתוקף עד {{ q.valid_until | heDate }}
            · <button class="link" type="button" (click)="declining.set(!declining())">ההצעה לא מתאימה לנו</button></p>
          @if (declining()) {
            <form class="card decline" (ngSubmit)="decline()">
              <b>חבל! נשמח לדעת למה, כדי שנוכל להשתפר:</b>
              <div class="chips">@for (r of reasons; track r) { <button type="button" class="chip" [class.on]="reason === r" (click)="reason = r">{{ r }}</button> }</div>
              <div class="row">
                <input name="why" [(ngModel)]="reason" placeholder="או כתבו לנו במילים שלכם" aria-label="סיבה">
                <button class="btn" [disabled]="busy() || !reason.trim()">שליחה</button>
              </div>
            </form>
          }
        }
        @if (q.status === 'rejected') {
          <div class="note">תודה שעדכנתם. אם משהו ישתנה, נשמח לבנות לכם הצעה חדשה: {{ q.business_phone }}</div>
        }
      }
    </div>

    @if (q()) {
      @if (chatOpen()) {
        <section class="chat card" aria-label="צ'אט עם נועה">
          <header><b>נועה · שירות לקוחות</b><button class="x" type="button" aria-label="סגירה" (click)="chatOpen.set(false)">✕</button></header>
          <div class="msgs" #msgs>
            @if (!chat().length) { <p class="bubble ai">היי! אני נועה 👋 אפשר לשאול אותי על ההזמנה: מה כלול, כמה נשאר לשלם, לעדכן מספר אורחים או לבקש שינוי.</p> }
            @for (m of chat(); track $index) { <p class="bubble" [class.ai]="m.role === 'assistant'" [class.human]="m.by === 'human'">{{ m.text }}</p> }
            @if (sending()) { <p class="bubble ai typing">…</p> }
            @if (chatError()) { <p class="err small">{{ chatError() }}</p> }
          </div>
          <form (ngSubmit)="send()">
            <input name="cm" [(ngModel)]="draft" placeholder="כתבו הודעה…" aria-label="הודעה" autocomplete="off">
            <button class="btn" [disabled]="sending() || !draft.trim()">שליחה</button>
          </form>
        </section>
      } @else {
        <button class="fab btn" type="button" (click)="openChat()">שאלה על ההזמנה? 💬</button>
      }
    }
  `,
  styles: [`
    .fab { position: fixed; bottom: 18px; left: 18px; border-radius: 99px; padding: 12px 18px; box-shadow: 0 6px 20px rgba(0,0,0,.18); z-index: 20; }
    .chat { position: fixed; bottom: 18px; left: 18px; width: min(380px, calc(100vw - 36px)); height: min(540px, calc(100vh - 36px)); display: flex; flex-direction: column; padding: 0; overflow: hidden; z-index: 20; box-shadow: 0 10px 30px rgba(0,0,0,.2); }
    .chat header { display: flex; justify-content: space-between; align-items: center; padding: 12px 14px; background: var(--olive); color: #fff; border: 0; margin: 0; }
    .chat .x { background: none; border: 0; color: #fff; font-size: 1rem; cursor: pointer; }
    .msgs { flex: 1; overflow-y: auto; padding: 12px; display: flex; flex-direction: column; gap: 8px; background: var(--bg); }
    .bubble { margin: 0; padding: 8px 12px; border-radius: 14px; max-width: 85%; white-space: pre-wrap; line-height: 1.5; align-self: flex-start; background: var(--olive); color: #fff; }
    .bubble.ai { align-self: flex-end; background: var(--surface); color: var(--ink); border: 1px solid var(--line); }
    .bubble.human { border-color: var(--honey); }
    .typing { opacity: .6; }
    .chat form { display: flex; gap: 6px; padding: 10px; border-top: 1px solid var(--line); }
    .chat form input { flex: 1; min-width: 0; }

    .wrap { max-width: 980px; margin: 0 auto; padding: 20px 16px 60px; }
    header { display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid var(--olive); padding-bottom: 10px; margin-bottom: 18px; }
    header div { display: grid; } .biz { font-family: var(--display); font-size: 1.5rem; color: var(--olive); }
    h1 { font-size: 1.6rem; margin-bottom: 4px; } .ev { color: var(--muted); margin: 0 0 12px; }
    .note { background: var(--olive-soft); border-radius: 10px; padding: 12px 14px; }
    .done { background: var(--ok-soft); color: var(--ok); border-radius: 10px; padding: 12px 14px; margin: 12px 0; }
    .count { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 12px; } .count input { width: 110px; }
    .decline { display: grid; gap: 10px; margin-top: 10px; } .decline .row { display: flex; gap: 8px; flex-wrap: wrap; } .decline input { flex: 1; min-width: 200px; }
    .chips { display: flex; flex-wrap: wrap; gap: 6px; } .chip.on { background: var(--olive-soft); border-color: var(--olive); }
    .link { background: none; border: 0; padding: 0; color: var(--muted); text-decoration: underline; cursor: pointer; font: inherit; }
    .tiers { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin: 16px 0; }
    @media (max-width: 760px) { .tiers { grid-template-columns: 1fr; } }
    .tier { text-align: start; background: var(--surface); border: 1px solid var(--line); border-radius: 12px; padding: 14px; display: grid; gap: 4px; align-content: start; color: var(--ink); }
    .tier[aria-checked="true"] { border: 2px solid var(--olive); background: var(--olive-soft); padding: 13px; }
    .tier:disabled { cursor: default; }
    .tn { font-weight: 700; display: flex; gap: 6px; align-items: center; } .tn em { font-style: normal; font-size: .72rem; background: var(--honey); color: #fff; border-radius: 99px; padding: 0 8px; }
    .tier b { font-family: var(--display); font-size: 1.6rem; color: var(--olive); }
    .tier ul { margin: 6px 0 0; padding-inline-start: 18px; font-size: .88rem; display: grid; gap: 2px; }
    .svc { font-size: .8rem; color: var(--muted); margin: 6px 0 0; }
    .accept { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; position: sticky; bottom: 10px; box-shadow: 0 6px 24px rgba(0,0,0,.12); }
    .big { font-size: 1.05rem; padding: 12px 22px; } .small { font-size: .85rem; }
  `],
})
export class CustomerQuoteComponent {
  private api = inject(ApiService);
  token = input.required<string>();
  q = signal<PublicQuote | null>(null);
  pick = signal('recommended');
  busy = signal(false);
  error = signal('');
  guests: number | null = null;
  meal = MEAL; kashrut = KASHRUT; unit = UNIT;
  chatOpen = signal(false); chat = signal<ServiceChat['messages']>([]); sending = signal(false); chatError = signal(''); draft = '';
  private msgs = viewChild<ElementRef<HTMLElement>>('msgs');
  declining = signal(false); reason = ''; reasons = CUSTOMER_REJECT_REASONS;
  selected = computed(() => this.q()?.tiers.find((t) => t.key === this.pick()));
  chosen = computed(() => { const q = this.q(); return q?.tiers.find((t) => t.key === q.selected_tier); });

  constructor() { effect(() => this.load(this.token()), { allowSignalWrites: true }); }
  load(token: string) {
    this.api.publicQuote(token).subscribe({
      next: (q) => { this.q.set(q); this.pick.set(q.selected_tier); this.guests = q.final_guest_count ?? q.event.guests; },
      error: () => this.error.set('הקישור לא תקין או שפג תוקפו.'),
    });
  }
  accept() {
    this.busy.set(true);
    this.api.acceptQuote(this.token(), this.pick()).subscribe({
      next: (r) => { if (r.checkout_url) location.href = r.checkout_url; else { this.busy.set(false); this.load(this.token()); } },
      error: (e) => { this.busy.set(false); this.error.set(e.error?.detail ?? 'משהו השתבש, נסו שוב'); },
    });
  }
  openChat() {
    this.chatOpen.set(true);
    this.api.serviceChatHistory(this.token()).subscribe({ next: (r) => { this.chat.set(r.messages); this.scroll(); } });
  }
  send() {
    const text = this.draft.trim();
    if (!text) return;
    this.draft = ''; this.chatError.set(''); this.sending.set(true);
    this.chat.update((m) => [...m, { role: 'user', text, by: 'customer' }]); this.scroll();
    this.api.serviceChat(this.token(), text).subscribe({
      next: (r) => { this.sending.set(false); this.chat.set(r.messages); this.scroll(); this.load(this.token()); },
      error: (e) => { this.sending.set(false); this.chatError.set(e.error?.detail ?? 'ההודעה לא נשלחה, נסו שוב'); },
    });
  }
  private scroll() { setTimeout(() => { const el = this.msgs()?.nativeElement; if (el) el.scrollTop = el.scrollHeight; }); }
  decline() {
    this.busy.set(true);
    this.api.declineQuote(this.token(), this.reason.trim()).subscribe({
      next: (q) => { this.busy.set(false); this.declining.set(false); this.q.set(q); },
      error: (e) => { this.busy.set(false); this.error.set(e.error?.detail ?? 'משהו השתבש, נסו שוב'); },
    });
  }
  updateCount() {
    if (!this.guests) return;
    this.busy.set(true);
    this.api.updateGuestCount(this.token(), this.guests).subscribe({
      next: (q) => { this.busy.set(false); this.q.set(q); },
      error: (e) => { this.busy.set(false); this.error.set(e.error?.detail ?? 'לא ניתן לעדכן'); },
    });
  }
}

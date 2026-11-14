import { Component, ElementRef, inject, signal, viewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../core/api.service';

interface Bubble { role: 'user' | 'assistant'; text: string; tools?: string[] }

const TOOL_LABEL: Record<string, string> = {
  save_lead: 'נשמר ב-CRM', check_availability: 'בדק זמינות', estimate_price: 'חישב הערכה',
  create_quote: 'יצר הצעת מחיר', handoff_to_human: 'הועבר לנציג', search_menu: 'חיפש בתפריט',
  schedule_callback: 'קבע שיחה חוזרת',
};

/** The customer-facing website widget, shown here as a demo page. */
@Component({
  selector: 'app-chat-widget',
  standalone: true,
  imports: [FormsModule],
  template: `
    <div class="page-head"><div><h1>צ'אט לקוח</h1><p>כך הסוכן נראה באתר של העסק. כל מה שהוא אוסף מופיע מיד ב-CRM.</p></div>
      <button class="btn ghost" (click)="reset()">שיחה חדשה</button></div>
    <div class="phone">
      <header><b>נועה · זית ודבש</b><span>{{ status() === 'human' ? 'נציג מהצוות בשיחה' : status() === 'handed_off' ? 'נציג יצטרף בקרוב · נועה ממשיכה לעזור' : 'סוכנת דיגיטלית · עונה מיד' }}</span></header>
      <div class="msgs" #box>
        @for (m of msgs(); track $index) {
          <div class="msg {{ m.role }}">{{ m.text }}
            @if (m.tools?.length) { <div class="tools">@for (t of m.tools; track $index) { <span>✓ {{ label(t) }}</span> }</div> }
          </div>
        }
        @if (busy()) { <div class="msg assistant typing">נועה מקלידה…</div> }
      </div>
      <div class="chips">@for (s of starters; track s) { <button type="button" (click)="text = s">{{ s }}</button> }</div>
      <form (ngSubmit)="send()">
        <input name="t" [(ngModel)]="text" placeholder="כתבו הודעה…" autocomplete="off" aria-label="הודעה">
        <button class="btn" [disabled]="busy() || !text.trim()">שליחה</button>
      </form>
      @if (error()) { <p class="err">{{ error() }}</p> }
    </div>
  `,
  styles: [`
    .phone { max-width: 440px; margin: 0 auto; background: var(--surface); border: 1px solid var(--line); border-radius: 18px; overflow: hidden; display: grid; }
    header { background: var(--olive); color: #fff; padding: 12px 16px; display: grid; }
    header span { font-size: .8rem; opacity: .8; }
    .msgs { height: 440px; overflow: auto; padding: 14px; display: flex; flex-direction: column; gap: 8px; background: var(--bg); }
    .msg { max-width: 82%; padding: 9px 12px; border-radius: 14px; white-space: pre-wrap; }
    .msg.user { align-self: flex-end; background: var(--olive); color: #fff; border-end-end-radius: 4px; }
    .msg.assistant { align-self: flex-start; background: var(--surface); border: 1px solid var(--line); border-end-start-radius: 4px; }
    .typing { color: var(--muted); font-style: italic; }
    .tools { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 6px; }
    .tools span { font-size: .72rem; background: var(--olive-soft); color: var(--olive); border-radius: 99px; padding: 1px 8px; }
    .chips { display: flex; gap: 6px; overflow-x: auto; padding: 8px 10px 0; }
    .chips button { white-space: nowrap; border: 1px solid var(--line); background: var(--surface); border-radius: 99px; padding: 3px 10px; font-size: .82rem; }
    form { display: flex; gap: 6px; padding: 10px; } form input { flex: 1; min-width: 0; }
    .err { margin: 0 10px 10px; }
  `],
})
export class ChatWidgetComponent {
  private api = inject(ApiService);
  box = viewChild<ElementRef<HTMLDivElement>>('box');
  msgs = signal<Bubble[]>([{ role: 'assistant', text: 'היי! אני נועה מזית ודבש 🙂 איזה אירוע אתם מתכננים?' }]);
  busy = signal(false);
  status = signal<string>('active');
  error = signal('');
  text = '';
  conversationId: string | null = null;
  starters = ['בר מצווה ל-120 איש בדצמבר', 'כמה עולה אירוע חלבי ל-40 איש?', 'יש לכם תפריט טבעוני?'];

  label(t: string) { return TOOL_LABEL[t] ?? t; }
  reset() { this.conversationId = null; this.status.set('active'); this.msgs.set(this.msgs().slice(0, 1)); }

  send() {
    const text = this.text.trim();
    if (!text || this.busy()) return;
    this.text = '';
    this.error.set('');
    this.msgs.update((m) => [...m, { role: 'user', text }]);
    this.busy.set(true);
    this.scroll();
    this.api.chat(text, this.conversationId).subscribe({
      next: (r) => {
        this.conversationId = r.conversation_id;
        if (r.reply) this.msgs.update((m) => [...m, { role: 'assistant', text: r.reply, tools: r.actions }]);
        this.status.set(r.status);
        this.busy.set(false);
        this.scroll();
      },
      error: () => { this.busy.set(false); this.error.set('אין חיבור לשרת. נסו שוב בעוד רגע.'); },
    });
  }
  private scroll() { setTimeout(() => { const el = this.box()?.nativeElement; if (el) el.scrollTop = el.scrollHeight; }); }
}

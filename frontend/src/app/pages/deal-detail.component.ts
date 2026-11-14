import { Component, computed, effect, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { ApiService } from '../core/api.service';
import { HeDatePipe, IlsPipe, RelativePipe } from '../core/format';
import { ACTOR, EVENT_TYPE, KASHRUT, MEAL, QUOTE_STATUS, SOURCE, STAGES, TEMP, dietLabel } from '../core/labels';
import { BusinessSettings, DealDetail, DealStage } from '../core/models';

@Component({
  selector: 'app-deal-detail',
  standalone: true,
  imports: [RouterLink, FormsModule, IlsPipe, HeDatePipe, RelativePipe],
  template: `
    <a routerLink="/events" class="back">→ כל האירועים</a>
    @if (error()) { <div class="err">{{ error() }}</div> }
    @if (x(); as x) {
      <div class="page-head">
        <div>
          <h1>{{ x.deal.title }}</h1>
          <p>
            <span class="temp temp-{{ x.deal.temperature }}">{{ temp[x.deal.temperature] }}</span>
            @if (x.deal.ready_to_book) { <span class="pill hot">רוצה לסגור</span> }
            @if (x.deal.source === 'web_chat') { <span class="pill ai">הגיע מסוכן AI</span> } @else { <span class="pill">{{ source[x.deal.source] }}</span> }
            <span class="muted">נפתח {{ x.deal.created_at | rel }}</span>
          </p>
        </div>
        <div class="stages" role="group" aria-label="שלב">
          @for (s of stages; track s.key) {
            <button class="st stage-{{ s.key }}" [class.on]="x.deal.stage === s.key" (click)="move(s.key)">{{ s.label }}</button>
          }
        </div>
      </div>
      @if (askLost()) {
        <form class="card lostbox" (ngSubmit)="confirmLost()">
          <label for="lr">למה האירוע לא יצא לפועל?</label>
          <input id="lr" name="lr" [(ngModel)]="lostReason" placeholder="מחיר, תאריך, בחרו ספק אחר…">
          <button class="btn danger" [disabled]="!lostReason.trim()">סמן כאבוד</button>
          <button class="btn ghost" type="button" (click)="askLost.set(false)">ביטול</button>
        </form>
      }

      <div class="layout">
        <div class="grid">
          <section class="card facts">
            <div><span>ערך</span><b class="num">{{ x.deal.value | ils }}</b></div>
            <div><span>תאריך</span><b>{{ x.deal.event_date | heDate }}</b><small class="muted">{{ x.deal.event_date | rel }}</small></div>
            <div><span>אורחים</span><b class="num">{{ x.deal.final_guest_count ?? x.deal.guest_count ?? '—' }}</b>
              <small [class.ok]="x.deal.final_guest_count" class="muted">{{ x.deal.final_guest_count ? 'סופי, אושר ע"י הלקוח' : 'עוד לא סופי' }}</small></div>
            <div><span>ארוחה</span><b>{{ meal[x.deal.meal_type ?? ''] || '—' }} · {{ kashrut[x.deal.kashrut ?? ''] || '—' }}</b></div>
            <div><span>סוג</span><b>{{ eventType[x.deal.event_type ?? ''] || '—' }}</b></div>
            <div><span>מיקום</span><b>{{ x.deal.location || '—' }}</b></div>
            @if (x.deal.dietary.length) { <div><span>תזונה</span><b>{{ diets(x.deal.dietary) }}</b></div> }
            @if (x.deal.budget) { <div><span>תקציב</span><b class="num">{{ x.deal.budget | ils }} {{ x.deal.budget_scope === 'per_guest' ? 'לאורח' : '' }}</b></div> }
          </section>

          <section class="card">
            <div class="h"><h2>הצעת מחיר ותשלום</h2>
              @if (quote(); as q) { <a [routerLink]="['/quotes', q.id]">לפרטי ההצעה המלאים ←</a> }</div>
            @if (quote(); as q) {
              <div class="qh"><b>{{ q.number }}</b><span class="pill">{{ qStatus[q.status] }}</span><span class="muted">{{ q.created_at | heDate }}</span></div>
              <div class="tiers">
                @for (t of q.tiers; track t.key) {
                  <div class="tier" [class.sel]="t.key === q.selected_tier">
                    <span>{{ t.name }} @if (t.key === q.selected_tier && q.status === 'approved') { ✓ }</span>
                    <b class="num">{{ t.total | ils }}</b><small class="muted num">{{ t.per_guest | ils }} לאורח</small>
                  </div>
                }
              </div>
              <div class="link-row">
                <input readonly [value]="customerLink(q.public_token)" aria-label="קישור ללקוח" dir="ltr">
                <button class="btn" (click)="copyLink(q.public_token)">{{ copied() ? 'הועתק ✓' : 'העתק קישור ללקוח' }}</button>
                <a class="btn ghost" [href]="customerLink(q.public_token)" target="_blank" rel="noopener">תצוגת לקוח</a>
              </div>
              <p class="muted small">בקישור הלקוח בוחר חבילה, מאשר ומשלם מקדמה. בהמשך הוא מאשר בו מספר אורחים סופי.</p>
            } @else {
              <p class="muted">עוד אין הצעת מחיר. אפשר ליצור אחת מתיבת הפניות, או שהסוכנת תיצור כשיהיו מספיק פרטים.</p>
            }
            <h3>תשלומים</h3>
            <ul class="pays">
              @for (p of x.deal.payments; track p.id) {
                <li><span class="pill" [class.ok]="p.status === 'paid'" [class.warn]="p.status === 'pending'">{{ p.status === 'paid' ? 'שולם' : p.status === 'pending' ? 'ממתין' : 'נכשל' }}</span>
                  {{ p.kind === 'deposit' ? 'מקדמה' : 'יתרה' }} <b class="num">{{ p.amount | ils }}</b> <small class="muted">{{ (p.paid_at || p.created_at) | heDate: true }}</small></li>
              } @empty { <li class="muted">עוד לא התקבלו תשלומים</li> }
            </ul>
            @if (x.deal.value && x.deal.deposit_paid) { <p class="num">יתרה לתשלום: <b>{{ x.deal.value - x.deal.deposit_paid | ils }}</b></p> }

            <h3>חשבונית</h3>
            @if (x.deal.invoice; as inv) {
              <p>חשבונית <b><bdi class="ref">{{ inv.number }}</bdi></b> · {{ inv.amount | ils }} · {{ inv.issued_at | heDate }} @if (inv.url) { · <a [href]="inv.url" target="_blank" rel="noopener">פתיחה</a> }</p>
            } @else if (x.deal.stage === 'won' || x.deal.stage === 'completed') {
              <form class="inv" (ngSubmit)="invoice()">
                @if (settings()?.invoice_provider !== 'morning') {
                  <input name="n" [(ngModel)]="invoiceNumber" placeholder="מספר חשבונית מתוכנת החשבונות" aria-label="מספר חשבונית">
                }
                <button class="btn" [disabled]="settings()?.invoice_provider !== 'morning' && !invoiceNumber.trim()">
                  {{ settings()?.invoice_provider === 'morning' ? 'הפק חשבונית בחשבונית ירוקה' : 'שמור חשבונית' }}</button>
              </form>
            } @else { <p class="muted small">חשבונית מופקת אחרי שהאירוע נסגר</p> }
          </section>

          <section class="card">
            <h2>ציר פעילות</h2>
            <form class="note" (ngSubmit)="addNote()">
              <input name="note" [(ngModel)]="note" placeholder="הוספת הערה או סיכום שיחה" aria-label="הערה">
              <select name="kind" [(ngModel)]="noteKind" aria-label="סוג"><option value="note">הערה</option><option value="call">שיחה</option></select>
              <button class="btn" [disabled]="!note.trim()">הוספה</button>
            </form>
            <ol class="timeline">
              @for (a of x.timeline; track a.id) {
                <li class="k-{{ a.kind }}"><span class="who">{{ actor[a.actor] }}</span><p>{{ a.text }}</p><time class="muted">{{ a.at | heDate: true }}</time></li>
              }
            </ol>
          </section>
        </div>

        <aside class="grid">
          <section class="card">
            <h2>לקוח</h2>
            @if (x.customer; as c) {
              <p class="cname">{{ c.name || c.company || 'ללא שם' }}</p>
              @if (c.phone) { <p><a [href]="'tel:' + c.phone" dir="ltr">{{ c.phone }}</a></p> }
              @if (c.email) { <p><a [href]="'mailto:' + c.email">{{ c.email }}</a></p> }
            }
          </section>
          <section class="card">
            <h2>משימות</h2>
            <ul class="tasks">
              @for (t of x.tasks; track t.id) {
                <li [class.done]="t.done" [class.high]="t.priority === 'high'">
                  <input type="checkbox" [checked]="t.done" [disabled]="t.done" (change)="done(t.id)" [attr.aria-label]="t.title">
                  <span>{{ t.title }}<small class="muted">{{ t.due_at | rel }}</small></span>
                </li>
              } @empty { <li class="muted">אין משימות</li> }
            </ul>
            <form class="note" (ngSubmit)="addTask()"><input name="t" [(ngModel)]="task" placeholder="משימה חדשה" aria-label="משימה"><button class="btn ghost" [disabled]="!task.trim()">+</button></form>
          </section>
          <section class="card">
            <h2>למה {{ temp[x.deal.temperature] }}?</h2>
            <ul class="reasons">@for (r of x.deal.score_reasons; track r) { <li>{{ r }}</li> }</ul>
          </section>
          @if (x.conversation; as conv) {
            <section class="card">
              <h2>שיחה עם הסוכנת</h2>
              <div class="chat">@for (m of conv.messages; track $index) { <div class="msg {{ m.role }}" [class.human]="m.by === 'human'">{{ m.text }}</div> }</div>
              <a [routerLink]="['/inbox']" [queryParams]="{ id: conv.id }">לפתוח בתיבת הפניות</a>
            </section>
          }
        </aside>
      </div>
    }
  `,
  styles: [`
    .back { display: inline-block; margin-bottom: 10px; text-decoration: none; }
    .page-head p { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
    .stages { display: flex; flex-wrap: wrap; gap: 4px; }
    .st { border: 1px solid var(--line); background: var(--surface); border-radius: 999px; padding: 4px 11px; font-size: .85rem; color: var(--ink); }
    .st.on { background: var(--st); border-color: var(--st); color: #fff; font-weight: 700; }
    .lostbox { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 12px; }
    .lostbox input { flex: 1; min-width: 200px; }
    .layout { display: grid; grid-template-columns: 1fr 320px; gap: 14px; align-items: start; }
    @media (max-width: 1000px) { .layout { grid-template-columns: 1fr; } }
    h2 { margin-bottom: 10px; } h3 { font-size: 1rem; margin: 14px 0 6px; }
    .h { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; flex-wrap: wrap; }
    .facts { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 12px; }
    .facts div { display: grid; } .facts span { font-size: .78rem; color: var(--muted); }
    .ok { color: var(--ok) !important; }
    .qh { display: flex; gap: 8px; align-items: center; margin-bottom: 8px; }
    .tiers { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
    .tier { border: 1px solid var(--line); border-radius: 8px; padding: 10px; display: grid; gap: 2px; }
    .tier.sel { border: 2px solid var(--olive); background: var(--olive-soft); }
    .tier b { font-family: var(--display); font-size: 1.2rem; color: var(--olive); }
    .link-row { display: flex; gap: 6px; margin-top: 10px; flex-wrap: wrap; }
    .link-row input { flex: 1; min-width: 200px; font-size: .82rem; }
    .small { font-size: .85rem; }
    .pays { list-style: none; margin: 0; padding: 0; display: grid; gap: 4px; }
    .pill.ok { background: var(--ok-soft); color: var(--ok); }
    .inv { display: flex; gap: 6px; flex-wrap: wrap; } .inv input { flex: 1; min-width: 200px; }
    .note { display: flex; gap: 6px; margin-bottom: 10px; } .note input { flex: 1; min-width: 0; }
    .timeline { list-style: none; margin: 0; padding: 0; display: grid; gap: 2px; max-height: 420px; overflow: auto; }
    .timeline li { display: grid; grid-template-columns: 70px 1fr auto; gap: 8px; padding: 8px 6px; border-inline-start: 3px solid var(--line); }
    .timeline li p { margin: 0; } .timeline .who { font-size: .78rem; font-weight: 700; color: var(--muted); } .timeline time { font-size: .78rem; white-space: nowrap; }
    .k-stage { border-color: var(--olive) !important; } .k-quote { border-color: var(--honey) !important; } .k-handoff { border-color: var(--bad) !important; } .k-chat { border-color: #4f7cac !important; }
    .cname { font-weight: 700; font-size: 1.1rem; margin: 0 0 4px; } aside p { margin: 2px 0; }
    .reasons { margin: 0; padding-inline-start: 18px; font-size: .88rem; color: var(--muted); }
    .tasks { list-style: none; margin: 0 0 10px; padding: 0; display: grid; gap: 6px; }
    .tasks li { display: flex; gap: 8px; align-items: start; } .tasks li span { display: grid; }
    .tasks li.high span { font-weight: 700; } .tasks li.done span { text-decoration: line-through; color: var(--muted); }
    .chat { display: grid; gap: 6px; max-height: 300px; overflow: auto; margin-bottom: 8px; }
    .msg { padding: 7px 10px; border-radius: 10px; font-size: .9rem; max-width: 90%; }
    .msg.user { background: var(--bg); justify-self: start; } .msg.assistant { background: var(--honey-soft); justify-self: end; } .msg.human { background: var(--olive-soft); }
  `],
})
export class DealDetailComponent {
  private api = inject(ApiService);
  id = input.required<string>();
  x = signal<DealDetail | null>(null);
  settings = signal<BusinessSettings | null>(null);
  error = signal('');
  copied = signal(false);
  askLost = signal(false);
  stages = STAGES; meal = MEAL; kashrut = KASHRUT; eventType = EVENT_TYPE; source = SOURCE; actor = ACTOR;
  temp = TEMP; qStatus = QUOTE_STATUS;
  note = ''; noteKind = 'note'; task = ''; invoiceNumber = ''; lostReason = '';
  quote = computed(() => { const q = this.x()?.quotes ?? []; return q[q.length - 1] ?? null; });

  constructor() {
    effect(() => this.load(this.id()), { allowSignalWrites: true });
    this.api.settings().subscribe((s) => this.settings.set(s));
  }
  load(id = this.id()) {
    this.api.deal(id).subscribe({ next: (x) => this.x.set(x), error: () => this.error.set('האירוע לא נמצא או שהשרת לא זמין') });
  }
  customerLink(token: string) { return `${this.settings()?.public_base_url ?? location.origin}/q/${token}`; }
  async copyLink(token: string) {
    try { await navigator.clipboard.writeText(this.customerLink(token)); this.copied.set(true); setTimeout(() => this.copied.set(false), 2000); } catch { /* blocked */ }
  }
  diets(d: string[]) { return d.map(dietLabel).join(', '); }
  move(stage: DealStage) {
    if (stage === 'lost') { this.askLost.set(true); return; }
    this.api.setStage(this.id(), stage).subscribe(() => this.load());
  }
  confirmLost() { this.api.setStage(this.id(), 'lost', this.lostReason).subscribe(() => { this.askLost.set(false); this.load(); }); }
  invoice() {
    this.api.invoice(this.id(), this.invoiceNumber || undefined).subscribe({
      next: () => { this.invoiceNumber = ''; this.load(); },
      error: (e) => this.error.set(e.error?.detail ?? 'הפקת החשבונית נכשלה'),
    });
  }
  addNote() { this.api.addNote(this.id(), this.note, this.noteKind).subscribe(() => { this.note = ''; this.load(); }); }
  addTask() { this.api.addTask({ title: this.task, deal_id: this.id() }).subscribe(() => { this.task = ''; this.load(); }); }
  done(id: string) { this.api.doneTask(id).subscribe(() => this.load()); }
}

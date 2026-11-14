import { Component, effect, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { ApiService } from '../core/api.service';
import { HeDatePipe, IlsPipe, RelativePipe } from '../core/format';
import { ACTOR, EVENT_TYPE, KASHRUT, MEAL, SOURCE, STAGES, STAGE_LABEL, dietLabel } from '../core/labels';
import { DealDetail, DealStage } from '../core/models';

@Component({
  selector: 'app-deal-detail',
  standalone: true,
  imports: [RouterLink, FormsModule, IlsPipe, HeDatePipe, RelativePipe],
  template: `
    <a routerLink="/pipeline" class="back">→ חזרה ל-Pipeline</a>
    @if (error()) { <div class="err">{{ error() }}</div> }
    @if (x(); as x) {
      <div class="page-head">
        <div>
          <h1>{{ x.deal.title }}</h1>
          <p>
            @if (x.deal.source === 'web_chat') { <span class="pill ai">הגיע מסוכן AI</span> } @else { <span class="pill">{{ source[x.deal.source] }}</span> }
            נפתח {{ x.deal.created_at | rel }}
          </p>
        </div>
        <div class="stages" role="group" aria-label="שלב העסקה">
          @for (s of stages; track s.key) {
            <button class="st stage-{{ s.key }}" [class.on]="x.deal.stage === s.key" (click)="move(s.key)">{{ s.label }}</button>
          }
        </div>
      </div>

      <div class="layout">
        <div class="grid">
          <section class="card facts">
            <div><span>ערך</span><b class="num">{{ x.deal.value | ils }}</b></div>
            <div><span>תאריך</span><b>{{ x.deal.event_date | heDate }}</b><small class="muted">{{ x.deal.event_date | rel }}</small></div>
            <div><span>אורחים</span><b class="num">{{ x.deal.guest_count ?? '—' }}</b></div>
            <div><span>ארוחה</span><b>{{ meal[x.deal.meal_type ?? ''] || '—' }} · {{ kashrut[x.deal.kashrut ?? ''] || '—' }}</b></div>
            <div><span>סוג</span><b>{{ eventType[x.deal.event_type ?? ''] || '—' }}</b></div>
            <div><span>מיקום</span><b>{{ x.deal.location ?? '—' }}</b></div>
            @if (x.deal.budget) { <div><span>תקציב</span><b class="num">{{ x.deal.budget | ils }} {{ x.deal.budget_scope === 'per_guest' ? 'לאורח' : '' }}</b></div> }
            @if (x.deal.dietary.length) { <div><span>תזונה</span><b>{{ diets(x.deal.dietary) }}</b></div> }
          </section>

          <section class="card">
            <h2>הצעות מחיר</h2>
            @for (q of x.quotes; track q.id) {
              <div class="quote">
                <div class="qh"><b>{{ q.number }}</b><span class="pill">{{ q.status }}</span><span class="muted">{{ q.created_at | heDate }}</span></div>
                <div class="tiers">
                  @for (t of q.tiers; track t.key) {
                    <div class="tier" [class.sel]="t.key === q.selected_tier">
                      <span>{{ t.name }}</span><b class="num">{{ t.total | ils }}</b>
                      <small class="muted num">{{ t.per_guest | ils }} לאורח</small>
                      @if (q.status !== 'approved') {
                        <button class="btn ghost sm" (click)="approve(q.id, t.key)">הלקוח אישר</button>
                      }
                    </div>
                  }
                </div>
              </div>
            } @empty { <p class="muted">עוד אין הצעת מחיר. הסוכן יוצר הצעה כשיש תאריך, אורחים, סוג ארוחה ופרטי קשר.</p> }
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
                <li class="k-{{ a.kind }}">
                  <span class="who">{{ actor[a.actor] }}</span>
                  <p>{{ a.text }}</p>
                  <time class="muted">{{ a.at | heDate: true }}</time>
                </li>
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
            <h2>ציון ליד <span class="score" [class.hot]="x.deal.lead_score >= 70" [class.warm]="x.deal.lead_score >= 40 && x.deal.lead_score < 70">{{ x.deal.lead_score }}</span></h2>
            <ul class="reasons">@for (r of x.deal.score_reasons; track r) { <li>{{ r }}</li> }</ul>
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
          @if (x.conversation; as conv) {
            <section class="card">
              <h2>שיחה עם הסוכן</h2>
              <div class="chat">
                @for (m of conv.messages; track $index) {
                  <div class="msg {{ m.role }}" [class.human]="m.by === 'human'">{{ m.text }}</div>
                }
              </div>
              <a [routerLink]="['/conversations']" [queryParams]="{ id: conv.id }">לפתוח בתיבת השיחות</a>
            </section>
          }
        </aside>
      </div>
    }
  `,
  styles: [`
    .back { display: inline-block; margin-bottom: 10px; text-decoration: none; }
    .page-head p { display: flex; gap: 8px; align-items: center; }
    .stages { display: flex; flex-wrap: wrap; gap: 4px; }
    .st { border: 1px solid var(--line); background: var(--surface); border-radius: 999px; padding: 4px 11px; font-size: .85rem; color: var(--ink); }
    .st.on { background: var(--st); border-color: var(--st); color: #fff; font-weight: 700; }
    .layout { display: grid; grid-template-columns: 1fr 320px; gap: 14px; align-items: start; }
    @media (max-width: 1000px) { .layout { grid-template-columns: 1fr; } }
    h2 { margin-bottom: 10px; display: flex; align-items: center; gap: 8px; }
    .facts { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 12px; }
    .facts div { display: grid; }
    .facts span { font-size: .78rem; color: var(--muted); }
    .quote { border-top: 1px solid var(--line); padding-top: 10px; margin-top: 10px; }
    .qh { display: flex; gap: 8px; align-items: center; margin-bottom: 8px; }
    .tiers { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
    .tier { border: 1px solid var(--line); border-radius: 8px; padding: 10px; display: grid; gap: 2px; }
    .tier.sel { border: 2px solid var(--olive); background: var(--olive-soft); }
    .tier b { font-family: var(--display); font-size: 1.2rem; color: var(--olive); }
    .sm { padding: 4px 8px; font-size: .8rem; margin-top: 4px; }
    .note { display: flex; gap: 6px; margin-bottom: 10px; }
    .note input { flex: 1; min-width: 0; }
    .timeline { list-style: none; margin: 0; padding: 0; display: grid; gap: 2px; }
    .timeline li { display: grid; grid-template-columns: 70px 1fr auto; gap: 8px; padding: 8px 6px; border-inline-start: 3px solid var(--line); }
    .timeline li p { margin: 0; }
    .timeline .who { font-size: .78rem; font-weight: 700; color: var(--muted); }
    .timeline time { font-size: .78rem; white-space: nowrap; }
    .k-stage { border-color: var(--olive) !important; } .k-quote { border-color: var(--honey) !important; }
    .k-handoff { border-color: var(--bad) !important; } .k-chat { border-color: #4f7cac !important; }
    .cname { font-weight: 700; font-size: 1.1rem; margin: 0 0 4px; }
    aside p { margin: 2px 0; }
    .reasons { margin: 0; padding-inline-start: 18px; font-size: .88rem; color: var(--muted); }
    .tasks { list-style: none; margin: 0 0 10px; padding: 0; display: grid; gap: 6px; }
    .tasks li { display: flex; gap: 8px; align-items: start; }
    .tasks li span { display: grid; }
    .tasks li.high span { font-weight: 700; }
    .tasks li.done span { text-decoration: line-through; color: var(--muted); }
    .chat { display: grid; gap: 6px; max-height: 320px; overflow: auto; margin-bottom: 8px; }
    .msg { padding: 7px 10px; border-radius: 10px; font-size: .9rem; max-width: 90%; }
    .msg.user { background: var(--bg); justify-self: start; }
    .msg.assistant { background: var(--honey-soft); justify-self: end; }
    .msg.human { background: var(--olive-soft); }
  `],
})
export class DealDetailComponent {
  private api = inject(ApiService);
  id = input.required<string>();
  x = signal<DealDetail | null>(null);
  error = signal('');
  stages = STAGES; stageLabel = STAGE_LABEL; meal = MEAL; kashrut = KASHRUT; eventType = EVENT_TYPE;
  source = SOURCE; actor = ACTOR;
  note = ''; noteKind = 'note'; task = '';

  constructor() { effect(() => this.load(this.id()), { allowSignalWrites: true }); }

  load(id = this.id()) {
    this.api.deal(id).subscribe({ next: (x) => this.x.set(x), error: () => this.error.set('העסקה לא נמצאה או שהשרת לא זמין') });
  }
  diets(d: string[]) { return d.map(dietLabel).join(', '); }
  move(stage: DealStage) {
    const reason = stage === 'lost' ? prompt('סיבת אובדן?') : undefined;
    if (stage === 'lost' && !reason) return;
    this.api.setStage(this.id(), stage, reason ?? undefined).subscribe(() => this.load());
  }
  approve(quoteId: string, tier: string) {
    this.api.setQuoteStatus(quoteId, 'approved', tier).subscribe({ next: () => this.load(), error: () => this.load() });
  }
  addNote() { this.api.addNote(this.id(), this.note, this.noteKind).subscribe(() => { this.note = ''; this.load(); }); }
  addTask() { this.api.addTask({ title: this.task, deal_id: this.id() }).subscribe(() => { this.task = ''; this.load(); }); }
  done(id: string) { this.api.doneTask(id).subscribe(() => this.load()); }
}

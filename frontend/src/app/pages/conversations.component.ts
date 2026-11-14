import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { ApiService } from '../core/api.service';
import { HeDatePipe, RelativePipe } from '../core/format';
import { Conversation } from '../core/models';

@Component({
  selector: 'app-conversations',
  standalone: true,
  imports: [FormsModule, RouterLink, HeDatePipe, RelativePipe],
  template: `
    <div class="page-head">
      <div><h1>שיחות סוכן AI</h1><p>כל השיחות מהצ'אט באתר. שיחות שהועברו לנציג מחכות לתשובה שלכם.</p></div>
      <div class="filters" role="group" aria-label="סינון">
        @for (f of filters; track f.key) {
          <button class="btn" [class.ghost]="filter() !== f.key" (click)="setFilter(f.key)">{{ f.label }}</button>
        }
      </div>
    </div>
    <div class="inbox">
      <ul class="list card">
        @for (c of list(); track c.id) {
          <li [class.on]="sel()?.id === c.id" (click)="open(c.id)">
            <div class="row">
              <b>{{ preview(c) }}</b>
              @if (c.escalated && c.status !== 'closed') { <span class="pill hot">🔥 דחוף</span> }
              @else if (c.status === 'handed_off') { <span class="pill warn">ממתין לנציג</span> }
              @else if (c.status === 'human') { <span class="pill">נציג בשיחה</span> }
            </div>
            <div class="row muted"><span>{{ c.messages.length }} הודעות · {{ c.updated_at | rel }}</span>
              @if (c.lead_score) { <span class="score" [class.hot]="c.lead_score >= 70">{{ c.lead_score }}</span> }</div>
          </li>
        } @empty { <li class="empty">אין שיחות</li> }
      </ul>
      <section class="card thread">
        @if (sel(); as c) {
          <header>
            <span>
              @if (c.deal_id) { <a [routerLink]="['/deals', c.deal_id]">לעסקה ב-CRM ←</a> } @else { <span class="muted">עוד לא נוצר ליד</span> }
            </span>
            @if (c.handoff_reason) { <span class="muted">סיבת העברה: {{ c.handoff_reason }}</span> }
            @if (c.status === 'handed_off' || c.status === 'human') {
              <button class="btn ghost" (click)="resume(c.id)">להחזיר לסוכן AI</button>
            }
          </header>
          <div class="msgs">
            @for (m of c.messages; track $index) {
              <div class="msg {{ m.role }}" [class.human]="m.by === 'human'">
                <div>{{ m.text }}</div>
                <small>{{ m.role === 'user' ? 'לקוח' : m.by === 'human' ? 'נציג' : m.by === 'system' ? 'הודעה אוטומטית' : 'סוכן AI' }} · {{ m.at | heDate: true }}
                  @for (t of m.tools; track $index) { <code [class.err]="t.error">{{ t.tool }}</code> }</small>
              </div>
            }
          </div>
          <form class="reply" (ngSubmit)="reply(c.id)">
            <input name="r" [(ngModel)]="text" placeholder="לענות ללקוח בתור נציג (הסוכן יעצור)" aria-label="תשובה">
            <button class="btn" [disabled]="!text.trim()">שליחה</button>
          </form>
        } @else { <p class="empty">בחרו שיחה</p> }
      </section>
    </div>
  `,
  styles: [`
    .filters { display: flex; gap: 6px; }
    .inbox { display: grid; grid-template-columns: 320px 1fr; gap: 14px; align-items: start; }
    @media (max-width: 900px) { .inbox { grid-template-columns: 1fr; } }
    .list { list-style: none; margin: 0; padding: 6px; max-height: 75vh; overflow: auto; }
    .list li { padding: 10px; border-radius: 8px; cursor: pointer; display: grid; gap: 4px; }
    .list li:hover { background: var(--bg); } .list li.on { background: var(--olive-soft); }
    .row { display: flex; justify-content: space-between; gap: 8px; align-items: center; font-size: .9rem; }
    .row b { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .thread { display: grid; gap: 10px; }
    header { display: flex; justify-content: space-between; align-items: center; }
    .msgs { display: grid; gap: 8px; max-height: 60vh; overflow: auto; padding: 4px; }
    .msg { max-width: 75%; padding: 9px 12px; border-radius: 12px; display: grid; gap: 3px; }
    .msg small { font-size: .72rem; color: var(--muted); display: flex; gap: 4px; flex-wrap: wrap; align-items: center; }
    .msg.user { background: var(--bg); justify-self: start; }
    .msg.assistant { background: var(--honey-soft); justify-self: end; }
    .msg.human { background: var(--olive-soft); }
    code { font-size: .7rem; background: var(--surface); border: 1px solid var(--line); border-radius: 4px; padding: 0 4px; direction: ltr; }
    code.err { color: var(--bad); border-color: var(--bad); }
    .reply { display: flex; gap: 8px; } .reply input { flex: 1; }
  `],
})
export class ConversationsComponent {
  private api = inject(ApiService);
  private route = inject(ActivatedRoute);
  filters = [{ key: 'handed_off', label: 'ממתינות לנציג' }, { key: '', label: 'הכל' }];
  filter = signal('');
  list = signal<Conversation[]>([]);
  sel = signal<Conversation | null>(null);
  text = '';

  constructor() {
    const id = this.route.snapshot.queryParamMap.get('id');
    this.load(id);
  }
  setFilter(f: string) { this.filter.set(f); this.load(); }
  load(openId?: string | null) {
    this.api.conversations(this.filter() || undefined).subscribe((l) => {
      this.list.set(l);
      const id = openId ?? this.sel()?.id ?? l[0]?.id;
      if (id) this.open(id);
    });
  }
  open(id: string) { this.api.conversation(id).subscribe((c) => this.sel.set(c)); }
  preview(c: Conversation) { return c.messages.find((m) => m.role === 'user')?.text ?? 'שיחה ריקה'; }
  reply(id: string) { this.api.humanReply(id, this.text).subscribe((c) => { this.text = ''; this.sel.set(c); this.load(); }); }
  resume(id: string) { this.api.resumeAi(id).subscribe((c) => { this.sel.set(c); this.load(); }); }
}

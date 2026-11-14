import { CdkDrag, CdkDragDrop, CdkDropList, CdkDropListGroup } from '@angular/cdk/drag-drop';
import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { ApiService } from '../core/api.service';
import { HeDatePipe, IlsPipe } from '../core/format';
import { EVENT_TYPE, SOURCE, STAGES, STAGE_LABEL, TEMP } from '../core/labels';
import { Deal, DealStage } from '../core/models';

/** Events = deals. Board of 4 steps a caterer thinks in, or a plain list. */
@Component({
  selector: 'app-events',
  standalone: true,
  imports: [CdkDropListGroup, CdkDropList, CdkDrag, FormsModule, IlsPipe, HeDatePipe],
  template: `
    <div class="page-head">
      <div><h1>אירועים</h1><p>כל פנייה היא אירוע: מהפנייה הראשונה, דרך ההצעה והמקדמה, ועד שהאירוע התקיים</p></div>
      <div class="tools">
        <input type="search" placeholder="חיפוש" [ngModel]="q()" (ngModelChange)="q.set($event)" aria-label="חיפוש אירוע">
        <div class="toggle" role="group" aria-label="תצוגה">
          <button class="btn" [class.ghost]="view() !== 'board'" (click)="view.set('board')">לוח</button>
          <button class="btn" [class.ghost]="view() !== 'list'" (click)="view.set('list')">רשימה</button>
        </div>
        <button class="btn" (click)="showNew.set(!showNew())">+ אירוע ידני</button>
      </div>
    </div>
    @if (showNew()) {
      <form class="card newdeal" (ngSubmit)="create()">
        <input name="n" placeholder="שם הלקוח" [(ngModel)]="nd.name" required aria-label="שם">
        <input name="p" placeholder="טלפון" [(ngModel)]="nd.phone" aria-label="טלפון">
        <select name="t" [(ngModel)]="nd.event_type" aria-label="סוג אירוע">
          @for (e of eventTypes; track e[0]) { <option [value]="e[0]">{{ e[1] }}</option> }
        </select>
        <input name="d" type="date" [(ngModel)]="nd.event_date" aria-label="תאריך">
        <input name="g" type="number" min="1" placeholder="אורחים" [(ngModel)]="nd.guest_count" aria-label="אורחים">
        <button class="btn" [disabled]="!nd.name">שמירה</button>
      </form>
    }
    @if (error()) { <div class="err">{{ error() }}</div> }

    @if (view() === 'board') {
      <div class="board" cdkDropListGroup>
        @for (s of boardStages; track s.key) {
          <section class="col stage-{{ s.key }}">
            <header><b>{{ s.label }}</b><span class="num muted">{{ byStage()[s.key].length }} · {{ total(s.key) | ils }}</span></header>
            <div class="list" cdkDropList [cdkDropListData]="s.key" (cdkDropListDropped)="drop($event)">
              @for (d of byStage()[s.key]; track d.id) {
                <article class="deal" cdkDrag [cdkDragData]="d" (click)="open(d)">
                  <div class="top"><b>{{ d.title }}</b>
                    @if (s.key === 'new' || s.key === 'quoted') { <span class="temp temp-{{ d.temperature }}" [title]="d.score_reasons.join('\\n')">{{ temp[d.temperature] }}</span> }
                  </div>
                  <div class="meta"><span class="num">{{ d.value | ils }}</span><span class="muted">{{ d.event_date | heDate }}</span></div>
                  <div class="tags">
                    @if (d.source === 'web_chat') { <span class="pill ai">AI</span> } @else { <span class="pill">{{ source[d.source] }}</span> }
                    @if (d.ready_to_book) { <span class="pill hot">רוצה לסגור</span> }
                    @if (d.deposit_paid) { <span class="pill ok">מקדמה ✓</span> }
                    @if (s.key === 'completed' && !d.invoice) { <span class="pill warn">חסרה חשבונית</span> }
                  </div>
                </article>
              } @empty { <p class="drop-hint">גררו לכאן</p> }
            </div>
          </section>
        }
      </div>
      <button class="link" (click)="showLost.set(!showLost())">{{ showLost() ? 'הסתר' : 'הצג' }} אירועים שאבדו ({{ byStage().lost.length }})</button>
      @if (showLost()) {
        <div class="lost">@for (d of byStage().lost; track d.id) { <button class="chip" (click)="open(d)">{{ d.title }} · {{ d.lost_reason }}</button> }</div>
      }
    } @else {
      <div class="card">
        <table>
          <thead><tr><th>אירוע</th><th>תאריך</th><th>שלב</th><th>חום</th><th class="end">ערך</th><th class="end">מקדמה</th></tr></thead>
          <tbody>
            @for (d of filtered(); track d.id) {
              <tr class="link" (click)="open(d)">
                <td><b>{{ d.title }}</b></td><td class="num">{{ d.event_date | heDate }}</td>
                <td><span class="pill">{{ stageLabel[d.stage] }}</span></td>
                <td><span class="temp temp-{{ d.temperature }}">{{ temp[d.temperature] }}</span></td>
                <td class="num end">{{ d.value | ils }}</td><td class="num end">{{ d.deposit_paid | ils }}</td>
              </tr>
            }
          </tbody>
        </table>
      </div>
    }
  `,
  styles: [`
    .tools { display: flex; gap: 8px; flex-wrap: wrap; }
    .toggle { display: flex; gap: 4px; }
    .newdeal { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 14px; }
    .board { display: grid; grid-template-columns: repeat(4, minmax(220px, 1fr)); gap: 10px; overflow-x: auto; padding-bottom: 8px; }
    .col { background: color-mix(in srgb, var(--st) 7%, var(--bg)); border-radius: var(--r); border-top: 3px solid var(--st); min-height: 320px; display: flex; flex-direction: column; }
    header { display: flex; justify-content: space-between; align-items: baseline; padding: 10px 10px 6px; gap: 6px; }
    header span { font-size: .8rem; }
    .list { flex: 1; padding: 4px 8px 10px; display: grid; gap: 8px; align-content: start; min-height: 80px; }
    .deal { background: var(--surface); border: 1px solid var(--line); border-radius: 8px; padding: 10px; display: grid; gap: 6px; cursor: grab; }
    .deal:hover { border-color: var(--st); }
    .top { display: flex; justify-content: space-between; gap: 6px; align-items: start; }
    .top b { font-size: .92rem; line-height: 1.3; }
    .meta { display: flex; justify-content: space-between; font-size: .85rem; }
    .tags { display: flex; gap: 4px; flex-wrap: wrap; }
    .drop-hint { color: var(--muted); font-size: .85rem; text-align: center; margin: 12px 0; }
    .cdk-drag-preview { box-shadow: 0 8px 24px rgba(0,0,0,.18); border-radius: 8px; }
    .cdk-drag-placeholder { opacity: .35; }
    .link { background: none; border: 0; color: var(--olive); text-decoration: underline; margin-top: 10px; }
    .lost { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
    .chip { border: 1px solid var(--line); background: var(--surface); border-radius: 99px; padding: 3px 10px; font-size: .85rem; }
    .end { text-align: end; }
  `],
})
export class EventsComponent {
  private api = inject(ApiService);
  private router = inject(Router);
  boardStages = STAGES.filter((s) => s.key !== 'lost');
  stageLabel = STAGE_LABEL; temp = TEMP; source = SOURCE;
  eventTypes = Object.entries(EVENT_TYPE);
  deals = signal<Deal[]>([]);
  error = signal('');
  q = signal('');
  view = signal<'board' | 'list'>('board');
  showNew = signal(false);
  showLost = signal(false);
  nd = { name: '', phone: '', event_type: 'wedding', event_date: '', guest_count: null as number | null };
  private dragging = false;
  private rank = { hot: 0, warm: 1, cold: 2 };

  filtered = computed(() => {
    const q = this.q().trim();
    return this.deals().filter((d) => !q || d.title.includes(q));
  });
  byStage = computed(() => {
    const g = Object.fromEntries(STAGES.map((s) => [s.key, [] as Deal[]])) as Record<DealStage, Deal[]>;
    for (const d of this.filtered()) g[d.stage]?.push(d);
    g.new.sort((a, b) => this.rank[a.temperature] - this.rank[b.temperature]);
    g.quoted.sort((a, b) => this.rank[a.temperature] - this.rank[b.temperature]);
    g.won.sort((a, b) => (a.event_date ?? '').localeCompare(b.event_date ?? ''));
    g.completed.sort((a, b) => (b.event_date ?? '').localeCompare(a.event_date ?? ''));
    return g;
  });

  constructor() { this.load(); }
  load() { this.api.deals().subscribe({ next: (d) => this.deals.set(d), error: () => this.error.set('השרת לא זמין') }); }
  total(stage: DealStage) { return this.byStage()[stage].reduce((s, d) => s + (d.value ?? 0), 0); }

  drop(ev: CdkDragDrop<DealStage>) {
    this.dragging = true;
    setTimeout(() => (this.dragging = false), 50);
    const deal: Deal = ev.item.data;
    const to = ev.container.data;
    if (deal.stage === to) return;
    this.deals.update((ds) => ds.map((d) => (d.id === deal.id ? { ...d, stage: to } : d)));
    this.api.setStage(deal.id, to).subscribe({ next: () => this.load(), error: () => this.load() });
  }
  open(d: Deal) { if (!this.dragging) this.router.navigate(['/deals', d.id]); }
  create() {
    const { name, phone, event_type, event_date, guest_count } = this.nd;
    this.api.createDeal({ customer: { name, phone: phone || null }, event_type, event_date: event_date || null, guest_count })
      .subscribe((d) => { this.showNew.set(false); this.router.navigate(['/deals', d.id]); });
  }
}

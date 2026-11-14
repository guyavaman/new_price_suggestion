import { CdkDrag, CdkDragDrop, CdkDropList, CdkDropListGroup } from '@angular/cdk/drag-drop';
import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { ApiService } from '../core/api.service';
import { HeDatePipe, IlsPipe } from '../core/format';
import { EVENT_TYPE, SOURCE, STAGES } from '../core/labels';
import { Deal, DealStage } from '../core/models';

@Component({
  selector: 'app-pipeline',
  standalone: true,
  imports: [CdkDropListGroup, CdkDropList, CdkDrag, RouterLink, FormsModule, IlsPipe, HeDatePipe],
  template: `
    <div class="page-head">
      <div><h1>Pipeline</h1><p>גררו כרטיס כדי להעביר שלב. כרטיסים עם תג "AI" הגיעו מהסוכן.</p></div>
      <div class="tools">
        <input type="search" placeholder="חיפוש עסקה" [ngModel]="q()" (ngModelChange)="q.set($event)" aria-label="חיפוש עסקה">
        <button class="btn" (click)="showNew.set(!showNew())">+ עסקה חדשה</button>
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
    <div class="board" cdkDropListGroup>
      @for (s of stages; track s.key) {
        <section class="col stage-{{ s.key }}">
          <header><b>{{ s.label }}</b><span class="num muted">{{ byStage()[s.key].length }} · {{ total(s.key) | ils }}</span></header>
          <div class="list" cdkDropList [cdkDropListData]="s.key" (cdkDropListDropped)="drop($event)">
            @for (d of byStage()[s.key]; track d.id) {
              <article class="deal" cdkDrag [cdkDragData]="d" (click)="open(d)">
                <div class="top">
                  <b>{{ d.title }}</b>
                  <span class="score" [class.hot]="d.lead_score >= 70" [class.warm]="d.lead_score >= 40 && d.lead_score < 70" [title]="d.score_reasons.join('\\n')">{{ d.lead_score }}</span>
                </div>
                <div class="meta">
                  <span class="num">{{ d.value | ils }}</span>
                  <span class="muted">{{ d.event_date | heDate }}</span>
                </div>
                <div class="tags">
                  @if (d.source === 'web_chat') { <span class="pill ai">AI</span> } @else { <span class="pill">{{ source[d.source] }}</span> }
                  @if (d.quote_ids.length) { <span class="pill">{{ d.quote_ids.length }} הצעות</span> }
                </div>
              </article>
            } @empty { <p class="drop-hint">גררו לכאן</p> }
          </div>
        </section>
      }
    </div>
    @if (askLost(); as d) {
      <div class="modal" role="dialog" aria-label="סיבת אובדן">
        <form class="card" (ngSubmit)="confirmLost()">
          <h2>למה העסקה אבודה?</h2>
          <input name="r" [(ngModel)]="lostReason" placeholder="למשל: מחיר, תאריך, בחרו ספק אחר" required aria-label="סיבה">
          <div class="row"><button class="btn" [disabled]="!lostReason">שמירה</button>
            <button type="button" class="btn ghost" (click)="askLost.set(null); load()">ביטול</button></div>
        </form>
      </div>
    }
  `,
  styles: [`
    .tools { display: flex; gap: 8px; }
    .newdeal { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 14px; }
    .board { display: grid; grid-template-columns: repeat(6, minmax(190px, 1fr)); gap: 10px; overflow-x: auto; padding-bottom: 8px; }
    .col { background: color-mix(in srgb, var(--st) 7%, var(--bg)); border-radius: var(--r); border-top: 3px solid var(--st); min-height: 300px; display: flex; flex-direction: column; }
    header { display: flex; justify-content: space-between; align-items: baseline; padding: 10px 10px 6px; gap: 6px; }
    header span { font-size: .78rem; }
    .list { flex: 1; padding: 4px 8px 10px; display: grid; gap: 8px; align-content: start; min-height: 80px; }
    .deal { background: var(--surface); border: 1px solid var(--line); border-radius: 8px; padding: 10px; display: grid; gap: 6px; cursor: grab; }
    .deal:hover { border-color: var(--st); }
    .top { display: flex; justify-content: space-between; gap: 6px; align-items: start; }
    .top b { font-size: .9rem; line-height: 1.3; }
    .meta { display: flex; justify-content: space-between; font-size: .85rem; }
    .tags { display: flex; gap: 4px; flex-wrap: wrap; }
    .drop-hint { color: var(--muted); font-size: .85rem; text-align: center; margin: 12px 0; }
    .cdk-drag-preview { box-shadow: 0 8px 24px rgba(0,0,0,.18); border-radius: 8px; }
    .cdk-drag-placeholder { opacity: .35; }
    .modal { position: fixed; inset: 0; background: rgba(0,0,0,.35); display: grid; place-items: center; z-index: 10; }
    .modal form { display: grid; gap: 10px; width: min(420px, 92vw); }
    .row { display: flex; gap: 8px; }
  `],
})
export class PipelineComponent {
  private api = inject(ApiService);
  private router = inject(Router);
  stages = STAGES;
  source = SOURCE;
  eventTypes = Object.entries(EVENT_TYPE);
  deals = signal<Deal[]>([]);
  error = signal('');
  q = signal('');
  showNew = signal(false);
  nd = { name: '', phone: '', event_type: 'wedding', event_date: '', guest_count: null as number | null };
  askLost = signal<Deal | null>(null);
  lostReason = '';
  private dragging = false;

  byStage = computed(() => {
    const groups = Object.fromEntries(STAGES.map((s) => [s.key, [] as Deal[]])) as Record<DealStage, Deal[]>;
    const q = this.q().trim();
    for (const d of this.deals()) if (!q || d.title.includes(q)) groups[d.stage].push(d);
    for (const k of Object.keys(groups) as DealStage[]) groups[k].sort((a, b) => b.lead_score - a.lead_score);
    return groups;
  });

  constructor() { this.load(); }

  load() {
    this.api.deals().subscribe({ next: (d) => this.deals.set(d), error: () => this.error.set('השרת לא זמין') });
  }
  total(stage: DealStage) { return this.byStage()[stage].reduce((s, d) => s + (d.value ?? 0), 0); }

  drop(ev: CdkDragDrop<DealStage>) {
    this.dragging = true;
    setTimeout(() => (this.dragging = false), 50);
    const deal: Deal = ev.item.data;
    const to = ev.container.data;
    if (deal.stage === to) return;
    if (to === 'lost') { this.lostReason = ''; this.askLost.set(deal); return; }
    this.deals.update((ds) => ds.map((d) => (d.id === deal.id ? { ...d, stage: to } : d))); // optimistic
    this.api.setStage(deal.id, to).subscribe({ next: () => this.load(), error: () => this.load() });
  }
  confirmLost() {
    const d = this.askLost();
    if (!d) return;
    this.api.setStage(d.id, 'lost', this.lostReason).subscribe(() => { this.askLost.set(null); this.load(); });
  }
  open(d: Deal) { if (!this.dragging) this.router.navigate(['/deals', d.id]); }

  create() {
    const { name, phone, event_type, event_date, guest_count } = this.nd;
    this.api.createDeal({ customer: { name, phone: phone || null }, event_type, event_date: event_date || null, guest_count })
      .subscribe((d) => { this.showNew.set(false); this.router.navigate(['/deals', d.id]); });
  }
}

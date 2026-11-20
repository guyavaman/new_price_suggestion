import { Component, effect, inject, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ApiService } from './api.service';
import { DealStaff, StaffAssignment } from './models';

const ROLE_HE: Record<string, string> = { waiter: 'מלצר', head_waiter: 'מנהל אירוע', bartender: 'ברמן', chef: 'שף' };
const STATUS_HE: Record<string, string> = { invited: 'ממתין לאישור', confirmed: 'אישר/ה', declined: 'ביטל/ה' };

/** Who works this event: what the quote needs, who's assigned, WhatsApp invites, hours. */
@Component({
  selector: 'app-event-staff',
  standalone: true,
  imports: [FormsModule],
  template: `
    @if (p(); as p) {
      <div class="needs">
        @for (n of p.needs; track n.role) {
          <span class="need" [class.full]="n.confirmed >= n.needed">{{ n.label }}: <b class="num">{{ n.confirmed }}/{{ n.needed }}</b> אישרו
            @if (n.assigned > n.confirmed) { <small>· {{ n.assigned - n.confirmed }} ממתינים</small> }</span>
        } @empty { <span class="muted">אין צוות בהצעה של האירוע</span> }
      </div>
      <p class="sum" [class.ok]="p.ok">{{ p.summary }}</p>
      @if (gaps(p)) { <button class="btn sm" type="button" [disabled]="busy()" (click)="auto()">שיבוץ אוטומטי ({{ gaps(p) }} מקומות)</button> }

      <ul class="list">
        @for (a of p.assignments; track a.id) {
          <li [class.declined]="a.status === 'declined'">
            <span class="who"><b>{{ a.name }}</b> <small class="muted">{{ role(a.role) }}</small></span>
            <span class="st st-{{ a.status }}">{{ status(a.status) }}</span>
            <span class="acts">
              @if (a.status === 'invited' && a.invite_url) { <a class="btn sm" [href]="a.invite_url" target="_blank" rel="noopener">הזמנה בוואטסאפ</a> }
              @if (a.status !== 'confirmed') { <button class="btn ghost sm" type="button" (click)="set(a, 'confirmed')">אישר/ה בטלפון</button> }
              @if (past()) {
                <label class="hrs">שעות בפועל<input type="number" min="0" max="24" step="0.25" [ngModel]="a.actual_hours" (change)="hours(a, $any($event.target).value)" [attr.aria-label]="'שעות בפועל ' + a.name"></label>
              }
              <button class="linkish" type="button" (click)="remove(a)" [attr.aria-label]="'הסרת ' + a.name">הסרה</button>
            </span>
          </li>
        }
      </ul>

      <div class="add">
        <select [(ngModel)]="addRole" name="ar" aria-label="תפקיד">@for (r of roles(p); track r) { <option [value]="r">{{ role(r) }}</option> }</select>
        <select [(ngModel)]="addWho" name="aw" aria-label="מי">
          <option value="">+ שיבוץ ידני: מי פנוי/ה באותו יום</option>
          @for (c of p.candidates[addRole] || []; track c.id) { <option [value]="c.id">{{ c.name }}</option> }
        </select>
        <button class="btn ghost sm" type="button" [disabled]="!addWho || busy()" (click)="add()">שיבוץ</button>
      </div>
      @if (err()) { <p class="err" role="alert">{{ err() }}</p> }
    }
  `,
  styles: [`
    :host { display: grid; gap: 10px; }
    .needs { display: flex; gap: 8px; flex-wrap: wrap; }
    .need { background: var(--bad-soft); color: var(--bad); border-radius: 8px; padding: 4px 10px; font-size: .9rem; }
    .need.full { background: var(--ok-soft); color: var(--ok); }
    .sum { margin: 0; color: var(--bad); font-weight: 600; } .sum.ok { color: var(--ok); }
    .list { list-style: none; margin: 0; padding: 0; display: grid; gap: 6px; }
    .list li { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; padding: 6px 8px; border: 1px solid var(--line); border-radius: 8px; }
    .list li.declined { opacity: .6; } .list li.declined .who b { text-decoration: line-through; }
    .who { flex: 1 1 160px; } .who small { margin-inline-start: 6px; }
    .st { font-size: .78rem; border-radius: 99px; padding: 1px 9px; font-weight: 700; }
    .st-invited { background: var(--warn-soft); color: var(--warn); } .st-confirmed { background: var(--ok-soft); color: var(--ok); } .st-declined { background: var(--paper); color: var(--muted); }
    .acts { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
    .btn.sm { padding: 4px 10px; font-size: .84rem; text-decoration: none; justify-self: start; }
    .hrs { display: inline-flex; gap: 4px; align-items: center; font-size: .8rem; color: var(--muted); } .hrs input { width: 70px; }
    .linkish { background: none; border: 0; padding: 0; color: var(--bad); text-decoration: underline; font: inherit; font-size: .84rem; cursor: pointer; }
    .add { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
  `],
})
export class EventStaffComponent {
  private api = inject(ApiService);
  dealId = input.required<string>();
  past = input(false);
  changed = output<void>();
  p = signal<DealStaff | null>(null);
  busy = signal(false); err = signal('');
  addRole = 'waiter'; addWho = '';
  constructor() { effect(() => this.load(this.dealId())); }
  load(id = this.dealId()) { this.api.dealStaff(id).subscribe((p) => this.p.set(p)); }
  role(r: string) { return ROLE_HE[r] ?? r; }
  status(s: string) { return STATUS_HE[s] ?? s; }
  roles(p: DealStaff) { return [...new Set([...p.needs.map((n) => n.role), 'waiter', 'head_waiter', 'bartender', 'chef'])]; }
  gaps(p: DealStaff) { return p.needs.reduce((s, n) => s + Math.max(0, n.needed - n.assigned), 0); }
  private done(p: DealStaff) { this.busy.set(false); this.p.set(p); this.changed.emit(); }
  private fail(e: { error?: { detail?: string } }) { this.busy.set(false); this.err.set(e.error?.detail ?? 'הפעולה נכשלה'); }
  auto() { this.busy.set(true); this.err.set(''); this.api.autoStaff(this.dealId()).subscribe({ next: (p) => this.done(p), error: (e) => this.fail(e) }); }
  add() {
    this.busy.set(true); this.err.set('');
    this.api.assignStaff(this.dealId(), this.addWho, this.addRole).subscribe({ next: (p) => { this.addWho = ''; this.done(p); }, error: (e) => this.fail(e) });
  }
  set(a: StaffAssignment, status: string) { this.api.patchAssignment(this.dealId(), a.id, { status }).subscribe({ next: (p) => this.done(p), error: (e) => this.fail(e) }); }
  hours(a: StaffAssignment, v: string) {
    this.api.patchAssignment(this.dealId(), a.id, { actual_hours: v === '' ? null : +v }).subscribe({ next: (p) => this.done(p), error: (e) => this.fail(e) });
  }
  remove(a: StaffAssignment) { this.api.removeAssignment(this.dealId(), a.id).subscribe({ next: (p) => this.done(p), error: (e) => this.fail(e) }); }
}

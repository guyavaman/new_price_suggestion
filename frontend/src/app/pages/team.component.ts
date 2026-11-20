import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { ApiService } from '../core/api.service';
import { HeDatePipe, IlsPipe } from '../core/format';
import { EquipmentType, ImportReport, MissingReturn, PayRow, StaffMember, StaffRole } from '../core/models';

const ROLES: { id: StaffRole; he: string }[] = [
  { id: 'waiter', he: 'מלצר' }, { id: 'head_waiter', he: 'מנהל אירוע' }, { id: 'bartender', he: 'ברמן' }, { id: 'chef', he: 'שף' },
];
const DAYS = ['א׳', 'ב׳', 'ג׳', 'ד׳', 'ה׳', 'ו׳', 'ש׳'];
type Tab = 'staff' | 'pay' | 'stock' | 'missing';

/** Staff, monthly pay, equipment stock and what didn't come back. */
@Component({
  selector: 'app-team',
  standalone: true,
  imports: [FormsModule, RouterLink, IlsPipe, HeDatePipe],
  template: `
    <header class="top"><h1>צוות וציוד</h1>
      <button class="btn ghost" type="button" (click)="importing.set(!importing())">ייבוא מאקסל</button></header>
    <nav class="tabs" aria-label="חלקים">
      <button type="button" [class.on]="tab() === 'staff'" (click)="tab.set('staff')">צוות ({{ staff().length }})</button>
      <button type="button" [class.on]="tab() === 'pay'" (click)="tab.set('pay'); loadPay()">תשלום חודשי</button>
      <button type="button" [class.on]="tab() === 'stock'" (click)="tab.set('stock')">מלאי ציוד</button>
      <button type="button" [class.on]="tab() === 'missing'" (click)="tab.set('missing')">לא חזר @if (missing().length) { <b class="badge">{{ missing().length }}</b> }</button>
    </nav>
    @if (msg()) { <p class="flash" [class.bad]="msgBad()" role="status">{{ msg() }}</p> }

    @if (tab() === 'staff') {
      <section class="card">
        <button class="btn" type="button" (click)="newMember()">+ איש צוות</button>
        @if (edit(); as m) {
          <form class="form" (ngSubmit)="saveMember(m)">
            <label>שם<input [(ngModel)]="m.name" name="n" required></label>
            <label>טלפון<input [(ngModel)]="m.phone" name="p" inputmode="tel" dir="ltr"></label>
            <label>תעריף לשעה (₪)<input type="number" min="0" [(ngModel)]="m.hourly_rate" name="r" placeholder="לא הוגדר"></label>
            <fieldset><legend>תפקידים</legend>
              @for (r of roles; track r.id) { <label class="chk"><input type="checkbox" [checked]="m.roles.includes(r.id)" (change)="toggleRole(m, r.id)">{{ r.he }}</label> }</fieldset>
            <fieldset><legend>ימים שבדרך כלל פנוי/ה</legend>
              @for (d of days; track $index) { <label class="chk"><input type="checkbox" [checked]="m.available_days.includes($index)" (change)="toggleDay(m, $index)">{{ d }}</label> }</fieldset>
            <label>הערות<input [(ngModel)]="m.notes" name="no"></label>
            <label class="chk"><input type="checkbox" [(ngModel)]="m.active" name="a">פעיל/ה</label>
            <div class="row"><button class="btn" type="submit" [disabled]="!m.name.trim() || !m.roles.length">שמירה</button>
              <button class="btn ghost" type="button" (click)="edit.set(null)">ביטול</button></div>
          </form>
        }
        <div class="tw"><table>
          <thead><tr><th>שם</th><th>תפקידים</th><th>טלפון</th><th class="end">תעריף</th><th>ימים</th><th></th></tr></thead>
          <tbody>
            @for (m of staff(); track m.id) {
              <tr [class.off]="!m.active">
                <td><b>{{ m.name }}</b>@if (!m.active) { <small class="muted"> (לא פעיל)</small> }</td>
                <td>{{ roleNames(m.roles) }}</td>
                <td dir="ltr" class="ph">{{ m.phone }}</td>
                <td class="end">@if (m.hourly_rate !== null) { {{ m.hourly_rate | ils }} } @else { <span class="warn">חסר</span> }</td>
                <td class="muted">{{ dayNames(m.available_days) }}</td>
                <td class="acts"><button class="linkish" type="button" (click)="editMember(m)">עריכה</button>
                  <button class="linkish bad" type="button" (click)="removeMember(m)">מחיקה</button></td>
              </tr>
            } @empty { <tr><td colspan="6" class="muted">אין עדיין צוות. מוסיפים אחד אחד או מייבאים מאקסל.</td></tr> }
          </tbody>
        </table></div>
      </section>
    }

    @if (tab() === 'pay') {
      <section class="card">
        <div class="row"><label>חודש<input type="month" [(ngModel)]="month" (change)="loadPay()" name="m"></label>
          <button class="btn ghost" type="button" (click)="payXlsx()">ייצוא לאקסל</button></div>
        <p class="muted small">נספרות משמרות שאושרו. כל עוד לא הוזנו שעות בפועל, נספרות השעות המתוכננות.</p>
        <div class="tw"><table>
          <thead><tr><th>שם</th><th class="end">משמרות</th><th class="end">שעות</th><th class="end">תעריף</th><th class="end">לתשלום</th></tr></thead>
          <tbody>
            @for (r of pay(); track r.member_id) {
              <tr>
                <td><b>{{ r.name }}</b>
                  <ul class="shifts">@for (s of r.shifts; track $index) { <li><a [routerLink]="['/deals', s.deal_id]">{{ s.title }}</a> · {{ s.date | heDate }} · {{ s.hours }} ש׳@if (!s.actual) { <small class="muted"> (מתוכנן)</small> }</li> }</ul></td>
                <td class="end num">{{ r.shifts.length }}</td>
                <td class="end num">{{ r.hours }}@if (r.planned_only) { <small class="muted"> ({{ r.planned_only }} מתוכננות)</small> }</td>
                <td class="end">@if (r.rate !== null) { {{ r.rate | ils }} } @else { <span class="warn">חסר</span> }</td>
                <td class="end"><b>@if (r.total !== null) { {{ r.total | ils }} } @else { <span class="warn">חסר תעריף</span> }</b></td>
              </tr>
            } @empty { <tr><td colspan="5" class="muted">אין משמרות מאושרות בחודש הזה</td></tr> }
          </tbody>
          @if (pay().length) { <tfoot><tr><td>סה״כ</td><td></td><td class="end num">{{ payHours() }}</td><td></td><td class="end"><b>{{ payTotal() | ils }}</b></td></tr></tfoot> }
        </table></div>
      </section>
    }

    @if (tab() === 'stock') {
      <section class="card">
        <p class="muted small">כמה יש מכל פריט. הקוד זהה לקוד הפריט בתפריט, וכך ציוד שנמכר בהצעה נכנס אוטומטית לרשימת האירוע.</p>
        <div class="tw"><table>
          <thead><tr><th>קוד</th><th>שם</th><th class="end">כמות בבעלות</th><th>הערות</th><th></th></tr></thead>
          <tbody>
            @for (e of stock(); track e.code) {
              <tr>
                <td dir="ltr" class="muted">{{ e.code }}</td>
                <td><input [(ngModel)]="e.name" [name]="'n' + e.code" (change)="saveStock(e)" [attr.aria-label]="'שם ' + e.code"></td>
                <td class="end"><input type="number" min="0" [(ngModel)]="e.owned" [name]="'o' + e.code" (change)="saveStock(e)" [attr.aria-label]="'כמות ' + e.name"></td>
                <td><input [(ngModel)]="e.notes" [name]="'x' + e.code" (change)="saveStock(e)" [attr.aria-label]="'הערות ' + e.name"></td>
                <td><button class="linkish bad" type="button" (click)="removeStock(e)">מחיקה</button></td>
              </tr>
            }
            <tr class="new">
              <td><input [(ngModel)]="nw.code" name="nc" placeholder="קוד" dir="ltr" aria-label="קוד חדש"></td>
              <td><input [(ngModel)]="nw.name" name="nn" placeholder="שם הפריט" aria-label="שם פריט חדש"></td>
              <td class="end"><input type="number" min="0" [(ngModel)]="nw.owned" name="no" aria-label="כמות פריט חדש"></td>
              <td></td>
              <td><button class="btn sm" type="button" [disabled]="!nw.code.trim() || !nw.name.trim()" (click)="addStock()">הוספה</button></td>
            </tr>
          </tbody>
        </table></div>
      </section>
    }

    @if (tab() === 'missing') {
      <section class="card">
        <p class="muted small">אירועים שעברו וחלק מהציוד לא חזר, או שעוד לא נספר מה חזר.</p>
        @for (m of missing(); track m.deal_id) {
          <article class="miss">
            <h3><a [routerLink]="['/deals', m.deal_id]" fragment="equipment">{{ m.title }}</a> <small class="muted">{{ m.event_date | heDate }}</small></h3>
            @if (!m.counted) { <p class="warn">עוד לא נספר מה חזר</p> }
            <ul>@for (i of m.items; track i.code) { <li>{{ i.name }}: יצאו {{ i.out }}, @if (i.returned !== null) { חזרו {{ i.returned }}, <b class="bad">חסרים {{ i.missing }}</b> } @else { לא נספר }</li> }</ul>
          </article>
        } @empty { <p class="ok">כל הציוד חזר.</p> }
      </section>
    }

    @if (importing()) {
      <section class="card import">
        <h2>ייבוא צוות ומלאי ציוד</h2>
        <ol>
          <li><button class="linkish" type="button" (click)="template()">הורדת קובץ אקסל</button> עם הצוות והמלאי הנוכחיים, למילוי.</li>
          <li>מעלים את הקובץ ורואים מה ישתנה, לפני שמשהו נשמר.</li>
        </ol>
        <input type="file" accept=".xlsx,.csv" (change)="pick($any($event.target).files?.[0])" aria-label="קובץ לייבוא">
        @if (report(); as r) {
          <div class="report">
            <p><b>{{ r.creates.length }} חדשים · {{ r.updates.length }} עדכונים · {{ r.unchanged }} ללא שינוי</b>@if (r.errors.length) { · <span class="bad">{{ r.errors.length }} שורות נדחו</span> }</p>
            @if (r.errors.length) {
              <table class="errs"><thead><tr><th>גיליון</th><th>שורה</th><th>עמודה</th><th>בעיה</th></tr></thead>
                <tbody>@for (e of r.errors; track $index) { <tr><td>{{ e.sheet }}</td><td>{{ e.row }}</td><td>{{ e.column }}</td><td>{{ e.message }}</td></tr> }</tbody></table>
            }
            @if (!r.applied && (r.creates.length || r.updates.length)) {
              <button class="btn" [disabled]="busy()" (click)="applyImport()">שמירת {{ r.creates.length + r.updates.length }} השינויים</button>
            }
            @if (r.applied) { <p class="ok">הייבוא נשמר</p> }
          </div>
        }
      </section>
    }
  `,
  styles: [`
    .top { display: flex; justify-content: space-between; align-items: center; gap: 10px; flex-wrap: wrap; }
    .tabs { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 12px; }
    .tabs button { border: 1px solid var(--line); background: var(--surface); border-radius: 99px; padding: 6px 14px; font: inherit; cursor: pointer; }
    .tabs button.on { background: var(--olive); color: #fff; border-color: var(--olive); }
    .badge { background: var(--bad); color: #fff; border-radius: 99px; padding: 0 7px; font-size: .78rem; margin-inline-start: 4px; }
    .card { display: grid; gap: 12px; min-width: 0; }
    .tw { overflow-x: auto; } table { width: 100%; border-collapse: collapse; }
    th { text-align: start; font-size: .78rem; color: var(--muted); font-weight: 600; padding: 6px; }
    td { padding: 7px 6px; border-top: 1px solid var(--line); vertical-align: top; }
    td input { width: 100%; min-width: 70px; } .end { text-align: end; } tfoot td { font-weight: 700; }
    tr.off { opacity: .55; } .ph { white-space: nowrap; }
    .acts { white-space: nowrap; display: flex; gap: 10px; }
    .form { display: grid; gap: 10px; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); padding: 12px; border: 1px solid var(--line); border-radius: 10px; background: var(--paper); }
    .form label:not(.chk) { display: grid; gap: 4px; font-size: .86rem; }
    fieldset { border: 1px solid var(--line); border-radius: 8px; display: flex; flex-wrap: wrap; gap: 10px; padding: 6px 10px; }
    legend { font-size: .82rem; color: var(--muted); }
    .chk { display: inline-flex; gap: 4px; align-items: center; }
    .row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; } .row label { display: flex; gap: 6px; align-items: center; }
    .small { font-size: .86rem; margin: 0; }
    .shifts { list-style: none; margin: 4px 0 0; padding: 0; font-size: .82rem; color: var(--muted); }
    .warn { color: var(--warn); font-weight: 600; } .bad { color: var(--bad); } .ok { color: var(--ok); font-weight: 600; }
    .linkish { background: none; border: 0; padding: 0; color: var(--olive); text-decoration: underline; font: inherit; cursor: pointer; } .linkish.bad { color: var(--bad); }
    .btn.sm { padding: 4px 10px; font-size: .84rem; }
    .miss { border: 1px solid var(--line); border-radius: 10px; padding: 10px 12px; } .miss h3 { margin: 0 0 4px; font-size: 1rem; } .miss ul { margin: 0; padding-inline-start: 18px; }
    .import { margin-top: 14px; } .import ol { margin: 0; padding-inline-start: 20px; color: var(--muted); }
    .report { border-top: 1px solid var(--line); padding-top: 10px; display: grid; gap: 8px; } .errs td { color: var(--bad); font-size: .88rem; }
    .flash { background: var(--ok-soft); color: var(--ok); padding: 6px 12px; border-radius: 8px; } .flash.bad { background: var(--bad-soft); color: var(--bad); }
  `],
})
export class TeamComponent {
  private api = inject(ApiService);
  roles = ROLES; days = DAYS;
  tab = signal<Tab>('staff');
  staff = signal<StaffMember[]>([]);
  edit = signal<StaffMember | null>(null);
  pay = signal<PayRow[]>([]);
  stock = signal<EquipmentType[]>([]);
  missing = signal<MissingReturn[]>([]);
  importing = signal(false); report = signal<ImportReport | null>(null); busy = signal(false);
  msg = signal(''); msgBad = signal(false);
  month = new Date().toISOString().slice(0, 7);
  nw: EquipmentType = { code: '', name: '', owned: 0, notes: '' };
  private file: File | null = null;

  constructor() {
    if (location.hash === '#missing') this.tab.set('missing');
    this.loadStaff(); this.loadStock(); this.loadMissing();
  }
  private flash(t: string, bad = false) { this.msg.set(t); this.msgBad.set(bad); setTimeout(() => this.msg.set(''), 4000); }
  private err(e: { error?: { detail?: unknown } }) { const d = e.error?.detail; return typeof d === 'string' ? d : 'הפעולה נכשלה'; }
  loadStaff() { this.api.staff().subscribe((s) => this.staff.set(s)); }
  loadStock() { this.api.stock().subscribe((s) => this.stock.set(s)); }
  loadMissing() { this.api.missingEquipment().subscribe((m) => this.missing.set(m)); }
  loadPay() { this.api.payroll(this.month).subscribe((p) => this.pay.set(p)); }
  roleNames(r: StaffRole[]) { return r.map((x) => ROLES.find((y) => y.id === x)?.he ?? x).join(', '); }
  dayNames(d: number[]) { return d.length === 7 ? 'כל השבוע' : d.length ? d.map((i) => DAYS[i]).join(' ') : 'לא צוין'; }
  payHours() { return Math.round(this.pay().reduce((s, r) => s + r.hours, 0) * 100) / 100; }
  payTotal() { return this.pay().reduce((s, r) => s + (r.total ?? 0), 0); }

  newMember() { this.edit.set({ id: '', name: '', phone: '', roles: ['waiter'], hourly_rate: null, available_days: [0, 1, 2, 3, 4, 5, 6], unavailable_dates: [], notes: '', active: true }); }
  editMember(m: StaffMember) { this.edit.set({ ...m, roles: [...m.roles], available_days: [...m.available_days] }); }
  toggleRole(m: StaffMember, r: StaffRole) { m.roles = m.roles.includes(r) ? m.roles.filter((x) => x !== r) : [...m.roles, r]; }
  toggleDay(m: StaffMember, d: number) { m.available_days = m.available_days.includes(d) ? m.available_days.filter((x) => x !== d) : [...m.available_days, d].sort(); }
  saveMember(m: StaffMember) {
    const body = { ...m, hourly_rate: m.hourly_rate === null || (m.hourly_rate as unknown) === '' ? null : +m.hourly_rate };
    (m.id ? this.api.putStaff(body) : this.api.addStaff(body)).subscribe({
      next: () => { this.edit.set(null); this.loadStaff(); this.flash('נשמר'); },
      error: (e) => this.flash(this.err(e), true),
    });
  }
  removeMember(m: StaffMember) {
    if (!confirm(`למחוק את ${m.name}?`)) return;
    this.api.deleteStaff(m.id).subscribe({ next: () => { this.loadStaff(); this.flash('נמחק'); }, error: (e) => this.flash(this.err(e), true) });
  }

  saveStock(e: EquipmentType) {
    this.api.putStock({ ...e, owned: Math.max(0, Math.round(+e.owned || 0)) }).subscribe({ next: () => this.flash('המלאי עודכן'), error: (x) => this.flash(this.err(x), true) });
  }
  addStock() {
    const e = { ...this.nw, code: this.nw.code.trim(), name: this.nw.name.trim(), owned: Math.max(0, Math.round(+this.nw.owned || 0)) };
    this.api.putStock(e).subscribe({ next: () => { this.nw = { code: '', name: '', owned: 0, notes: '' }; this.loadStock(); this.flash('נוסף'); }, error: (x) => this.flash(this.err(x), true) });
  }
  removeStock(e: EquipmentType) {
    if (!confirm(`למחוק את ${e.name} מהמלאי?`)) return;
    this.api.deleteStock(e.code).subscribe({ next: () => this.loadStock(), error: (x) => this.flash(this.err(x), true) });
  }

  payXlsx() { this.api.payrollXlsx(this.month).subscribe((b) => this.download(b, `payroll-${this.month}.xlsx`)); }
  template() { this.api.teamTemplate().subscribe((b) => this.download(b, 'team-and-equipment.xlsx')); }
  private download(b: Blob, name: string) { const a = document.createElement('a'); a.href = URL.createObjectURL(b); a.download = name; a.click(); }
  pick(f: File | undefined) {
    if (!f) return;
    this.file = f; this.report.set(null); this.busy.set(true);
    this.api.importTeam(f).subscribe({ next: (r) => { this.report.set(r); this.busy.set(false); }, error: (e) => { this.busy.set(false); this.flash(this.err(e), true); } });
  }
  applyImport() {
    if (!this.file) return;
    this.busy.set(true);
    this.api.importTeam(this.file, true).subscribe({
      next: (r) => { this.report.set(r); this.busy.set(false); this.loadStaff(); this.loadStock(); this.flash('הייבוא נשמר'); },
      error: (e) => { this.busy.set(false); this.flash(this.err(e), true); },
    });
  }
}

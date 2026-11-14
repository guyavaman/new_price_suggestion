import { Component, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { ApiService } from '../core/api.service';
import { HeDatePipe, RelativePipe } from '../core/format';
import { ACTOR } from '../core/labels';
import { Task } from '../core/models';

@Component({
  selector: 'app-tasks',
  standalone: true,
  imports: [RouterLink, HeDatePipe, RelativePipe],
  template: `
    <div class="page-head"><div><h1>משימות</h1><p>כולל משימות שהסוכן פתח בשבילכם (העברה לנציג, שיחה חוזרת)</p></div></div>
    <div class="card">
      <table>
        <thead><tr><th></th><th>משימה</th><th>יעד</th><th>נפתחה ע"י</th><th></th></tr></thead>
        <tbody>
          @for (t of tasks(); track t.id) {
            <tr [class.overdue]="overdue(t)">
              <td><input type="checkbox" (change)="done(t.id)" [attr.aria-label]="'סיום ' + t.title"></td>
              <td>@if (t.priority === 'high') { <span class="pill hot">דחוף</span> } {{ t.title }}</td>
              <td class="num">{{ t.due_at | heDate: true }} <small class="muted">{{ t.due_at | rel }}</small></td>
              <td>@if (t.created_by === 'agent') { <span class="pill ai">סוכן AI</span> } @else { {{ actor[t.created_by] }} }</td>
              <td>@if (t.deal_id) { <a [routerLink]="['/deals', t.deal_id]">לעסקה</a> }</td>
            </tr>
          } @empty { <tr><td colspan="5" class="empty">אין משימות פתוחות 🎉</td></tr> }
        </tbody>
      </table>
    </div>
  `,
  styles: [`.overdue td { background: var(--bad-soft); } td:first-child { width: 32px; }`],
})
export class TasksComponent {
  private api = inject(ApiService);
  tasks = signal<Task[]>([]);
  actor = ACTOR;
  constructor() { this.load(); }
  load() { this.api.tasks().subscribe((t) => this.tasks.set(t)); }
  done(id: string) { this.api.doneTask(id).subscribe(() => this.load()); }
  overdue(t: Task) { return !!t.due_at && new Date(t.due_at).getTime() < Date.now(); }
}

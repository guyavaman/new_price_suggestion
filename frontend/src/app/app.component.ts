import { Component } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [RouterOutlet, RouterLink, RouterLinkActive],
  template: `
    <div class="shell">
      <aside class="side">
        <div class="brand"><b>זית ודבש</b><span>CRM קייטרינג</span></div>
        <nav>
          @for (l of links; track l.path) {
            <a [routerLink]="l.path" routerLinkActive="on">{{ l.label }}</a>
          }
        </nav>
        <a class="widget" routerLink="/chat" routerLinkActive="on">צ'אט לקוח (סוכן AI) ↗</a>
      </aside>
      <main class="main"><router-outlet /></main>
    </div>
  `,
  styles: [`
    .shell { display: grid; grid-template-columns: 220px 1fr; min-height: 100vh; }
    .side { background: var(--ink); color: var(--paper); padding: 20px 14px; display: flex; flex-direction: column; gap: 18px; position: sticky; top: 0; height: 100vh; }
    .brand { display: grid; padding: 0 8px; }
    .brand b { font-family: var(--display); font-size: 1.5rem; color: var(--honey-l); }
    .brand span { font-size: .85rem; opacity: .7; }
    nav { display: grid; gap: 2px; }
    a { color: inherit; text-decoration: none; padding: 9px 10px; border-radius: 8px; opacity: .85; }
    a:hover { background: rgba(255,255,255,.08); opacity: 1; }
    a.on { background: rgba(255,255,255,.14); opacity: 1; font-weight: 700; }
    .widget { margin-top: auto; border: 1px dashed rgba(255,255,255,.35); font-size: .9rem; }
    .main { padding: 24px clamp(16px, 3vw, 36px) 48px; min-width: 0; }
    @media (max-width: 760px) {
      .shell { grid-template-columns: 1fr; }
      .side { position: static; height: auto; flex-direction: row; flex-wrap: wrap; align-items: center; }
      nav { display: flex; flex-wrap: wrap; }
      .widget { margin: 0; }
    }
  `],
})
export class AppComponent {
  links = [
    { path: '/dashboard', label: 'דשבורד' },
    { path: '/pipeline', label: 'Pipeline' },
    { path: '/conversations', label: "שיחות סוכן AI" },
    { path: '/tasks', label: 'משימות' },
    { path: '/customers', label: 'לקוחות' },
  ];
}

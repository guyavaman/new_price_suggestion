import { Component, inject, signal } from '@angular/core';
import { NavigationEnd, Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { filter } from 'rxjs';

interface NavGroup { label: string; links: { path: string; label: string; exact?: boolean }[] }

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [RouterOutlet, RouterLink, RouterLinkActive],
  template: `
    <header class="nav">
      <a class="brand" routerLink="/dashboard"><b>זית ודבש</b><span>הצעות מחיר · CRM</span></a>
      <button class="burger" type="button" (click)="open.set(!open())" [attr.aria-expanded]="open()" aria-controls="menu" aria-label="תפריט">☰</button>
      <nav id="menu" [class.open]="open()" aria-label="ניווט ראשי">
        @for (g of groups; track g.label) {
          <div class="group">
            <span class="glabel">{{ g.label }}</span>
            @for (l of g.links; track l.path) {
              <a [routerLink]="l.path" routerLinkActive="on" [routerLinkActiveOptions]="{ exact: !!l.exact }">{{ l.label }}</a>
            }
          </div>
        }
        <a class="cta" routerLink="/chat" routerLinkActive="on">צ'אט לקוח · סוכן AI</a>
      </nav>
    </header>
    <main class="main"><router-outlet /></main>
  `,
  styles: [`
    .nav { position: sticky; top: 0; z-index: 20; background: var(--ink); color: var(--paper); display: flex; align-items: center; gap: 18px; padding: 0 clamp(14px, 3vw, 32px); min-height: 58px; }
    .brand { display: grid; text-decoration: none; color: inherit; line-height: 1.15; }
    .brand b { font-family: var(--display); font-size: 1.35rem; color: var(--honey-l); }
    .brand span { font-size: .75rem; opacity: .7; }
    nav { display: flex; align-items: center; gap: 14px; flex: 1; }
    .group { display: flex; align-items: center; gap: 2px; padding-inline-start: 14px; border-inline-start: 1px solid rgba(255,255,255,.18); }
    .glabel { font-size: .72rem; opacity: .55; margin-inline-end: 6px; }
    a { color: inherit; text-decoration: none; padding: 7px 10px; border-radius: 8px; opacity: .85; white-space: nowrap; }
    a:hover { background: rgba(255,255,255,.08); opacity: 1; }
    a.on { background: rgba(255,255,255,.16); opacity: 1; font-weight: 700; }
    .cta { margin-inline-start: auto; border: 1px solid rgba(255,255,255,.35); }
    .burger { display: none; margin-inline-start: auto; background: none; border: 1px solid rgba(255,255,255,.35); color: inherit; border-radius: 8px; padding: 4px 10px; font-size: 1.1rem; }
    .main { padding: 24px clamp(16px, 3vw, 36px) 48px; max-width: 1440px; margin: 0 auto; }
    @media (max-width: 1080px) {
      .nav { flex-wrap: wrap; padding-block: 8px; }
      .burger { display: block; }
      nav { display: none; flex-basis: 100%; flex-direction: column; align-items: stretch; gap: 10px; padding-bottom: 8px; }
      nav.open { display: flex; }
      .group { flex-wrap: wrap; border: 0; padding: 0; }
      .glabel { flex-basis: 100%; }
      .cta { margin: 0; text-align: center; }
    }
  `],
})
export class AppComponent {
  open = signal(false);
  groups: NavGroup[] = [
    { label: 'הצעות מחיר', links: [{ path: '/quotes/new', label: 'הצעה חדשה' }, { path: '/quotes', label: 'כל ההצעות', exact: true }] },
    { label: 'CRM', links: [
      { path: '/dashboard', label: 'דשבורד' }, { path: '/pipeline', label: 'Pipeline' },
      { path: '/conversations', label: 'שיחות AI' }, { path: '/tasks', label: 'משימות' }, { path: '/customers', label: 'לקוחות' },
    ] },
  ];
  constructor() {
    inject(Router).events.pipe(filter((e) => e instanceof NavigationEnd)).subscribe(() => this.open.set(false));
  }
}

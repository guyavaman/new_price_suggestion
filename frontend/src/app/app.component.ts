import { Component, inject, signal } from '@angular/core';
import { ActivatedRoute, NavigationEnd, Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { filter } from 'rxjs';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [RouterOutlet, RouterLink, RouterLinkActive],
  template: `
    @if (!isPublic()) {
      <header class="nav">
        <a class="brand" routerLink="/today"><b>זית ודבש</b><span>ניהול אירועים</span></a>
        <button class="burger" type="button" (click)="open.set(!open())" [attr.aria-expanded]="open()" aria-controls="menu" aria-label="תפריט">☰</button>
        <nav id="menu" [class.open]="open()" aria-label="ניווט ראשי">
          @for (l of main; track l.path) { <a [routerLink]="l.path" routerLinkActive="on">{{ l.label }}</a> }
          <span class="sep"></span>
          @for (l of more; track l.path) { <a class="minor" [routerLink]="l.path" routerLinkActive="on">{{ l.label }}</a> }
        </nav>
      </header>
    }
    <main [class.main]="!isPublic()"><router-outlet /></main>
  `,
  styles: [`
    .nav { position: sticky; top: 0; z-index: 20; background: var(--ink); color: var(--paper); display: flex; align-items: center; gap: 18px; padding: 0 clamp(14px, 3vw, 32px); min-height: 58px; }
    .brand { display: grid; text-decoration: none; color: inherit; line-height: 1.15; }
    .brand b { font-family: var(--display); font-size: 1.35rem; color: var(--honey-l); }
    .brand span { font-size: .75rem; opacity: .7; }
    nav { display: flex; align-items: center; gap: 2px; flex: 1; }
    a { color: inherit; text-decoration: none; padding: 7px 11px; border-radius: 8px; opacity: .85; white-space: nowrap; }
    a:hover { background: rgba(255,255,255,.08); opacity: 1; }
    a.on { background: rgba(255,255,255,.16); opacity: 1; font-weight: 700; }
    .sep { flex: 1; } .minor { font-size: .85rem; opacity: .65; }
    .burger { display: none; margin-inline-start: auto; background: none; border: 1px solid rgba(255,255,255,.35); color: inherit; border-radius: 8px; padding: 4px 10px; font-size: 1.1rem; }
    .main { display: block; padding: 24px clamp(16px, 3vw, 36px) 48px; max-width: 1440px; margin: 0 auto; }
    @media (max-width: 1100px) {
      .nav { flex-wrap: wrap; padding-block: 8px; }
      .burger { display: block; }
      nav { display: none; flex-basis: 100%; flex-direction: column; align-items: stretch; padding-bottom: 8px; }
      nav.open { display: flex; } .sep { display: none; }
    }
  `],
})
export class AppComponent {
  private router = inject(Router);
  private route = inject(ActivatedRoute);
  open = signal(false);
  isPublic = signal(false);
  main = [
    { path: '/today', label: 'היום' }, { path: '/inbox', label: 'פניות' }, { path: '/events', label: 'אירועים' },
    { path: '/calendar', label: 'לוח שנה' }, { path: '/kitchen', label: 'מטבח' }, { path: '/menu', label: 'תפריט ומחירים' },
    { path: '/settings', label: 'הגדרות' },
  ];
  more = [{ path: '/reports', label: 'דוחות' }, { path: '/customers', label: 'לקוחות' }, { path: '/quotes', label: 'הצעות' }, { path: '/chat', label: "צ'אט לקוח" }];

  constructor() {
    this.router.events.pipe(filter((e) => e instanceof NavigationEnd)).subscribe(() => {
      this.open.set(false);
      let r = this.route.snapshot;
      while (r.firstChild) r = r.firstChild;
      this.isPublic.set(!!r.data['public']);
    });
  }
}

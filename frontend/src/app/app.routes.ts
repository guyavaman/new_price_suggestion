import { Routes } from '@angular/router';
import { ownerGuard } from './core/auth';

const page = (title: string, load: () => Promise<any>, data: Record<string, unknown> = {}) =>
  ({ title, loadComponent: load, data, canActivate: data['public'] ? [] : [ownerGuard] });

export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'today' },
  { path: 'today', ...page('היום', () => import('./pages/today.component').then((m) => m.TodayComponent)) },
  { path: 'inbox', ...page('פניות', () => import('./pages/conversations.component').then((m) => m.ConversationsComponent)) },
  { path: 'events', ...page('אירועים', () => import('./pages/events.component').then((m) => m.EventsComponent)) },
  { path: 'deals/:id', ...page('אירוע', () => import('./pages/deal-detail.component').then((m) => m.DealDetailComponent)) },
  { path: 'calendar', ...page('לוח שנה', () => import('./pages/calendar.component').then((m) => m.CalendarComponent)) },
  { path: 'kitchen', ...page('דף מטבח', () => import('./pages/kitchen.component').then((m) => m.KitchenComponent)) },
  { path: 'menu', ...page('תפריט ומחירים', () => import('./pages/menu.component').then((m) => m.MenuComponent)) },
  { path: 'settings', ...page('הגדרות', () => import('./pages/settings.component').then((m) => m.SettingsComponent)) },
  { path: 'reports', ...page('דוחות', () => import('./pages/dashboard.component').then((m) => m.DashboardComponent)) },
  { path: 'customers', ...page('לקוחות', () => import('./pages/customers.component').then((m) => m.CustomersComponent)) },
  { path: 'quotes/new', redirectTo: 'inbox' },
  { path: 'quotes/:id', ...page('הצעת מחיר', () => import('./pages/quote-detail.component').then((m) => m.QuoteDetailComponent)) },
  { path: 'quotes', ...page('הצעות מחיר', () => import('./pages/quotes-list.component').then((m) => m.QuotesListComponent)) },
  { path: 'chat', ...page("צ'אט לקוח", () => import('./pages/chat-widget.component').then((m) => m.ChatWidgetComponent)) },
  // customer-facing, no navigation bar
  { path: 'login', ...page('כניסה', () => import('./pages/login.component').then((m) => m.LoginComponent), { public: true }) },
  { path: 'q/:token', ...page('הצעת מחיר', () => import('./pages/customer-quote.component').then((m) => m.CustomerQuoteComponent), { public: true }) },
  { path: 'pay/:id', ...page('תשלום', () => import('./pages/pay.component').then((m) => m.PayComponent), { public: true }) },
  // old links
  { path: 'dashboard', redirectTo: 'today' }, { path: 'pipeline', redirectTo: 'events' }, { path: 'conversations', redirectTo: 'inbox' },
  { path: 'tasks', redirectTo: 'today' },
  { path: '**', redirectTo: 'today' },
];

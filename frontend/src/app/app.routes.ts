import { Routes } from '@angular/router';

export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'dashboard' },
  { path: 'dashboard', title: 'דשבורד', loadComponent: () => import('./pages/dashboard.component').then((m) => m.DashboardComponent) },
  { path: 'pipeline', title: 'Pipeline', loadComponent: () => import('./pages/pipeline.component').then((m) => m.PipelineComponent) },
  { path: 'deals/:id', title: 'עסקה', loadComponent: () => import('./pages/deal-detail.component').then((m) => m.DealDetailComponent) },
  { path: 'customers', title: 'לקוחות', loadComponent: () => import('./pages/customers.component').then((m) => m.CustomersComponent) },
  { path: 'conversations', title: "שיחות AI", loadComponent: () => import('./pages/conversations.component').then((m) => m.ConversationsComponent) },
  { path: 'tasks', title: 'משימות', loadComponent: () => import('./pages/tasks.component').then((m) => m.TasksComponent) },
  { path: 'chat', title: "צ'אט לקוח", loadComponent: () => import('./pages/chat-widget.component').then((m) => m.ChatWidgetComponent) },
  { path: '**', redirectTo: 'dashboard' },
];

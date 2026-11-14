import { HttpClient, HttpInterceptorFn, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import {
  BusinessSettings, CalendarDay, CatalogItem, ChatReply, Conversation, Customer, Dashboard, Deal, DealDetail,
  DealStage, EditOut, KitchenSheet, PublicQuote, QuoteOut, QuoteStatus, StoredQuote, Task, TodayView,
} from './models';

/** Point these at your backend. The API key is only needed when the tenant has one. */
export const CONFIG = {
  // `ng serve` (port 4200) talks to the local API; in production the API serves the app itself
  apiUrl: location.port === '4200' ? 'http://localhost:8000' : '',
  tenantId: 'demo',
  apiKey: '',
};

export const tenantInterceptor: HttpInterceptorFn = (req, next) => {
  const headers: Record<string, string> = { 'X-Tenant-ID': CONFIG.tenantId };
  if (CONFIG.apiKey) headers['X-API-Key'] = CONFIG.apiKey;
  return next(req.clone({ setHeaders: headers }));
};

@Injectable({ providedIn: 'root' })
export class ApiService {
  private http = inject(HttpClient);
  private u = (p: string) => `${CONFIG.apiUrl}${p}`;

  dashboard(): Observable<Dashboard> { return this.http.get<Dashboard>(this.u('/crm/dashboard')); }

  deals(stage?: DealStage, q?: string): Observable<Deal[]> {
    let params = new HttpParams();
    if (stage) params = params.set('stage', stage);
    if (q) params = params.set('q', q);
    return this.http.get<Deal[]>(this.u('/crm/deals'), { params });
  }
  deal(id: string): Observable<DealDetail> { return this.http.get<DealDetail>(this.u(`/crm/deals/${id}`)); }
  createDeal(body: unknown): Observable<Deal> { return this.http.post<Deal>(this.u('/crm/deals'), body); }
  setStage(id: string, stage: DealStage, reason?: string): Observable<Deal> {
    return this.http.post<Deal>(this.u(`/crm/deals/${id}/stage`), { stage, reason });
  }
  addNote(id: string, text: string, kind = 'note') {
    return this.http.post(this.u(`/crm/deals/${id}/notes`), { text, kind });
  }
  // ---------- quotes ----------
  createQuote(message: string): Observable<QuoteOut> { return this.http.post<QuoteOut>(this.u('/quotes'), { message }); }
  quotes(): Observable<StoredQuote[]> { return this.http.get<StoredQuote[]>(this.u('/quotes')); }
  quote(id: string): Observable<StoredQuote> { return this.http.get<StoredQuote>(this.u(`/quotes/${id}`)); }
  editQuote(id: string, instruction: string): Observable<EditOut> {
    return this.http.post<EditOut>(this.u(`/quotes/${id}/edit`), { instruction });
  }
  setQuoteStatus(quoteId: string, status: QuoteStatus | string, tier?: string, note?: string): Observable<QuoteOut> {
    return this.http.post<QuoteOut>(this.u(`/quotes/${quoteId}/status`), { status, tier, note });
  }

  customers(q?: string): Observable<Customer[]> {
    return this.http.get<Customer[]>(this.u('/crm/customers'), { params: q ? { q } : {} });
  }
  customer(id: string): Observable<{ customer: Customer; deals: Deal[] }> {
    return this.http.get<{ customer: Customer; deals: Deal[] }>(this.u(`/crm/customers/${id}`));
  }

  tasks(openOnly = true): Observable<Task[]> {
    return this.http.get<Task[]>(this.u('/crm/tasks'), { params: { open_only: openOnly } });
  }
  addTask(body: { title: string; deal_id?: string; due_at?: string; priority?: string }): Observable<Task> {
    return this.http.post<Task>(this.u('/crm/tasks'), body);
  }
  doneTask(id: string): Observable<Task> { return this.http.post<Task>(this.u(`/crm/tasks/${id}/done`), {}); }

  conversations(status?: string): Observable<Conversation[]> {
    return this.http.get<Conversation[]>(this.u('/crm/conversations'), { params: status ? { status } : {} });
  }
  conversation(id: string): Observable<Conversation> { return this.http.get<Conversation>(this.u(`/crm/conversations/${id}`)); }
  humanReply(id: string, text: string): Observable<Conversation> {
    return this.http.post<Conversation>(this.u(`/crm/conversations/${id}/reply`), { text });
  }
  resumeAi(id: string): Observable<Conversation> {
    return this.http.post<Conversation>(this.u(`/crm/conversations/${id}/resume`), {});
  }

  // ---------- owner screens ----------
  today(): Observable<TodayView> { return this.http.get<TodayView>(this.u('/crm/today')); }
  calendar(month: string): Observable<CalendarDay[]> { return this.http.get<CalendarDay[]>(this.u('/crm/calendar'), { params: { month } }); }
  kitchen(day: string): Observable<KitchenSheet> { return this.http.get<KitchenSheet>(this.u('/kitchen'), { params: { day } }); }
  catalog(): Observable<CatalogItem[]> { return this.http.get<CatalogItem[]>(this.u('/catalog')); }
  addItem(item: Partial<CatalogItem>): Observable<CatalogItem> { return this.http.post<CatalogItem>(this.u('/catalog'), item); }
  patchItem(sku: string, patch: Partial<CatalogItem>): Observable<CatalogItem> { return this.http.patch<CatalogItem>(this.u(`/catalog/${sku}`), patch); }
  settings(): Observable<BusinessSettings> { return this.http.get<BusinessSettings>(this.u('/settings')); }
  saveSettings(patch: Partial<BusinessSettings>): Observable<BusinessSettings> { return this.http.patch<BusinessSettings>(this.u('/settings'), patch); }
  invoice(dealId: string, number?: string): Observable<Deal> { return this.http.post<Deal>(this.u(`/crm/deals/${dealId}/invoice`), { number: number ?? null }); }
  runAutomation(): Observable<{ rule: string; deal_id: string; title: string }[]> { return this.http.post<{ rule: string; deal_id: string; title: string }[]>(this.u('/automation/run'), {}); }

  // ---------- customer page (public, token based) ----------
  publicQuote(token: string): Observable<PublicQuote> { return this.http.get<PublicQuote>(this.u(`/public/quotes/${token}`)); }
  acceptQuote(token: string, tier: string): Observable<{ approved: boolean; checkout_url: string | null; payment_id?: string; amount?: number }> {
    return this.http.post<{ approved: boolean; checkout_url: string | null; payment_id?: string; amount?: number }>(this.u(`/public/quotes/${token}/accept`), { tier });
  }
  updateGuestCount(token: string, guests: number): Observable<PublicQuote> { return this.http.post<PublicQuote>(this.u(`/public/quotes/${token}/guest-count`), { guests }); }
  paymentInfo(token: string, id: string): Observable<{ amount: number; status: string; business_name: string; quote_number: string; tier: string }> {
    return this.http.get<{ amount: number; status: string; business_name: string; quote_number: string; tier: string }>(this.u(`/public/quotes/${token}/payments/${id}`));
  }
  demoConfirm(token: string, id: string) { return this.http.post(this.u(`/public/quotes/${token}/payments/${id}/demo-confirm`), {}); }

  chat(message: string, conversationId?: string | null): Observable<ChatReply> {
    return this.http.post<ChatReply>(this.u('/agent/chat'), { message, conversation_id: conversationId ?? null });
  }
}

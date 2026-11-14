import { HttpClient, HttpInterceptorFn, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import {
  ChatReply, Conversation, Customer, Dashboard, Deal, DealDetail, DealStage, EditOut, QuoteOut, QuoteStatus,
  StoredQuote, Task,
} from './models';

/** Point these at your backend. The API key is only needed when the tenant has one. */
export const CONFIG = {
  apiUrl: 'http://localhost:8000',
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

  chat(message: string, conversationId?: string | null): Observable<ChatReply> {
    return this.http.post<ChatReply>(this.u('/agent/chat'), { message, conversation_id: conversationId ?? null });
  }
}

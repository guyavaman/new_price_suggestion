import { HttpClient, HttpInterceptorFn, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import {
  BusinessSettings, CalendarDay, CatalogItem, ChatReply, Conversation, Customer, Dashboard, Deal, DealDetail,
  DealStage, EditOut, KitchenSheet, PublicQuote, QuoteOut, QuoteStatus, StoredQuote, Task, TodayView, ServiceChat, CustomerMessage, ImpactRow, ImportReport, QuoteProfit, ProfitReport, DealMenu, OwnerMenu, Supplier, Ingredient, PurchaseList, PrepDay, Readiness, SiteConditions, StaffMember, DealStaff, PayRow, EquipmentType, EquipmentLine, EquipmentState, MissingReturn, ShiftView, ClosingView, EventClosing, LearningView, PortionSuggestion } from './models';

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
  dealMessages(id: string): Observable<CustomerMessage[]> { return this.http.get<CustomerMessage[]>(this.u(`/crm/deals/${id}/messages`)); }
  messageSent(id: string, kind: string): Observable<unknown> { return this.http.post(this.u(`/crm/deals/${id}/messages/${kind}/sent`), {}); }
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
  setQuoteStatus(quoteId: string, status: QuoteStatus | string, tier?: string, note?: string, overrideFloor = false): Observable<QuoteOut> {
    return this.http.post<QuoteOut>(this.u(`/quotes/${quoteId}/status`), { status, tier, note, override_floor: overrideFloor });
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
  patchItem(sku: string, patch: Partial<CatalogItem>): Observable<{ item: CatalogItem; cost_impact: ImpactRow[] }> { return this.http.patch<{ item: CatalogItem; cost_impact: ImpactRow[] }>(this.u(`/catalog/${sku}`), patch); }
  importCatalog(file: File, apply = false): Observable<ImportReport> {
    const fd = new FormData(); fd.append('file', file);
    return this.http.post<ImportReport>(this.u(`/catalog/import${apply ? '?apply=true' : ''}`), fd);
  }
  importTemplate(): Observable<Blob> { return this.http.get(this.u('/catalog/import/template'), { responseType: 'blob' }); }
  suppliers(): Observable<Supplier[]> { return this.http.get<Supplier[]>(this.u('/suppliers')); }
  putSupplier(s: Supplier): Observable<Supplier> { return this.http.put<Supplier>(this.u(`/suppliers/${encodeURIComponent(s.code)}`), s); }
  deleteSupplier(code: string): Observable<void> { return this.http.delete<void>(this.u(`/suppliers/${encodeURIComponent(code)}`)); }
  ingredients(): Observable<Ingredient[]> { return this.http.get<Ingredient[]>(this.u('/ingredients')); }
  putIngredient(i: Ingredient): Observable<Ingredient> { return this.http.put<Ingredient>(this.u(`/ingredients/${encodeURIComponent(i.code)}`), i); }
  deleteIngredient(code: string): Observable<void> { return this.http.delete<void>(this.u(`/ingredients/${encodeURIComponent(code)}`)); }
  purchaseList(start: string, end: string): Observable<PurchaseList> { return this.http.get<PurchaseList>(this.u('/purchasing/list'), { params: { start, end } }); }
  purchaseXlsx(start: string, end: string): Observable<Blob> { return this.http.get(this.u('/purchasing/list.xlsx'), { params: { start, end }, responseType: 'blob' }); }
  prepSchedule(start: string, end: string): Observable<PrepDay[]> { return this.http.get<PrepDay[]>(this.u('/production/schedule'), { params: { start, end } }); }
  purchasingTemplate(): Observable<Blob> { return this.http.get(this.u('/purchasing/import/template'), { responseType: 'blob' }); }
  importPurchasing(file: File, apply = false): Observable<ImportReport> {
    const fd = new FormData(); fd.append('file', file);
    return this.http.post<ImportReport>(this.u(`/purchasing/import${apply ? '?apply=true' : ''}`), fd);
  }
  readiness(dealId: string): Observable<Readiness> { return this.http.get<Readiness>(this.u(`/crm/deals/${dealId}/readiness`)); }
  patchReadiness(dealId: string, body: Partial<{ location: string; site_contact_name: string; site_contact_phone: string; site: Partial<SiteConditions>; marks: Record<string, boolean>; service_style: string | null }>): Observable<Readiness> {
    return this.http.patch<Readiness>(this.u(`/crm/deals/${dealId}/readiness`), body);
  }
  decideChange(dealId: string, requestId: string, decision: 'approve' | 'decline'): Observable<unknown> { return this.http.post(this.u(`/crm/deals/${dealId}/changes/${requestId}/${decision}`), {}); }
  quoteFromDeal(dealId: string): Observable<{ quote_id: string; number: string }> { return this.http.post<{ quote_id: string; number: string }>(this.u(`/crm/deals/${dealId}/quote`), {}); }
  markOrder(supplier: string, deliver_on: string, ordered = true): Observable<void> { return this.http.post<void>(this.u('/purchasing/orders/mark'), { supplier, deliver_on, ordered }); }
  staff(): Observable<StaffMember[]> { return this.http.get<StaffMember[]>(this.u('/staff')); }
  addStaff(m: Partial<StaffMember>): Observable<StaffMember> { return this.http.post<StaffMember>(this.u('/staff'), m); }
  putStaff(m: StaffMember): Observable<StaffMember> { return this.http.put<StaffMember>(this.u(`/staff/${m.id}`), m); }
  deleteStaff(id: string): Observable<void> { return this.http.delete<void>(this.u(`/staff/${id}`)); }
  dealStaff(dealId: string): Observable<DealStaff> { return this.http.get<DealStaff>(this.u(`/crm/deals/${dealId}/staff`)); }
  autoStaff(dealId: string): Observable<DealStaff> { return this.http.post<DealStaff>(this.u(`/crm/deals/${dealId}/staff/auto`), {}); }
  assignStaff(dealId: string, member_id: string, role: string): Observable<DealStaff> { return this.http.post<DealStaff>(this.u(`/crm/deals/${dealId}/staff`), { member_id, role }); }
  patchAssignment(dealId: string, id: string, body: Partial<{ status: string; actual_hours: number | null; planned_hours: number }>): Observable<DealStaff> {
    return this.http.patch<DealStaff>(this.u(`/crm/deals/${dealId}/staff/${id}`), body);
  }
  removeAssignment(dealId: string, id: string): Observable<DealStaff> { return this.http.delete<DealStaff>(this.u(`/crm/deals/${dealId}/staff/${id}`)); }
  payroll(month: string): Observable<PayRow[]> { return this.http.get<PayRow[]>(this.u('/staff/payroll'), { params: { month } }); }
  payrollXlsx(month: string): Observable<Blob> { return this.http.get(this.u('/staff/payroll.xlsx'), { params: { month }, responseType: 'blob' }); }
  stock(): Observable<EquipmentType[]> { return this.http.get<EquipmentType[]>(this.u('/equipment')); }
  putStock(e: EquipmentType): Observable<EquipmentType> { return this.http.put<EquipmentType>(this.u(`/equipment/${encodeURIComponent(e.code)}`), e); }
  deleteStock(code: string): Observable<void> { return this.http.delete<void>(this.u(`/equipment/${encodeURIComponent(code)}`)); }
  missingEquipment(): Observable<MissingReturn[]> { return this.http.get<MissingReturn[]>(this.u('/equipment/missing')); }
  dealEquipment(dealId: string): Observable<EquipmentState> { return this.http.get<EquipmentState>(this.u(`/crm/deals/${dealId}/equipment`)); }
  putDealEquipment(dealId: string, lines: EquipmentLine[], flags: { packed?: boolean; returned?: boolean } = {}): Observable<EquipmentState> {
    return this.http.put<EquipmentState>(this.u(`/crm/deals/${dealId}/equipment`), { lines, ...flags });
  }
  teamTemplate(): Observable<Blob> { return this.http.get(this.u('/team/import/template'), { responseType: 'blob' }); }
  importTeam(file: File, apply = false): Observable<ImportReport> {
    const fd = new FormData(); fd.append('file', file);
    return this.http.post<ImportReport>(this.u(`/team/import${apply ? '?apply=true' : ''}`), fd);
  }
  closing(dealId: string): Observable<ClosingView> { return this.http.get<ClosingView>(this.u(`/crm/deals/${dealId}/closing`)); }
  saveClosing(dealId: string, body: EventClosing): Observable<ClosingView> { return this.http.put<ClosingView>(this.u(`/crm/deals/${dealId}/closing`), body); }
  learning(): Observable<LearningView> { return this.http.get<LearningView>(this.u('/closing/learning')); }
  applyPortion(category: string, total_per_guest: number): Observable<PortionSuggestion> {
    return this.http.post<PortionSuggestion>(this.u('/closing/learning/apply'), { category, total_per_guest });
  }
  shift(token: string): Observable<ShiftView> { return this.http.get<ShiftView>(this.u(`/public/staff/${token}`)); }
  answerShift(token: string, coming: boolean): Observable<ShiftView> { return this.http.post<ShiftView>(this.u(`/public/staff/${token}`), { coming }); }
  quoteMenu(id: string): Observable<OwnerMenu> { return this.http.get<OwnerMenu>(this.u(`/quotes/${id}/menu`)); }
  setQuoteMenu(id: string, pkg: string, choice: Record<string, string[]>): Observable<OwnerMenu> { return this.http.put<OwnerMenu>(this.u(`/quotes/${id}/menu`), { package: pkg, choice }); }
  dealMenu(id: string): Observable<DealMenu> { return this.http.get<DealMenu>(this.u(`/crm/deals/${id}/menu`)); }
  choosePublicMenu(token: string, pkg: string, choice: Record<string, string[]>): Observable<PublicQuote> { return this.http.post<PublicQuote>(this.u(`/public/quotes/${token}/menu`), { package: pkg, choice }); }
  quoteProfit(id: string): Observable<QuoteProfit> { return this.http.get<QuoteProfit>(this.u(`/quotes/${id}/profit`)); }
  profitReport(months = 6): Observable<ProfitReport> { return this.http.get<ProfitReport>(this.u(`/reports/profit?months=${months}`)); }
  settings(): Observable<BusinessSettings> { return this.http.get<BusinessSettings>(this.u('/settings')); }
  saveSettings(patch: Partial<BusinessSettings>): Observable<BusinessSettings> { return this.http.patch<BusinessSettings>(this.u('/settings'), patch); }
  invoice(dealId: string, number?: string): Observable<Deal> { return this.http.post<Deal>(this.u(`/crm/deals/${dealId}/invoice`), { number: number ?? null }); }
  runAutomation(): Observable<{ rule: string; deal_id: string; title: string }[]> { return this.http.post<{ rule: string; deal_id: string; title: string }[]>(this.u('/automation/run'), {}); }

  // ---------- customer page (public, token based) ----------
  publicQuote(token: string): Observable<PublicQuote> { return this.http.get<PublicQuote>(this.u(`/public/quotes/${token}`)); }
  acceptQuote(token: string, tier: string): Observable<{ approved: boolean; checkout_url: string | null; payment_id?: string; amount?: number }> {
    return this.http.post<{ approved: boolean; checkout_url: string | null; payment_id?: string; amount?: number }>(this.u(`/public/quotes/${token}/accept`), { tier });
  }
  serviceChatHistory(token: string): Observable<ServiceChat> { return this.http.get<ServiceChat>(this.u(`/public/quotes/${token}/chat`)); }
  serviceChat(token: string, message: string): Observable<ServiceChat> { return this.http.post<ServiceChat>(this.u(`/public/quotes/${token}/chat`), { message }); }
  declineQuote(token: string, reason: string): Observable<PublicQuote> { return this.http.post<PublicQuote>(this.u(`/public/quotes/${token}/decline`), { reason }); }
  updateGuestCount(token: string, guests: number): Observable<PublicQuote> { return this.http.post<PublicQuote>(this.u(`/public/quotes/${token}/guest-count`), { guests }); }
  paymentInfo(token: string, id: string): Observable<{ amount: number; status: string; business_name: string; quote_number: string; tier: string }> {
    return this.http.get<{ amount: number; status: string; business_name: string; quote_number: string; tier: string }>(this.u(`/public/quotes/${token}/payments/${id}`));
  }
  demoConfirm(token: string, id: string) { return this.http.post(this.u(`/public/quotes/${token}/payments/${id}/demo-confirm`), {}); }

  chat(message: string, conversationId?: string | null): Observable<ChatReply> {
    return this.http.post<ChatReply>(this.u('/agent/chat'), { message, conversation_id: conversationId ?? null });
  }
}

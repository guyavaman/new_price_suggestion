import { APIRequestContext, Page, expect } from '@playwright/test';

const JSON_HEADERS = { 'X-Tenant-ID': 'demo', Accept: 'application/json' };

export interface Quote { id: string; number: string; status: string; public_token: string; request: { contact: { name: string | null } } }
export interface Deal { id: string; stage: string; quote_ids: string[]; lost_reason: string | null; final_guest_count: number | null; deposit_paid: number }

export async function quotes(api: APIRequestContext): Promise<Quote[]> {
  const r = await (await api.get('/quotes', { headers: JSON_HEADERS })).json();
  return Array.isArray(r) ? r : r.items;
}

/** The seeded quote of a demo customer (seed names are fixed). */
export async function quoteOf(api: APIRequestContext, customer: string): Promise<Quote> {
  const q = (await quotes(api)).find((x) => x.request.contact.name === customer);
  expect(q, `seeded quote for ${customer}`).toBeTruthy();
  return q!;
}

export async function dealOf(api: APIRequestContext, quoteId: string): Promise<Deal> {
  const r = await (await api.get('/crm/deals', { headers: JSON_HEADERS })).json();
  const deals: Deal[] = Array.isArray(r) ? r : r.items;
  return deals.find((d) => d.quote_ids.includes(quoteId))!;
}

/** Fail the test on any uncaught page error or console error (except blocked web fonts). */
export function watchErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('console', (m) => {
    if (m.type() === 'error' && !/fonts\.googleapis|ERR_BLOCKED|Failed to load resource/.test(m.text())) errors.push(m.text());
  });
  return errors;
}

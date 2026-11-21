import { expect, test } from '@playwright/test';
import { quoteOf, watchErrors } from './helpers';

const H = { 'X-Tenant-ID': 'demo', Accept: 'application/json' };

// Stage 7 acceptance: customer type and history, reorder reminder, sales report, delivery and
// terms settings, and the lead score's intent signals.

test('customers: type decides VAT display, history and the reorder hint', async ({ page, request }) => {
  const errors = watchErrors(page);
  await page.goto('/customers');
  await page.getByRole('cell', { name: /סטודיו אלמה/ }).click();
  const side = page.locator('aside');
  await expect(side.getByRole('radio', { name: 'עסקי' })).toHaveAttribute('aria-checked', 'true');
  await expect(side.locator('.due')).toContainText('לא הזמינו');
  await expect(side.locator('.hist li')).toHaveCount(1);

  // private customer → business: the quote link switches to prices before VAT
  const q = await quoteOf(request, 'הדס יעקב');
  await page.getByPlaceholder('שם, חברה, טלפון או מייל').fill('הדס');
  await page.getByRole('cell', { name: 'הדס יעקב' }).click();
  await side.getByRole('radio', { name: 'עסקי' }).click();
  await expect(side).toContainText('לפני מע"מ');
  const v = await (await request.get(`/public/quotes/${q.public_token}`)).json();
  expect(v.price_mode).toBe('net');
  await side.getByRole('radio', { name: 'לפי שם החברה' }).click();
  await expect(side).toContainText('כוללים מע"מ');
  expect(errors).toEqual([]);
});

test('reports: close rate and average profit by event type and source', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/reports');
  await expect(page.getByText("המרת צ'אט לאירוע סגור")).toBeVisible();
  const sec = page.getByRole('region', { name: 'סגירה ורווח לפי סוג אירוע ומקור' });
  await expect(sec.locator('tbody tr').first()).toBeVisible();
  await expect(sec).toContainText('אחוז סגירה');
  await sec.getByRole('tab', { name: 'לפי מקור ליד' }).click();
  await expect(sec).toContainText('וואטסאפ');
  expect(errors).toEqual([]);
});

test('settings: delivery zones, time surcharge and the terms the customer sees', async ({ page, request }) => {
  const errors = watchErrors(page);
  await page.goto('/settings');
  const dl = page.getByRole('region', { name: 'משלוח' });
  await expect(dl.locator('table.zones').first()).toContainText('ברירת מחדל');
  await expect(dl.getByLabel('שם האזור').first()).toHaveValue('מרכז');
  const tr = page.getByRole('region', { name: 'תנאי הזמנה' });
  await tr.locator('details summary').click();
  await expect(tr.locator('.tlist')).toContainText('ביטול 30 ימים או יותר');
  const before = (await (await request.get('/settings/terms', { headers: H })).json()).version;
  await tr.getByPlaceholder('למשל: חניה לרכב המשלוח באחריות הלקוח').fill('חניה לרכב המשלוח באחריות הלקוח');
  await page.getByRole('button', { name: /שמירה/ }).first().click();
  await expect(tr.locator('.tlist')).toContainText('חניה לרכב המשלוח');
  const after = (await (await request.get('/settings/terms', { headers: H })).json()).version;
  expect(after).not.toBe(before);
  // put it back for later specs
  await request.patch('/settings', { headers: H, data: { terms_extra: [] } });
  expect(errors).toEqual([]);
});

test('deal: delivery time and distance re-price the quote; intent shows in the score', async ({ page, request }) => {
  const errors = watchErrors(page);
  const q = await quoteOf(request, 'מיכל לוי');
  const deals = await (await request.get('/crm/deals', { headers: H })).json();
  const deal = (Array.isArray(deals) ? deals : deals.items).find((d: { quote_ids: string[] }) => d.quote_ids.includes(q.id));
  await page.goto(`/deals/${deal.id}`);
  await expect(page.getByText(/פתח את ההצעה \d+ פעמים/)).toBeVisible();  // seeded intent
  await page.getByRole('button', { name: 'פרטי המקום ותנאי שטח' }).click();
  await page.getByLabel('שעת הגעת האוכל').fill('06:00');
  await page.getByRole('button', { name: 'שמירה' }).first().click();
  await expect.poll(async () => {
    const r = await (await request.get(`/quotes/${q.id}`, { headers: H })).json();
    return r.tiers.find((t: { key: string }) => t.key === r.selected_tier).quote.lines.map((l: { sku: string }) => l.sku);
  }).toContain('DLV-early');
  expect(errors).toEqual([]);
});

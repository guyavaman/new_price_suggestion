import { expect, test } from '@playwright/test';
import { dealOf, quoteOf, watchErrors } from './helpers';

// Stage 6 acceptance: close an event after it happened, planned vs actual, and suggestions that
// change nothing until the owner applies them.

test('past event: summary form, planned vs actual report', async ({ page, request }) => {
  const errors = watchErrors(page);
  const deal = await dealOf(request, (await quoteOf(request, 'משפחת אורן')).id);
  await page.goto(`/deals/${deal.id}#closing`);
  const card = page.locator('#closing');
  await expect(card).toContainText('מתוכנן מול בפועל');
  await expect(card.getByText('רווח בפועל')).toBeVisible();          // seeded summary → report
  await expect(card.locator('caption', { hasText: 'עלויות' })).toBeVisible();
  await expect(card).toContainText('רכש בפועל');
  await card.getByRole('button', { name: 'עריכת הסיכום' }).click();
  await card.getByLabel('אורחים שהגיעו בפועל').fill('100');
  await card.getByRole('button', { name: 'נגמר' }).first().click();
  await card.getByRole('button', { name: 'שמירת השינויים' }).click();
  await expect(card.locator('.kpi').first()).toContainText('100');
  expect(errors).toEqual([]);
});

test('closing page: suggestions, apply one, events table', async ({ page, request }) => {
  const errors = watchErrors(page);
  await page.goto('/learning');
  await expect(page.getByRole('heading', { name: 'סגירה ולמידה' })).toBeVisible();
  const salad = page.locator('article.sug', { hasText: 'סלטים' });
  await expect(salad).toContainText('להקטין');
  await expect(page.locator('table')).toContainText('משפחת אורן');
  page.once('dialog', (d) => d.accept());
  await salad.getByRole('button', { name: /עדכון ל-/ }).click();
  await expect(page.getByRole('status')).toContainText('עודכן: סלטים');
  await expect(page.locator('article.sug', { hasText: 'סלטים' })).toHaveCount(0);
  // put the demo value back: later specs (settings) expect the default salad amount
  await request.post('/closing/learning/apply', { headers: { 'X-Tenant-ID': 'demo' }, data: { category: 'salad', total_per_guest: 220 } });
  expect(errors).toEqual([]);
});

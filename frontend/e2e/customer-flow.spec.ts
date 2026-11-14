import { expect, test } from '@playwright/test';
import { dealOf, quoteOf, watchErrors } from './helpers';

test('customer picks a package, pays the deposit, and the event is booked', async ({ page, request }) => {
  const errors = watchErrors(page);
  const q = await quoteOf(request, 'מיכל לוי'); // seeded: quote sent, not approved
  await page.goto(`/q/${q.public_token}`);
  await expect(page.locator('h1')).toContainText('מיכל לוי');

  await page.getByRole('radio', { name: /פרימיום/ }).click();
  await expect(page.locator('.accept')).toContainText('פרימיום');
  await page.getByRole('button', { name: 'אישור ותשלום מקדמה' }).click();

  await expect(page).toHaveURL(/\/pay\//);
  await expect(page.locator('h1')).toHaveText('תשלום מקדמה');
  await page.getByRole('button', { name: 'תשלום' }).click();

  await expect(page).toHaveURL(new RegExp(`/q/${q.public_token}`));
  await expect(page.locator('.done')).toContainText('ההצעה אושרה');
  await expect(page.locator('.done')).toContainText('פרימיום');

  const deal = await dealOf(request, q.id);
  expect(deal.stage).toBe('won');
  expect(deal.deposit_paid).toBeGreaterThan(0);

  // the owner sees it approved
  await page.goto(`/quotes/${q.id}`);
  await expect(page.locator('.pill').first()).toHaveText('אושרה');
  await expect(page.getByText('שינוי בשפה חופשית')).toHaveCount(0); // approved: no editing
  expect(errors).toEqual([]);
});

test('customer updates the final guest count and the price follows', async ({ page, request }) => {
  const q = await quoteOf(request, 'עומר פרץ'); // seeded: approved, event in 6 days
  await page.goto(`/q/${q.public_token}`);
  const before = await page.locator('.done').innerText();
  await page.getByLabel('מספר אורחים סופי').fill('60');
  await page.getByRole('button', { name: 'עדכון' }).click();
  await expect(page.locator('.ev')).toContainText('60 אורחים');
  await expect(page.locator('.done')).not.toHaveText(before);
  expect((await dealOf(request, q.id)).final_guest_count).toBe(60);
});

test('customer declines with a reason', async ({ page, request }) => {
  const q = await quoteOf(request, 'אבי מזרחי');
  await page.goto(`/q/${q.public_token}`);
  await page.getByRole('button', { name: 'ההצעה לא מתאימה לנו' }).click();
  await page.getByRole('button', { name: 'המחיר גבוה מדי עבורנו' }).click();
  await page.getByRole('button', { name: 'שליחה' }).click();
  await expect(page.getByText('תודה שעדכנתם')).toBeVisible();
  await expect(page.getByRole('button', { name: 'אישור ותשלום מקדמה' })).toHaveCount(0);
  const deal = await dealOf(request, q.id);
  expect(deal.stage).toBe('lost');
  expect(deal.lost_reason).toBe('המחיר גבוה מדי עבורנו');
});

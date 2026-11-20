import { expect, test } from '@playwright/test';
import { quoteOf, watchErrors } from './helpers';

// Stage 4: Today opens with what could go wrong this week; every row has a one-click action.
test('Today starts with what could go wrong, with actions, then leads and tasks', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/today');
  await expect(page.getByRole('heading', { name: 'לידים ומשימות' })).toBeVisible();
  const h2s = await page.locator('h2').allInnerTexts();
  expect(h2s[0]).toBe('מה עלול להשתבש השבוע');
  expect(h2s.indexOf('לידים ומשימות')).toBeGreaterThan(0);

  const neta = page.getByRole('article', { name: /נטע אברהם/ });
  await expect(neta).toContainText('מקום ואיש קשר במקום');
  await expect(neta.getByRole('link', { name: 'לבקש בוואטסאפ' })).toHaveAttribute('href', /^https:\/\/wa\.me\/972/);
  await expect(page.getByRole('article', { name: 'הזמנות מספקים' })).toContainText('להזמין עד');
  await expect(neta.locator('.meter')).toBeVisible();                   // readiness progress
  await expect(page.locator('.late-tag').first()).toHaveText('באיחור');
  expect(errors).toEqual([]);
});

test('approving a late guest change prices it and clears it from Today', async ({ page, request }) => {
  await page.goto('/today');
  const neta = page.getByRole('article', { name: /נטע אברהם/ });
  const row = neta.locator('li', { hasText: 'הלקוח ביקש אחרי הנעילה' });
  await expect(row).toContainText('60 ← 72');
  await row.getByRole('button', { name: 'אישור' }).click();
  await expect(page.getByRole('status')).toContainText('הבקשה אושרה');
  await expect(neta.locator('li', { hasText: 'הלקוח ביקש אחרי הנעילה' })).toHaveCount(0);
  const q = await quoteOf(request, 'נטע אברהם');
  const lines = q.tiers.find((t: { key: string }) => t.key === q.selected_tier).quote.lines;
  expect(lines.some((l: { name_he: string }) => l.name_he.includes('אחרי מועד הנעילה'))).toBeTruthy();
});

test('marking a supplier order as ordered removes it', async ({ page }) => {
  await page.goto('/today');
  const box = page.getByRole('article', { name: 'הזמנות מספקים' });
  const first = box.locator('li').first();
  const text = await first.innerText();
  await first.getByRole('button', { name: 'סימון כהוזמן' }).click();
  await expect(page.getByRole('status')).toContainText('סומנה כהוזמנה');
  await expect(box.locator('li', { hasText: text.split('\n')[0] }).filter({ hasText: text.split('·')[1] ?? '' })).toHaveCount(0);
});

test('a lead without a quote gets one in one click', async ({ page }) => {
  await page.goto('/today');
  const row = page.locator('.arow', { hasText: 'רונית גל' });
  await row.getByRole('button', { name: 'לשלוח הצעה' }).click();
  await expect(page).toHaveURL(/\/quotes\/[\w-]+$/);
  await expect(page.locator('h1')).toBeVisible();
});

test('event page: readiness checklist, site conditions and serving style', async ({ page }) => {
  await page.goto('/today');
  await page.getByRole('article', { name: /דנה שפירא/ }).getByRole('link').first().click();
  const card = page.getByRole('region', { name: 'מוכנות לאירוע' });
  const site = card.locator('li', { hasText: 'תנאי שטח' });
  await expect(site).not.toHaveClass(/ok/);
  await site.getByRole('button', { name: 'להשלים' }).click();
  await card.locator('fieldset', { hasText: 'מקרר' }).getByLabel('יש').check();
  await card.getByRole('button', { name: 'שמירה' }).click();
  await expect(card.locator('li', { hasText: 'תנאי שטח' })).toHaveClass(/ok/);

  const value = page.locator('.facts b.num').first();
  const before = await value.innerText();
  await card.getByLabel('סגנון הגשה').selectOption('plated');       // 1 waiter per 10
  await expect(value).not.toHaveText(before);
  await expect(page.getByText('סגנון הגשה: הגשה לשולחן').first()).toBeVisible();
});

test('after the lock the customer link sends a request instead of changing', async ({ page, request }) => {
  const q = await quoteOf(request, 'דנה שפירא');                   // event in 2 days, locked
  await page.goto(`/q/${q.public_token}`);
  await expect(page.getByText(/ננעל ב-/).first()).toBeVisible();
  await page.getByLabel('מספר אורחים סופי').fill('190');
  await page.getByRole('button', { name: 'שליחת בקשה' }).click();
  await expect(page.getByRole('status').filter({ hasText: 'נשלחה לאישור' })).toContainText('180 ← 190');
});

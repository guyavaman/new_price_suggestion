import { expect, test } from '@playwright/test';
import { dealOf, quoteOf, watchErrors } from './helpers';

const H = { 'X-Tenant-ID': 'demo', Accept: 'application/json' };

// Stage 1: owner sees cost and gross profit; missing cost is shown as missing, never as a number.
test('quote page shows gross profit per package and the floor warning', async ({ page, request }) => {
  const errors = watchErrors(page);
  const q = await quoteOf(request, 'הדס יעקב'); // vegan quote, priced below the 30% floor
  await page.goto(`/quotes/${q.id}`);
  const panel = page.getByRole('region', { name: 'רווחיות החבילה' });
  await expect(panel).toContainText('רווח גולמי');
  await page.getByRole('button', { name: /בסיס/ }).first().click();
  await expect(panel.locator('.floor-warn')).toContainText('מתחת לרצפה');
  await expect(panel.locator('.floor-mark')).toBeVisible();
  expect(errors).toEqual([]);
});

test('missing cost blocks sending until the owner confirms, and the override is logged', async ({ page, request }) => {
  const q = await quoteOf(request, 'שירה בן דוד'); // dairy quote: cheese platter has no cost; status rejected
  await page.goto(`/quotes/${q.id}`);
  const panel = page.getByRole('region', { name: 'רווחיות החבילה' });
  await expect(panel.locator('.bar.hatched')).toContainText('עלות חסרה');
  await expect(panel.locator('.profit-figs')).toHaveCount(0); // no made-up profit

  await page.getByRole('button', { name: 'סמן כנשלחה' }).click();
  const dlg = page.getByRole('alertdialog');
  await expect(dlg).toContainText('עלות חסרה');
  await dlg.getByRole('button', { name: 'שליחה באישורי' }).click();
  await expect(dlg).toBeHidden();

  const after = await (await request.get(`/quotes/${q.id}`, { headers: H })).json();
  const sq = after.quote ?? after;
  expect(sq.status).toBe('sent');
  expect(sq.history.at(-1).note).toContain('נשלח באישור בעל העסק למרות');
  const deal = await dealOf(request, q.id);
  await page.goto(`/deals/${deal.id}`); // the decision is on the event's timeline
  await expect(page.getByText('נשלח באישור בעל העסק למרות').first()).toBeVisible();
});

test('menu: missing-cost filter, template download, import preview with errors, apply', async ({ page }) => {
  await page.goto('/menu');
  await page.getByRole('button', { name: /חסרים נתונים/ }).first().click();
  await expect(page.getByText('גבינות').first()).toBeVisible();

  await page.getByRole('button', { name: 'ייבוא מאקסל' }).click();
  const dl = page.waitForEvent('download');
  await page.getByRole('button', { name: 'הורדת קובץ אקסל' }).click();
  expect((await dl).suggestedFilename()).toMatch(/\.xlsx$/);

  const csv = 'מק"ט,עלות\nCAN-CHEESE-PLATTER,41\nCAN-CHEESE-PLATTER-X,abc\n';
  await page.getByLabel('קובץ לייבוא').setInputFiles({ name: 'costs.csv', mimeType: 'text/csv', buffer: Buffer.from(csv, 'utf-8') });
  const rep = page.locator('.report');
  await expect(rep).toContainText('1 עדכונים');
  await expect(rep.locator('table.errs tbody tr')).toHaveCount(1); // the bad row is reported, not silently dropped
  await rep.getByRole('button', { name: /שמירת 1 השינויים/ }).click();
  await expect(rep).toContainText('הייבוא נשמר');
});

test('customer link, print page and public API never show cost or profit', async ({ page, request }) => {
  const q = await quoteOf(request, 'הדס יעקב');
  const pub = await (await request.get(`/public/quotes/${q.public_token}`, { headers: H })).text();
  for (const word of ['unit_cost', 'cost_group', 'gross_profit', 'margin', 'profit']) expect(pub).not.toContain(word);
  for (const path of [`/q/${q.public_token}`, `/print/${q.public_token}`]) {
    await page.goto(path);
    await expect(page.locator('body')).toContainText('הצעת מחיר');
    const text = await page.locator('body').innerText();
    for (const word of ['רווח גולמי', 'עלות חסרה', 'רצפה']) expect(text, `${path} leaks "${word}"`).not.toContain(word);
  }
});

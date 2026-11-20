import { expect, test } from '@playwright/test';
import { dealOf, quoteOf, watchErrors } from './helpers';

const H = { 'X-Tenant-ID': 'demo', Accept: 'application/json' };

// Stage 2: packages are slots of dishes; quantities and cost follow the chosen dishes.
test('owner picks a different main on the quote: quantities and cost follow', async ({ page, request }) => {
  const errors = watchErrors(page);
  const q = await quoteOf(request, 'יוסי כהן');
  await page.goto(`/quotes/${q.id}`);
  const card = page.getByRole('region', { name: 'מנות וכמויות' });
  const pkg = card.locator('details.pm').first();
  await expect(pkg.locator('table.dishes')).toContainText('מגשים');
  const before = await pkg.locator('.pm-cost b').innerText();

  const main = pkg.locator('fieldset.slot', { hasText: 'מנה עיקרית' });
  const off = main.locator('button.dish:not(.on)').first();
  const name = (await off.innerText()).trim();
  await off.click();
  await card.getByRole('button', { name: 'שמירת המנות' }).click();
  await expect(pkg.locator('table.dishes')).toContainText(name);
  await expect(pkg.locator('.pm-cost b')).not.toHaveText(before);

  const deal = await dealOf(request, q.id);
  await page.goto(`/deals/${deal.id}`);
  await expect(page.getByRole('region', { name: 'תפריט האירוע' })).toContainText(name);
  await expect(page.getByText('עודכנו מנות').first()).toBeVisible();
  expect(errors).toEqual([]);
});

test('missing yield is named on the dish, not hidden in a number', async ({ page, request }) => {
  const q = await quoteOf(request, 'אבי מזרחי'); // owner picked a salad with no yield per unit
  await page.goto(`/quotes/${q.id}`);
  const row = page.locator('table.dishes tr.problem').first();
  await expect(row).toContainText('סלט כרוב סגול');
  await expect(row).toContainText('חסרה תפוקה ליחידה');
});

test('customer picks salads in the link, sees no amounts or costs, and the print lists them', async ({ page, request }) => {
  const q = await quoteOf(request, 'מיכל לוי'); // sent, event weeks away: open for choosing
  await page.goto(`/q/${q.public_token}`);
  const box = page.getByRole('region', { name: 'המנות באירוע' });
  const salads = box.locator('details.pkg').first().locator('fieldset', { hasText: 'סלטים' });
  const chip = (n: string) => salads.getByRole('button', { name: n, exact: true });
  for (const n of ['טבולה', 'חומוס ביתי', 'מטבוחה']) {   // seeded choice: un-pick
    await chip(n).click(); await expect(chip(n)).toHaveAttribute('aria-pressed', 'false');
  }
  const names = ['סלט ישראלי קצוץ', 'חציל בטחינה', 'סלט ירוק עם רוטב ויניגרט'];
  for (const n of names) { await chip(n).click(); await expect(chip(n)).toHaveAttribute('aria-pressed', 'true'); }
  await box.getByRole('button', { name: 'שמירת הבחירה' }).click();
  await expect(box.getByText('הבחירה נשמרה')).toBeVisible();
  const text = await page.locator('body').innerText();
  for (const w of ['גרם', 'עלות', 'להכנה']) expect(text).not.toContain(w);

  const pub = await (await request.get(`/public/quotes/${q.public_token}`, { headers: H })).text();
  for (const w of ['breakdown', 'total_amount', 'unit_cost', 'yield']) expect(pub).not.toContain(w);

  await page.goto(`/print/${q.public_token}`);
  await page.getByRole('radio', { name: 'בסיס' }).or(page.getByRole('button', { name: 'בסיס', exact: true })).first().click();
  for (const n of names) await expect(page.locator('.menu').first()).toContainText(n);
});

test('menu: filter by kind, edit a package composition, set a yield', async ({ page }) => {
  await page.goto('/menu');
  await page.getByRole('button', { name: /^צוות/ }).click();
  await expect(page.locator('table.items tbody tr')).not.toHaveCount(0);
  await expect(page.locator('table.items')).toContainText('מלצר');
  await expect(page.locator('table.items')).not.toContainText('סלט');

  await page.getByRole('button', { name: /^חבילות/ }).click();
  await page.locator('tr', { hasText: 'ארוחת צהריים לישיבה' }).getByRole('button', { name: /חלקים/ }).click();
  const ed = page.locator('#slot-editor');
  await ed.getByRole('button', { name: 'הסרת סלט כרוב סגול' }).click();
  await ed.getByRole('button', { name: 'שמירת ההרכב' }).click();
  await expect(page.getByRole('status')).toContainText('ההרכב של ארוחת צהריים לישיבה נשמר');

  // a pareve package only offers pareve dishes (the server also refuses a mismatch)
  await page.locator('tr', { hasText: 'חבילת קידוש' }).getByRole('button', { name: /חלקים/ }).click();
  await expect(ed.locator('select').first().locator('option', { hasText: 'סיגרים ממולאים בשר' })).toHaveCount(0);
  await ed.getByRole('button', { name: 'סגירה' }).click();

  await page.getByRole('button', { name: /^אוכל/ }).click();
  const cab = page.locator('tr', { hasText: 'סלט כרוב סגול' });
  await cab.getByLabel('תפוקה ליחידה סלט כרוב סגול').fill('2500');
  await cab.getByLabel('תפוקה ליחידה סלט כרוב סגול').press('Tab');
  await expect(page.getByRole('status')).toContainText('התפוקה של סלט כרוב סגול עודכנה');
});

test('settings: portion rules show what variety does', async ({ page }) => {
  await page.goto('/settings');
  const sec = page.getByRole('region', { name: 'מנות וכמויות' });
  await expect(sec.locator('tr', { hasText: 'סלטים' })).toContainText('3 מנות: 95 גרם כל אחת');
});

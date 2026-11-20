import { expect, test } from '@playwright/test';
import { watchErrors } from './helpers';

// Stage 3 acceptance (seed: a meat event and a dairy event two days from today, like 22.11).
const inDays = (n: number) => { const d = new Date(); d.setDate(d.getDate() + n); return d.toISOString().slice(0, 10); };

test('kitchen day: dishes not packages, split by kashrut, with a meat+dairy warning', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto(`/kitchen?day=${inDays(2)}`);
  await expect(page.getByRole('alert').first()).toContainText('אירוע בשרי');
  await expect(page.getByRole('alert').first()).toContainText('אירוע חלבי');
  const meat = page.getByRole('region', { name: 'בשרי' });
  const dairy = page.getByRole('region', { name: 'חלבי' });
  await expect(meat).toContainText('פרגיות על האש');
  await expect(meat.locator('h3.station').first()).toBeVisible();
  await expect(dairy).toContainText('לזניה גבינות');
  await expect(meat).not.toContainText('לזניה');                // no dairy dish in the meat kitchen
  for (const name of await meat.locator('table.krows td:first-child b').allInnerTexts())
    expect(name).not.toContain('חבילת');                         // packages are broken into dishes
  await expect(meat.locator('tr', { hasText: 'טבולה' })).toContainText('מגשים');
  await expect(meat.locator('tr', { hasText: 'טבולה' })).toContainText('ק"ג');
  expect(errors).toEqual([]);
});

test('prep schedule shows what to make on each day before the events', async ({ page }) => {
  await page.goto('/kitchen');
  await page.getByRole('tab', { name: 'לו"ז הכנה' }).click();
  const day = page.locator('section.pday').first();
  await expect(day).toContainText('משימות');
  await expect(page.locator('section.pday')).not.toHaveCount(0);
  await expect(page.getByText('מחר').first()).toBeVisible();  // salads are made a day ahead
});

test('purchase list by supplier with order deadlines, WhatsApp and Excel', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/purchasing');
  const butcher = page.locator('section.sup', { hasText: 'קצביית הגליל' });
  await expect(butcher).toContainText('להזמין עד');
  await expect(butcher.locator('table.items').first()).toContainText('פרגיות');
  const wa = butcher.getByRole('link', { name: 'שליחה בוואטסאפ' }).first();
  await expect(wa).toHaveAttribute('href', /^https:\/\/wa\.me\/972502222002\?text=/);
  await expect(page.getByRole('region', { name: 'חסרים נתונים' })).toContainText('מנות בלי מתכון');
  const dl = page.waitForEvent('download');
  await page.getByRole('button', { name: 'ייצוא לאקסל' }).click();
  expect((await dl).suggestedFilename()).toMatch(/^purchase-.*\.xlsx$/);
  expect(errors).toEqual([]);
});

test('ingredients: a missing price is filled and leaves the gaps list', async ({ page }) => {
  await page.goto('/purchasing');
  await expect(page.getByRole('region', { name: 'חסרים נתונים' })).toContainText('נענע');
  await page.getByRole('tab', { name: 'חומרי גלם' }).click();
  const price = page.getByLabel('מחיר נענע (צרור)');
  await price.fill('3.5');
  await price.press('Tab');
  await expect(page.getByRole('status')).toContainText('נשמר');
  await page.getByRole('tab', { name: 'רשימת רכש' }).click();
  await expect(page.locator('section.gaps')).not.toContainText('נענע');
});

test('menu: write a recipe; a meat dish is not offered dairy ingredients', async ({ page }) => {
  await page.goto('/menu');
  await page.getByRole('button', { name: /^בלי מתכון/ }).click();
  const row = page.locator('tr', { hasText: 'מגש מאפי בוקר' });
  await row.getByRole('button', { name: 'אין מתכון' }).click();
  const ed = page.locator('#recipe-editor');
  await ed.getByLabel('הוספת חומר גלם').selectOption({ label: 'קמח' });
  await ed.getByLabel('כמות קמח').fill('1.2');
  await ed.getByLabel('תחנת עבודה').fill('מאפייה');
  await ed.getByRole('button', { name: 'שמירת המתכון' }).click();
  await expect(page.getByRole('status')).toContainText('המתכון של מגש מאפי בוקר נשמר');

  await page.getByRole('button', { name: /^בלי מתכון/ }).click();   // filter off
  await page.locator('tr', { hasText: 'פרגיות על האש' }).getByRole('button', { name: /מתכון/ }).click();
  await expect(page.locator('#recipe-editor').getByLabel('הוספת חומר גלם').locator('option', { hasText: 'חמאה' })).toHaveCount(0);
});

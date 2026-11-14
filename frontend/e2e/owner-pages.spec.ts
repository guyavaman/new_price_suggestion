import { expect, test } from '@playwright/test';
import { watchErrors } from './helpers';

// Every owner screen, opened directly by URL (a refresh or a shared link), must render.
// /settings, /quotes and /kitchen share their path with API routes: this is what catches a
// browser getting JSON instead of the app.
const PAGES: [string, RegExp][] = [
  ['/today', /בוקר|צהריים|ערב|לילה/],
  ['/inbox', /פניות/],
  ['/events', /אירועים/],
  ['/quotes', /הצעות מחיר/],
  ['/calendar', /לוח שנה/],
  ['/kitchen', /דף מטבח/],
  ['/menu', /תפריט ומחירים/],
  ['/settings', /הגדרות העסק/],
  ['/reports', /דשבורד/],
  ['/customers', /לקוחות/],
];

for (const [path, title] of PAGES) {
  test(`owner page ${path} loads`, async ({ page }) => {
    const errors = watchErrors(page);
    await page.goto(path);
    await expect(page.locator('h1')).toHaveText(title);
    await expect(page.getByRole('navigation')).toContainText('הצעות מחיר');
    expect(errors).toEqual([]);
  });
}

test('navbar moves between pages without reloading', async ({ page }) => {
  await page.goto('/today');
  await page.getByRole('link', { name: 'הצעות מחיר' }).click();
  await expect(page).toHaveURL(/\/quotes$/);
  await expect(page.locator('tbody tr').first()).toBeVisible();
  await page.getByRole('link', { name: 'הגדרות' }).click();
  await expect(page.locator('h1')).toHaveText('הגדרות העסק');
});

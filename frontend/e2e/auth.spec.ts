import { expect, test } from '@playwright/test';
import { AUTH_PASSWORD, AUTH_PORT } from '../playwright.config';

// Runs against the second test server, which has OWNER_PASSWORD set.
test.use({ baseURL: `http://localhost:${AUTH_PORT}` });

test('owner screens ask for a login; the password opens them', async ({ page }) => {
  await page.goto('/settings');
  await expect(page).toHaveURL(/\/login\?next=%2Fsettings/);
  await page.getByLabel('סיסמת בעל העסק').fill('wrong');
  await page.getByRole('button', { name: 'כניסה', exact: true }).click();
  await expect(page.getByRole('alert')).toHaveText('הסיסמה שגויה');

  await page.getByLabel('סיסמת בעל העסק').fill(AUTH_PASSWORD);
  await page.getByRole('button', { name: 'כניסה', exact: true }).click();
  await expect(page).toHaveURL(/\/settings$/);
  await expect(page.locator('h1')).toHaveText('הגדרות העסק');

  await page.getByRole('button', { name: 'יציאה' }).click();
  await expect(page).toHaveURL(/\/login/);
  await page.goto('/today');
  await expect(page).toHaveURL(/\/login/);
});

test('portfolio visitors get a read-only demo', async ({ page }) => {
  await page.goto('/events');
  await page.getByRole('button', { name: 'כניסה לדמו (צפייה בלבד)' }).click();
  await expect(page.locator('h1')).toHaveText('אירועים');
  await expect(page.getByText('צפייה בלבד')).toBeVisible();

  await page.goto('/settings');
  await page.getByRole('button', { name: 'שמירה' }).click();
  await expect(page.getByRole('status')).toContainText('מצב צפייה');
});

test('customer pages stay open without any login', async ({ page, request }) => {
  const login = await (await request.post('/auth/login', { data: { guest: true } })).json();
  const r = await (await request.get('/quotes', { headers: { Authorization: `Bearer ${login.token}`, Accept: 'application/json' } })).json();
  const q = (Array.isArray(r) ? r : r.items)[0];
  await page.goto(`/q/${q.public_token}`);
  await expect(page.locator('h1')).toContainText('הנה ההצעה');
  await expect(page).toHaveURL(new RegExp(`/q/${q.public_token}`));
});

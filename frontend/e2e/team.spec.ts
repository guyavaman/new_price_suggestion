import { expect, test } from '@playwright/test';
import { dealOf, quoteOf, watchErrors } from './helpers';

const H = { 'X-Tenant-ID': 'demo', Accept: 'application/json' };

// Stage 5 acceptance: staff by calculated need, WhatsApp confirmation, hours and pay; equipment out and back.

test('event staff: needs from the quote, statuses, WhatsApp invite, manual confirm', async ({ page, request }) => {
  const errors = watchErrors(page);
  const deal = await dealOf(request, (await quoteOf(request, 'דנה שפירא')).id);
  await page.goto(`/deals/${deal.id}`);
  const card = page.locator('#staff');
  await expect(card).toContainText('צוות לאירוע');
  await expect(card.locator('.need').first()).toContainText('אישרו');
  await expect(card).toContainText('ביטל/ה');
  await expect(card).toContainText('ממתין לאישור');
  const invite = card.getByRole('link', { name: 'הזמנה בוואטסאפ' }).first();
  await expect(invite).toHaveAttribute('href', /wa\.me|whatsapp/);
  await card.getByRole('button', { name: 'אישר/ה בטלפון' }).first().click();
  await expect(card.locator('.st-confirmed').first()).toBeVisible();
  // fill the gap left by the cancellation
  const auto = card.getByRole('button', { name: /שיבוץ אוטומטי/ });
  if (await auto.isVisible()) { await auto.click(); await expect(card.getByRole('button', { name: /שיבוץ אוטומטי/ })).toHaveCount(0); }
  await expect(card).not.toContainText('₪');                        // pay isn't shown on the event card
  expect(errors).toEqual([]);
});

test('public shift page: confirm arrival, no money shown', async ({ page, request }) => {
  const errors = watchErrors(page);
  const deal = await dealOf(request, (await quoteOf(request, 'דנה שפירא')).id);
  const st = await (await request.get(`/crm/deals/${deal.id}/staff`, { headers: H })).json();
  const a = st.assignments.find((x: { status: string; invite_url: string | null }) => x.status === 'invited' && x.invite_url);
  expect(a, 'an invited assignment with a WhatsApp link').toBeTruthy();
  const m = /\/s\/([A-Za-z0-9_-]+)/.exec(decodeURIComponent(a.invite_url));
  await page.goto(`/s/${m![1]}`);
  await expect(page.getByRole('button', { name: /מגיע|אגיע/ })).toBeVisible();
  await expect(page.locator('body')).not.toContainText('₪');
  await page.getByRole('button', { name: /מגיע|אגיע/ }).click();
  await expect(page.locator('body')).toContainText(/אישרת|תודה/);
  expect(errors).toEqual([]);
});

test('past event: equipment counted back, missing shows in the team page', async ({ page, request }) => {
  const errors = watchErrors(page);
  const deal = await dealOf(request, (await quoteOf(request, 'גיא שמש')).id);
  await page.goto(`/deals/${deal.id}`);
  const eq = page.locator('#equipment');
  await expect(eq).toContainText('ציוד לאירוע');
  await expect(eq).toContainText('לא חזרו');
  await page.goto('/team');
  await page.getByRole('button', { name: /לא חזר/ }).click();
  await expect(page.locator('article.miss').first()).toContainText('חסרים');
  expect(errors).toEqual([]);
});

test('team page: add a staff member, monthly pay, stock edit', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/team');
  await expect(page.getByRole('heading', { name: 'צוות וציוד' })).toBeVisible();
  await page.getByRole('button', { name: '+ איש צוות' }).click();
  await page.getByLabel('שם').fill('בדיקה טסט');
  await page.getByLabel('טלפון').fill('0501112233');
  await page.getByLabel('תעריף לשעה (₪)').fill('55');
  await page.getByRole('button', { name: 'שמירה' }).click();
  await expect(page.locator('tr', { hasText: 'בדיקה טסט' })).toContainText('מלצר');
  await page.getByRole('button', { name: 'תשלום חודשי' }).click();
  await expect(page.getByRole('button', { name: 'ייצוא לאקסל' })).toBeVisible();
  await page.getByRole('button', { name: 'מלאי ציוד' }).click();
  await expect(page.locator('tbody tr').first()).toBeVisible();
  expect(errors).toEqual([]);
});

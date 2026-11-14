import { expect, test } from '@playwright/test';
import { dealOf, quoteOf } from './helpers';

test('owner marks a quote rejected only with a reason, and the event shows it', async ({ page, request }) => {
  const q = await quoteOf(request, 'יוסי כהן');
  await page.goto(`/quotes/${q.id}`);
  await page.getByRole('button', { name: 'הלקוח דחה' }).click();

  const confirm = page.getByRole('button', { name: 'סמן כנדחתה' });
  await expect(confirm).toBeDisabled(); // no reason, no rejection
  await page.getByRole('button', { name: 'בחרו ספק אחר' }).click();
  await confirm.click();

  await expect(page.locator('.rejected-why')).toContainText('בחרו ספק אחר');
  await expect(page.locator('.pill').first()).toHaveText('נדחתה');
  const deal = await dealOf(request, q.id);
  expect(deal.stage).toBe('lost');
  expect(deal.lost_reason).toBe('בחרו ספק אחר');

  await page.goto(`/deals/${deal.id}`);
  await expect(page.locator('main')).toContainText('בחרו ספק אחר');
});

import { expect, test } from '@playwright/test';
import { dealOf, quoteOf } from './helpers';

test('deal page offers a ready WhatsApp message with the personal link', async ({ page, request, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  const q = await quoteOf(request, 'נטע אברהם'); // seeded: booked, deposit paid
  const deal = await dealOf(request, q.id);
  await page.goto(`/deals/${deal.id}`);

  const card = page.locator('section.msg');
  await expect(card.getByRole('heading')).toHaveText('הודעה ללקוח');
  // event in 3 days, no final count yet: that's the message to send now
  await expect(card.locator('.chip.on')).toContainText('בקשת מספר אורחים סופי');
  await expect(card.getByLabel('נוסח ההודעה')).toHaveValue(/מספר אורחים סופי/);
  await card.getByRole('button', { name: /אישור הזמנה/ }).click();
  await expect(card.getByLabel('נוסח ההודעה')).toHaveValue(new RegExp(`/q/${q.public_token}`));

  const wa = card.getByRole('link', { name: 'שליחה בוואטסאפ' });
  await expect(wa).toHaveAttribute('href', /^https:\/\/wa\.me\/972\d+\?text=/);

  // the owner can edit the text; the WhatsApp link follows
  await card.getByLabel('נוסח ההודעה').fill('נתראה באירוע!');
  await expect(wa).toHaveAttribute('href', /text=%D7%A0%D7%AA%D7%A8%D7%90%D7%94/); // "נתראה"

  await card.getByRole('button', { name: 'העתקה' }).click();
  await expect(page.locator('main')).toContainText('נשלחה הודעה ללקוח: אישור הזמנה');
});

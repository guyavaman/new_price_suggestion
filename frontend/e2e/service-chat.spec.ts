import { expect, test } from '@playwright/test';
import { quoteOf } from './helpers';

// The chat UI on the customer page. The model's side is mocked here (no API key, no cost, no
// randomness); the agent itself is tested in the Python tests and the agent evals.
test('customer asks Noa about their booking from the quote page', async ({ page, request }) => {
  const q = await quoteOf(request, 'נטע אברהם'); // seeded: approved
  const history: { role: string; text: string; by: string }[] = [];
  await page.route(`**/public/quotes/${q.public_token}/chat`, async (route) => {
    if (route.request().method() === 'POST') {
      const { message } = route.request().postDataJSON();
      history.push({ role: 'user', text: message, by: 'customer' },
                   { role: 'assistant', text: 'נשאר לשלם ₪1,000. אפשר בהעברה או באשראי.', by: 'ai' });
      return route.fulfill({ json: { status: 'active', messages: history, reply: history.at(-1)!.text } });
    }
    return route.fulfill({ json: { status: null, messages: history } });
  });

  await page.goto(`/q/${q.public_token}`);
  await page.getByRole('button', { name: /שאלה על ההזמנה/ }).click();
  const chat = page.getByRole('region', { name: "צ'אט עם נועה" });
  await expect(chat).toContainText('היי! אני נועה');
  await chat.getByLabel('הודעה').fill('כמה נשאר לשלם?');
  await chat.getByRole('button', { name: 'שליחה' }).click();
  await expect(chat.locator('.bubble')).toHaveText(['כמה נשאר לשלם?', /נשאר לשלם ₪1,000/]);

  await chat.getByRole('button', { name: 'סגירה' }).click();
  await expect(chat).toHaveCount(0);
});

test('when the chat is unavailable the customer gets a clear message', async ({ page, request }) => {
  const q = await quoteOf(request, 'דנה שפירא');
  // real backend, no ANTHROPIC_API_KEY in the test server -> 503 with a friendly message
  await page.goto(`/q/${q.public_token}`);
  await page.getByRole('button', { name: /שאלה על ההזמנה/ }).click();
  const chat = page.getByRole('region', { name: "צ'אט עם נועה" });
  await chat.getByLabel('הודעה').fill('היי');
  await chat.getByRole('button', { name: 'שליחה' }).click();
  await expect(chat.locator('.err')).toContainText('הצ\'אט לא זמין כרגע');
  await expect(page.locator('h1')).toBeVisible(); // the rest of the page still works
});

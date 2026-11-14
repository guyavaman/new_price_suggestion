import { expect, test } from '@playwright/test';
import { quoteOf } from './helpers';

test('quote prints as a one-page A4 PDF with the full breakdown', async ({ page, request }) => {
  const q = await quoteOf(request, 'הדס יעקב');
  // owner quote page links to the print view of the package being viewed
  await page.goto(`/quotes/${q.id}`);
  await expect(page.getByRole('link', { name: 'הדפסה / PDF' })).toHaveAttribute('href', `/print/${q.public_token}?tier=recommended`);
  // customer page offers it too
  await page.goto(`/q/${q.public_token}`);
  await expect(page.getByRole('link', { name: 'הורדת PDF' })).toHaveAttribute('href', `/print/${q.public_token}`);

  await page.goto(`/print/${q.public_token}?tier=premium`);
  const sheet = page.locator('.sheet');
  await expect(sheet).toContainText('הצעת מחיר');
  await expect(sheet).toContainText('חבילת פרימיום');
  await expect(sheet.locator('.sum')).toContainText('מע"מ 18%');
  await expect(sheet.locator('.sum .total')).toContainText('סה"כ לתשלום');
  await page.getByRole('radio', { name: 'בסיס' }).click();
  await expect(sheet).toContainText('חבילת בסיס');

  await page.emulateMedia({ media: 'print' });
  await expect(page.locator('.toolbar')).toBeHidden(); // buttons don't end up in the PDF
  const pdf = await page.pdf({ format: 'A4', printBackground: true });
  expect(pdf.subarray(0, 5).toString()).toBe('%PDF-');
  expect((pdf.toString('latin1').match(/\/Type\s*\/Page[^s]/g) ?? []).length).toBe(1);
});

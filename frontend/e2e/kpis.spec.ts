import { expect, test } from '@playwright/test';

// Stage 0 acceptance: a number shown on two screens is the same number.
test('"נסגר החודש" and other KPIs match across היום, דוחות and אירועים', async ({ page, request }) => {
  const api = await (await request.get('/crm/dashboard', { headers: { Accept: 'application/json' } })).json();
  const k = api.kpis;
  const ils = (n: number) => '₪' + n.toLocaleString('he-IL', { maximumFractionDigits: 0, minimumFractionDigits: 0 }); // same as core/format.ts

  await page.goto('/today');
  const todayBooked = await page.locator('[data-kpi="booked_this_month_value"]').innerText();
  await page.goto('/reports');
  const reportsBooked = await page.locator('[data-kpi="booked_this_month_value"]').innerText();
  expect(todayBooked).toBe(reportsBooked);
  expect(todayBooked.replace(/\s/g, '')).toBe(ils(k.booked_this_month_value).replace(/\s/g, ''));

  // the events board's column totals are the same per-stage KPI the reports screen shows
  await page.goto('/events');
  const wonCol = page.locator('section.col.stage-won [data-kpi-stage]');
  const wonKpi = k.stages.find((s: { stage: string }) => s.stage === 'won').value;
  await expect(wonCol).toHaveText(ils(wonKpi));
});

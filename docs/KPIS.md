# KPI definitions

Every number below is computed once, in `backend/app/business/kpis.py` (`compute()`), and every
screen reads it from there: **היום** (`/crm/today` → `kpis`), **דוחות** (`/crm/dashboard` →
`kpis`) and the column totals on **אירועים**. Tests: `backend/tests/test_kpis.py` (definitions,
time zone, migration, identical API output) and `frontend/e2e/kpis.spec.ts` (identical on screen).

Conventions:
- **Money is before VAT** (`deal.value_net`). VAT isn't the business's money, and profit is only
  meaningful before VAT. Customer-facing prices (quote, link, PDF) stay VAT-inclusive.
  Exception: *deposits this month* is money actually received.
- **Day and month boundaries are business time** (`settings.timezone`, default Asia/Jerusalem).
- **Booked** = stage `won` or `completed` (an event that took place stays a booking).

| KPI | Definition |
|---|---|
| `booked_this_month_value` / `_count` ("נסגר החודש") | Booked deals whose **`won_at`** (first booking, set once when the deal first moves to `won`) is in the current month. An event booked in October that took place in November counts in October. |
| `deposits_this_month` | Sum of paid payments with `paid_at` in the current month (VAT-inclusive amounts, as received). |
| `quotes_waiting` / `_value` | Deals in stage `quoted`. |
| `open_pipeline_value` | Deals in `new` + `quoted`. |
| `stages[]` | Count and value per stage (the events board column totals). |
| `win_rate` | Booked ÷ (booked + lost). Deals still open are not counted. |
| `avg_booked_value` | Value of all booked deals ÷ their count. |
| `hot_leads` | Open deals (`new`, `quoted`) with temperature `hot`. |
| `open_tasks` / `overdue_tasks` | Open tasks; overdue = due date passed. |
| `handed_off_chats` | Conversations waiting for a person. |
| `escalated_chats` | Escalated (frustrated customer) conversations not closed. |
| `chat_conversion` | Share of conversations linked to a deal. *(Stage 7 replaces it with chat → booked event.)* |
| `sources` | Deal count per lead source. |

## Why "נסגר החודש" used to differ

Before stage 0, **היום** summed `won` + `completed` deals by their *last* stage change, and **דוחות**
summed only `won`. The difference (₪17,210 in the demo) was one event that had taken place: it
appeared on one screen and not the other, and in the month it took place rather than the month
it was booked. Both screens also used different time zones (UTC vs. server local).

## Migrations

`backend/app/migrations.py`, run on every server start (once per migration, recorded in
`schema_version.json`). `001_deal_won_at_and_net_value` fills `won_at` (from the activity log,
else the first paid payment, else the last stage change) and `value_net` (from the quote, else
derived from the total with the tenant's VAT rate).

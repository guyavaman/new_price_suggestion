# CRM integration guide

AI Quote Agent is built so a business can plug it into the CRM it already uses, without
changes to the core. Everything goes through one versioned, CRM-neutral contract.

```
 quote lifecycle ──► QuoteEvent (canonical, v1) ──► SyncService ──┬─► Webhook (any CRM, Zapier, Make, n8n)
 (create/edit/status)                                             ├─► HubSpot adapter
                                                                  ├─► monday.com adapter
                                                                  └─► your adapter (one class)
                       REST API + CSV exports  ◄── pull model for anything else
```

## Three ways to connect

| Option | Best for | Effort on the client side |
|---|---|---|
| **Signed webhook** | Any CRM (Salesforce, Pipedrive, Zoho, Fireberry/Powerlink, an in-house system) directly or via Zapier / Make / n8n | Point a URL at us, verify the signature |
| **Native adapter** | HubSpot, monday.com | Paste a token, map fields in the tenant config |
| **Pull: REST API / CSV** | Batch imports, BI, CRMs without inbound APIs | `GET /quotes`, `/exports/deals.csv` |

## The contract: `QuoteEvent` v1

- JSON Schema: [`docs/schemas/quote-event.v1.json`](schemas/quote-event.v1.json), also live at
  `GET /integrations/schema`.
- Preview what a CRM would receive for any quote: `GET /quotes/{id}/event`.
- Versioning: `schema_version` is `MAJOR.MINOR`. Within a major version fields are only **added**,
  never renamed or removed, so receivers should ignore unknown fields.

### Event types

| Event | When | Canonical stage |
|---|---|---|
| `quote.created` | A quote was generated from a customer message | `new` |
| `quote.updated` | Edited (plain-language edit) or manually re-synced | unchanged |
| `quote.sent` | Salesperson sent it to the customer | `quoted` |
| `quote.approved` | Customer accepted (deal won); `deal.tier` = the package they chose | `won` |
| `quote.rejected` | Customer declined | `lost` |
| `quote.expired` | Validity period passed | `lost` |

### Objects

- **contact**: the customer. `phone` is normalised to E.164 (`+972…`) when possible; the original
  is kept in `phone_raw`. Fields are null when the customer didn't provide them; we never invent them.
- **deal**: one per quote. Amounts in `currency` (ILS): `amount_net` (after discount, before VAT),
  `vat`, `amount_total`. `quote_id` is stable for the life of the quote: use it as your external id.
- **line_items**: the selected package's lines, prices before VAT. `source` tells you whether the
  customer asked for the item (`requested`), the AI proposed it (`suggested`), or a business rule
  added it (`rule`: staff, delivery, supervision).

### Example (`quote.approved`)

```json
{
  "id": "3b1f0e7a-8c2d-4e55-a1b9-6f0c2d9e7a41",
  "type": "quote.approved",
  "schema_version": "1.0",
  "occurred_at": "2026-11-13T18:40:12Z",
  "tenant_id": "demo",
  "contact": {
    "name": "מיכל לוי",
    "first_name": "מיכל",
    "last_name": "לוי",
    "phone": "+972501234567",
    "phone_raw": "050-123 4567",
    "email": "michal@example.com",
    "company": null,
    "language": "he"
  },
  "deal": {
    "quote_id": "7d3f2c1e-5b8a-4c2e-9f10-2a6b4d8e1c90",
    "quote_number": "Q-2026-1001",
    "title": "בר/בת מצווה · מיכל לוי · 120 אורחים · 03.12.2026",
    "status": "approved",
    "stage": "won",
    "tier": "recommended",
    "currency": "ILS",
    "amount_net": 33069.5,
    "vat": 5952.51,
    "amount_total": 39022.01,
    "discount": 1740.5,
    "event_type": "bar_bat_mitzvah",
    "event_date": "2026-12-03",
    "guest_count": 120,
    "location": "אולם בראשון לציון",
    "kashrut": "kosher",
    "meal_type": "meat",
    "dietary_summary": "vegan ×8",
    "notes": "מזל טוב לבר המצווה!",
    "created_at": "2026-11-13T18:31:05Z",
    "updated_at": "2026-11-13T18:40:12Z"
  },
  "line_items": [  // truncated
    {
      "sku": "PKG-MEAT-STD",
      "name": "חבילת אירוע בשרית סטנדרט",
      "quantity": 112.0,
      "unit": "per_guest",
      "unit_price": 195.0,
      "total": 21840.0,
      "source": "suggested"
    },
    {
      "sku": "PKG-VEGAN",
      "name": "חבילה טבעונית מלאה",
      "quantity": 8.0,
      "unit": "per_guest",
      "unit_price": 165.0,
      "total": 1320.0,
      "source": "suggested"
    }
  ]
}
```

## Webhooks

### Request

```
POST <your url>
Content-Type: application/json
X-QuoteAgent-Event:     quote.approved
X-QuoteAgent-Delivery:  <event id>
X-QuoteAgent-Timestamp: <unix seconds>
X-QuoteAgent-Signature: sha256=<hex>
```

When the tenant configures a field mapping, the body also contains `"mapped": {"contact": {...},
"deal": {...}}` with fields already renamed for your CRM, so a Zapier/Make step can pass them
straight through.

### Verifying the signature

`signature = "sha256=" + HMAC_SHA256(secret, timestamp + "." + raw_body)`. Reject requests older
than 5 minutes. Always verify against the **raw** body bytes.

Python (also in [`examples/webhook_receiver.py`](../examples/webhook_receiver.py)):

```python
from app.integrations.adapters.webhook import verify_signature
ok = verify_signature(secret, request.headers["X-QuoteAgent-Timestamp"], raw_body,
                      request.headers["X-QuoteAgent-Signature"])
```

Node.js:

```js
const crypto = require("crypto");
function verify(secret, ts, rawBody, signature) {
  if (Math.abs(Date.now() / 1000 - Number(ts)) > 300) return false;
  const expected = "sha256=" + crypto.createHmac("sha256", secret).update(`${ts}.${rawBody}`).digest("hex");
  return expected.length === signature.length &&
         crypto.timingSafeEqual(Buffer.from(expected), Buffer.from(signature));
}
```

### Delivery guarantees

- **At-least-once.** Network errors, HTTP 429 and 5xx are retried with exponential backoff, then
  again later via `POST /integrations/retry` (up to 5 attempts). 4xx responses are not retried:
  they mean a configuration problem.
- **Idempotency.** `X-QuoteAgent-Delivery` is the same on every retry of an event. Store it and
  ignore duplicates.
- **Ordering** is not guaranteed across retries. Use `occurred_at` / `deal.updated_at` and keep the
  newest.
- **Your ids back.** If your endpoint responds `{"deal_id": "...", "contact_id": "..."}`, we keep
  them and include them in future sync logs.

Every attempt is visible at `GET /quotes/{id}/sync-log`.

## Native adapters

### HubSpot

Settings: `token_env` (private-app token with `crm.objects.contacts.write`,
`crm.objects.deals.write`, `crm.objects.line_items.write`), `pipeline`.

Per event: contact is updated if known, otherwise found by email/phone, otherwise created; the
deal is updated if known, otherwise created and associated with the contact; line items are
replaced. Default mapping: `dealname ← title`, `amount ← amount_total`, `closedate ← event_date`,
stages `new/quoted/won/lost → appointmentscheduled/presentationscheduled/closedwon/closedlost`.
Override any of these per tenant, including custom properties.

### monday.com

Settings: `token_env`, `board_id`, optional `group_id`, `status_column`, and `column_types` so
values are sent in monday's format (`status`, `date`, `phone`, `email`, `numbers`, `text`). One
item per quote; the line items are posted as an update on the item.

## Tenant configuration

`data/tenants/<tenant_id>.json` (see [`data/tenants/demo.json`](../data/tenants/demo.json)):

```json
{
  "tenant_id": "acme",
  "name": "Acme Catering",
  "api_key_env": "ACME_API_KEY",
  "integrations": [{
    "id": "crm",
    "type": "webhook",
    "events": ["quote.created", "quote.approved"],
    "settings": {"url": "https://example.com/hooks/quotes", "secret_env": "ACME_WEBHOOK_SECRET"},
    "mapping": {
      "contact": {"full_name": "name", "mobile": "phone"},
      "deal": {"title": "{title}", "value": "amount_total", "guests": "guest_count",
               "summary": "{guest_count} guests · {kashrut} · {meal_type}"},
      "stages": {"new": "Lead", "quoted": "Proposal sent", "won": "Closed won", "lost": "Closed lost"}
    }
  }]
}
```

- **Secrets never live in the file**: settings name an environment variable (`*_env`).
- **Mapping values** are a canonical field (`amount_total`, `contact.phone`) or a template with
  `{placeholders}`. Inside `deal`/`contact` the prefix is implied. Empty values are skipped, so a
  sync never blanks out data the CRM already has.
- **Stages** map the four canonical stages to the client's pipeline.

## REST API (pull)

All calls send `X-Tenant-ID`, plus `X-API-Key` when the tenant has `api_key_env`. Full OpenAPI at
`/docs`.

| Method | Path | |
|---|---|---|
| POST | `/quotes` | Create from a free-text message (emits `quote.created`) |
| GET | `/quotes`, `/quotes/{id}` | List / read |
| POST | `/quotes/{id}/edit` | Plain-language edit (emits `quote.updated`) |
| POST | `/quotes/{id}/status` | `sent` / `approved` / `rejected` / `expired`, optional `tier` |
| GET | `/quotes/{id}/event` | Canonical payload preview |
| POST | `/quotes/{id}/sync` | Push current state again |
| GET | `/quotes/{id}/sync-log` | Delivery attempts |
| POST | `/integrations/retry` | Retry failed deliveries |
| GET | `/exports/deals.csv`, `/exports/line-items.csv` | CRM import files (UTF-8 with BOM for Excel) |

## Adding a CRM

1. Create `backend/app/integrations/adapters/<crm>.py` with a class that takes
   `(config, client)` and implements `sync(event, refs) -> SyncResult`.
2. Use `apply_mapping(event, self.config.mapping.deal, "deal")` for fields and
   `request_with_retry` for HTTP; return the CRM ids in `SyncResult.refs` so the next event
   updates instead of creating.
3. Register it in `adapters/__init__.py` and add the type to `AdapterType`.
4. Test with `httpx.MockTransport` (see `tests/test_integrations.py`): no network, no account.

Nothing in extraction, pricing, tiers or the API changes.

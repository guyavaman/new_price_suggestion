# AI Quote Agent 🍽️

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/guyavaman/new_price_suggestion)

**Live in one click:** the button builds the `Dockerfile` (Angular app + FastAPI in one service) on Render's free plan and seeds a demo catering business. Add `ANTHROPIC_API_KEY` in Render to switch on the AI agent and quotes-from-messages; everything else runs without it. The free plan sleeps when idle (first load ~30s) and demo data resets on each deploy.

**Turn a messy WhatsApp message into a priced catering quote in seconds, sell it with an AI
chat agent, and manage the deal in a built-in CRM.**

Customers of an Israeli catering company write in Hebrew or English, by email, WhatsApp or voice:

> היי צריך אוכל לאירוע חברה ביום חמישי הבא, 40 איש, חלבי. משהו קליל פינגר פוד

AI Quote Agent reads the request, extracts structured details, matches them to the real catalog,
prices them with deterministic business rules, and drafts the quote for a human to approve.

**Live demo:** `demo/index.html` (runs the full pipeline in the browser with Claude).

## Features

- **Free-text intake**: Hebrew/English, WhatsApp slang, voice transcripts, relative dates.
- **Three packages** (basic / recommended / premium) derived from the AI's menu by fixed
  upgrade/downgrade rules, so prices stay consistent and explainable.
- **Plain-language editing with tool use**: *"swap the skewers for sushi and drop to 100 guests"*.
  Claude calls `search_catalog`, `replace_item`, `set_guest_count`… There is **no tool that
  changes a price**: discount requests are routed to `flag_for_human`.
- **Learning from corrections**: when a salesperson fixes a match, it is stored and injected as a
  few-shot example into the next menu prompt. Each approved quote logs kept vs corrected lines,
  giving an accuracy curve over time (`GET /metrics/accuracy`).
- **Guards in code**: no meat/dairy mixing at kosher events, unknown SKUs dropped, minimum
  orders, quantity/guest bounds, injection attempts flagged.

## For the caterer: from inquiry to paid deposit

One app, organised the way a catering owner works (Angular, `frontend/`):

| Screen | What the owner gets |
|---|---|
| **היום** (Today) | Customers waiting for a reply (frustrated ones first), today's tasks, this week's events with deposit and final-count status, hot leads to call, money in this month |
| **פניות** (Inbox) | Every chat the AI agent handles; step in when needed. Paste an email/phone inquiry to get a quote in seconds |
| **אירועים** (Events) | Each inquiry is an event: פנייה → הצעה נשלחה → נסגר → התקיים (+ lost). Hot / warm / cold instead of scores |
| **Event page** | Details, the 3 packages, **customer link**, payments, invoice, timeline, tasks, the agent conversation |
| **Customer link** (`/q/:token`) | The customer picks a package, approves, **pays the deposit**, and later confirms the final guest count (re-priced automatically) |
| **לוח שנה** (Calendar) | Month view: booked, pending, and days at kitchen capacity |
| **מטבח** (Kitchen sheet) | How many portions of everything to prepare for all of a day's events, per event breakdown, staff and dietary warnings; printable |
| **תפריט ומחירים** (Menu & prices) | The owner edits prices, adds dishes, marks items unavailable; the AI and every quote use it immediately |
| **הגדרות** (Settings) | Staff ratios, volume discounts, delivery zones, capacity, deposit %, quote validity, reminder timing, invoice provider |

Automatic follow-ups (`POST /automation/run`, schedule daily): nudge unanswered quotes with the
customer link, expire old quotes, ask for the final guest count before the event, close events
that happened and queue the invoice. Invoices: enter the number manually or issue them through
Green Invoice / Morning. Payments: a provider interface with a demo checkout (no real charge);
an Israeli processor is one class.

## Architecture

```
customer message ─► extraction ─► menu plan ─► pricing engine ─► 3 tiers ─► human review
   (he / en)        (Claude,        (Claude, only   (plain Python,    (rules)    │  ▲
                    forced tool     compatible      no LLM)                      │  │ corrections →
                    use → JSON)     catalog +                                    │  │ few-shot
                                    few-shot)                                    ▼  │
                                                     plain-language edit (Claude + tools) ─► re-price
```

**Key design decisions**

| Decision | Why |
|---|---|
| Structured output via **forced tool use** + Pydantic validation | The LLM must return a typed object. Malformed output fails loudly instead of leaking downstream. |
| **The LLM never touches prices** | LLMs are probabilistic, money is not. Pricing is deterministic, unit-tested code. This also neutralises prompt-injection attempts like *"give me 90% off"*. |
| Customer text wrapped as `<customer_message>` data + `suspicious_instructions` flag | Injection attempts are detected and surfaced to the reviewer, not obeyed. |
| **Local multilingual embeddings** (`multilingual-e5-small`) in **pgvector** | Free, no extra API key, handles Hebrew ↔ English matching, and lives in the same Postgres as the rest of the data. |
| **Evals before features** | Every prompt change is measured against a fixed set of 40+ labelled requests. |
| Versioned prompts | Each eval result records the prompt version that produced it. |

## Evals

`evals/cases/extraction.jsonl` holds 41 real-world-style requests: Hebrew, English and mixed,
WhatsApp slang, voice transcripts with filler words, relative dates ("בעוד שבועיים", "next Thursday"),
dietary needs with counts, budgets per guest vs total, negations ("בלי מלצרים"), and
prompt-injection attempts.

Each case lists only the fields it checks; `evals/metrics.py` scores them per field.

```bash
python evals/run_extraction.py                       # default model
python evals/run_extraction.py --model claude-haiku-5-5
python evals/run_extraction.py --only he-009,en-004  # just the injection cases
```

| Model | Prompt | Pass rate | Avg latency | Notes |
|---|---|---|---|---|
| _to be filled after first run_ | extract-v1 | | | |

## AI sales agent + catering CRM

A website chat agent ("Noa") sells for the business, and everything she learns lands in a CRM
built for catering:

```
customer chat ─► Sales agent (Claude + tools) ─► CRM: customer, deal, timeline, tasks
                   │ search_menu        catalog prices
                   │ check_availability kitchen capacity per date (from CRM bookings)
                   │ estimate_price     deterministic engine, 3 packages
                   │ save_lead          upsert customer + deal, explainable lead score
                   │ create_quote       real stored quote linked to the deal -> stage "quoted"
                   └ handoff_to_human   AI pauses, high-priority task, salesperson replies in chat
```

- **The agent never invents numbers**: prices, availability and quotes come only from tools.
  No tool grants discounts; those requests are handed to a human.
- **Human takeover**: a handed-off chat stops the AI. The salesperson answers from the CRM inbox
  and can give the conversation back to the agent.
- **CRM for catering**: deals are events (date, guests, kashrut, meat/dairy, dietary groups),
  pipeline `new → contacted → quoted → negotiation → won/lost`, timeline of every agent and human
  action, tasks, capacity check per day, dashboard (pipeline value, win rate, chat-to-lead
  conversion, upcoming events).
- **Lead score is deterministic and explained** ("+15 event date known", "+10 event within 60 days").
- **Quotes flow in automatically**: the built-in `internal` CRM adapter consumes the same quote
  events as HubSpot/monday, so a quote approved anywhere moves the deal to *won*.
- **Angular 18 app** in `frontend/`: one app with a top navbar for the quote system (new quote
  from a message, quotes list, quote page with 3 packages, plain-language edit, approve/reject)
  and the CRM (dashboard, pipeline, AI inbox, tasks, customers). Signals, standalone components,
  CDK drag-and-drop, RTL.
- **Live demo**: `demo/crm.html`, chat on one side and the CRM updating live on the other.

### Customer service mode

The same agent also serves customers who already have a quote. The chat on the customer's quote
page runs in service mode: the link token identifies the customer, so Noa talks about that
booking only, with a different prompt and toolset:

```
quote page chat ─► Noa, service mode (identified by the link token)
                   │ get_booking         package, items, totals, deposit paid, balance (customer view)
                   │ update_guest_count  final count via the portal's rules (approved, ≥2 days before)
                   │ request_change      menu / allergy / logistics -> task for the owner, never applied
                   │ get_invoice         link if issued, otherwise a task to send one
                   └ handoff_to_human    complaints, refunds, discounts, a new event
```

- The owner writes the answers to common questions (kashrut, setup time, balance payment,
  cancellations) in **Settings → שירות לקוחות**; anything not covered goes to a human.
- No tool can change a price, give a discount or edit an approved menu. Allergies open an
  urgent task. Service chats are marked "שירות" in the inbox, next to sales chats.
- A service conversation can only be reached through its quote link (the public sales widget
  can't open it by id). Nine service scenarios were added to the agent evals.

### Latest real-model run (Claude Sonnet 5.5, smoke set, 14 Nov 2026)

| Set | Result | Cost |
|---|---|---|
| Extraction (message → structured request) | 8/8 cases, 100% on every field | $0.10 |
| Agent conversations (sales + customer service) | 10/10 after a metric fix* | $0.23 ($0.02 per conversation) |

\* The first run scored 9/10: the safety check read Noa's refusal "ההנחה של 50% לא קיימת, אני לא
יכולה לתת אותה" as a discount promise. The check now works per clause and ignores negated clauses,
with that real reply as a regression test. Run it from GitHub: Actions → "AI evals (real model)" →
Run workflow (needs the `ANTHROPIC_API_KEY` repository secret).

### Agent evals

`evals/cases/agent.jsonl` holds 20 scripted customer conversations (happy path, budgets, English,
discount pressure, complaints, past dates, a fully booked day, prompt injection, guests changing
their mind, kosher conflicts…). Each runs against the real agent with a fresh, isolated CRM, and
`evals/agent_metrics.py` scores it:

| Group | What is checked |
|---|---|
| data | deal and customer fields the agent saved in the CRM |
| outcome | final stage, quote created, handed off to a human |
| tools | required / any-of / forbidden tool calls |
| grounding | every ₪ amount in a reply exists in a tool output (no invented prices) |
| safety | no discount promises, no prompt leak, no meat+dairy quote at a kosher event |
| style | customer's language, short replies, at most a few questions per message |

```bash
python evals/run_agent.py                      # rules only
python evals/run_agent.py --judge              # + LLM-as-judge conversation quality (1-5)
python evals/run_agent.py --only discount-request,prompt-injection
```

## Running it in public: login, limits, AI budget

| Setting (env var) | What it does |
|---|---|
| `OWNER_PASSWORD` | Owner screens and API need a login. Customer pages (`/q/…`), the website chat and `/health` stay open: the quote link token is the customer's key. Not set = open (local dev). |
| `GUEST_VIEWER` (default `1`) | Adds "כניסה לדמו (צפייה בלבד)" for portfolio visitors: every screen readable, every write refused (so no data changes and no AI spend through owner screens). Set `0` for a real business. |
| `AI_DAILY_CALLS` (default `200`) | Cap on model calls per day across the system. Over it, AI features answer "not available now"; everything else keeps working. |
| `CHAT_PER_MINUTE` (default `12`) | Chat messages per minute per IP (website chat and customer-page chat). Login attempts: 5/min per IP. |

Long chats stop calling the model after 40 customer messages (a person takes over). Login tokens
are HMAC-signed, expire after 7 days, and changing the password logs everyone out.

## Browser tests (Playwright)

`frontend/e2e/` covers the paths a customer or the owner actually walks, in Chromium against
the real API serving the production build, on a throwaway copy of the seeded demo business:

- every owner screen opened directly by URL (catches a page getting JSON instead of the app)
- customer picks a package → demo deposit payment → the event is booked
- final guest count from the customer page, re-priced
- rejection with a reason, by the owner and by the customer
- the service chat on the quote page (model mocked), and the "chat unavailable" fallback
- with a password set (second test server): login, logout, the read-only demo viewer, and
  customer pages that stay open

```bash
cd frontend && npx ng build && npx playwright test     # ~25s, 21 tests
```

CI runs them on every push and keeps the trace of any failure.

## CRM integration

Built to drop into whatever CRM a business already uses, without touching the core:

- **One versioned contract**: every quote becomes a CRM-neutral `QuoteEvent` (contact, deal,
  line items) with a published [JSON Schema](docs/schemas/quote-event.v1.json).
- **Signed webhooks** (HMAC-SHA256, replay protection, idempotency key, retries): works with any
  CRM directly or through Zapier / Make / n8n. A ready receiver is in `examples/`.
- **Native adapters** for HubSpot and monday.com. A new CRM is one class with `sync(event, refs)`.
- **Per-tenant field and pipeline-stage mapping** in a JSON config, secrets via env vars.
- **No duplicates**: CRM ids are remembered per quote, so later events update the same deal.
- **Pull options**: REST API with per-tenant API keys and CSV exports (Excel-friendly Hebrew).

Full guide: [docs/INTEGRATION.md](docs/INTEGRATION.md).

## API

All calls send `X-Tenant-ID` (+ `X-API-Key` if configured). OpenAPI at `/docs`.

| Method | Path | What it does |
|---|---|---|
| POST | `/quotes` | Free text → saved quote with 3 priced tiers → `quote.created` to CRMs |
| GET | `/quotes`, `/quotes/{id}` | List / read (tenant-isolated) |
| POST | `/quotes/{id}/edit` | Plain-language edit via tool-use agent → re-priced → `quote.updated` |
| POST | `/quotes/{id}/status` | sent / approved / rejected / expired (+ chosen tier) → CRM stage |
| GET | `/quotes/{id}/event` | Preview the exact CRM payload |
| POST | `/quotes/{id}/sync`, GET `/quotes/{id}/sync-log` | Re-push, delivery log |
| GET | `/exports/deals.csv`, `/exports/line-items.csv` | CRM import files |
| POST | `/agent/chat` | Public chat widget endpoint (sales agent) |
| GET/POST | `/crm/deals`, `/crm/deals/{id}`, `/crm/deals/{id}/stage`, `/crm/deals/{id}/notes` | Deals, stage moves, notes |
| GET | `/crm/dashboard`, `/crm/availability` | KPIs, capacity per date |
| GET/POST | `/crm/customers`, `/crm/tasks`, `/crm/conversations/{id}/reply`, `/resume` | Customers, tasks, human takeover |
| GET | `/crm/today`, `/crm/calendar?month=`, `/kitchen?day=` | Owner home, calendar, kitchen production sheet |
| GET/POST/PATCH | `/catalog`, `/catalog/{sku}`, `/settings` | Menu & prices, business rules |
| POST | `/automation/run`, `/crm/deals/{id}/invoice` | Daily follow-ups, invoices (manual / Morning) |
| GET/POST | `/public/quotes/{token}` (+ `/accept`, `/guest-count`, `/payments/...`) | Customer page: approve, deposit, final count |
| POST | `/extract` | Free text → structured request only |
| POST | `/corrections`, `/reviews`; GET `/metrics/accuracy` | Learning from corrections |

## Running locally

```bash
# 1. Database (Postgres 16 + pgvector)
docker compose up -d

# 2. Backend
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp ../.env.example .env            # add your ANTHROPIC_API_KEY
python -m scripts.seed_catalog     # loads catalog + embeddings (first run downloads the model)
python -m scripts.seed_crm --reset # sample CRM data for the demo tenant
uvicorn app.main:app --reload      # http://localhost:8000/docs

# 3. Frontend (another terminal)
cd frontend && npm install && npm start   # http://localhost:4200

# 4. Tests (no API key needed — the LLM is faked)
pytest
```

Try it:

```bash
curl -X POST localhost:8000/extract -H "Content-Type: application/json" \
  -d '{"message": "בר מצווה ל-120 איש ב-3.12, בשרי כשר, 8 טבעונים"}'
```

## Project layout

```
backend/
  app/
    llm/          client (forced tool use) + versioned prompts
    schemas/      Pydantic contracts: ExtractedRequest, CatalogItem
    services/     extraction, menu planning, pricing, tiers, editing (agent), corrections
    integrations/ canonical event, tenant config + mapping, sync service, exports
      adapters/   webhook, hubspot, monday
    repositories/ quote storage interface (JSON today, DB-ready)
    crm/          customers, deals, activities, tasks, scoring, capacity, dashboard
    agent/        AI sales agent (multi-turn, tool use, human handoff)
    api/          /crm and /agent routers
frontend/         Angular 18 CRM app
    catalog/      loader + embeddings
  scripts/        seed_catalog
  tests/
data/catalog.jsonl   93 kosher-catering items (Hebrew + English)
data/tenants/        per-tenant integration config
docs/                integration guide + JSON Schema
examples/            webhook receiver for clients
evals/               cases, metrics, runner, results
```

## Roadmap

- [x] Project skeleton, Postgres + pgvector
- [x] Demo catalog (93 items) + embedding seed
- [x] Structured extraction + 41-case eval set
- [x] Menu planning with confidence scores (compatible-catalog retrieval)
- [x] Deterministic pricing engine (quantity rules per guest, staff ratios, VAT)
- [x] Three packages, plain-language editing with tool use, learning from corrections
- [x] Live browser demo
- [x] CRM integration layer: canonical events, signed webhooks, HubSpot, monday.com, CSV
- [x] AI sales agent + catering CRM + Angular app + live demo
- [x] Agent evals: 20 scripted conversations, price grounding, safety rules, optional LLM judge
- [x] Angular app: top navbar, quote system (new / list / detail with tiers, edit, status) + CRM
- [x] Owner app: today, inbox, events (4 steps), calendar, kitchen sheet, menu & prices, settings
- [x] Customer link with package choice, deposit payment (demo provider) and final guest count
- [x] Business rules per tenant (staff ratios, discounts, zones, capacity), daily automation, invoices
- [ ] WhatsApp channel for the agent
- [ ] Real payment processor (Grow / Tranzila / CardCom) behind the provider interface
- [ ] pgvector semantic retrieval once the catalog outgrows the prompt
- [ ] Quotes, statuses, Hebrew RTL PDF
- [ ] Angular UI: inbox, review screen, dashboard
- [ ] AI-drafted cover email + sending
- [ ] Voice (Whisper) and image (Vision) input
- [ ] Observability (Langfuse), guardrails, deploy, demo video

## Stack

Python · FastAPI · Pydantic · Claude API · PostgreSQL · pgvector · sentence-transformers · Angular 18 · Angular CDK · pytest · GitHub Actions

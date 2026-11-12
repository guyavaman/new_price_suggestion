# AI Quote Agent 🍽️

**Turn a messy WhatsApp message into a priced catering quote in seconds.**

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

## API

| Method | Path | What it does |
|---|---|---|
| POST | `/extract` | Free text → structured request |
| POST | `/quote` | Full pipeline → request, menu plan, 3 priced tiers |
| POST | `/quote/edit` | Plain-language edit via tool-use agent → re-priced tiers, actions log, flags |
| POST | `/corrections` | Store a salesperson's match correction |
| POST | `/reviews` | Log an approved quote (lines kept vs corrected) |
| GET | `/metrics/accuracy` | Rolling accuracy series for the learning chart |

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
uvicorn app.main:app --reload      # http://localhost:8000/docs

# 3. Tests (no API key needed — the LLM is faked)
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
    catalog/      loader + embeddings
  scripts/        seed_catalog
  tests/
data/catalog.jsonl   93 kosher-catering items (Hebrew + English)
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
- [ ] pgvector semantic retrieval once the catalog outgrows the prompt
- [ ] Quotes, statuses, Hebrew RTL PDF
- [ ] Angular UI: inbox, review screen, dashboard
- [ ] AI-drafted cover email + sending
- [ ] Voice (Whisper) and image (Vision) input
- [ ] Observability (Langfuse), guardrails, deploy, demo video

## Stack

Python · FastAPI · Pydantic · Claude API · PostgreSQL · pgvector · sentence-transformers · Angular · pytest · GitHub Actions

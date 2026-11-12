# AI Quote Agent 🍽️

**Turn a messy WhatsApp message into a priced catering quote in seconds.**

Customers of an Israeli catering company write in Hebrew or English, by email, WhatsApp or voice:

> היי צריך אוכל לאירוע חברה ביום חמישי הבא, 40 איש, חלבי. משהו קליל פינגר פוד

AI Quote Agent reads the request, extracts structured details, matches them to the real catalog,
prices them with deterministic business rules, and drafts the quote for a human to approve.

> 🚧 Work in progress: see the roadmap below.

## Architecture

```
customer message ──► LLM extraction ──► catalog matching ──► pricing engine ──► human review ──► PDF + email
   (he / en)        (Claude, forced     (multilingual       (plain Python,     (confidence
                     tool use → JSON)    embeddings +        no LLM)            colours)
                                         pgvector)
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
    services/     extraction (later: matching, pricing, quotes)
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
- [ ] Catalog matching with confidence scores
- [ ] Deterministic pricing engine (quantity rules per guest, staff ratios, VAT)
- [ ] Quotes, statuses, Hebrew RTL PDF
- [ ] Angular UI: inbox, review screen, dashboard
- [ ] AI-drafted cover email + sending
- [ ] Voice (Whisper) and image (Vision) input
- [ ] Observability (Langfuse), guardrails, deploy, demo video

## Stack

Python · FastAPI · Pydantic · Claude API · PostgreSQL · pgvector · sentence-transformers · Angular · pytest · GitHub Actions

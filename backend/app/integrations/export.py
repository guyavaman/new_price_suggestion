"""File exports for CRMs without an API connection: every CRM can import CSV.

- deals CSV: one row per quote (contact + deal fields), for a deals/leads import.
- line items CSV: one row per line, keyed by quote_number, for a products import.
UTF-8 with BOM so Excel opens Hebrew correctly.
"""

from __future__ import annotations

import csv
import io

from app.integrations.canonical import QuoteEvent, flatten_for_export

DEAL_COLUMNS = [
    "deal.quote_number", "deal.title", "deal.status", "deal.stage", "deal.tier",
    "deal.amount_net", "deal.vat", "deal.amount_total", "deal.currency", "deal.event_type",
    "deal.event_date", "deal.guest_count", "deal.location", "deal.kashrut", "deal.meal_type",
    "deal.dietary_summary", "contact.name", "contact.phone", "contact.email", "contact.company",
    "deal.created_at", "deal.updated_at", "deal.quote_id",
]
LINE_COLUMNS = ["quote_number", "sku", "name", "quantity", "unit", "unit_price", "total", "source"]


def _csv(rows: list[list], header: list[str]) -> str:
    buf = io.StringIO()
    buf.write("﻿")
    w = csv.writer(buf)
    w.writerow(header)
    w.writerows(rows)
    return buf.getvalue()


def deals_csv(events: list[QuoteEvent]) -> str:
    rows = []
    for e in events:
        flat = flatten_for_export(e)
        rows.append([flat.get(c, "") if flat.get(c) is not None else "" for c in DEAL_COLUMNS])
    return _csv(rows, DEAL_COLUMNS)


def line_items_csv(events: list[QuoteEvent]) -> str:
    rows = [[e.deal.quote_number, li.sku, li.name, li.quantity, li.unit, li.unit_price,
             li.total, li.source] for e in events for li in e.line_items]
    return _csv(rows, LINE_COLUMNS)

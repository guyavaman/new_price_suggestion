"""monday.com (GraphQL API v2): one board item per quote.

Settings:
  token_env      env var with the API token
  board_id       target board
  group_id       optional group for new items
  column_types   {"<column id>": "status" | "date" | "phone" | "email" | "numbers" | "text"}
Mapping:
  deal / contact: {"<column id>": "<canonical field or template>"}
  stages: canonical stage -> status label on the board

On creation the line items are posted as an update (comment) on the item.
"""

from __future__ import annotations

import json

import httpx

from app.integrations.base import AdapterError, ExternalRefs, SyncResult, request_with_retry
from app.integrations.canonical import QuoteEvent
from app.integrations.config import IntegrationConfig, apply_mapping

URL = "https://api.monday.com/v2"
API_VERSION = "2024-10"

CREATE = """mutation ($board: ID!, $group: String, $name: String!, $cols: JSON!) {
  create_item(board_id: $board, group_id: $group, item_name: $name, column_values: $cols,
              create_labels_if_missing: true) { id } }"""
UPDATE = """mutation ($board: ID!, $item: ID!, $cols: JSON!) {
  change_multiple_column_values(board_id: $board, item_id: $item, column_values: $cols,
                                create_labels_if_missing: true) { id } }"""
NOTE = """mutation ($item: ID!, $body: String!) {
  create_update(item_id: $item, body: $body) { id } }"""


def format_column(kind: str, value) -> object:
    if kind == "status":
        return {"label": str(value)}
    if kind == "date":
        return {"date": str(value)[:10]}
    if kind == "phone":
        return {"phone": str(value), "countryShortName": "IL"}
    if kind == "email":
        return {"email": str(value), "text": str(value)}
    if kind == "numbers":
        return str(value)
    return str(value)


class MondayAdapter:
    def __init__(self, config: IntegrationConfig, client: httpx.Client | None = None):
        self.config = config
        self.client = client or httpx.Client(timeout=15)

    def _gql(self, query: str, variables: dict) -> dict:
        r = request_with_retry(self.client, "POST", URL, json={"query": query,
                               "variables": variables}, headers={
            "Authorization": self.config.secret("token"), "API-Version": API_VERSION,
            "Content-Type": "application/json"})
        data = r.json()
        if data.get("errors") or data.get("error_message"):
            raise AdapterError(f"monday: {data.get('errors') or data.get('error_message')}")
        return data["data"]

    def column_values(self, event: QuoteEvent) -> dict:
        m = self.config.mapping
        types = self.config.settings.get("column_types", {})
        raw = {**apply_mapping(event, m.contact, "contact"), **apply_mapping(event, m.deal, "deal")}
        status_col = self.config.settings.get("status_column")
        if status_col:
            raw[status_col] = m.stages.get(event.deal.stage.value, event.deal.stage.value)
            types = {**types, status_col: "status"}
        return {col: format_column(types.get(col, "text"), v) for col, v in raw.items()}

    @staticmethod
    def items_note(event: QuoteEvent) -> str:
        rows = "".join(f"<li>{li.name} × {li.quantity:g} = ₪{li.total:,.2f}</li>"
                       for li in event.line_items)
        return (f"<p><b>{event.deal.quote_number}</b> · {event.deal.tier}</p><ul>{rows}</ul>"
                f"<p>סה\"כ כולל מע\"מ: ₪{event.deal.amount_total:,.2f}</p>")

    def sync(self, event: QuoteEvent, refs: ExternalRefs) -> SyncResult:
        board = str(self.config.settings.get("board_id", ""))
        if not board:
            return SyncResult(ok=False, detail="board_id missing")
        cols = json.dumps(self.column_values(event), ensure_ascii=False)
        try:
            if refs.deal_id:
                self._gql(UPDATE, {"board": board, "item": refs.deal_id, "cols": cols})
                item_id = refs.deal_id
            else:
                res = self._gql(CREATE, {"board": board, "name": event.deal.title, "cols": cols,
                                         "group": self.config.settings.get("group_id")})
                item_id = res["create_item"]["id"]
            if not refs.deal_id or event.type.value == "quote.updated":
                self._gql(NOTE, {"item": item_id, "body": self.items_note(event)})
        except AdapterError as e:
            return SyncResult(ok=False, detail=str(e), retryable=e.retryable, refs=refs)
        return SyncResult(ok=True, detail=f"item {item_id}",
                          refs=ExternalRefs(deal_id=item_id, contact_id=refs.contact_id))

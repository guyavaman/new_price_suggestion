"""Minimal webhook receiver a client can deploy in front of their CRM.

Run:  WEBHOOK_SECRET=... uvicorn examples.webhook_receiver:app --port 9000
It verifies the signature, drops duplicate deliveries, and shows where to call your CRM.
"""

import hashlib
import hmac
import json
import os
import time

from fastapi import FastAPI, Header, HTTPException, Request

app = FastAPI()
SECRET = os.environ.get("WEBHOOK_SECRET", "")
seen_deliveries: set[str] = set()  # use your DB in production


def verify(ts: str, body: bytes, signature: str) -> bool:
    if abs(time.time() - int(ts)) > 300:
        return False
    expected = "sha256=" + hmac.new(SECRET.encode(), f"{ts}.".encode() + body,
                                    hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


@app.post("/hooks/quotes")
async def quotes_hook(
    request: Request,
    x_quoteagent_event: str = Header(...),
    x_quoteagent_delivery: str = Header(...),
    x_quoteagent_timestamp: str = Header(...),
    x_quoteagent_signature: str = Header(...),
):
    body = await request.body()
    if not verify(x_quoteagent_timestamp, body, x_quoteagent_signature):
        raise HTTPException(status_code=401, detail="bad signature")
    if x_quoteagent_delivery in seen_deliveries:
        return {"duplicate": True}
    seen_deliveries.add(x_quoteagent_delivery)

    event = json.loads(body)
    deal, contact = event["deal"], event["contact"]
    # --- your CRM call goes here, e.g. upsert by deal["quote_id"] ---
    print(x_quoteagent_event, deal["quote_number"], deal["stage"], deal["amount_total"],
          contact.get("phone"))
    # Optionally return your ids; they will be stored in the sync log.
    return {"deal_id": f"crm-{deal['quote_id'][:8]}"}

"""Daily reminders without anyone pressing a button (stage 4).

Every business with `automation_enabled` gets `run_automation` once a day, at or after its
`automation_hour` (its own time zone). The run is recorded in `automation_last_run`, so a
restart or a second trigger the same day does nothing. Two triggers call `tick()`:
- a background thread in the server (every 10 minutes while the server is up);
- `POST /public/cron/daily` with the CRON_KEY secret, for an external scheduler (a free
  Render instance sleeps when idle, so the thread alone can miss a day).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from app.business.operations import AutomationAction, run_automation

log = logging.getLogger(__name__)
INTERVAL_SECONDS = 600


def tenants(crm, settings) -> set[str]:
    found = set()
    for path in (crm.deals.path, settings.col.path):
        if path.exists():
            found |= {o.get("tenant_id") for o in json.loads(path.read_text()).values()}
    return {t for t in found if t}


def tick(crm, repo, settings, now: datetime | None = None, force: bool = False
         ) -> dict[str, list[AutomationAction]]:
    out = {}
    for tenant in sorted(tenants(crm, settings)):
        rules = settings.get(tenant)
        local = (now or datetime.now(ZoneInfo(rules.timezone))).astimezone(
            ZoneInfo(rules.timezone))
        today = local.date().isoformat()
        if not force and (not rules.automation_enabled or local.hour < rules.automation_hour
                          or rules.automation_last_run == today):
            continue
        out[tenant] = run_automation(crm, repo, rules, tenant, local.date())
        settings.update(tenant, {"automation_last_run": today})
    return out


def start_background(crm, repo, settings) -> threading.Thread | None:
    """Start the daily-reminder thread when this process should run it."""
    on = os.environ.get("SCHEDULER", "1" if os.environ.get("RENDER") else "0") == "1"
    if not on:
        return None

    def loop():
        while True:
            try:
                done = tick(crm, repo, settings)
                if done:
                    log.info("daily reminders: %s", {t: len(a) for t, a in done.items()})
            except Exception:  # noqa: BLE001 — keep the thread alive, try again later
                log.exception("daily reminders failed")
            time.sleep(INTERVAL_SECONDS)

    th = threading.Thread(target=loop, name="daily-reminders", daemon=True)
    th.start()
    return th

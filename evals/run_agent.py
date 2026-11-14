"""Run scripted customer conversations against the real sales agent and score them.

Each case gets a fresh, isolated CRM and quote store, so cases never affect each other.

Usage (from repo root, ANTHROPIC_API_KEY in backend/.env or the environment):
    python evals/run_agent.py                         # all cases, standard menu planner
    python evals/run_agent.py --planner               # also use the LLM menu planner (slower)
    python evals/run_agent.py --only discount-request,prompt-injection
    python evals/run_agent.py --model claude-haiku-5-5 --judge
    python evals/run_agent.py --price-in 3 --price-out 15   # USD per million tokens

Writes evals/results/agent_<timestamp>_<model>.json with full transcripts.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "evals"))

from agent_metrics import (  # noqa: E402
    CaseScore,
    Transcript,
    render,
    render_obj,
    score_case,
    summarize,
)
from pydantic import BaseModel, Field  # noqa: E402

from app.agent.sales import SalesAgent  # noqa: E402
from app.agent.service import ServiceContext  # noqa: E402
from app.business.settings import SettingsService  # noqa: E402
from app.catalog.loader import load_catalog  # noqa: E402
from app.catalog.service import CatalogService  # noqa: E402
from app.crm.models import Deal, DealStage  # noqa: E402
from app.crm.service import CrmService  # noqa: E402
from app.integrations.adapters.internal import InternalCrmAdapter  # noqa: E402
from app.integrations.canonical import EventType  # noqa: E402
from app.integrations.config import IntegrationConfig, TenantConfig  # noqa: E402
from app.integrations.sync import SyncLog, SyncService  # noqa: E402
from app.llm.client import LLMClient  # noqa: E402
from app.repositories.quotes import JsonQuoteRepository  # noqa: E402
from app.schemas.extraction import ContactInfo, ExtractedRequest  # noqa: E402
from app.schemas.quote import MenuLine, MenuPlan  # noqa: E402
from app.services.menu import MenuPlanner  # noqa: E402
from app.services.portal import CustomerPortal  # noqa: E402
from app.services.pricing import PricingEngine  # noqa: E402
from app.services.quotes import create_quote  # noqa: E402

CASES = ROOT / "evals" / "cases" / "agent.jsonl"
RESULTS_DIR = ROOT / "evals" / "results"
TENANT = "eval"


def load_cases(only: set[str] | None = None) -> list[dict]:
    cases = [json.loads(x) for x in CASES.read_text(encoding="utf-8").splitlines() if x.strip()]
    return [c for c in cases if not only or c["id"] in only]


def _setup(crm: CrmService, setup: dict) -> None:
    booked = setup.get("booked")
    if booked:
        c = crm.upsert_customer(TENANT, name="לקוח קיים")
        for _ in range(booked["events"]):
            crm.save_deal(Deal(tenant_id=TENANT, customer_id=c.id, title="",
                               event_date=date.fromisoformat(booked["date"]),
                               guest_count=booked.get("guests", 100), stage=DealStage.won))


def _service_setup(tmp: Path, crm: CrmService, repo, catalog, engine, svc: dict,
                   today: date) -> ServiceContext:
    """A customer with a quote (approved + deposit paid unless status says otherwise),
    chatting from their quote page."""
    settings, catalogs = SettingsService(tmp), CatalogService(tmp)
    tenant = TenantConfig(tenant_id=TENANT, name="eval",
                          integrations=[IntegrationConfig(id="crm", type="internal")])
    sync = SyncService(SyncLog(tmp / "sync.json"), lambda cfg: InternalCrmAdapter(cfg, crm=crm))
    portal = CustomerPortal(repo, crm, catalogs, settings, sync, lambda t: tenant)
    guests = svc.get("guests", 100)
    req = ExtractedRequest(language="he", event_type="bar_bat_mitzvah", guest_count=guests,
                           event_date=date.fromisoformat(svc["date"]), meal_type="meat",
                           kashrut="kosher", service={"waiters": True},
                           contact=ContactInfo(name="דנה כהן", phone="0521234567"))
    plan = MenuPlan(lines=[MenuLine(sku="PKG-MEAT-STD", for_guests=guests),
                           MenuLine(sku="CAN-SKEWER-CHICK", for_guests=guests),
                           MenuLine(sku="DRK-SOFT", for_guests=guests)])
    q = create_quote(repo, TENANT, req, plan, catalog, engine, "eval")
    sync.deliver(tenant, q, EventType.created)
    if svc.get("status", "approved") == "approved":
        r = portal.accept(q.public_token, "recommended", today)
        portal.confirm_payment(q.public_token, r["payment_id"])
    return ServiceContext(quote=repo.get(TENANT, q.id), portal=portal)


def run_case(case: dict, llm: LLMClient, today: date, use_planner: bool = False) -> dict:
    catalog = load_catalog()
    engine = PricingEngine(catalog)
    by_sku = {i.sku: i for i in catalog}
    with tempfile.TemporaryDirectory() as tmp:
        crm = CrmService(Path(tmp))
        repo = JsonQuoteRepository(Path(tmp) / "quotes.json")
        setup = render_obj(case.get("setup", {}), today)
        _setup(crm, setup)
        service = None
        if setup.get("service"):
            service = _service_setup(Path(tmp), crm, repo, catalog, engine, setup["service"],
                                     today)
        planner = None
        if use_planner:
            mp = MenuPlanner(catalog, llm)
            planner = lambda req: mp.plan(req)[0]  # noqa: E731
        agent = SalesAgent(crm, catalog, engine, repo, llm=llm, planner=planner)

        turns, tool_calls, replies = [], [], []
        usage = {"input_tokens": 0, "output_tokens": 0, "latency_ms": 0}
        conv_id, error = None, None
        try:
            for msg in case["turns"]:
                text = render(msg, today)
                if service:  # the quote page identifies the customer; refresh the snapshot
                    service.quote = repo.get(TENANT, service.quote.id)
                r = agent.chat(TENANT, text, conv_id, today=today, service=service)
                conv_id = r.conversation.id
                if r.reply:
                    replies.append(r.reply)
                tool_calls += r.actions
                for k in usage:
                    usage[k] += r.usage.get(k, 0)
                turns.append({"customer": text, "agent": r.reply,
                              "tools": [{"tool": a["tool"], "input": a["input"],
                                         "error": a["error"]} for a in r.actions]})
        except Exception as e:  # a crash fails the case, not the run
            error = f"{type(e).__name__}: {e}"

        conv = crm.conversations.get(TENANT, conv_id) if conv_id else None
        deal = crm.deals.get(TENANT, conv.deal_id) if conv and conv.deal_id else None
        customer = crm.customers.get(TENANT, deal.customer_id) if deal else None
        quote_lines = []
        if deal and deal.quote_ids:
            q = repo.get(TENANT, deal.quote_ids[-1])
            if q:
                quote_lines = [{"sku": ln.sku, "meal_type": by_sku[ln.sku].meal_type.value}
                               for ln in q.tier("recommended").quote.lines if ln.sku in by_sku]
        transcript = Transcript(
            replies=replies,
            tool_calls=[{"tool": a["tool"], "input": a["input"], "output": a["output"],
                         "error": a["error"]} for a in tool_calls],
            deal=deal.model_dump(mode="json") if deal else None,
            customer=customer.model_dump(mode="json") if customer else None,
            status=conv.status.value if conv else "none",
            quote_lines=quote_lines,
            escalated=bool(conv and conv.escalated),
            tasks=[x.title for x in crm.tasks.list(TENANT) if not x.done],
        )
    expected = render_obj(case.get("expected", {}), today)
    score = score_case(case["id"], expected, transcript)
    score.error = error
    return {"case": case, "score": score, "turns": turns, "transcript": transcript,
            "usage": usage}


# ---------- optional LLM-as-judge for what rules can't measure ----------

class JudgeResult(BaseModel):
    score: int = Field(..., ge=1, le=5, description="1 poor .. 5 excellent")
    strengths: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)


JUDGE_PROMPT = """\
You review a website sales chat for an Israeli kosher catering company. The agent is an AI.
Score the AGENT's conversation quality 1-5 on: warmth and natural Hebrew (or the customer's
language), asking at most one or two questions at a time, moving the sale forward, honesty
(no promises it can't keep), and handing off to a human when appropriate.
Facts like prices and CRM data are checked elsewhere; judge the conversation itself.
"""


def judge(llm: LLMClient, result: dict) -> JudgeResult:
    convo = "\n".join(f"Customer: {t['customer']}\nAgent: {t['agent']}" for t in result["turns"])
    j, _ = llm.structured(system=JUDGE_PROMPT, user=f"<conversation>\n{convo}\n</conversation>",
                          schema=JudgeResult, tool_name="record_review",
                          tool_description="Record the review.")
    return j


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--model", default=None)
    p.add_argument("--only", default=None)
    p.add_argument("--workers", type=int, default=3)
    p.add_argument("--planner", action="store_true", help="Use the LLM menu planner for quotes")
    p.add_argument("--judge", action="store_true", help="Add an LLM-as-judge quality score")
    p.add_argument("--price-in", type=float, default=None)
    p.add_argument("--price-out", type=float, default=None)
    args = p.parse_args()

    os.chdir(ROOT / "backend")  # so settings find backend/.env
    cases = load_cases(set(args.only.split(",")) if args.only else None)
    llm = LLMClient(model=args.model)
    today = date.today()
    print(f"Running {len(cases)} conversations on {llm.model} "
          f"({sum(len(c['turns']) for c in cases)} customer turns)...")

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(lambda c: run_case(c, llm, today, args.planner), cases))
    wall = time.perf_counter() - t0

    scores: list[CaseScore] = [r["score"] for r in results]
    summary = summarize(scores)
    tok_in = sum(r["usage"]["input_tokens"] for r in results)
    tok_out = sum(r["usage"]["output_tokens"] for r in results)
    n_turns = sum(len(r["turns"]) for r in results) or 1
    summary.update(model=llm.model, input_tokens=tok_in, output_tokens=tok_out,
                   avg_turn_latency_ms=int(
                       sum(r["usage"]["latency_ms"] for r in results) / n_turns),
                   avg_tool_calls_per_case=round(
                       sum(len(r["transcript"].tool_calls) for r in results) / len(results), 1),
                   wall_seconds=round(wall, 1))
    if args.price_in is not None and args.price_out is not None:
        cost = (tok_in * args.price_in + tok_out * args.price_out) / 1e6
        summary["cost_usd"] = round(cost, 4)
        summary["cost_per_conversation_usd"] = round(cost / len(results), 4)
    if args.judge:
        for r in results:
            try:
                r["judge"] = judge(llm, r).model_dump()
            except Exception as e:
                r["judge"] = {"error": str(e)}
        js = [r["judge"]["score"] for r in results if "score" in r["judge"]]
        summary["judge_avg"] = round(sum(js) / len(js), 2) if js else None

    # ---- report ----
    print(f"\nPass rate: {summary['passed']}/{summary['cases']} ({summary['pass_rate']:.0%})   "
          f"safety/grounding violations: {summary['safety_violations']}   "
          f"avg turn latency: {summary['avg_turn_latency_ms']} ms")
    if "cost_usd" in summary:
        per = summary["cost_per_conversation_usd"]
        print(f"Cost: ${summary['cost_usd']} (${per}/conversation)")
    if "judge_avg" in summary:
        print(f"Judge (1-5): {summary['judge_avg']}")
    print("\nBy group:")
    for g, v in summary["group_accuracy"].items():
        print(f"  {g:<10} {v:>6.0%}")
    failed = [r for r in results if not r["score"].passed]
    if failed:
        print("\nFailures:")
        for r in failed:
            sc = r["score"]
            if sc.error:
                print(f"  {sc.case_id}: ERROR {sc.error}")
            for c in sc.checks:
                if not c.passed:
                    print(f"  {sc.case_id} · {c.name}: {c.detail}")

    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / f"agent_{datetime.now():%Y%m%d-%H%M%S}_{llm.model}.json"
    out.write_text(json.dumps({"summary": summary, "cases": [{
        "id": r["case"]["id"], "passed": r["score"].passed, "error": r["score"].error,
        "failed_checks": [c.__dict__ for c in r["score"].checks if not c.passed],
        "turns": r["turns"], "deal": r["transcript"].deal, "status": r["transcript"].status,
        "usage": r["usage"], "judge": r.get("judge"),
    } for r in results]}, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\nSaved {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

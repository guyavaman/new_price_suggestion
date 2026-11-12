"""Run the extraction eval set against the real model.

Usage (from repo root, with ANTHROPIC_API_KEY set in backend/.env or the environment):
    python evals/run_extraction.py
    python evals/run_extraction.py --model claude-haiku-5-5 --only he-009,en-004
    python evals/run_extraction.py --price-in 3 --price-out 15   # USD per million tokens

Writes evals/results/<timestamp>_<model>.json and prints a summary table.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "evals"))
os.chdir(ROOT / "backend")  # so pydantic-settings finds backend/.env

from metrics import CaseResult, score_case, summarize  # noqa: E402

from app.llm.client import LLMClient  # noqa: E402
from app.services.extraction import ExtractionService  # noqa: E402

CASES = ROOT / "evals" / "cases" / "extraction.jsonl"
RESULTS_DIR = ROOT / "evals" / "results"


def load_cases(only: set[str] | None) -> list[dict]:
    cases = [json.loads(line) for line in CASES.read_text(encoding="utf-8").splitlines() if line]
    return [c for c in cases if not only or c["id"] in only]


def run_case(service: ExtractionService, case: dict) -> tuple[CaseResult, dict, dict]:
    try:
        extracted, stats = service.extract(
            case["message"], date.fromisoformat(case["reference_date"])
        )
        actual = extracted.model_dump(mode="json")
        return (
            score_case(case["id"], case["expected"], actual),
            actual,
            {"in": stats.input_tokens, "out": stats.output_tokens, "ms": stats.latency_ms},
        )
    except Exception as e:  # a crash is a failed case, not a crashed run
        return CaseResult(case["id"], error=f"{type(e).__name__}: {e}"), {}, {}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--model", default=None)
    p.add_argument("--only", default=None, help="Comma-separated case ids")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--price-in", type=float, default=None, help="USD per 1M input tokens")
    p.add_argument("--price-out", type=float, default=None, help="USD per 1M output tokens")
    args = p.parse_args()

    cases = load_cases(set(args.only.split(",")) if args.only else None)
    service = ExtractionService(LLMClient(model=args.model))
    model = service.llm.model
    print(f"Running {len(cases)} cases on {model} (prompt {service.prompt_version})...")

    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        outputs = list(pool.map(lambda c: run_case(service, c), cases))
    wall = time.perf_counter() - start

    results = [o[0] for o in outputs]
    usage = [o[2] for o in outputs if o[2]]
    summary = summarize(results)
    summary.update(
        model=model,
        prompt_version=service.prompt_version,
        avg_latency_ms=int(sum(u["ms"] for u in usage) / len(usage)) if usage else None,
        input_tokens=sum(u["in"] for u in usage),
        output_tokens=sum(u["out"] for u in usage),
        wall_seconds=round(wall, 1),
    )
    if args.price_in is not None and args.price_out is not None:
        cost = (summary["input_tokens"] * args.price_in
                + summary["output_tokens"] * args.price_out) / 1e6
        summary["cost_usd"] = round(cost, 4)

    # ---- print report ----
    print(f"\nPass rate: {summary['passed']}/{summary['cases']} ({summary['pass_rate']:.0%})"
          f"   errors: {summary['errors']}   avg latency: {summary['avg_latency_ms']} ms")
    if "cost_usd" in summary:
        print(f"Cost: ${summary['cost_usd']}")
    print("\nField accuracy:")
    for k, v in summary["field_accuracy"].items():
        print(f"  {k:<26} {v:>6.0%}")
    failed = [r for r in results if not r.passed]
    if failed:
        print("\nFailures:")
        for r in failed:
            if r.error:
                print(f"  {r.case_id}: ERROR {r.error}")
                continue
            for c in r.checks:
                if not c.passed:
                    print(f"  {r.case_id} · {c.name}: expected {c.expected!r}, got {c.actual!r}")

    # ---- save ----
    RESULTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = RESULTS_DIR / f"{stamp}_{model}.json"
    out.write_text(
        json.dumps(
            {
                "summary": summary,
                "cases": [
                    {
                        "id": r.case_id,
                        "passed": r.passed,
                        "error": r.error,
                        "failed_checks": [c.__dict__ for c in r.checks if not c.passed],
                        "actual": o[1],
                        "usage": o[2],
                    }
                    for r, o in zip(results, outputs, strict=True)
                ],
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    print(f"\nSaved {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

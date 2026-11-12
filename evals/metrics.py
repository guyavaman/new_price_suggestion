"""Scoring for extraction evals. Pure functions — no LLM calls — so they are unit-tested.

An eval case lists only the fields it cares about in `expected`. Each listed field becomes one
check. A case passes only if all its checks pass. Supported keys:

  event_type, guest_count, event_date, kashrut, meal_type, suspicious_instructions
      exact match (expected null means the model must return null)
  location_contains      substring (case-insensitive) of the extracted location
  budget                 {"amount": n, "scope": "total"|"per_guest"}  (amount within 1%)
  dietary                [{"tag": ..., "guest_count": n|null}]  — set equality
  service                {"waiters": bool, ...}  — each listed flag must match
  items                  [{"any": [keywords], "quantity": n?}]  — each must be found
  items_count            exact number of requested_items
  missing_info_includes  every listed field must appear in missing_info
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

EXACT_FIELDS = (
    "event_type",
    "guest_count",
    "event_date",
    "kashrut",
    "meal_type",
    "suspicious_instructions",
)


@dataclass
class CheckResult:
    name: str
    passed: bool
    expected: Any
    actual: Any


@dataclass
class CaseResult:
    case_id: str
    checks: list[CheckResult] = field(default_factory=list)
    error: str | None = None

    @property
    def passed(self) -> bool:
        return self.error is None and all(c.passed for c in self.checks)


def _item_matches(spec: dict, item: dict) -> bool:
    desc = (item.get("description") or "").lower()
    if not any(k.lower() in desc for k in spec["any"]):
        return False
    if "quantity" in spec:
        q = item.get("quantity")
        return q is not None and abs(float(q) - float(spec["quantity"])) < 1e-6
    return True


def score_case(case_id: str, expected: dict, actual: dict) -> CaseResult:
    result = CaseResult(case_id=case_id)
    add = result.checks.append

    for f in EXACT_FIELDS:
        if f in expected:
            add(CheckResult(f, actual.get(f) == expected[f], expected[f], actual.get(f)))

    if "location_contains" in expected:
        loc = actual.get("location") or ""
        exp = expected["location_contains"]
        add(CheckResult("location", exp.lower() in loc.lower(), exp, loc))

    if "budget" in expected:
        exp, act = expected["budget"], actual.get("budget")
        ok = (
            act is not None
            and abs(float(act["amount"]) - exp["amount"]) <= 0.01 * exp["amount"]
            and act.get("scope") == exp["scope"]
        )
        add(CheckResult("budget", ok, exp, act))

    if "dietary" in expected:
        exp_set = {(d["tag"], d.get("guest_count")) for d in expected["dietary"]}
        act_set = {(d["tag"], d.get("guest_count")) for d in actual.get("dietary_requirements", [])}
        add(CheckResult("dietary", exp_set == act_set, sorted(exp_set, key=str),
                        sorted(act_set, key=str)))

    if "service" in expected:
        act_service = actual.get("service") or {}
        for flag, exp_val in expected["service"].items():
            add(CheckResult(f"service.{flag}", act_service.get(flag) == exp_val, exp_val,
                            act_service.get(flag)))

    items = actual.get("requested_items", [])
    if "items" in expected:
        for spec in expected["items"]:
            found = any(_item_matches(spec, it) for it in items)
            add(CheckResult(f"item:{spec['any'][0]}", found, spec,
                            [it.get("description") for it in items]))

    if "items_count" in expected:
        add(CheckResult("items_count", len(items) == expected["items_count"],
                        expected["items_count"], len(items)))

    if "missing_info_includes" in expected:
        missing = set(actual.get("missing_info", []))
        for f in expected["missing_info_includes"]:
            add(CheckResult(f"missing_info:{f}", f in missing, f, sorted(missing)))

    return result


def check_group(name: str) -> str:
    """Group check names for the per-field report (item:סושי -> items)."""
    if name.startswith("item:"):
        return "items"
    if name.startswith("missing_info:"):
        return "missing_info"
    if name.startswith("service."):
        return "service"
    return name


def summarize(results: list[CaseResult]) -> dict:
    per_field: dict[str, list[bool]] = {}
    for r in results:
        for c in r.checks:
            per_field.setdefault(check_group(c.name), []).append(c.passed)
    return {
        "cases": len(results),
        "passed": sum(r.passed for r in results),
        "errors": sum(r.error is not None for r in results),
        "pass_rate": round(sum(r.passed for r in results) / len(results), 3) if results else 0,
        "field_accuracy": {
            k: round(sum(v) / len(v), 3) for k, v in sorted(per_field.items())
        },
    }

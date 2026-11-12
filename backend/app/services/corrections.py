"""Learning from salesperson corrections, without fine-tuning.

1. When a salesperson fixes a match ("קנאפה" was matched to X, should be Y), we store it.
2. The most recent corrections are injected into the menu prompt as few-shot examples,
   so the next quote gets it right.
3. Every reviewed quote logs how many lines were kept vs corrected, which gives an accuracy
   curve over time: the portfolio's "it learns" chart.

Storage is a JSON file to keep the demo dependency-free; the interface is DB-ready.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

DEFAULT_PATH = Path(__file__).resolve().parents[3] / "data" / "corrections.json"


class Correction(BaseModel):
    customer_wording: str
    wrong_sku: str | None = None
    correct_sku: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Review(BaseModel):
    lines_total: int = Field(..., ge=1)
    lines_corrected: int = Field(..., ge=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def accuracy(self) -> float:
        return 1 - self.lines_corrected / self.lines_total


class _State(BaseModel):
    corrections: list[Correction] = Field(default_factory=list)
    reviews: list[Review] = Field(default_factory=list)


class CorrectionStore:
    def __init__(self, path: Path = DEFAULT_PATH):
        self.path = path
        self._lock = threading.Lock()

    def _load(self) -> _State:
        if not self.path.exists():
            return _State()
        return _State.model_validate_json(self.path.read_text(encoding="utf-8"))

    def _save(self, state: _State) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(state.model_dump_json(indent=2), encoding="utf-8")
        tmp.replace(self.path)  # atomic on POSIX

    def add_correction(self, c: Correction) -> None:
        with self._lock:
            s = self._load()
            # newest wins: drop an older correction for the same wording
            s.corrections = [x for x in s.corrections
                             if x.customer_wording.strip() != c.customer_wording.strip()]
            s.corrections.append(c)
            self._save(s)

    def add_review(self, r: Review) -> None:
        with self._lock:
            s = self._load()
            s.reviews.append(r)
            self._save(s)

    def corrections(self) -> list[Correction]:
        return self._load().corrections

    def few_shot_block(self, limit: int = 15) -> str:
        cs = self._load().corrections[-limit:]
        if not cs:
            return ""
        lines = [f'- "{c.customer_wording}" -> {c.correct_sku}'
                 + (f" (not {c.wrong_sku})" if c.wrong_sku else "") for c in cs]
        return ("Past corrections by our salespeople. Follow them when the same wording "
                "appears:\n" + "\n".join(lines))

    def accuracy_series(self, window: int = 5) -> list[dict]:
        """Rolling accuracy over the last `window` reviews, one point per review."""
        reviews = self._load().reviews
        out = []
        for i in range(len(reviews)):
            chunk = reviews[max(0, i - window + 1): i + 1]
            total = sum(r.lines_total for r in chunk)
            corrected = sum(r.lines_corrected for r in chunk)
            out.append({"review": i + 1, "accuracy": round(1 - corrected / total, 3),
                        "at": reviews[i].created_at.isoformat()})
        return out

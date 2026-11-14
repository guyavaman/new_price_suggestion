"""A tiny tenant-aware JSON collection store.

Good enough for a demo and for tests; every CRM service talks to `Collection`, so swapping in
SQLAlchemy/Postgres later means re-implementing five methods, not touching business logic.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Generic, TypeVar

from pydantic import BaseModel, TypeAdapter

T = TypeVar("T", bound=BaseModel)

# STORE_DIR env var moves all runtime data (used by the browser tests to run on a throwaway copy)
_DEFAULT_STORE = Path(__file__).resolve().parents[3] / "data" / "store"
STORE_DIR = Path(os.environ.get("STORE_DIR") or _DEFAULT_STORE)
_locks: dict[Path, threading.RLock] = {}


class Collection(Generic[T]):
    def __init__(self, model: type[T], path: Path):
        self.model = model
        self.path = path
        self._adapter = TypeAdapter(dict[str, model])
        self._lock = _locks.setdefault(path.resolve(), threading.RLock())

    def _load(self) -> dict[str, T]:
        if not self.path.exists():
            return {}
        return self._adapter.validate_json(self.path.read_bytes())

    def _write(self, data: dict[str, T]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_bytes(self._adapter.dump_json(data, indent=2))
        tmp.replace(self.path)

    def put(self, obj: T) -> T:
        with self._lock:
            data = self._load()
            data[obj.id] = obj  # type: ignore[attr-defined]
            self._write(data)
            return obj

    def get(self, tenant_id: str, obj_id: str) -> T | None:
        obj = self._load().get(obj_id)
        return obj if obj is not None and obj.tenant_id == tenant_id else None  # type: ignore

    def list(self, tenant_id: str, where: Callable[[T], bool] | None = None) -> list[T]:
        return [o for o in self._load().values()
                if o.tenant_id == tenant_id and (where is None or where(o))]  # type: ignore

    def delete(self, tenant_id: str, obj_id: str) -> bool:
        with self._lock:
            data = self._load()
            obj = data.get(obj_id)
            if obj is None or obj.tenant_id != tenant_id:  # type: ignore[attr-defined]
                return False
            del data[obj_id]
            self._write(data)
            return True

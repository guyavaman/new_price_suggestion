import json
from pathlib import Path

from app.schemas.catalog import CatalogItem

DEFAULT_CATALOG_PATH = Path(__file__).resolve().parents[3] / "data" / "catalog.jsonl"


def load_catalog(path: Path = DEFAULT_CATALOG_PATH) -> list[CatalogItem]:
    items: list[CatalogItem] = []
    with path.open(encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                items.append(CatalogItem.model_validate(json.loads(line)))
            except Exception as e:  # surface the bad line, not a vague error
                raise ValueError(f"{path.name}:{line_no}: {e}") from e
    skus = [i.sku for i in items]
    if len(skus) != len(set(skus)):
        raise ValueError("Duplicate SKUs in catalog")
    return items

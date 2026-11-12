"""Load data/catalog.jsonl into Postgres and compute embeddings.

Usage (from backend/):  python -m scripts.seed_catalog
Idempotent: re-running updates existing rows.
"""

from sqlalchemy import text

from app.catalog.embeddings import embed_passages
from app.catalog.loader import load_catalog
from app.db import Base, Product, SessionLocal, engine


def main() -> None:
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(engine)

    items = load_catalog()
    print(f"Loaded {len(items)} catalog items, computing embeddings...")
    vectors = embed_passages([i.embedding_text() for i in items])

    with SessionLocal() as session:
        for item, vec in zip(items, vectors, strict=True):
            session.merge(
                Product(
                    sku=item.sku,
                    name_he=item.name_he,
                    name_en=item.name_en,
                    category=item.category.value,
                    unit=item.unit.value,
                    price=item.price,
                    meal_type=item.meal_type.value,
                    tags=[t.value for t in item.tags],
                    serves=item.serves,
                    min_qty=item.min_qty,
                    description_he=item.description_he,
                    embedding=vec,
                )
            )
        session.commit()
    print("Done.")


if __name__ == "__main__":
    main()

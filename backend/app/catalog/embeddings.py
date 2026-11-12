"""Local multilingual embeddings (no API key, works for Hebrew).

E5 models expect a prefix: "passage: " for documents and "query: " for searches.
Vectors are L2-normalised, so cosine similarity == dot product.
"""

from functools import lru_cache

from app.config import get_settings


@lru_cache
def _model():
    from sentence_transformers import SentenceTransformer  # heavy import, load lazily

    return SentenceTransformer(get_settings().embedding_model)


def embed_passages(texts: list[str]) -> list[list[float]]:
    vecs = _model().encode([f"passage: {t}" for t in texts], normalize_embeddings=True)
    return [v.tolist() for v in vecs]


def embed_query(text: str) -> list[float]:
    return _model().encode(f"query: {text}", normalize_embeddings=True).tolist()

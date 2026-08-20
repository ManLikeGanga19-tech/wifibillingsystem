"""Retrieval-augmented generation over the product docs.

A self-hosted fastembed model (baked into the image) turns docs and questions into vectors; the
docs live in pgvector; retrieval finds the passages nearest a question by cosine distance. The
model is loaded once per process and never talks to the network at runtime.
"""

from __future__ import annotations

import functools

from django.conf import settings
from pgvector.django import CosineDistance

from .models import DocChunk


@functools.lru_cache(maxsize=1)
def _model():
    # Imported lazily so importing this module (e.g. in migrations) never loads the model.
    from fastembed import TextEmbedding

    return TextEmbedding(settings.ASSISTANT_EMBED_MODEL, cache_dir=settings.FASTEMBED_CACHE_DIR)


def embed(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts to vectors (plain lists, ready for pgvector)."""
    return [v.tolist() for v in _model().embed(list(texts))]


def embed_one(text: str) -> list[float]:
    return embed([text])[0]


def retrieve(query: str, k: int = 5, min_score: float = 0.55) -> list[dict]:
    """The top-k doc passages most relevant to `query`, each with a 0–1 similarity score.

    Cosine distance in pgvector; similarity = 1 − distance. Passages below `min_score` are
    dropped, so an off-topic or unknown question returns [] and the caller can refuse rather than
    invent an answer.
    """
    query = (query or "").strip()
    if not query:
        return []
    qvec = embed_one(query)
    rows = (
        DocChunk.objects.annotate(distance=CosineDistance("embedding", qvec))
        .order_by("distance")[:k]
    )
    out = []
    for r in rows:
        score = 1.0 - float(r.distance)
        if score < min_score:
            continue
        out.append({
            "slug": r.slug,
            "title": r.title,
            "heading": r.heading,
            "content": r.content,
            "score": round(score, 3),
        })
    return out

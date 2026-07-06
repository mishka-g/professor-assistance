"""Retrieve relevant passages from the professor's corpus for a piece of draft text."""

from __future__ import annotations

from dataclasses import dataclass

from .config import get_settings
from .store import get_collection


@dataclass
class Passage:
    text: str
    source: str
    score: float


def retrieve(query: str, top_k: int | None = None) -> list[Passage]:
    settings = get_settings()
    k = top_k or settings.retrieval_top_k
    if not query.strip():
        return []
    try:
        collection = get_collection(create=False)
    except Exception:
        return []
    if collection.count() == 0:
        return []

    res = collection.query(
        query_texts=[query[:2000]],
        n_results=min(k, collection.count()),
        include=["documents", "metadatas", "distances"],
    )
    passages: list[Passage] = []
    docs = res.get("documents", [[]])[0]
    metas = res.get("metadatas", [[]])[0]
    dists = res.get("distances", [[]])[0]
    for doc, meta, dist in zip(docs, metas, dists):
        passages.append(
            Passage(
                text=doc,
                source=str(meta.get("source", "?")) if meta else "?",
                score=1.0 - float(dist),  # cosine distance -> similarity
            )
        )
    return passages


def format_context(passages: list[Passage], max_chars: int = 3000) -> str:
    """Render retrieved passages as a context block for the LLM prompt."""
    out: list[str] = []
    used = 0
    for i, p in enumerate(passages, 1):
        snippet = p.text.strip()
        block = f"[{i}] (source: {p.source}, sim={p.score:.2f})\n{snippet}\n"
        if used + len(block) > max_chars:
            break
        out.append(block)
        used += len(block)
    return "\n".join(out) if out else "(no corpus context available)"

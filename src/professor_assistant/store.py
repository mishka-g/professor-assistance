"""Vector store access: a local, persistent Chroma collection with local embeddings.

Embeddings and the vector DB always run locally (private, free), regardless of which
generation backend is selected.
"""

from __future__ import annotations

from functools import lru_cache

import chromadb
from chromadb.api.models.Collection import Collection
from chromadb.utils import embedding_functions

from .config import get_settings


@lru_cache
def get_embedding_function():
    """Local embedding function (cached once per process).

    Default: Chroma's built-in ONNX model (all-MiniLM) — no torch, quiet, works everywhere.
    Opt in to sentence-transformers (EMBEDDING_MODEL) with USE_ST_EMBEDDER=1 where torch works.
    """
    settings = get_settings()
    if settings.use_st_embedder:
        try:
            return embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name=settings.embedding_model
            )
        except Exception as exc:  # pragma: no cover - environment dependent
            print(
                f"[store] Could not load '{settings.embedding_model}' "
                f"({exc}); using Chroma's built-in embeddings instead."
            )
    return embedding_functions.DefaultEmbeddingFunction()


def get_client() -> chromadb.ClientAPI:
    settings = get_settings()
    settings.chroma_dir.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(settings.chroma_dir))


def get_collection(create: bool = True, name: str | None = None) -> Collection:
    """Get (or create) a named Chroma collection. Defaults to the main corpus collection;
    pass `name=settings.examples_collection_name` for the before/after edit-pattern index.
    """
    settings = get_settings()
    client = get_client()
    ef = get_embedding_function()
    collection_name = name or settings.collection_name
    if create:
        return client.get_or_create_collection(
            name=collection_name,
            embedding_function=ef,
            metadata={"hnsw:space": "cosine"},
        )
    return client.get_collection(name=collection_name, embedding_function=ef)

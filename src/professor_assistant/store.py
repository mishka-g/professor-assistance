"""Vector store access: a local, persistent Chroma collection with local embeddings.

Embeddings and the vector DB always run locally (private, free), regardless of which
generation backend is selected.
"""

from __future__ import annotations

import chromadb
from chromadb.api.models.Collection import Collection
from chromadb.utils import embedding_functions

from .config import get_settings


def get_embedding_function():
    """Local embedding function. Prefer the configured sentence-transformers model;
    fall back to Chroma's bundled ONNX model if it can't be loaded (e.g. no torch)."""
    settings = get_settings()
    try:
        return embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=settings.embedding_model
        )
    except Exception as exc:  # pragma: no cover - environment dependent
        print(
            f"[store] Could not load '{settings.embedding_model}' "
            f"({exc}); falling back to Chroma default embeddings."
        )
        return embedding_functions.DefaultEmbeddingFunction()


def get_client() -> chromadb.ClientAPI:
    settings = get_settings()
    settings.chroma_dir.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(settings.chroma_dir))


def get_collection(create: bool = True) -> Collection:
    settings = get_settings()
    client = get_client()
    ef = get_embedding_function()
    if create:
        return client.get_or_create_collection(
            name=settings.collection_name,
            embedding_function=ef,
            metadata={"hnsw:space": "cosine"},
        )
    return client.get_collection(
        name=settings.collection_name, embedding_function=ef
    )

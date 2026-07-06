"""Ingest the professor's corpus into the local vector store."""

from __future__ import annotations

import re
from pathlib import Path

from .config import get_settings
from .readers import iter_corpus_files, read_any
from .store import get_client, get_collection


def _clean(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def chunk_text(text: str, size: int, overlap: int) -> list[str]:
    """Character-based chunking with overlap, preferring to break on paragraph/sentence."""
    text = _clean(text)
    if len(text) <= size:
        return [text] if text else []

    chunks: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + size, n)
        if end < n:
            # try to break on a paragraph or sentence boundary within the window
            window = text[start:end]
            for sep in ("\n\n", "\n", ". "):
                idx = window.rfind(sep)
                if idx > size * 0.5:
                    end = start + idx + len(sep)
                    break
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= n:
            break
        start = max(end - overlap, start + 1)
    return chunks


def ingest_corpus(rebuild: bool = True) -> dict:
    settings = get_settings()
    settings.corpus_dir.mkdir(parents=True, exist_ok=True)

    if rebuild:
        client = get_client()
        try:
            client.delete_collection(settings.collection_name)
        except Exception:
            pass

    collection = get_collection(create=True)

    files = list(iter_corpus_files(settings.corpus_dir))
    total_chunks = 0
    per_file: dict[str, int] = {}

    for path in files:
        try:
            raw = read_any(path)
        except Exception as exc:
            print(f"[ingest] skip {path.name}: {exc}")
            continue
        chunks = chunk_text(raw, settings.chunk_size, settings.chunk_overlap)
        if not chunks:
            continue
        rel = str(path.relative_to(settings.corpus_dir))
        ids = [f"{rel}::chunk::{i}" for i in range(len(chunks))]
        metadatas = [{"source": rel, "chunk": i} for i in range(len(chunks))]
        collection.add(ids=ids, documents=chunks, metadatas=metadatas)
        per_file[rel] = len(chunks)
        total_chunks += len(chunks)
        print(f"[ingest] {rel}: {len(chunks)} chunks")

    return {
        "files": len(per_file),
        "chunks": total_chunks,
        "per_file": per_file,
        "collection_count": collection.count(),
    }

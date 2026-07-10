"""FastAPI backend: a thin HTTP layer over the existing review/ingest pipeline.

Two jobs, mirroring the UI:
- POST /api/corpus  -> add one of the professor's papers to the RAG corpus
- POST /api/review  -> review a student draft; then export only the accepted edits
"""

from __future__ import annotations

import threading
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import get_settings
from .docx_io import write_accepted_docx
from .ingest import ingest_corpus
from .readers import SUPPORTED, iter_corpus_files
from .retrieve import retrieve
from .review import analyze_draft
from .store import get_collection
from .style import build_style_card

app = FastAPI(title="professor-assistant")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory cache of active reviews (single local user; drafts also persist on disk).
_REVIEWS: dict[str, dict] = {}

# Serializes corpus rebuilds so two concurrent uploads can't race and empty the collection.
_INGEST_LOCK = threading.Lock()


def _status() -> dict:
    settings = get_settings()
    try:
        chunks = get_collection(create=False).count()
    except Exception:
        chunks = 0
    files = list(iter_corpus_files(settings.corpus_dir))
    return {
        "backend": settings.model_backend,
        "corpus_files": len(files),
        "corpus_chunks": chunks,
        "style_card": settings.style_card_path.exists(),
    }


def _corpus_papers() -> list[dict]:
    """List the papers in the corpus with their per-file chunk counts + size."""
    settings = get_settings()
    counts: dict[str, int] = {}
    try:
        got = get_collection(create=False).get(include=["metadatas"])
        for m in got.get("metadatas") or []:
            src = (m or {}).get("source")
            if src:
                counts[src] = counts.get(src, 0) + 1
    except Exception:
        pass
    papers = []
    for p in iter_corpus_files(settings.corpus_dir):
        rel = str(p.relative_to(settings.corpus_dir))
        st = p.stat()
        papers.append(
            {"name": rel, "chunks": counts.get(rel, 0), "size_kb": max(1, round(st.st_size / 1024))}
        )
    papers.sort(key=lambda x: x["name"].lower())
    return papers


def _rebuild_style_card_async() -> None:
    """Refresh the style card off the request thread (it can be slow on the LLM backends)."""
    def _run():
        try:
            build_style_card()
        except Exception:
            pass
    threading.Thread(target=_run, daemon=True).start()


def _save_upload(upload: UploadFile, dest_dir: Path) -> Path:
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in SUPPORTED:
        raise HTTPException(400, f"Unsupported file type '{suffix}'. Allowed: {sorted(SUPPORTED)}")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / Path(upload.filename).name
    dest.write_bytes(upload.file.read())
    return dest


@app.get("/api/status")
def status() -> dict:
    return _status()


@app.get("/api/corpus")
def list_corpus() -> dict:
    return {"papers": _corpus_papers(), "status": _status()}


@app.post("/api/corpus")
def add_paper(file: UploadFile = File(...)) -> dict:
    settings = get_settings()
    saved = _save_upload(file, settings.corpus_dir)
    # One rebuild at a time: a second upload waits here instead of racing the first.
    with _INGEST_LOCK:
        result = ingest_corpus(rebuild=True)
    _rebuild_style_card_async()
    return {
        "added": saved.name,
        "per_file": result["per_file"],
        "papers": _corpus_papers(),
        "status": _status(),
    }


@app.delete("/api/corpus/{name}")
def delete_paper(name: str) -> dict:
    settings = get_settings()
    target = settings.corpus_dir / name
    # guard against path traversal (e.g. "../foo")
    if not target.resolve().is_relative_to(settings.corpus_dir.resolve()):
        raise HTTPException(400, "Invalid file name.")
    if not target.exists():
        raise HTTPException(404, "No such paper.")
    with _INGEST_LOCK:
        target.unlink()
        ingest_corpus(rebuild=True)
    _rebuild_style_card_async()
    return {"deleted": name, "papers": _corpus_papers(), "status": _status()}


@app.get("/api/corpus/{name}/chunks")
def paper_chunks(name: str) -> dict:
    settings = get_settings()
    target = settings.corpus_dir / name
    if not target.resolve().is_relative_to(settings.corpus_dir.resolve()):
        raise HTTPException(400, "Invalid file name.")
    try:
        got = get_collection(create=False).get(
            where={"source": name}, include=["documents", "metadatas"]
        )
    except Exception:
        got = {"documents": [], "metadatas": []}
    rows = sorted(
        zip(got.get("documents") or [], got.get("metadatas") or []),
        key=lambda r: (r[1] or {}).get("chunk", 0),
    )
    chunks = [
        {"index": (m or {}).get("chunk", i), "chars": len(d), "text": d}
        for i, (d, m) in enumerate(rows)
    ]
    return {"name": name, "chunks": chunks}


@app.get("/api/search")
def search(q: str, k: int = 5) -> dict:
    """Live retrieval preview: the chunks the reviewer would pull for this text."""
    passages = retrieve(q, top_k=k)
    return {
        "query": q,
        "passages": [
            {"source": p.source, "score": round(p.score, 3), "text": p.text} for p in passages
        ],
    }


@app.post("/api/review")
def review(file: UploadFile = File(...)) -> dict:
    settings = get_settings()
    if Path(file.filename or "").suffix.lower() != ".docx":
        raise HTTPException(400, "Student drafts must be .docx")
    saved = _save_upload(file, settings.drafts_dir)
    result = analyze_draft(saved)

    review_id = uuid.uuid4().hex[:12]
    _REVIEWS[review_id] = {
        "draft_path": result["draft_path"],
        "suggestions_by_index": result["suggestions_by_index"],
    }

    sections = [
        {
            "title": sr["title"],
            "stype": sr["stype"],
            "suggestions": [
                {
                    "id": s["id"],
                    "severity": s.get("severity", "language"),
                    "reason": s.get("reason", ""),
                    "original": s.get("original", ""),
                    "suggestion": s.get("suggestion", ""),
                }
                for s in sr["suggestions"]
            ],
        }
        for sr in result["section_reviews"]
    ]
    total = sum(len(s["suggestions"]) for s in sections)
    return {
        "review_id": review_id,
        "draft": saved.name,
        "meta": {"backend": result["backend"], "context_used": result["context_used"], "suggestions": total},
        "sections": sections,
    }


class ExportRequest(BaseModel):
    accepted_ids: list[str]


@app.post("/api/review/{review_id}/export")
def export(review_id: str, req: ExportRequest) -> FileResponse:
    review = _REVIEWS.get(review_id)
    if review is None:
        raise HTTPException(404, "Unknown review id (server may have restarted).")

    accepted = set(req.accepted_ids)
    accepted_by_index: dict[int, list[dict]] = {}
    for idx, suggestions in review["suggestions_by_index"].items():
        kept = [s for s in suggestions if s.get("id") in accepted]
        if kept:
            accepted_by_index[idx] = kept

    draft_path: Path = review["draft_path"]
    out_dir = get_settings().output_dir / draft_path.stem
    out_path = out_dir / "accepted.docx"
    write_accepted_docx(draft_path, accepted_by_index, out_path)
    return FileResponse(
        out_path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=f"{draft_path.stem}-accepted.docx",
    )


# Serve the single-file frontend so the whole app runs from one server.
_WEB = Path(__file__).resolve().parents[2] / "web"
if _WEB.exists():
    app.mount("/", StaticFiles(directory=str(_WEB), html=True), name="web")

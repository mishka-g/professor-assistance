"""Extract plain text from corpus files (.pdf, .docx, .txt)."""

from __future__ import annotations

from pathlib import Path

SUPPORTED = {".pdf", ".docx", ".txt", ".md"}


def read_pdf(path: Path) -> str:
    import fitz  # PyMuPDF

    parts: list[str] = []
    with fitz.open(path) as doc:
        for page in doc:
            parts.append(page.get_text("text"))
    return "\n".join(parts)


def read_docx(path: Path) -> str:
    from docx import Document

    doc = Document(str(path))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


def read_txt(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def read_any(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return read_pdf(path)
    if suffix == ".docx":
        return read_docx(path)
    if suffix in {".txt", ".md"}:
        return read_txt(path)
    raise ValueError(f"Unsupported file type: {path.suffix}")


def iter_corpus_files(corpus_dir: Path):
    for path in sorted(corpus_dir.rglob("*")):
        if path.is_file() and path.suffix.lower() in SUPPORTED and path.name != "README.md":
            yield path

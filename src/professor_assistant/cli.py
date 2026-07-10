"""Command-line interface: `profa ingest | style | review | info`."""

from __future__ import annotations

from pathlib import Path

import typer

from .config import get_settings

app = typer.Typer(
    add_completion=False,
    help="professor-assistant: grounded scientific-writing reviewer.",
)


@app.command()
def info() -> None:
    """Show current configuration and corpus status."""
    s = get_settings()
    typer.echo(f"Backend        : {s.model_backend}")
    typer.echo(f"Local LLM      : {s.local_llm}  (host: {s.ollama_host})")
    typer.echo(f"Gemini         : {s.gemini_model}")
    typer.echo(f"API            : {s.api_provider} / {s.api_model}")
    typer.echo(f"Embeddings     : {s.embedding_model}")
    typer.echo(f"Corpus dir     : {s.corpus_dir}")
    typer.echo(f"Chroma dir     : {s.chroma_dir}")
    typer.echo(f"Style card     : {'present' if s.style_card_path.exists() else 'not built'}")
    try:
        from .store import get_collection

        c = get_collection(create=False)
        typer.echo(f"Corpus chunks  : {c.count()}")
    except Exception:
        typer.echo("Corpus chunks  : 0 (run `profa ingest`)")


@app.command()
def ingest(
    rebuild: bool = typer.Option(True, help="Rebuild the collection from scratch."),
) -> None:
    """Parse, chunk and embed the corpus in data/corpus/ into the local vector store."""
    from .ingest import ingest_corpus

    typer.echo("Ingesting corpus...")
    result = ingest_corpus(rebuild=rebuild)
    if result["files"] == 0:
        typer.secho(
            "No corpus files found. Add PDFs/DOCX/TXT to data/corpus/ and retry.",
            fg=typer.colors.YELLOW,
        )
        raise typer.Exit(code=1)
    typer.secho(
        f"Done: {result['files']} files -> {result['chunks']} chunks "
        f"(collection now has {result['collection_count']}).",
        fg=typer.colors.GREEN,
    )


@app.command()
def style() -> None:
    """Build the STYLE CARD (config/style_card.md) from the corpus."""
    from .style import build_style_card

    typer.echo("Building style card...")
    result = build_style_card()
    typer.secho(
        f"Style card written to {result['path']} "
        f"(backend={result['backend']}, {result['chars']} chars).",
        fg=typer.colors.GREEN,
    )


@app.command()
def review(
    draft: str = typer.Argument(..., help="Path to a .docx draft to review."),
) -> None:
    """Review a student draft; writes reviewed.docx + suggestions.md to output/<name>/."""
    from .review import review_draft

    path = Path(draft)
    typer.echo(f"Reviewing {path.name} ...")
    result = review_draft(path)
    typer.secho(
        f"Done ({result['backend']} backend): {result['suggestions']} suggestions "
        f"across {result['sections']} sections; {result['context_used']} corpus passages used.",
        fg=typer.colors.GREEN,
    )
    typer.echo(f"  - {result['reviewed_docx']}")
    typer.echo(f"  - {result['suggestions_md']}")
    if result["backend"] == "mock":
        typer.secho(
            "Note: mock backend uses heuristics only. Set MODEL_BACKEND=local, gemini, or api "
            "for full LLM-quality, corpus-grounded review.",
            fg=typer.colors.YELLOW,
        )


if __name__ == "__main__":
    app()

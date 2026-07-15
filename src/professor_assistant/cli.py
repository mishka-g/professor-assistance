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

    from .examples import find_example_pairs

    pairs = find_example_pairs(s.examples_dir)
    typer.echo(f"Example pairs  : {len(pairs)} found in {s.examples_dir}")
    try:
        from .store import get_collection

        ec = get_collection(create=False, name=s.examples_collection_name)
        typer.echo(f"Example edits  : {ec.count()} indexed (run `profa examples` to rebuild)")
    except Exception:
        typer.echo("Example edits  : 0 indexed (run `profa examples` after adding pairs)")


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
def examples() -> None:
    """Learn from before/after pairs in data/examples/ (*.before.docx / *.after.docx).

    Diffs each pair to extract phrase swaps, hedging/claim calibration, and section
    habits, then (re)builds the retrieval index `profa review` uses for few-shot
    grounding. Run this before `profa style` so the style card can fold in these
    edit habits too.
    """
    from .examples import (
        build_examples_index,
        examples_are_synthetic,
        extract_all_patterns,
        find_example_pairs,
        summarize_patterns,
    )

    settings = get_settings()
    pairs = find_example_pairs(settings.examples_dir)
    if not pairs:
        typer.secho(
            f"No before/after pairs found in {settings.examples_dir}. Add "
            "<name>.before.docx / <name>.after.docx pairs (see data/examples/README.md), "
            "or run `python scripts/make_sample_examples.py` for a testable demo set.",
            fg=typer.colors.YELLOW,
        )
        raise typer.Exit(code=1)

    if examples_are_synthetic(settings.examples_dir):
        typer.secho(
            f"⚠️  {settings.examples_dir} holds the SYNTHETIC demo set from "
            "scripts/make_sample_examples.py, not the professor's real edits. Everything "
            "learned below is for testing the pipeline only — the style card and reviewer "
            "will label it as demo data, not his real editing habits.",
            fg=typer.colors.YELLOW,
        )

    typer.echo(f"Learning edit patterns from {len(pairs)} pair(s)...")
    result = build_examples_index(rebuild=True)
    summary = summarize_patterns(extract_all_patterns())

    typer.secho(
        f"Done: {result['pairs']} pairs -> {result['patterns']} edit patterns indexed "
        f"(collection now has {result['collection_count']}).",
        fg=typer.colors.GREEN,
    )
    if summary["top_swaps"]:
        typer.echo("Top phrase swaps:")
        for (before, after), count in summary["top_swaps"][:5]:
            typer.echo(f'  "{before}" -> "{after}"  ({count}x)')
    typer.echo(
        "Next: `profa style` folds these habits into the style card, and "
        "`profa review <draft>` will use them as few-shot grounding."
    )


@app.command()
def style(
    use_examples: bool = typer.Option(
        True,
        "--examples/--no-examples",
        help="Fold data/examples/ before/after pairs into the style card (and rebuild their retrieval index).",
    ),
) -> None:
    """Build the STYLE CARD (config/style_card.md) from the corpus, plus before/after examples."""
    from .style import build_style_card

    typer.echo("Building style card...")
    result = build_style_card(use_examples=use_examples)
    typer.secho(
        f"Style card written to {result['path']} "
        f"(backend={result['backend']}, {result['chars']} chars).",
        fg=typer.colors.GREEN,
    )
    if result.get("examples_pairs"):
        typer.echo(
            f"  + folded in {result['examples_patterns']} edit patterns from "
            f"{result['examples_pairs']} before/after pair(s)."
        )
        if result.get("examples_synthetic"):
            typer.secho(
                "  ⚠️  data/examples/ currently holds the SYNTHETIC demo set — the style "
                "card's 'Edit habits' section is labeled as demo data, not the professor's "
                "real edits. Replace it with his real before/after drafts and re-run "
                "`profa examples && profa style` for genuine habits.",
                fg=typer.colors.YELLOW,
            )
    else:
        typer.echo("  (no before/after pairs found in data/examples/ — corpus-only style card.)")


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
            "Note: mock backend uses heuristics only. For quality demos set "
            "MODEL_BACKEND=gemini (recommended), or local / api.",
            fg=typer.colors.YELLOW,
        )


if __name__ == "__main__":
    app()

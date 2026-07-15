"""Learn from the professor's before/after edited drafts (`data/examples/`).

Pairs of `<name>.before.docx` / `<name>.after.docx` are diffed section-by-section to
extract concrete edit patterns (phrase swaps, hedging/claim calibration, trimmed filler,
section habits). These patterns are:

1. summarized into a markdown block folded into the STYLE CARD (`style.py`), and
2. indexed into a small local Chroma collection so `review.py` can retrieve the most
   relevant edits as few-shot grounding for a given draft section.

This is intentionally a lightweight diff, not ML: it is meant to reliably surface the
professor's real editing decisions when real before/after pairs are present, not to model
style probabilistically. Until real pairs exist, `data/examples/` may only hold the
synthetic demo set from `scripts/make_sample_examples.py` (see `examples_are_synthetic`) —
every summary/markdown renderer here must label that case as demo/synthetic rather than
presenting it as the professor's real editing habits.
"""

from __future__ import annotations

import difflib
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .config import get_settings
from .docx_io import read_sections
from .store import get_client, get_collection

# Phrases that flag an overreaching / unhedged claim (before) ...
_HEDGE_TARGETS = {
    "significant", "significantly", "proves", "prove", "proven", "obviously",
    "clearly", "definitely", "always", "never", "best", "perfect", "we believe",
    "we think", "certainly",
}
# ... and the calibrated phrasing the professor tends to replace them with (after).
_HEDGE_SOFTENERS = {
    "suggests", "suggest", "suggesting", "may", "might", "appears", "appear",
    "could", "indicates", "indicate", "likely", "consistent with", "these results suggest",
    "we hypothesize", "is expected to",
}
_FILLER_WORDS = {"very", "really", "quite", "extremely", "obviously", "clearly", "etc", "etc.", "a lot of"}

# Coordinating/subordinating words that, when they appear inside a short before/after
# anchor, are a strong signal the anchor spans a clause boundary rather than a single,
# reusable phrase — e.g. "it and then we" or "lot of applications, and obviously". Diffing
# a heavily rewritten sentence at the word level can otherwise "anchor" on a coincidental
# nearby match and hand back a before/after pair that reads as nonsense together (quality
# gate for Must-fix 1 — see tests/test_examples.py::test_classify_replace_* ).
_CLAUSE_BOUNDARY_WORDS = {"and", "but", "or", "then", "so", "because", "while", "although", "which"}

_MAX_PHRASE_TOKENS = 12
_MIN_SWAP_TOKENS = 1
# A clean "phrase swap" habit should be a short, single-clause anchor on both sides.
_MAX_SWAP_TOKENS = 6
# Hedging/claim-calibration edits are allowed to run a little longer (they're flagged, not
# blindly reused as a literal find/replace), but a multi-clause blob is a rewrite, not a habit.
_MAX_HEDGE_TOKENS = 10
# If one side is much longer than the other (by character count) it usually means the
# "before" anchor is a coincidental short match inside a much bigger rewritten passage.
_MAX_SWAP_CHAR_RATIO = 4.0


# Written by scripts/make_sample_examples.py into data/examples/ alongside the demo docx
# pairs it generates. Its presence means the pairs currently in that directory are
# synthetic/invented, not the professor's real edited drafts — every place that summarizes
# or quotes them (style card, prompts) must say so instead of claiming "his real edits"
# (Must-fix 3: style card honesty).
SYNTHETIC_MARKER_NAME = ".synthetic_examples"


def examples_are_synthetic(examples_dir: Path | None = None) -> bool:
    """True if data/examples/ currently holds the synthetic demo set, not real pairs."""
    directory = examples_dir or get_settings().examples_dir
    return (directory / SYNTHETIC_MARKER_NAME).exists()


@dataclass
class EditPattern:
    pair: str
    section: str
    kind: str  # phrase_swap | hedge_softened | hedge_added | trimmed_filler | deletion | insertion | rewrite
    before: str
    after: str


@dataclass
class ExampleMatch:
    before: str
    after: str
    section: str
    kind: str
    pair: str
    score: float


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #


def find_example_pairs(examples_dir: Path | None = None) -> list[tuple[str, Path, Path]]:
    """Return (stem, before_path, after_path) for every matched pair in data/examples/."""
    directory = examples_dir or get_settings().examples_dir
    if not directory.exists():
        return []
    pairs: list[tuple[str, Path, Path]] = []
    for before_path in sorted(directory.glob("*.before.docx")):
        stem = before_path.name[: -len(".before.docx")]
        after_path = directory / f"{stem}.after.docx"
        if after_path.exists():
            pairs.append((stem, before_path, after_path))
    return pairs


# --------------------------------------------------------------------------- #
# Diffing: section text -> edit patterns
# --------------------------------------------------------------------------- #


def _tokenize(text: str) -> list[str]:
    return re.findall(r"\S+", text)


def _is_clause_fragment(phrase: str) -> bool:
    """True if ``phrase`` looks like it spans a clause/item boundary rather than being a
    single, self-contained anchor — e.g. contains a comma/semicolon (usually joining
    distinct clauses or stacking multiple descriptors) or a coordinating/subordinating
    word. These anchors diff "correctly" in the SequenceMatcher sense but are not a
    coherent, reusable phrase habit, so they must not be surfaced as one (Must-fix 1).
    """
    if not phrase:
        return False
    if any(ch in phrase for ch in (",", ";", ":")):
        return True
    words = (w.strip(".,;:!?()").lower() for w in phrase.split())
    return any(w in _CLAUSE_BOUNDARY_WORDS for w in words if w)


def _classify_replace(before_phrase: str, after_phrase: str) -> str:
    b, a = before_phrase.lower(), after_phrase.lower()
    before_n, after_n = len(before_phrase.split()), len(after_phrase.split())
    multi_clause = _is_clause_fragment(before_phrase) or _is_clause_fragment(after_phrase)
    is_hedge = any(h in b for h in _HEDGE_TARGETS) or any(h in a for h in _HEDGE_SOFTENERS)

    # Hedging/claim-calibration edits get a bit more length slack than plain phrase swaps
    # (they're still flagged for review, never blindly reused as a literal find/replace),
    # but a multi-clause blob or an oversized anchor is a rewrite, not a coherent habit.
    if is_hedge and not multi_clause and before_n <= _MAX_HEDGE_TOKENS and after_n <= _MAX_HEDGE_TOKENS:
        return "hedge_softened"
    if multi_clause or before_n > _MAX_SWAP_TOKENS or after_n > _MAX_SWAP_TOKENS:
        return "rewrite"

    # A short anchor paired with a disproportionately longer replacement usually means
    # the diff latched onto a coincidental short match inside a larger rewrite, not a
    # crisp phrase-for-phrase swap — treat it as a general rewrite instead.
    shortest, longest = min(before_n, after_n), max(before_n, after_n)
    if shortest <= 2 and longest > 2 * shortest:
        return "rewrite"
    before_chars, after_chars = len(before_phrase), len(after_phrase)
    shortest_c, longest_c = min(before_chars, after_chars), max(before_chars, after_chars)
    if shortest_c and longest_c / shortest_c > _MAX_SWAP_CHAR_RATIO:
        return "rewrite"
    return "phrase_swap"


def _classify_insert(phrase: str) -> str:
    return "hedge_added" if any(h in phrase.lower() for h in _HEDGE_SOFTENERS) else "insertion"


def _classify_delete(phrase: str) -> str:
    return "trimmed_filler" if any(w in phrase.lower() for w in _FILLER_WORDS) else "deletion"


def _diff_section_text(before_text: str, after_text: str, section: str, pair: str) -> list[EditPattern]:
    before_tokens = _tokenize(before_text)
    after_tokens = _tokenize(after_text)
    sm = difflib.SequenceMatcher(None, before_tokens, after_tokens, autojunk=False)
    patterns: list[EditPattern] = []

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        # Cap huge blocks so a whole-paragraph rewrite doesn't drown out crisp patterns.
        bi2 = min(i2, i1 + _MAX_PHRASE_TOKENS)
        aj2 = min(j2, j1 + _MAX_PHRASE_TOKENS)
        before_phrase = " ".join(before_tokens[i1:bi2]).strip(" ,.;:")
        after_phrase = " ".join(after_tokens[j1:aj2]).strip(" ,.;:")

        if tag == "replace" and before_phrase and after_phrase:
            if before_phrase.lower() == after_phrase.lower():
                continue
            kind = _classify_replace(before_phrase, after_phrase)
            patterns.append(EditPattern(pair, section, kind, before_phrase, after_phrase))
        elif tag == "delete" and before_phrase and (i2 - i1) >= _MIN_SWAP_TOKENS:
            patterns.append(EditPattern(pair, section, _classify_delete(before_phrase), before_phrase, ""))
        elif tag == "insert" and after_phrase and (j2 - j1) >= _MIN_SWAP_TOKENS:
            patterns.append(EditPattern(pair, section, _classify_insert(after_phrase), "", after_phrase))

    return patterns


def extract_patterns_from_pair(pair: str, before_path: Path, after_path: Path) -> list[EditPattern]:
    """Diff one before/after pair, section-by-section (matched by section type)."""
    _, before_sections = read_sections(before_path)
    _, after_sections = read_sections(after_path)

    before_by_type: dict[str, str] = {}
    order: list[str] = []
    for s in before_sections:
        if s.stype == "references" or not s.paras or s.stype in before_by_type:
            continue
        before_by_type[s.stype] = s.text
        order.append(s.stype)

    after_by_type: dict[str, str] = {}
    for s in after_sections:
        if s.stype == "references" or not s.paras:
            continue
        after_by_type.setdefault(s.stype, s.text)

    patterns: list[EditPattern] = []
    for stype in order:
        if stype not in after_by_type:
            continue
        patterns.extend(_diff_section_text(before_by_type[stype], after_by_type[stype], stype, pair))
    return patterns


def extract_all_patterns(examples_dir: Path | None = None) -> list[EditPattern]:
    patterns: list[EditPattern] = []
    for pair, before_path, after_path in find_example_pairs(examples_dir):
        try:
            patterns.extend(extract_patterns_from_pair(pair, before_path, after_path))
        except Exception as exc:
            print(f"[examples] skip pair '{pair}': {exc}")
    return patterns


# --------------------------------------------------------------------------- #
# Summaries (fed into the style card)
# --------------------------------------------------------------------------- #


def summarize_patterns(patterns: list[EditPattern]) -> dict:
    swap_counter: Counter[tuple[str, str]] = Counter()
    hedge_counter: Counter[tuple[str, str]] = Counter()
    deletion_counter: Counter[str] = Counter()
    insertion_counter: Counter[str] = Counter()
    by_section: Counter[str] = Counter()

    for p in patterns:
        by_section[p.section] += 1
        if p.kind == "phrase_swap":
            swap_counter[(p.before, p.after)] += 1
        elif p.kind in ("hedge_softened", "hedge_added"):
            hedge_counter[(p.before or "(added)", p.after or "(removed)")] += 1
        elif p.kind in ("trimmed_filler", "deletion"):
            deletion_counter[p.before] += 1
        elif p.kind == "insertion":
            insertion_counter[p.after] += 1

    return {
        "pairs": sorted({p.pair for p in patterns}),
        "patterns": len(patterns),
        "top_swaps": swap_counter.most_common(12),
        "top_hedges": hedge_counter.most_common(8),
        "top_deletions": deletion_counter.most_common(8),
        "top_insertions": insertion_counter.most_common(8),
        "by_section": dict(by_section),
    }


def format_examples_markdown(summary: dict, synthetic: bool | None = None) -> str:
    """Render a summary as a markdown block to append to the style card / its prompt.

    ``synthetic`` controls the honesty disclaimer at the top of the block (Must-fix 3):
    when the pairs in ``data/examples/`` are the generated demo set (see
    ``examples_are_synthetic``), this must say so instead of presenting them as the
    professor's real editing decisions. Pass it explicitly when the summary was built from
    a non-default examples dir; otherwise it's resolved from the default settings dir.
    """
    if not summary or not summary.get("patterns"):
        return ""
    if synthetic is None:
        synthetic = examples_are_synthetic()
    if synthetic:
        lines = ["## Edit habits (SYNTHETIC/DEMO before/after examples)", ""]
        lines.append(
            f"_⚠️ Derived from {len(summary['pairs'])} **synthetic demo** pair(s) generated by "
            f"`scripts/make_sample_examples.py` ({summary['patterns']} edits total) — these are "
            f"NOT the professor's real edits, only a testable stand-in. Do not treat them as his "
            f"actual habits; replace `data/examples/` with his real before/after drafts and "
            f"re-run `profa examples && profa style` to rebuild this section from genuine edits._"
        )
    else:
        lines = ["## Edit habits (from before/after examples)", ""]
        lines.append(
            f"_Derived from {len(summary['pairs'])} before/after pair(s) in `data/examples/` "
            f"({summary['patterns']} edits total) — his editing decisions on those drafts; "
            f"weight them more heavily than generic corpus phrasing when they conflict._"
        )
    lines.append("")
    who = "seen in the sample data" if synthetic else "he consistently makes"
    trims_who = "trimmed in the sample data" if synthetic else "he trims"
    adds_who = "added in the sample data" if synthetic else "he adds"
    if summary["top_swaps"]:
        lines.append(f"### Phrase swaps {who}")
        for (before, after), count in summary["top_swaps"]:
            lines.append(f'- "{before}" → "{after}" (seen {count}x)')
        lines.append("")
    if summary["top_hedges"]:
        lines.append("### Hedging / claim calibration")
        for (before, after), count in summary["top_hedges"]:
            lines.append(f'- "{before}" → "{after}" (seen {count}x)')
        lines.append("")
    if summary["top_deletions"]:
        joined = ", ".join(f'"{w}" ({c}x)' for w, c in summary["top_deletions"])
        lines.append(f"### Words/phrases {trims_who}\n- {joined}")
        lines.append("")
    if summary["top_insertions"]:
        joined = ", ".join(f'"{w}" ({c}x)' for w, c in summary["top_insertions"])
        lines.append(f"### Words/phrases {adds_who}\n- {joined}")
        lines.append("")
    if summary["by_section"]:
        parts = ", ".join(f"{k}: {v}" for k, v in sorted(summary["by_section"].items()))
        lines.append(f"### Section habit counts\n- {parts}")
        lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Retrieval index (few-shot grounding at review time)
# --------------------------------------------------------------------------- #


def build_examples_index(rebuild: bool = True) -> dict:
    """(Re)build the local vector index of edit patterns for few-shot retrieval."""
    settings = get_settings()
    patterns = extract_all_patterns()

    if rebuild:
        client = get_client()
        try:
            client.delete_collection(settings.examples_collection_name)
        except Exception:
            pass

    collection = get_collection(create=True, name=settings.examples_collection_name)

    if patterns:
        ids, docs, metas = [], [], []
        for i, p in enumerate(patterns):
            # Embed the "before" side (draft text resembles it); fall back to "after" for
            # pure insertions where there is no "before" phrase to match against.
            doc = p.before or p.after
            if not doc:
                continue
            ids.append(f"{p.pair}::{p.section}::{p.kind}::{i}")
            docs.append(doc)
            metas.append({"after": p.after, "section": p.section, "kind": p.kind, "pair": p.pair})
        if docs:
            collection.add(ids=ids, documents=docs, metadatas=metas)

    pairs = sorted({p.pair for p in patterns})
    return {"pairs": len(pairs), "patterns": len(patterns), "collection_count": collection.count()}


def retrieve_examples(query: str, top_k: int | None = None) -> list[ExampleMatch]:
    """Retrieve the most relevant indexed edit patterns for a piece of draft text."""
    settings = get_settings()
    k = top_k or settings.retrieval_top_k
    if not query.strip():
        return []
    try:
        collection = get_collection(create=False, name=settings.examples_collection_name)
    except Exception:
        return []
    if collection.count() == 0:
        return []

    res = collection.query(
        query_texts=[query[:2000]],
        n_results=min(k, collection.count()),
        include=["documents", "metadatas", "distances"],
    )
    matches: list[ExampleMatch] = []
    docs = res.get("documents", [[]])[0]
    metas = res.get("metadatas", [[]])[0]
    dists = res.get("distances", [[]])[0]
    for doc, meta, dist in zip(docs, metas, dists):
        meta = meta or {}
        matches.append(
            ExampleMatch(
                before=doc,
                after=str(meta.get("after", "")),
                section=str(meta.get("section", "?")),
                kind=str(meta.get("kind", "edit")),
                pair=str(meta.get("pair", "?")),
                score=1.0 - float(dist),
            )
        )
    return matches


def format_examples_context(matches: list[ExampleMatch], max_chars: int = 2000, prefix: str = "E") -> str:
    """Render retrieved edit patterns as a numbered context block for the reviewer prompt."""
    out: list[str] = []
    used = 0
    for i, m in enumerate(matches, 1):
        label = f"{prefix}{i}"
        after = m.after or "(removed, no replacement)"
        before = m.before or "(new addition)"
        block = f"[{label}] (from: {m.pair}, section: {m.section}, kind: {m.kind})\nBEFORE: {before}\nAFTER:  {after}\n"
        if used + len(block) > max_chars:
            break
        out.append(block)
        used += len(block)
    return "\n".join(out) if out else "(no professor before/after examples indexed yet — run `profa examples`)"

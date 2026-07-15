"""Core review pipeline: draft -> retrieve corpus context -> suggestions -> outputs."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from . import examples as examples_lib
from . import llm
from .config import get_settings
from .docx_io import Section, read_sections, write_reviewed_docx, write_suggestions_md
from .retrieve import format_context, retrieve

SKIP_TYPES = {"references"}


# --------------------------------------------------------------------------- #
# Heuristic reviewer (used when MODEL_BACKEND=mock; no LLM required)
# --------------------------------------------------------------------------- #

_HEURISTICS = [
    (r"\bin order to\b", "clarity", "Wordy; 'to' is usually enough.", lambda m: "to"),
    (r"\b(very|really|quite|extremely)\s+", "language", "Vague intensifier; prefer a precise term or drop it.", lambda m: ""),
    (r"\ba lot of\b", "language", "Informal; use 'many' or a specific quantity.", lambda m: "many"),
    (r"\bIn recent years\b", "clarity", "Generic opener; start with the specific problem.", lambda m: ""),
    (r"\bIt is well known that\b", "clarity", "Unsupported framing; state the fact and cite it.", lambda m: ""),
    (r"\bobviously\b|\bclearly\b", "language", "Avoid asserting obviousness in scientific writing.", lambda m: ""),
    (r"\betc\.?\b", "language", "Avoid 'etc.'; list the relevant items explicitly.", lambda m: ""),
    (r"\bcan not\b", "language", "Spelling: use 'cannot'.", lambda m: "cannot"),
    (r"\s{2,}", "language", "Double space.", lambda m: " "),
    (r"\s+,", "language", "Space before comma.", lambda m: ","),
    (r"\bwe think\b|\bwe believe\b", "content", "Opinion phrasing; tie the claim to evidence or hedge appropriately.", lambda m: None),
    (r"\bsignificant(ly)?\b", "content", "'Significant' implies statistics; ensure it is supported (flag only).", lambda m: None),
]

_LONG_SENTENCE_WORDS = 40


@lru_cache
def _example_swap_patterns() -> tuple[tuple[re.Pattern, str, str], ...]:
    """Compile the top before/after phrase swaps (from data/examples/) into regexes.

    Lets even the `mock` heuristic reviewer benefit from the professor's real edits,
    without needing an LLM. Cached per process; re-run the process after `profa examples`
    picks up new/changed pairs.
    """
    try:
        patterns = examples_lib.extract_all_patterns()
    except Exception:
        return ()
    seen: dict[str, tuple[str, str, str]] = {}
    for p in patterns:
        if p.kind != "phrase_swap":
            continue
        before, after = p.before.strip(), p.after.strip()
        if len(before.split()) < 2 or not after or before.lower() == after.lower():
            continue
        seen.setdefault(before.lower(), (before, after, p.pair))
    return tuple(
        (re.compile(re.escape(before), flags=re.IGNORECASE), after, pair)
        for before, after, pair in list(seen.values())[:25]
    )


def _example_swap_reason(pair: str) -> str:
    """Human-readable 'reason' for a suggestion sourced from data/examples/ (not the
    grounded_in citation itself — that field is owned by the web UI). Must not claim these
    are the professor's real edits when data/examples/ currently holds the synthetic demo
    set (Must-fix 3).
    """
    if examples_lib.examples_are_synthetic():
        return f"Matches an edit in the synthetic demo pair '{pair}' — verify before relying on it."
    return f"Matches an edit the professor made in a similar draft ('{pair}')."


def heuristic_review(section: Section) -> list[dict]:
    suggestions: list[dict] = []
    for idx, text in section.paras:
        for pattern, severity, reason, fix in _HEURISTICS:
            for m in re.finditer(pattern, text, flags=re.IGNORECASE):
                original = m.group(0).strip() or text[max(0, m.start() - 15): m.end() + 15]
                replacement = fix(m)
                # replacement is None -> flag only (verify manually, not auto-applied).
                # replacement "" -> delete the phrase; non-empty -> replace it. Both applicable.
                suggestion = "" if replacement is None else replacement.strip()
                suggestions.append(
                    {
                        "para_index": idx,
                        "original": original,
                        "suggestion": suggestion,
                        "reason": reason,
                        "severity": severity,
                        "applicable": replacement is not None,
                        "grounded_in": [],
                    }
                )
                break  # one hit per pattern per paragraph is enough

        # Edits learned from data/examples/: a real phrase he swapped in a similar draft.
        for pattern, after, pair in _example_swap_patterns():
            m = pattern.search(text)
            if m:
                suggestions.append(
                    {
                        "para_index": idx,
                        "original": m.group(0),
                        "suggestion": after,
                        "reason": _example_swap_reason(pair),
                        "severity": "language",
                        "applicable": True,
                        "grounded_in": [f"example: {pair}"],
                    }
                )

        # long sentence check
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            if len(sentence.split()) > _LONG_SENTENCE_WORDS:
                suggestions.append(
                    {
                        "para_index": idx,
                        "original": sentence[:120] + ("..." if len(sentence) > 120 else ""),
                        "suggestion": "",
                        "reason": f"Long sentence (~{len(sentence.split())} words); consider splitting.",
                        "severity": "clarity",
                        "applicable": False,
                        "grounded_in": [],
                    }
                )
                break
    return suggestions


def _enforce_content_flag_only(suggestions: list[dict]) -> None:
    """Hard safety net: 'content' severity must never carry a silent rewrite.

    Applied regardless of backend/path — content issues (unsupported claims, invented
    numbers, overreaching statements) are always flagged for the professor to verify,
    never auto-rewritten. This is deliberately redundant with prompt-level instructions.
    """
    for s in suggestions:
        if s.get("severity") == "content" and s.get("suggestion"):
            s["suggestion"] = ""
            s["applicable"] = False
        s.setdefault("grounded_in", [])


# --------------------------------------------------------------------------- #
# LLM reviewer (used when MODEL_BACKEND=local|gemini|api)
# --------------------------------------------------------------------------- #

def _extract_json(text: str) -> dict:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start : end + 1]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"suggestions": []}


def _map_index(section: Section, original: str) -> int:
    original = (original or "").strip()
    if original:
        needle = original[:40].lower()
        for idx, text in section.paras:
            if needle and needle in text.lower():
                return idx
    return section.paras[0][0] if section.paras else 0


def llm_review_section(
    section: Section, context: str, style_card: str, example_context: str = ""
) -> list[dict]:
    settings = get_settings()
    system = settings.prompt("reviewer_system")
    section_rules = settings.prompt("section_rules")
    synthetic_examples = examples_lib.examples_are_synthetic()
    if synthetic_examples:
        examples_label = (
            'SYNTHETIC/DEMO EXAMPLES (⚠️ generated by scripts/make_sample_examples.py for '
            'pipeline testing — NOT the professor\'s real edits; do not present these as his '
            'editing decisions, and prefer the retrieved context above when they conflict'
        )
    else:
        examples_label = (
            "PROFESSOR'S PAST EDITS (before -> after changes he made on similar student drafts, "
            "from data/examples/; prefer this exact phrasing/decision over the retrieved papers "
            "above when they conflict"
        )

    user = f"""SECTION RULES:
{section_rules}

STYLE CARD:
{style_card or '(none provided)'}

RETRIEVED CONTEXT (from the professor's published papers — prefer this terminology/phrasing;
cite the ones you used by label, e.g. "C2", in `grounded_in`):
{context}

{examples_label} — cite the ones you used by label, e.g. "E1", in `grounded_in`):
{example_context or '(no before/after examples indexed yet)'}

SECTION TYPE: {section.stype}
SECTION TITLE: {section.title}

DRAFT SECTION TO REVIEW:
\"\"\"
{section.text}
\"\"\"

Return the JSON object described in the system prompt."""

    raw = llm.complete(system, user)
    data = _extract_json(raw)
    out: list[dict] = []
    for s in data.get("suggestions", []):
        if not isinstance(s, dict):
            continue
        s.setdefault("severity", "language")
        s.setdefault("suggestion", "")
        s.setdefault("reason", "")
        s.setdefault("original", "")
        s.setdefault("grounded_in", [])
        if not isinstance(s["grounded_in"], list):
            s["grounded_in"] = [s["grounded_in"]] if s["grounded_in"] else []
        # Hard guard: content severity is flag-only, never a silent rewrite of a claim —
        # enforced here even if the model ignores the system-prompt instruction.
        if s["severity"] == "content":
            s["suggestion"] = ""
        # A non-empty suggestion is an applicable rewrite; an empty one is a flag to verify.
        s["applicable"] = bool((s.get("suggestion") or "").strip())
        s["para_index"] = _map_index(section, s.get("original", ""))
        out.append(s)
    return out


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #

def analyze_draft(draft_path: Path, *, style_card_path: Path | None = None) -> dict:
    """Review a draft and return structured results (no files written).

    Each suggestion is given a stable `id` ("<section>-<n>") so a UI can track
    per-suggestion accept/skip decisions.

    ``style_card_path`` optionally overrides ``Settings.style_card_path`` so evals
    (and later example-trained cards from Horizon 1) can inject a card without
    rewriting the default config file.
    """
    settings = get_settings()
    draft_path = Path(draft_path)
    if not draft_path.exists():
        raise FileNotFoundError(draft_path)

    _doc, sections = read_sections(draft_path)
    card_path = Path(style_card_path) if style_card_path is not None else settings.style_card_path
    style_card = ""
    if card_path.exists():
        style_card = card_path.read_text(encoding="utf-8")

    backend = llm.backend()
    section_reviews: list[dict] = []
    suggestions_by_index: dict[int, list[dict]] = {}
    context_used = 0
    section_i = 0

    for section in sections:
        if section.stype in SKIP_TYPES or not section.paras:
            continue

        passages = retrieve(section.text[:1500])
        example_matches = examples_lib.retrieve_examples(section.text[:1500])
        context_used += len(passages)
        context = format_context(passages, prefix="C")
        example_context = examples_lib.format_examples_context(example_matches, prefix="E")

        if backend == "mock":
            suggestions = heuristic_review(section)
        else:
            suggestions = llm_review_section(section, context, style_card, example_context)
            # Resolve the model's "C1"/"E2"-style citations into readable sources so
            # suggestions.md / the web API can show "grounded in: ...".
            refs = {f"C{i}": f"corpus: {p.source}" for i, p in enumerate(passages, 1)}
            refs.update(
                {
                    f"E{i}": f"example: {m.pair} ({m.section}/{m.kind})"
                    for i, m in enumerate(example_matches, 1)
                }
            )
            for s in suggestions:
                s["grounded_in"] = [refs[t] for t in s.get("grounded_in", []) if t in refs]

        _enforce_content_flag_only(suggestions)

        para_by_idx = dict(section.paras)  # {global_index: paragraph text}
        for n, s in enumerate(suggestions):
            s["id"] = f"{section_i}-{n}"
            idx = int(s.get("para_index", section.paras[0][0] if section.paras else 0))
            s["paragraph"] = para_by_idx.get(idx, "")
            suggestions_by_index.setdefault(idx, []).append(s)

        section_reviews.append(
            {"title": section.title, "stype": section.stype, "suggestions": suggestions}
        )
        section_i += 1

    return {
        "draft_path": draft_path,
        "backend": backend,
        "context_used": context_used,
        "section_reviews": section_reviews,
        "suggestions_by_index": suggestions_by_index,
    }


def review_draft(draft_path: Path) -> dict:
    settings = get_settings()
    result = analyze_draft(draft_path)
    draft_path = result["draft_path"]
    section_reviews = result["section_reviews"]
    suggestions_by_index = result["suggestions_by_index"]
    backend = result["backend"]
    context_used = result["context_used"]

    stem = draft_path.stem
    out_dir = settings.output_dir / stem
    reviewed_docx = out_dir / "reviewed.docx"
    suggestions_md = out_dir / "suggestions.md"

    meta = {"backend": backend, "context_used": context_used}
    write_reviewed_docx(draft_path, suggestions_by_index, reviewed_docx)
    write_suggestions_md(draft_path.name, section_reviews, suggestions_md, meta=meta)

    total = sum(len(sr["suggestions"]) for sr in section_reviews)
    return {
        "draft": draft_path.name,
        "backend": backend,
        "sections": len(section_reviews),
        "suggestions": total,
        "context_used": context_used,
        "reviewed_docx": str(reviewed_docx),
        "suggestions_md": str(suggestions_md),
    }

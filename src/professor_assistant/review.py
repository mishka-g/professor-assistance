"""Core review pipeline: draft -> retrieve corpus context -> suggestions -> outputs."""

from __future__ import annotations

import json
import re
from pathlib import Path

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
                    }
                )
                break  # one hit per pattern per paragraph is enough

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
                    }
                )
                break
    return suggestions


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


def llm_review_section(section: Section, context: str, style_card: str) -> list[dict]:
    settings = get_settings()
    system = settings.prompt("reviewer_system")
    section_rules = settings.prompt("section_rules")

    user = f"""SECTION RULES:
{section_rules}

STYLE CARD:
{style_card or '(none provided)'}

RETRIEVED CONTEXT (from the professor's published work — prefer this terminology/phrasing):
{context}

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
        # A non-empty suggestion is an applicable rewrite; an empty one is a flag to verify.
        s["applicable"] = bool((s.get("suggestion") or "").strip())
        s["para_index"] = _map_index(section, s.get("original", ""))
        out.append(s)
    return out


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #

def analyze_draft(draft_path: Path) -> dict:
    """Review a draft and return structured results (no files written).

    Each suggestion is given a stable `id` ("<section>-<n>") so a UI can track
    per-suggestion accept/skip decisions.
    """
    settings = get_settings()
    draft_path = Path(draft_path)
    if not draft_path.exists():
        raise FileNotFoundError(draft_path)

    _doc, sections = read_sections(draft_path)
    style_card = ""
    if settings.style_card_path.exists():
        style_card = settings.style_card_path.read_text(encoding="utf-8")

    backend = llm.backend()
    section_reviews: list[dict] = []
    suggestions_by_index: dict[int, list[dict]] = {}
    context_used = 0
    section_i = 0

    for section in sections:
        if section.stype in SKIP_TYPES or not section.paras:
            continue

        passages = retrieve(section.text[:1500])
        context_used += len(passages)
        context = format_context(passages)

        if backend == "mock":
            suggestions = heuristic_review(section)
        else:
            suggestions = llm_review_section(section, context, style_card)

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

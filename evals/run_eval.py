#!/usr/bin/env python3
"""Tiny eval harness for professor-assistant review quality.

Scores a fixed draft set against golden expectation themes:
  - theme hit (expected phrases appear in suggestions)
  - severity mix (not all language, not runaway content)
  - no invented facts (content is flag-only; rewrites don't invent numbers)
  - optional retrieval hit (when corpus is ingested / --require-retrieval)

Defaults to MODEL_BACKEND=mock for fast, deterministic CI-like checks. For
demo-quality scoring against a real backend:

  python evals/run_eval.py --backend gemini --require-retrieval

Usage:
  python evals/run_eval.py
  python evals/run_eval.py --style-card config/style_card.md
  python evals/run_eval.py --backend gemini --require-retrieval
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

EVALS = Path(__file__).resolve().parent
CASES_PATH = EVALS / "cases.json"
# Decimals or multi-digit ints — single digits are too noisy as "invented facts".
_NUMBER = re.compile(r"\d+\.\d+|\b\d{2,}\b")


def _ensure_fixtures() -> None:
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    missing = [
        EVALS / c["fixture"]
        for c in cases["cases"]
        if not (EVALS / c["fixture"]).exists()
    ]
    if missing:
        sys.path.insert(0, str(EVALS))
        from build_fixtures import build_all

        build_all()


def _flat_suggestions(result: dict) -> list[dict]:
    out: list[dict] = []
    for sr in result["section_reviews"]:
        out.extend(sr["suggestions"])
    return out


def _haystack(s: dict, where: str) -> str:
    parts = []
    if where in ("original", "original_or_reason"):
        parts.append(s.get("original") or "")
    if where in ("reason", "original_or_reason"):
        parts.append(s.get("reason") or "")
    if where == "any":
        parts.extend(
            [
                s.get("original") or "",
                s.get("reason") or "",
                s.get("suggestion") or "",
            ]
        )
    return " ".join(parts).lower()


def score_themes(suggestions: list[dict], themes: list[dict]) -> dict:
    hits = []
    misses = []
    for theme in themes:
        matched = False
        for s in suggestions:
            if theme.get("severity") and s.get("severity") != theme["severity"]:
                continue
            hay = _haystack(s, theme.get("where", "original_or_reason"))
            if any(m.lower() in hay for m in theme["match_any"]):
                matched = True
                break
        (hits if matched else misses).append(theme["id"])
    return {
        "pass": len(misses) == 0,
        "hits": hits,
        "misses": misses,
        "score": len(hits) / max(1, len(themes)),
    }


def score_severity_mix(suggestions: list[dict], expect: dict) -> dict:
    n = len(suggestions)
    content = sum(1 for s in suggestions if s.get("severity") == "content")
    non_content = n - content
    frac = content / n if n else 0.0
    checks = {
        "min_suggestions": n >= expect.get("min_suggestions", 0),
        "min_non_content": non_content >= expect.get("min_non_content", 0),
        "min_content": content >= expect.get("min_content", 0),
        "max_content_fraction": frac <= expect.get("max_content_fraction", 1.0),
    }
    return {
        "pass": all(checks.values()),
        "counts": {
            "total": n,
            "content": content,
            "non_content": non_content,
            "content_fraction": round(frac, 3),
        },
        "checks": checks,
    }


def score_no_invented_facts(suggestions: list[dict]) -> dict:
    """Fail if content suggestions rewrite claims, or rewrites invent new numbers."""
    violations: list[str] = []
    for s in suggestions:
        sev = s.get("severity", "language")
        original = (s.get("original") or "").strip()
        suggestion = (s.get("suggestion") or "").strip()
        if sev == "content" and suggestion:
            violations.append(
                f"content suggestion rewrites text (id={s.get('id')}): {suggestion[:80]!r}"
            )
        if suggestion:
            for num in _NUMBER.findall(suggestion):
                if num not in original:
                    violations.append(
                        f"rewrite invents number {num!r} (id={s.get('id')})"
                    )
                    break
    return {"pass": len(violations) == 0, "violations": violations}


def score_retrieval(result: dict, required: bool) -> dict:
    used = int(result.get("context_used") or 0)
    if not required:
        return {"pass": True, "skipped": True, "context_used": used}
    return {"pass": used > 0, "skipped": False, "context_used": used}


def run_case(
    case: dict,
    *,
    style_card: Path | None,
    require_retrieval: bool,
) -> dict:
    from professor_assistant.review import analyze_draft

    draft = EVALS / case["fixture"]
    result = analyze_draft(draft, style_card_path=style_card)
    suggestions = _flat_suggestions(result)

    theme = score_themes(suggestions, case.get("expect_themes", []))
    severity = score_severity_mix(suggestions, case.get("expect_severity_mix", {}))
    facts = (
        score_no_invented_facts(suggestions)
        if case.get("expect_no_invented_facts", True)
        else {"pass": True, "violations": [], "skipped": True}
    )
    retrieval_needed = require_retrieval or case.get("expect_retrieval_hit", False)
    retrieval = score_retrieval(result, retrieval_needed)

    parts = {
        "themes": theme,
        "severity_mix": severity,
        "no_invented_facts": facts,
        "retrieval": retrieval,
    }
    passed = all(p["pass"] for p in parts.values())
    return {
        "id": case["id"],
        "pass": passed,
        "backend": result["backend"],
        "suggestion_count": len(suggestions),
        "scores": parts,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run professor-assistant review evals.")
    parser.add_argument(
        "--cases",
        type=Path,
        default=CASES_PATH,
        help="Path to cases.json (default: evals/cases.json)",
    )
    parser.add_argument(
        "--backend",
        default="mock",
        choices=["mock", "gemini", "local", "api"],
        help="Generation backend for this run (default: mock for CI-like checks). "
        "Use gemini for demo-quality scoring.",
    )
    parser.add_argument(
        "--style-card",
        type=Path,
        default=None,
        help="Optional style card override (Horizon 1 hook for example-trained cards).",
    )
    parser.add_argument(
        "--require-retrieval",
        action="store_true",
        help="Fail cases when no corpus passages were retrieved (needs `profa ingest`).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON summary only.",
    )
    args = parser.parse_args()

    # Force backend before settings are loaded (overrides .env for this process).
    os.environ["MODEL_BACKEND"] = args.backend

    from professor_assistant.config import get_settings

    get_settings.cache_clear()

    _ensure_fixtures()
    bundle = json.loads(args.cases.read_text(encoding="utf-8"))
    style_card = args.style_card
    if style_card is None and bundle.get("style_card"):
        style_card = Path(bundle["style_card"])
        if not style_card.is_absolute():
            style_card = ROOT / style_card

    results = [
        run_case(case, style_card=style_card, require_retrieval=args.require_retrieval)
        for case in bundle["cases"]
    ]
    summary = {
        "pass": all(r["pass"] for r in results),
        "passed": sum(1 for r in results if r["pass"]),
        "total": len(results),
        "backend": args.backend,
        "cases": results,
    }

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"backend={args.backend}")
        for r in results:
            mark = "PASS" if r["pass"] else "FAIL"
            print(
                f"[{mark}] {r['id']}  ({r['suggestion_count']} suggestions, "
                f"backend={r['backend']})"
            )
            if not r["pass"]:
                scores = r["scores"]
                if not scores["themes"]["pass"]:
                    print(f"       themes missed: {scores['themes']['misses']}")
                if not scores["severity_mix"]["pass"]:
                    print(f"       severity mix: {scores['severity_mix']}")
                if not scores["no_invented_facts"]["pass"]:
                    for v in scores["no_invented_facts"]["violations"]:
                        print(f"       invented: {v}")
                if not scores["retrieval"]["pass"]:
                    print(
                        f"       retrieval: context_used="
                        f"{scores['retrieval']['context_used']}"
                    )
        print()
        print(
            f"{'PASS' if summary['pass'] else 'FAIL'}: "
            f"{summary['passed']}/{summary['total']} cases"
        )

    return 0 if summary["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

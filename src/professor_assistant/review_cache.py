"""Local-file persistence for web reviews and Accept/Skip feedback.

Reviews survive API restarts (JSON under storage/reviews/). Feedback is a
JSONL preference signal for future ranking (storage/feedback/accept_skip.jsonl).
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from .config import get_settings

_LOCK = threading.Lock()


def _reviews_dir() -> Path:
    d = get_settings().reviews_dir
    d.mkdir(parents=True, exist_ok=True)
    return d


def _feedback_path() -> Path:
    p = get_settings().feedback_path
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def save_review(review_id: str, payload: dict) -> None:
    """Persist a review so Accept/Skip/export survives process restart."""
    path = _reviews_dir() / f"{review_id}.json"
    data = {
        "draft_path": str(payload["draft_path"]),
        "suggestions_by_index": {
            str(k): v for k, v in payload["suggestions_by_index"].items()
        },
        "section_reviews": payload.get("section_reviews", []),
        "backend": payload.get("backend"),
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }
    with _LOCK:
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_review(review_id: str) -> dict | None:
    path = _reviews_dir() / f"{review_id}.json"
    if not path.exists():
        return None
    with _LOCK:
        raw = json.loads(path.read_text(encoding="utf-8"))
    suggestions_by_index: dict[int, list[dict]] = {}
    for k, v in (raw.get("suggestions_by_index") or {}).items():
        suggestions_by_index[int(k)] = v
    return {
        "draft_path": Path(raw["draft_path"]),
        "suggestions_by_index": suggestions_by_index,
        "section_reviews": raw.get("section_reviews", []),
        "backend": raw.get("backend"),
    }


def log_accept_skip(
    review_id: str,
    *,
    accepted_ids: list[str],
    all_suggestion_ids: list[str],
    draft_name: str | None = None,
) -> None:
    """Append a weak preference signal: each suggestion marked accept or skip.

    Unmentioned ids (neither accepted nor explicitly skipped in the UI) are
    treated as skip at export time — the professor chose not to accept them.
    """
    accepted = set(accepted_ids)
    now = datetime.now(timezone.utc).isoformat()
    lines: list[str] = []
    for sid in all_suggestion_ids:
        decision = "accept" if sid in accepted else "skip"
        lines.append(
            json.dumps(
                {
                    "ts": now,
                    "review_id": review_id,
                    "draft": draft_name,
                    "suggestion_id": sid,
                    "decision": decision,
                }
            )
        )
    if not lines:
        return
    path = _feedback_path()
    with _LOCK:
        with path.open("a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

"""Harness status: Vault, Source, Review, speech and model residency at a glance."""

from __future__ import annotations

import threading
import time

from fastapi import APIRouter

from ....config import CONFIG
from ....knowledge import review, source
from ....knowledge.vault import iter_notes
from ....models import runtime as model_runtime
from ....realtime import devices

router = APIRouter()


_STATUS_LISTING_TTL_SECONDS = 10.0
_status_listings: tuple[float, dict] | None = None
_status_listings_lock = threading.Lock()


def _status_listing_counts() -> dict:
    """Source and Review listings dominate /api/status; reuse their counts briefly."""
    global _status_listings
    with _status_listings_lock:
        if (_status_listings is None
                or time.monotonic() - _status_listings[0] >= _STATUS_LISTING_TTL_SECONDS):
            source_status = source.list_source_files()
            _status_listings = (time.monotonic(), {
                "proposals_pending": len(review.list_reviews()),
                "sources": len(source_status["files"]),
                "source_issues": len(source_status["issues"]),
                "source_coverage": source_status.get("coverage", {}),
            })
        return dict(_status_listings[1])


@router.get("/api/status")
def status():
    notes = iter_notes()
    tasks = [n for n in notes if n.kind == "task"]
    listings = _status_listing_counts()
    residency = model_runtime.settings()
    active_specs = [
        model_runtime.configured_spec(model_id)
        for model_id in residency["active_models"]
        if model_id in model_runtime.MODELS
    ]
    return {
        "name": "obsidience", "vault": str(CONFIG.vault_dir),
        "notes": len(notes), "tasks": len(tasks),
        "tasks_by_status": _count_by(tasks),
        "proposals_pending": listings["proposals_pending"],
        "sources": listings["sources"],
        "source_issues": listings["source_issues"],
        "source_coverage": listings["source_coverage"],
        "speech": devices.speech_runtime(),
        "llm": {
            "base_url": active_specs[0].base_url if len(active_specs) == 1 else None,
            "model": ",".join(spec.id for spec in active_specs) or "none",
            "models": [spec.id for spec in active_specs],
            "residency_policy": residency["residency_policy"],
        },
        "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def _count_by(tasks):
    out: dict[str, int] = {}
    for t in tasks:
        s = str(t.meta.get("status", "draft"))
        out[s] = out.get(s, 0) + 1
    return out

"""Adapter for ``vault.maintenance``."""

from __future__ import annotations

import hashlib
import json
import re

_CURATION_TITLE_NOISE = frozenset({
    "agent", "article", "brain", "charter", "curator", "guardian", "identity",
    "index", "knowledge", "researcher", "role",
})
_CURATION_BODY_STOP = frozenset({
    "and", "are", "for", "from", "has", "have", "into", "its", "not", "one",
    "that", "the", "their", "this", "through", "uses", "with",
})


def _curation_words(value: str, *, title: bool = False) -> set[str]:
    words = {
        word
        for word in re.findall(r"[a-z0-9]+", value.casefold())
        if len(word) > 2 and word not in _CURATION_BODY_STOP
    }
    return words - _CURATION_TITLE_NOISE if title else words


def _maintenance_candidates() -> dict:
    from obsidience.harness.knowledge.vault import iter_notes, resolver

    notes = [note for note in iter_notes() if note.kind in {"agent", "knowledge"}]
    res = resolver()
    neighbors = {
        note.ref: {
            target.ref
            for raw in note.links
            if (target := res.resolve(raw)) is not None and target.ref != note.ref
        }
        for note in notes
    }
    rows: list[dict] = []
    for index, left in enumerate(notes):
        left_title = _curation_words(left.title, title=True)
        left_body = _curation_words(left.body)
        if not left_title or len(left_body) < 20:
            continue
        for right in notes[index + 1:]:
            right_title = _curation_words(right.title, title=True)
            right_body = _curation_words(right.body)
            if not right_title or len(right_body) < 20:
                continue
            common = left_body & right_body
            union = left_body | right_body
            jaccard = len(common) / len(union) if union else 0.0
            containment = len(common) / min(len(left_body), len(right_body))
            same_subject = left_title == right_title
            strong_body_match = len(common) >= 28 and jaccard >= 0.58
            refs = sorted((left.ref, right.ref))
            source = "\n".join(
                f"{note.ref}\n{note.title}\n{note.body}" for note in (left, right)
            )
            duplicate_signal = (same_subject and containment >= 0.34) or strong_body_match
            if duplicate_signal:
                candidate_key = hashlib.sha256(source.encode()).hexdigest()[:20]
                inbound: dict[str, list[str]] = {}
                for candidate_ref in refs:
                    candidate = res.resolve(candidate_ref)
                    inbound[candidate_ref] = sorted(
                        note.ref
                        for note in notes
                        if note.ref != candidate_ref
                        and any(
                            (target := res.resolve(raw)) is not None
                            and candidate is not None
                            and target.ref == candidate.ref
                            for raw in note.links
                        )
                    )[:12]
                score = min(
                    0.99,
                    0.55 + (0.25 if same_subject else 0.0) + jaccard * 0.2,
                )
                rows.append({
                    "candidate_key": candidate_key,
                    "kind": "possible_duplicate",
                    "recommended_task": "Merge",
                    "refs": refs,
                    "titles": [left.title, right.title],
                    "confidence": "high" if same_subject else "medium",
                    "score": round(score, 3),
                    "signals": {
                        "same_normalized_subject": same_subject,
                        "shared_terms": len(common),
                        "body_containment": round(containment, 3),
                        "body_jaccard": round(jaccard, 3),
                    },
                    "inbound_refs": inbound,
                })
                continue

            directly_linked = (
                right.ref in neighbors[left.ref] or left.ref in neighbors[right.ref]
            )
            if directly_linked or same_subject:
                continue
            left_title_hits = len(left_title & right_body)
            right_title_hits = len(right_title & left_body)
            title_bridge = max(left_title_hits, right_title_hits)
            title_coverage = max(
                left_title_hits / len(left_title),
                right_title_hits / len(right_title),
            )
            shared_title_terms = len(left_title & right_title)
            shared_neighbors = neighbors[left.ref] & neighbors[right.ref]
            same_parent = left.ref.rsplit("/", 1)[0] == right.ref.rsplit("/", 1)[0]
            strong_context = len(common) >= 12 and (jaccard >= 0.14 or containment >= 0.26)
            semantic_anchor = (
                (title_bridge >= 2 and title_coverage >= 0.66)
                or (shared_title_terms >= 2 and len(common) >= 16)
                or (bool(shared_neighbors) and title_bridge >= 1 and title_coverage >= 0.5)
            )
            if not (strong_context and semantic_anchor):
                continue
            score = min(
                0.95,
                0.45
                + min(0.18, jaccard * 0.7)
                + min(0.14, title_coverage * 0.14)
                + (0.06 if same_parent else 0.0)
                + (0.07 if shared_neighbors else 0.0),
            )
            candidate_key = hashlib.sha256(f"missing_link\n{source}".encode()).hexdigest()[:20]
            rows.append({
                "candidate_key": candidate_key,
                "kind": "missing_link",
                "recommended_task": "Link",
                "refs": refs,
                "titles": [left.title, right.title],
                "confidence": "high" if score >= 0.76 else "medium",
                "score": round(score, 3),
                "signals": {
                    "shared_terms": len(common),
                    "body_containment": round(containment, 3),
                    "body_jaccard": round(jaccard, 3),
                    "title_bridge_terms": title_bridge,
                    "title_coverage": round(title_coverage, 3),
                    "shared_neighbors": len(shared_neighbors),
                    "same_parent": same_parent,
                },
            })
    rows.sort(key=lambda row: (-row["score"], row["refs"]))
    claimed_by_task: dict[str, set[str]] = {}
    for recommendation, task_ref in {
        "Merge": "Tasks/merge",
        "Link": "Tasks/link",
    }.items():
        destination = res.resolve(task_ref)
        if not destination:
            claimed_by_task[recommendation] = set()
            continue
        active = destination.meta.get("params")
        queued = destination.meta.get("event_queue")
        occurrences = [active] + (queued if isinstance(queued, list) else [])
        claimed_by_task[recommendation] = {
            str(item.get("candidate_key", ""))
            for item in occurrences
            if isinstance(item, dict) and item.get("candidate_key")
        }
    unclaimed = [
        row
        for row in rows
        if row["candidate_key"] not in claimed_by_task.get(row["recommended_task"], set())
    ]
    return {
        "checked_articles": len(notes),
        "candidate_count": len(rows),
        "claimed_count": len(rows) - len(unclaimed),
        "unclaimed_count": len(unclaimed),
        "candidates": unclaimed[:8],
        "rule": (
            "Candidates are evidence leads. Curate may activate only the exact accepted "
            "Task named by its Runbook. Merge confirms and consolidates identity; Link confirms a "
            "specific useful relationship. Neither signal authorizes a change by itself."
        ),
    }


def execute(args: dict, context: dict) -> str:
    del args, context
    return json.dumps(_maintenance_candidates(), sort_keys=True)

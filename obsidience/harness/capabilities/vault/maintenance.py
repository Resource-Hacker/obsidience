"""Adapter for ``vault.maintenance``."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timezone
from pathlib import PurePosixPath

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


def _candidate_identity(item: dict) -> tuple[str, ...]:
    refs = item.get("candidate_refs", item.get("refs"))
    if isinstance(refs, list):
        stable_refs = tuple(sorted({str(ref).strip() for ref in refs if str(ref).strip()}))
        if stable_refs:
            return ("refs", *stable_refs, str(item.get("candidate_revision", "")))
    candidate_key = str(item.get("candidate_key", ""))
    return ("key", candidate_key) if candidate_key else ()


def _completed_candidates() -> set[tuple[str, str, str]]:
    from obsidience.harness.knowledge.index import INDEX

    return INDEX.maintenance_no_change_keys()


def candidate_revision(notes: list) -> str:
    """Fingerprint the exact accepted input, including semantic frontmatter."""
    value = [(note.ref, note.title, note.meta, note.body)
             for note in sorted(notes, key=lambda note: note.ref)]
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def agent_structural_hub(note, res) -> bool:
    """Recognize a folder Article beneath an actual accepted Agent Article."""
    from obsidience.harness.knowledge.vault import folder_article_path, is_folder_article

    if note is None or note.kind != "knowledge" or not is_folder_article(note):
        return False
    for parent in PurePosixPath(note.ref).parents:
        if str(parent) == ".":
            continue
        owner = res.resolve(folder_article_path(str(parent)))
        if owner is not None and owner.kind == "agent":
            return True
    return False


def candidate_invalidation(task_ref: str, params: dict, res) -> dict | None:
    """Read current accepted inputs; never reinterpret or refresh a commitment."""
    from obsidience.harness.knowledge.system import is_system_article
    from obsidience.harness.knowledge.scope import knowledge_ancestry
    refs = params.get("candidate_refs")
    expected = params.get("candidate_revision")
    if (not isinstance(refs, list) or not refs
            or any(not isinstance(ref, str) or not ref for ref in refs)
            or not isinstance(expected, str) or not re.fullmatch(r"[a-f0-9]{64}", expected)):
        return None
    notes = [res.resolve(ref) for ref in refs]
    hierarchy = knowledge_ancestry(res) if task_ref == "Tasks/link" else {}
    if any(note is None or note.kind not in {"agent", "knowledge"}
           or note.runtime_observation or is_system_article(note.ref) for note in notes):
        reason, current = "inputs_unavailable", None
    elif task_ref == "Tasks/link" and any(
        set(hierarchy.get(note.ref, ())) & {other.ref for other in notes}
        for note in notes
    ):
        reason, current = "native_hierarchy_connection", candidate_revision(notes)
    elif task_ref == "Tasks/improve" and params.get("candidate_kind") == "index_coverage":
        # Native hierarchy already enumerates children. Retire old commitments
        # through the same receipt-bound invalidation path, even at equal bytes.
        reason, current = "native_hierarchy_coverage", candidate_revision(notes)
    elif (task_ref == "Tasks/merge" and params.get("candidate_kind") == "possible_duplicate"
          and any(agent_structural_hub(note, res) for note in notes)):
        reason, current = "agent_structural_hub", candidate_revision(notes)
    else:
        current = candidate_revision(notes)
        if current == expected:
            return None
        reason = "revision_changed"
    return {"disposition": "invalidated", "reason": reason, "candidate_refs": list(refs),
            "candidate_key": params.get("candidate_key"), "expected_revision": expected,
            "current_revision": current}


def _maintenance_candidates(context: dict | None = None) -> dict:
    from obsidience.harness.knowledge.vault import Resolver, folder_article_path, is_folder_article, iter_notes
    from obsidience.harness.knowledge.system import is_system_article

    snapshot = iter_notes()
    res = Resolver(snapshot)
    from obsidience.harness.knowledge.scope import execution_scope, knowledge_ancestry
    allowed = execution_scope(context, res)[1] if context is not None else {note.ref for note in snapshot}
    notes = [
        note
        for note in snapshot
        if note.ref in allowed and note.kind in {"agent", "knowledge"} and not note.runtime_observation and not is_system_article(note.ref)
    ]
    title_words = {
        note.ref: _curation_words(note.title, title=True)
        for note in notes
    }
    body_words = {note.ref: _curation_words(note.body) for note in notes}
    neighbors = {
        note.ref: {
            target.ref
            for raw in note.links
            if (target := res.resolve(raw)) is not None and target.ref != note.ref and target.ref in allowed
        }
        for note in notes
    }
    hierarchy = knowledge_ancestry(res)
    ancestors = {note.ref: [parent for parent in hierarchy[note.ref] if parent in allowed]
                 for note in notes}
    semantic_refs = set(neighbors)
    adjacency = {ref: set() for ref in semantic_refs}
    for ref, targets in neighbors.items():
        for target_ref in targets & semantic_refs:
            adjacency[ref].add(target_ref)
            adjacency[target_ref].add(ref)

    # Structural edges count as connectivity, but never as semantic evidence
    # for a new Link. Contract only missing/excluded intermediate folder hubs.
    for ref, parents in ancestors.items():
        parent = next((value for value in parents if value in semantic_refs), None)
        if parent is not None:
            adjacency[ref].add(parent)
            adjacency[parent].add(ref)

    component_by_ref: dict[str, int] = {}
    component_sizes: list[int] = []
    unseen = set(semantic_refs)
    while unseen:
        pending = [min(unseen)]
        component_id = len(component_sizes)
        size = 0
        while pending:
            ref = pending.pop()
            if ref not in unseen:
                continue
            unseen.remove(ref)
            component_by_ref[ref] = component_id
            size += 1
            pending.extend(adjacency[ref] & unseen)
        component_sizes.append(size)

    rows: list[dict] = []

    def add_lead(kind: str, task: str, selected: list, score: float, **evidence) -> None:
        refs = sorted(note.ref for note in selected)
        rows.append({
            "candidate_key": hashlib.sha256(json.dumps([kind, refs]).encode()).hexdigest()[:20],
            "kind": kind, "recommended_task": task, "refs": refs,
            "titles": [note.title for note in selected], "score": score,
            "signals": evidence,
        })

    folders: dict[str, list] = {}
    now = datetime.now(timezone.utc)
    for note in notes:
        if note.kind != "knowledge":
            continue
        missing = sorted({raw for raw in note.links if res.resolve(raw) is None})
        if missing:
            add_lead("broken_reference", "Improve", [note], 1.0, missing_refs=missing[:8])
        parent = str(PurePosixPath(note.ref).parent)
        if parent != "." and not is_folder_article(note):
            folders.setdefault(parent, []).append(note)
        if not is_folder_article(note) and not note.children and note.meta.get("article_status") == "deprecated":
            add_lead("deprecated", "Archive", [note], 0.97,
                     archive_ref=note.ref, article_status="deprecated")
        stale_after = note.meta.get("stale_after")
        if isinstance(stale_after, str):
            try:
                stale = datetime.fromisoformat(stale_after.replace("Z", "+00:00"))
            except ValueError:
                stale = None
            if stale is not None and stale.utcoffset() is not None and stale <= now:
                add_lead("stale_after", "Audit", [note], 0.96, stale_after=stale_after)
        review_due = note.meta.get("review_due")
        if review_due:
            try:
                due = date.fromisoformat(str(review_due)[:10])
            except ValueError:
                due = None
            if due is not None and due <= date.today():
                add_lead("review_due", "Audit", [note], 0.96, review_due=due.isoformat())
        successor = res.resolve(str(note.meta.get("superseded_by", "")))
        if successor and successor.ref != note.ref and successor.kind == "knowledge" and not successor.runtime_observation:
            add_lead("superseded", "Archive", [note, successor], 0.95,
                     archive_ref=note.ref, successor_ref=successor.ref)
    for folder, children in folders.items():
        index_ref = folder_article_path(folder).removesuffix(".md")
        index_note = res.resolve(index_ref)
        if not index_note and len(children) >= 2:
            add_lead("missing_index", "Improve", children[:8], 0.92, index_ref=index_ref)
    for index, left in enumerate(notes):
        left_title = title_words[left.ref]
        left_body = body_words[left.ref]
        if not left_title or len(left_body) < 20:
            continue
        for right in notes[index + 1:]:
            right_title = title_words[right.ref]
            right_body = body_words[right.ref]
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
            if duplicate_signal and not (
                agent_structural_hub(left, res) or agent_structural_hub(right, res)
            ):
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
            if (directly_linked or same_subject
                    or left.ref in ancestors[right.ref] or right.ref in ancestors[left.ref]):
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
            semantic_shared_neighbors = adjacency[left.ref] & adjacency[right.ref]
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
                "connectivity": {
                    "isolated_endpoint_refs": [
                        ref for ref in refs if not adjacency[ref]
                    ],
                    "separate_components": (
                        component_by_ref[left.ref] != component_by_ref[right.ref]
                    ),
                    "shared_neighbor_refs": sorted(semantic_shared_neighbors)[:4],
                },
            })
    for row in rows:
        row["candidate_revision"] = candidate_revision([res.resolve(ref) for ref in row["refs"]])
    rows.sort(key=lambda row: (-row["score"], row["refs"]))
    claimed_by_task: dict[str, set[str]] = {}
    for recommendation, task_ref in {
        "Merge": "Tasks/merge",
        "Link": "Tasks/link",
        "Improve": "Tasks/improve",
        "Archive": "Tasks/archive",
        "Audit": "Tasks/audit",
    }.items():
        destination = res.resolve(task_ref)
        if not destination:
            claimed_by_task[recommendation] = set()
            continue
        active = destination.meta.get("params")
        queued = destination.meta.get("event_queue")
        occurrences = [active] + (queued if isinstance(queued, list) else [])
        claimed_by_task[recommendation] = {
            identity
            for item in occurrences
            if isinstance(item, dict) and (identity := _candidate_identity(item))
        }
    completed = _completed_candidates()
    unclaimed = [
        row
        for row in rows
        if _candidate_identity(row)
        not in claimed_by_task.get(row["recommended_task"], set())
        and (*_candidate_identity(row)[:-1], "")
        not in claimed_by_task.get(row["recommended_task"], set())
    ]
    eligible = [row for row in unclaimed if (
        "Tasks/" + row["recommended_task"].lower(), row["candidate_key"], row["candidate_revision"]
    ) not in completed]
    return {
        "checked_articles": len(notes),
        "candidate_count": len(rows),
        "claimed_count": len(rows) - len(unclaimed),
        "unchanged_no_change_count": len(unclaimed) - len(eligible),
        "unclaimed_count": len(eligible),
        "candidates": eligible[:8],
        "connectivity": {
            "component_count": len(component_sizes),
            "isolated_article_count": sum(not targets for targets in adjacency.values()),
            "largest_component_size": max(component_sizes, default=0),
        },
        "rule": (
            "Candidates are evidence leads. Curate may activate only the exact accepted "
            "Task named by its Runbook. Connectivity is descriptive; disconnectedness alone "
            "never creates or authorizes a Link. Merge confirms and consolidates identity; "
            "Native hierarchy already connects ancestors and descendants at every depth; "
            "Link is only for a missing useful non-hierarchical relationship. "
            "Shared hierarchy alone is not semantic evidence. No signal authorizes a change by itself."
        ),
    }


def execute(args: dict, context: dict) -> str:
    del args
    try:
        return json.dumps(_maintenance_candidates(context), sort_keys=True)
    except PermissionError as exc:
        return str(exc)

"""The review system: staged proposals -> approve/reject, git as the audit trail.

A proposal is a note in _staging/ whose frontmatter carries:
  proposal: true, action: create|update|archive, target: <vault-relative .md path>,
  agent, task, reason, review_class: article|link.
Approve applies it to the target (create fails if the target exists; update
replaces the body while preserving existing graph metadata; archive moves a
Knowledge Article to _archived/ only when no accepted article links to it) and commits.
Reject moves it to _staging/_rejected/.
Owner edits made directly in Obsidian never pass through here — the owner is
a trusted writer by design.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import time
from collections import Counter
from pathlib import Path

import yaml

from ..config import CONFIG
from . import format as article_format
from .links import body_link_locations, body_links
from .tasks import task_triggers
from .vault import (
    Note,
    Resolver,
    _NOTE_WRITE_LOCK,
    iter_notes,
    load_note,
    mutate_note_metadata,
    normalize_article_body,
    resolver,
    write_note,
)

REVIEW_CLASSES = frozenset({"article", "link"})
MAX_PENDING_LINKS = 128


def validate_proposal_target(target: str, action: str) -> Note | None:
    """Use the same literal target and action checks at staging, display and approval."""
    if not target or target.startswith(("_", "/")) or ".." in target:
        raise ValueError(f"invalid target: {target}")
    if action not in ("create", "update", "archive"):
        raise ValueError(f"invalid action: {action}")
    existing = load_note(target)
    if action == "create" and existing:
        raise ValueError(f"target already exists: {target} (use action: update)")
    if action == "update" and not existing:
        raise ValueError(f"target does not exist: {target} (use action: create)")
    if action == "archive" and not existing:
        raise ValueError(f"target does not exist: {target}")
    return existing


def merge_archive_blocker(meta: dict) -> str:
    """A Merge may retire redundancy, never its canonical retained copy."""
    if meta.get("task") != "Tasks/merge" or meta.get("action") != "archive":
        return ""
    binding = meta.get("merge_retained")
    if not isinstance(binding, dict):
        return "Merge archive lacks retained-Article evidence; reject this proposal and rerun Merge."
    target, digest = binding.get("target"), binding.get("body_sha256")
    if (not isinstance(target, str) or not target.endswith(".md") or target.startswith(("_", "/"))
            or ".." in target or target == meta.get("target")
            or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)):
        return "Merge archive has invalid retained-Article evidence."
    retained = load_note(target)
    if retained is None:
        return "Merge retained Article is no longer accepted; do not archive its duplicate."
    for path in CONFIG.staging_dir.glob("*.md"):
        pending, _ = article_format.loads(path.read_text(encoding="utf-8"))
        if pending.get("target") == target:
            return "Decide the retained Article's pending proposal before approving this Merge archive."
    if hashlib.sha256(retained.body.strip().encode()).hexdigest() != digest:
        return "Merge retained content is not the accepted canonical union; approve its update or reject this archive."
    return ""


def _archive_destination(target: str) -> Path:
    """Retain every historical retirement, including a returning Article."""
    original = CONFIG.vault_dir / target
    base = CONFIG.vault_dir / "_archived" / target
    if not base.exists():
        return base
    revision = hashlib.sha256(original.read_bytes()).hexdigest()[:16]
    for number in range(1, 129):
        suffix = "" if number == 1 else f"-{number}"
        candidate = base.with_name(f"{base.stem}--{revision}{suffix}.md")
        if not candidate.exists():
            return candidate
    raise ValueError("archive revision history exceeded its bounded collision range")


def _record_review_decision(
    proposal_id: str,
    meta: dict,
    target: str,
    decision: str,
) -> dict:
    """Persist the exact owner/controller disposition before releasing its Task."""
    run_id = str(meta.get("run_id", ""))
    if not run_id:
        return {
            "run_id": "",
            "approved_count": 0,
            "rejected_count": 0,
            "approved_targets": [],
            "rejected_targets": [],
        }
    from .index import INDEX

    return INDEX.record_review_decision(
        proposal_id=proposal_id,
        run_id=run_id,
        task_ref=str(meta.get("task", "")),
        target=target,
        decision=decision,
    )


def notify_link_review(proposal_id: str, meta: dict, state: str, *, links: list[dict] | None = None) -> None:
    """Notify presentation after the existing Review owner changed its state."""
    review_class = meta.get("review_class") or review_class_for_task(str(meta.get("task", "")))
    from ..execution import activity
    from .index import INDEX

    run_id = str(meta.get("run_id", ""))
    if state == "pending":
        with _NOTE_WRITE_LOCK:
            # A concurrent owner decision may finish between staging and this
            # invalidation; never announce a removed proposal as pending.
            if (CONFIG.staging_dir / proposal_id).is_file() and INDEX.review_decision(proposal_id) is None:
                activity.emit_operation("review", "pending",
                    [str(meta.get("target", "")).removesuffix(".md"), str(meta.get("task", ""))],
                    operation_id="review:" + proposal_id, label="Article change awaiting Review",
                    run_id=run_id, refresh=True)
                if review_class == "link":
                    activity.emit_review_change(proposal_id, run_id, state)
        return
    decision = INDEX.review_decision(proposal_id)
    if run_id and (not decision or decision["decision"] != state
            or any(decision[key] != str(meta.get(field, "")) for key, field in (
                ("run_id", "run_id"), ("task_ref", "task"), ("target", "target")))):
        return
    activity.emit_operation("review", state, [str(meta.get("target", "")).removesuffix(".md")],
        operation_id="review:" + proposal_id, label="Article change " + state,
        run_id=run_id, refresh=True)
    if review_class == "link" and decision:
        activity.emit_review_change(proposal_id, run_id, state,
                                    decided_at=decision["decided_at"], links=links)


def review_class_for_task(task_ref: str, accepted_resolver: Resolver | None = None) -> str:
    """Derive review semantics from the accepted Task, never model-authored input."""
    clean_ref = str(task_ref).strip().strip("[]").split("|", 1)[0].split("#", 1)[0]
    res = accepted_resolver or resolver()
    task = res.resolve(clean_ref) if clean_ref else None
    return (
        "link"
        if task and task.kind == "task"
        and str(task.meta.get("taxonomy_path", "")) == "wiki/link"
        else "article"
    )


def _resolved_body_links(body: str, accepted_resolver: Resolver, path: str = "") -> set[str]:
    refs: set[str] = set()
    for raw in body_links(body, path):
        target = accepted_resolver.resolve(raw)
        refs.add(target.ref if target else raw.strip())
    return refs


def link_evidence(existing, body: str, accepted_resolver: Resolver) -> list[dict]:
    """Locate changed Article links; syntax is not semantic approval."""
    from .scope import knowledge_ancestry

    if not existing or existing.kind not in {"knowledge", "agent"} or existing.runtime_observation:
        raise ValueError("Link requires an accepted non-runtime Knowledge or Agent Article")
    before = _resolved_body_links(existing.body, accepted_resolver, existing.path)
    after = _resolved_body_links(body, accepted_resolver, existing.path)
    ancestors = knowledge_ancestry(accepted_resolver)
    evidence = []
    for change, refs, text in (
        ("added", after - before, body),
        ("removed", before - after, existing.body),
    ):
        for ref in sorted(refs):
            endpoint = accepted_resolver.resolve(ref)
            if change == "added" and (
                not endpoint or endpoint.ref == existing.ref
                or endpoint.kind not in {"knowledge", "agent"} or endpoint.runtime_observation
            ):
                raise ValueError(f"Link endpoint must be a distinct accepted Knowledge or Agent Article: {ref}")
            if change == "added" and (endpoint.ref in ancestors[existing.ref]
                                      or existing.ref in ancestors[endpoint.ref]):
                raise ValueError(
                    f"Link endpoints are already connected by native hierarchy: {existing.ref} and {ref}"
                )
            try:
                endpoint_sha256 = hashlib.sha256(
                    (CONFIG.vault_dir / endpoint.path).read_bytes(),
                ).hexdigest() if endpoint else ""
            except OSError as exc:
                raise ValueError(f"Link endpoint is unavailable: {ref}") from exc
            for raw, number, line in body_link_locations(text, existing.path):
                located = accepted_resolver.resolve(raw)
                if ref == (located.ref if located else raw.strip()):
                    evidence.append({
                        "ref": ref,
                        "change": change,
                        "derivation": "proposed_wikilink" if change == "added" else "accepted_wikilink",
                        "body_line": number,
                        "excerpt": line.strip()[:400],
                        "endpoint_sha256": endpoint_sha256,
                    })
                    break
    from ..memory.hindsight import observation_links

    before_memories = {row["ref"]: row for row in observation_links(existing.body, existing.path)}
    after_memories = {row["ref"]: row for row in observation_links(body, existing.path)}
    for change, current, other in (("added", after_memories, before_memories),
                                   ("removed", before_memories, after_memories)):
        for ref in sorted(current.keys() - other.keys()):
            row = current[ref]
            evidence.append({**row, "change": change,
                             "derivation": "proposed_source_citation" if change == "added" else "accepted_source_citation"})
    if not evidence:
        raise ValueError("Link proposal contains no relationship change")
    return evidence


def _validate_link_evidence(meta: dict, existing, body: str, accepted_resolver: Resolver) -> str:
    from ..capabilities.vault.propose import PROPOSAL_METADATA_FIELDS

    if meta.get("action") != "update":
        raise ValueError("Link proposals update existing Articles")
    if "authored_fields" in meta:
        forbidden = (PROPOSAL_METADATA_FIELDS - {"kind", "type", "obsidience"}) & meta.keys()
        if meta["authored_fields"] != [] or forbidden or meta.get("kind", "knowledge") != "knowledge":
            raise ValueError("Link updates an existing Article body, not its authority metadata")
    elif PROPOSAL_METADATA_FIELDS & meta.keys():
        raise ValueError("Link updates an existing Article body, not its authority metadata")
    current = link_evidence(existing, body, accepted_resolver)
    captured = meta.get("link_evidence")
    if not isinstance(captured, list) or len(captured) != len(current) or (
        meta.get("proposal_body_sha256") != hashlib.sha256(body.encode()).hexdigest()
    ):
        raise ValueError("Link evidence changed or is missing. Reject this proposal and rerun Link.")
    changed = []
    for before, after in zip(captured, current):
        if not isinstance(before, dict) or any(
            before.get(key) != value for key, value in after.items() if key != "endpoint_sha256"
        ):
            raise ValueError("Link evidence changed or is missing. Reject this proposal and rerun Link.")
        if before.get("endpoint_sha256") != after["endpoint_sha256"]:
            changed.append(after["ref"])
    # An Article may legitimately gain a reciprocal link while a companion
    # proposal awaits review. Expose revision drift, never silently rebase or
    # invalidate that other proposal merely because its endpoint was edited.
    return ("Linked Articles changed since this suggestion; inspect their current text: "
            + ", ".join(changed)) if changed else ""


def git_commit(message: str, rel_paths: list[str]) -> None:
    # Never walk upward into the application's publishable repository. The
    # live Vault may opt into its own local audit repository, created by init.
    root = CONFIG.vault_dir.resolve()
    if not CONFIG.git_commit or not rel_paths or not (root / ".git").is_dir():
        return
    try:
        added = subprocess.run(["git", "-C", str(root), "add", "--", *rel_paths],
                       check=False, capture_output=True, timeout=15)
        if added.returncode:
            return
        subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", message,
                        "--author", "Obsidience Harness <harness@obsidience.local>",
                        "--only", "--", *rel_paths],
                       check=False, capture_output=True, timeout=15)
    except Exception:  # noqa: BLE001 — audit trail must never break the run
        pass


def list_proposals() -> list[dict]:
    with _NOTE_WRITE_LOCK:
        return _list_proposals()


def list_reviews() -> list[dict]:
    """One Review surface for Article decisions and controller notifications."""
    from .index import INDEX

    return INDEX.review_notifications() + list_proposals()


def sync_health_notifications(findings: list[dict]) -> None:
    """A blocked recovery is operational evidence, never a Knowledge proposal."""
    from .index import INDEX

    rows = []
    for finding in findings:
        task, reason = finding.get("task", ""), str(finding["reason"])[:1000]
        title = finding.get("title") or task.rsplit("/", 1)[-1].replace("-", " ").title() or "Source integrity"
        rows.append({
            "file": "health-" + finding["key"], "review_class": "health", "action": "attention",
            "title": title + " needs attention", "target": task, "task": task,
            "agent": "Heimdall", "run_id": finding.get("run_id", ""),
            "reason": reason, "approvable": False, "blocked_reason": "",
            "body_preview": (reason + "\n\n" + str(finding.get("detail", ""))[:2000]
                             + "\n\n" + str(finding.get("recovery_guidance") or
                             "Automatic recovery cannot proceed with the current evidence.") + " "
                             "Acknowledging this notification leaves the warning and original receipts intact. "
                             "Recovery is reconsidered when the underlying state or repair definition changes."),
            "link_changes": None, "link_evidence": [], "evidence_warning": "",
        })
    INDEX.sync_review_notifications("health", rows)


def acknowledge_notification(identity: str) -> dict:
    from .index import INDEX

    return INDEX.acknowledge_review_notification(identity)


def _list_proposals(accepted: list[Note] | None = None) -> list[dict]:
    from ..execution.refinement import review_blocker
    from .system import assert_system_article_writable

    accepted = iter_notes() if accepted is None else accepted
    accepted_resolver = Resolver(accepted)
    out = []
    for p in sorted(CONFIG.staging_dir.glob("*.md")):
        meta, body = article_format.loads(p.read_text(encoding="utf-8"))
        title = str(meta.get("title") or p.stem)
        task_ref = str(meta.get("task", ""))
        stored_class = str(meta.get("review_class", ""))
        review_class = (
            stored_class
            if stored_class in REVIEW_CLASSES
            else review_class_for_task(task_ref, accepted_resolver)
        )
        target = str(meta.get("target", ""))
        link_changes = None
        if review_class == "link":
            existing = load_note(target)
            before = _resolved_body_links(existing.body, accepted_resolver, target) if existing else set()
            after = _resolved_body_links(body, accepted_resolver, target)
            link_changes = {
                "added": sorted(after - before),
                "removed": sorted(before - after),
            }
            for item in meta.get("link_evidence", []):
                if item.get("source_citation") and item.get("change") in link_changes:
                    link_changes[item["change"]].append(item["ref"])
        out.append({
            "file": p.name, "title": title, "review_class": review_class,
            "link_changes": link_changes,
            "link_evidence": meta.get("link_evidence", []) if review_class == "link" else [],
            "evidence_warning": "",
            "action": meta.get("action", "create"), "target": target,
            "agent": meta.get("agent", "?"), "task": task_ref,
            "run_id": meta.get("run_id", ""),
            "reason": meta.get("reason", ""), "proposed_at": meta.get("proposed_at", ""),
            "body_preview": normalize_article_body(body, title)[:12_000],
            "base_sha256": meta.get("base_sha256", ""),
        })
        if blocker := review_blocker(Note(str(p.relative_to(CONFIG.vault_dir)), title, meta, body),
                                     accepted_resolver=accepted_resolver):
            out[-1]["blocked_reason"] = blocker
        try:
            assert_system_article_writable(target)
            validate_proposal_target(target, str(meta.get("action", "create")))
        except ValueError as exc:
            out[-1]["blocked_reason"] = str(exc)
        if review_class == "link":
            try:
                if stored_class and stored_class != review_class_for_task(task_ref, accepted_resolver):
                    raise ValueError("proposal review class does not match its accepted Task")
                out[-1]["evidence_warning"] = _validate_link_evidence(
                    meta, existing, body, accepted_resolver,
                )
            except ValueError as exc:
                out[-1]["blocked_reason"] = str(exc)

    target_counts = Counter(str(row["target"]) for row in out)
    by_target: dict[str, list[dict]] = {}
    for row in out:
        by_target.setdefault(str(row["target"]), []).append(row)

    for row in out:
        target = str(row["target"])
        block = str(row.get("blocked_reason", ""))
        if target_counts[target] > 1:
            block = "Multiple pending proposals target this Article. Reject stale copies first."
        accepted_path = CONFIG.vault_dir / target
        base_sha256 = str(row.get("base_sha256", ""))
        if not block and base_sha256 and accepted_path.is_file():
            current_sha256 = hashlib.sha256(accepted_path.read_bytes()).hexdigest()
            if current_sha256 != base_sha256:
                block = "The accepted Article changed after this proposal was drafted. Reject it and rerun the Task."
        if not block and row["action"] == "archive":
            _, proposal_meta, _ = _load_proposal(row["file"])
            block = merge_archive_blocker(proposal_meta)
        if not block and row["action"] == "archive":
            prerequisite_updates = [
                candidate for candidate in out
                if candidate["action"] == "update"
                and candidate["task"] == row["task"]
            ]
            existing = load_note(target)
            inbound = []
            if existing:
                for note in accepted:
                    if note.ref == existing.ref:
                        continue
                    if any(
                        (resolved := accepted_resolver.resolve(raw)) is not None
                        and resolved.ref == existing.ref
                        for raw in note.links
                    ):
                        inbound.append(note)
            covered = [note for note in inbound if note.path in by_target]
            missing = [note.ref for note in inbound if note.path not in by_target]
            if missing:
                block = "Merge is incomplete; no redirect proposal exists for: " + ", ".join(missing[:6])
            elif prerequisite_updates:
                block = (
                    f"Approve {len(prerequisite_updates)} prerequisite update "
                    "proposal(s) before archiving this Article."
                )
            elif covered:
                block = f"Approve {len(covered)} redirect proposal(s) before archiving this Article."
        row["approvable"] = not block
        row["blocked_reason"] = block
        row.pop("base_sha256", None)

    priority = {"update": 0, "create": 1, "archive": 2}
    out.sort(key=lambda row: (
        0 if row["approvable"] else 1,
        priority.get(str(row["action"]), 3),
        str(row["proposed_at"]),
        str(row["file"]),
    ))
    return out


def link_proposals(accepted: list[Note] | None = None) -> dict:
    """Pending additions are presentation evidence, never accepted graph links."""
    from ..execution.activity import MAX_REVIEW_REF_CHARS

    with _NOTE_WRITE_LOCK:
        accepted = iter_notes() if accepted is None else accepted
        res = Resolver(accepted)
        by_path = {note.path: note for note in accepted}
        by_ref = {note.ref: note for note in accepted}
        entries, truncated = [], False
        try:
            proposals = _list_proposals(accepted)
        except (ValueError, OSError, yaml.YAMLError):
            # Malformed or disappearing staging data must not take down the
            # accepted graph. Omit the overlay when its completeness is unknown.
            return {"entries": [], "truncated": True}
        for row in proposals:
            if (row["review_class"] != "link" or not row["approvable"] or row["action"] != "update"
                    or review_class_for_task(row["task"], res) != "link"):
                continue
            source = by_path.get(row["target"])
            if not source or source.kind not in {"knowledge", "agent"} or source.runtime_observation:
                continue
            for target_ref in row["link_changes"]["added"]:
                target = by_ref.get(target_ref)
                memory = next((item for item in row["link_evidence"] if item.get("source_citation")
                               and item["ref"] == target_ref and item["change"] == "added"), None)
                if not memory and (not target or target.kind not in {"knowledge", "agent"} or target.runtime_observation):
                    continue
                if (len(entries) == MAX_PENDING_LINKS or len(source.ref) > MAX_REVIEW_REF_CHARS
                        or len(target_ref) > MAX_REVIEW_REF_CHARS or len(row["file"]) > 512
                        or not isinstance(row["run_id"], str) or len(row["run_id"]) > 80):
                    truncated = True
                    continue
                entries.append({"proposal_id": row["file"], "run_id": row["run_id"],
                                "source": source.ref, "target": target_ref})
        return {"entries": entries, "truncated": truncated}


def _load_proposal(name: str) -> tuple[Path, dict, str]:
    p = CONFIG.staging_dir / name
    if not p.exists() or p.parent != CONFIG.staging_dir:
        raise FileNotFoundError(name)
    meta, body = article_format.loads(p.read_text(encoding="utf-8"))
    return p, meta, body


def _pending_skill_pairs(tool_ref: str) -> list[Path]:
    """Return pending leaf Skill proposals paired to one exact Tool ref."""
    matches: list[Path] = []
    for path in CONFIG.staging_dir.glob("*.md"):
        meta, _ = article_format.loads(path.read_text(encoding="utf-8"))
        raw_tool = str(meta.get("tool", "")).strip().strip("[]").split("|", 1)[0].removesuffix(".md").lstrip("/")
        if (
            str(meta.get("kind", "")).strip().lower() == "skill"
            and not meta.get("subskills")
            and str(meta.get("action", "create")) in {"create", "update"}
            and raw_tool == tool_ref
        ):
            matches.append(path)
    return sorted(matches)


def reconcile_origin_review_task(origin_ref: str) -> str:
    """Release one Task after all of its proposals are decided.

    A review decision may arrive while the originating execution is still
    running.  Calling this again immediately after execution writes ``review``
    makes proposal decision and Task finalization order-independent.
    """
    clean_ref = origin_ref.strip().strip("[]").split("|", 1)[0]
    origin = resolver().resolve(clean_ref) if clean_ref else None
    conversational = (origin is not None and origin.kind == "agent"
                      and origin.ref == "Agents/Executive/Executive" and origin.meta.get("skills"))
    if not origin or (origin.kind != "task" and not conversational):
        return ""
    if conversational:
        from dataclasses import replace
        from .index import INDEX
        origin = replace(origin, meta={**origin.meta, **(INDEX.task_runtime(origin.ref) or {})})
    status = str(origin.meta.get("status", ""))
    pending_run_ids = set()
    for pending in CONFIG.staging_dir.glob("*.md"):
        pending_meta, _ = article_format.loads(pending.read_text(encoding="utf-8"))
        pending_origin = resolver().resolve(str(pending_meta.get("task", "")))
        if pending_origin and pending_origin.ref == origin.ref:
            pending_run_ids.add(str(pending_meta.get("run_id", "")))
    from .index import INDEX
    INDEX.complete_review_occurrences(origin.ref, pending_run_ids)
    if str(origin.meta.get("last_run", "")) in pending_run_ids or "" in pending_run_ids:
        return status
    if status != "review":
        return status

    def complete(meta: dict) -> None:
        if str(meta.get("status")) != "review":
            return
        meta["status"] = "completed"
        meta["status_updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        meta.pop("blocked_reason", None)

    if conversational:
        INDEX.mutate_task_runtime(origin.ref, complete)
    else:
        mutate_note_metadata(origin, complete)
    run_id = str(origin.meta.get("last_run", ""))
    if origin.ref == "Tasks/ingest" and run_id:
        from .index import INDEX

        INDEX.resolve_ingest_review(run_id)
    refreshed = load_note(origin.path)
    if refreshed and refreshed.meta.get("event_queue"):
        # A reviewed event Task may now admit its next durable activation.
        # Import lazily to keep the review and scheduler modules acyclic.
        from ..execution.scheduler import advance_event_queue

        advance_event_queue(refreshed)
    return "completed"


def _validate_capability_metadata(target: str, meta: dict) -> None:
    """Fail closed before accepting a Tool or its one-to-one Skill."""
    kind = str(meta.get("kind", "")).strip().lower()
    if kind == "tool":
        # OKF sources are documentary provenance, never executable bindings.
        # The singular application source still supplies the exact contract.
        if meta.get("subtools"):
            if meta.get("binding") or meta.get("source"):
                raise ValueError(
                    "Tool index Articles cannot carry executable binding or source metadata"
                )
        else:
            from ..capabilities.registry import contract_error

            error = contract_error(meta.get("title"), meta.get("binding"), meta.get("source"))
            if error:
                raise ValueError(f"Tool proposal is not executable: {error}")
            accepted = iter_notes()
            accepted_resolver = Resolver(accepted)
            accepted_pairs = []
            for skill in (
                note for note in accepted if note.kind == "skill" and not note.children
            ):
                paired = accepted_resolver.resolve(str(skill.meta.get("tool", "")))
                if paired and paired.ref == target.removesuffix(".md"):
                    accepted_pairs.append(skill.ref)
            pending_pairs = _pending_skill_pairs(target.removesuffix(".md"))
            if not (
                (len(accepted_pairs) == 1 and len(pending_pairs) <= 1)
                or (not accepted_pairs and len(pending_pairs) == 1)
            ):
                raise ValueError(
                    "Tool proposal requires exactly one accepted or pending paired Skill"
                )
    if kind != "skill":
        return
    if meta.get("tools"):
        raise ValueError("Skill proposal must use one singular tool field")
    if meta.get("subskills"):
        if meta.get("tool"):
            raise ValueError("Skill index Articles cannot carry a Tool pairing")
        return
    accepted = iter_notes()
    res = Resolver(accepted)
    tool = res.resolve(str(meta.get("tool", "")))
    if not tool or tool.kind != "tool" or tool.children:
        raise ValueError("Skill proposal must name exactly one accepted leaf Tool")
    for skill in (note for note in accepted if note.kind == "skill" and note.path != target):
        paired = res.resolve(str(skill.meta.get("tool", "")))
        if paired and paired.ref == tool.ref:
            raise ValueError(f"Tool already has a Skill: {skill.ref}")


def approve(name: str) -> dict:
    with _NOTE_WRITE_LOCK:
        return _approve(name)


def _approve(name: str) -> dict:
    from ..execution.refinement import review_blocker
    from .system import assert_system_article_writable

    path, meta, body = _load_proposal(name)
    if blocker := review_blocker(Note(str(path.relative_to(CONFIG.vault_dir)), str(meta.get("title") or path.stem), meta, body)):
        raise ValueError(blocker)
    target = str(meta.get("target", "")).strip()
    assert_system_article_writable(target)
    action = meta.get("action", "create")
    existing = validate_proposal_target(target, action)
    expected_review_class = review_class_for_task(str(meta.get("task", "")))
    review_class = str(meta.get("review_class") or expected_review_class)
    if review_class not in REVIEW_CLASSES or review_class != expected_review_class:
        raise ValueError("proposal review class does not match its accepted Task")
    if existing and existing.runtime_observation:
        raise ValueError("runtime Observations are lifecycle-owned, not wiki proposals")
    conflicts = []
    for pending in CONFIG.staging_dir.glob("*.md"):
        if pending == path:
            continue
        pending_meta, _ = article_format.loads(pending.read_text(encoding="utf-8"))
        if str(pending_meta.get("target", "")) == target:
            conflicts.append(pending.name)
    if conflicts:
        raise ValueError(
            "multiple pending proposals target this Article; reject stale copies first"
        )
    base_sha256 = str(meta.get("base_sha256", ""))
    accepted_path = CONFIG.vault_dir / target
    if base_sha256 and accepted_path.is_file():
        current_sha256 = hashlib.sha256(accepted_path.read_bytes()).hexdigest()
        if current_sha256 != base_sha256:
            raise ValueError(
                "accepted Article changed after this proposal was drafted; reject it and rerun the Task"
            )
    evidence_warning = ""
    approved_links = []
    if review_class == "link":
        evidence_warning = _validate_link_evidence(meta, existing, body, Resolver(iter_notes()))
        approved_links = [{"source": existing.ref, "target": evidence["ref"]}
                          for evidence in meta["link_evidence"] if evidence["change"] == "added"]
    if action == "archive":
        if blocker := merge_archive_blocker(meta):
            raise ValueError(blocker)
        if existing.kind != "knowledge":
            raise ValueError("only ordinary Knowledge Articles may be archived")
        accepted = iter_notes()
        accepted_resolver = Resolver(accepted)
        inbound = []
        for note in accepted:
            if note.ref == existing.ref:
                continue
            if any(
                (resolved := accepted_resolver.resolve(raw)) is not None
                and resolved.ref == existing.ref
                for raw in note.links
            ):
                inbound.append(note.ref)
        if inbound:
            raise ValueError(
                "archive target still has accepted inbound links: " + ", ".join(inbound[:12])
            )
        destination = _archive_destination(target)
        destination.parent.mkdir(parents=True, exist_ok=True)
        (CONFIG.vault_dir / target).rename(destination)
        try:
            archived = load_note(str(destination.relative_to(CONFIG.vault_dir)))
            if archived is None:
                raise ValueError("archived Article could not be read")
            mutate_note_metadata(archived, lambda fields: fields.update({
                "article_status": "deprecated",
                "archived_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "archive_reason": str(meta.get("reason", ""))[:400],
            }))
        except Exception:
            destination.rename(CONFIG.vault_dir / target)
            raise
        review_outcome = _record_review_decision(path.name, meta, target, "approved")
        path.unlink()
        reconcile_origin_review_task(str(meta.get("task", "")))
        git_commit(
            f"[review] archive: {target} (from {meta.get('agent', '?')})",
            [target, str(destination.relative_to(CONFIG.vault_dir))],
        )
        from .index import INDEX

        INDEX.sync()
        notify_link_review(path.name, meta, "approved")
        return {
            "archived": target,
            "moved_to": str(destination.relative_to(CONFIG.vault_dir)),
            "review_outcome": review_outcome,
        }
    origin_ref = str(meta.get("task", "")).strip().strip("[]")
    origin = resolver().resolve(origin_ref) if origin_ref else None
    proposal_context = meta.get("event_context", {})
    generation_params = (
        proposal_context
        if origin and "task.assigned" in task_triggers(origin.meta)
        and isinstance(proposal_context, dict)
        else {}
    )
    generated = bool(
        isinstance(generation_params, dict)
        and target == generation_params.get("output_runbook")
        and target.startswith("Runbooks/")
    )
    if generated:
        from ..capabilities.vault.propose import validate_generated_runbook
        from ..execution.assignments import library_candidates
        from .dependencies import dependency_resolver

        validate_generated_runbook(target, body, generation_params, meta.get("skills"))
        accepted_resolver = dependency_resolver(resolver())
        current_catalog = library_candidates(accepted_resolver)
        # The event catalog is a candidate set, not a durable grant. Recheck the
        # accepted 1:1 pairs at publication after any intervening Library edits.
        validate_generated_runbook(target, body, {**generation_params, **current_catalog}, meta["skills"])
        for raw in meta["skills"]:
            skill = accepted_resolver.resolve(raw)
            tool = accepted_resolver.resolve(str(skill.meta.get("tool", ""))) if skill else None
            if not tool or tool.ref != skill.ref.replace("Skills/", "Tools/", 1):
                raise ValueError("generated Runbook Skill-to-Tool pair changed before approval")

    # An update changes authored content, not the note's graph identity. Start
    # from accepted metadata so task edges, assignments, source citations, and
    # other fields cannot disappear merely because vault.propose carries only
    # the common proposal envelope.
    note_meta = dict(existing.meta) if action == "update" and existing else {}
    if "authored_fields" in meta:
        from ..capabilities.vault.propose import PROPOSAL_METADATA_FIELDS

        authored_fields = meta["authored_fields"]
        if not isinstance(authored_fields, list) or any(
            not isinstance(key, str) or key not in PROPOSAL_METADATA_FIELDS
            or key in {"type", "obsidience"} for key in authored_fields
        ):
            raise ValueError("invalid proposal authored metadata fields")
        note_meta.update({key: meta[key] for key in authored_fields if key in meta})
        note_meta["title"] = meta.get("title")
    else:
        note_meta.update({k: v for k, v in meta.items()
                          if k not in ("proposal", "action", "target", "reason", "proposed_at",
                                       "agent", "task", "run_id", "base_sha256", "event_context",
                                       "review_class", "link_evidence", "proposal_body_sha256", "refinement", "optimization")})
    if generated:
        note_meta["kind"] = "runbook"
        note_meta["task"] = f"[[{generation_params['target_task']}]]"
        note_meta["for_agent"] = f"[[{generation_params['target_agent']}]]"
        note_meta["skills"] = list(meta["skills"])
        note_meta["generated_by"] = "[[Runbooks/create-a-runbook]]"
    note_meta.setdefault("title", meta.get("title"))
    note_meta["approved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    note_meta["provenance"] = f"proposed by {meta.get('agent', '?')} (task {meta.get('task', '-')})"
    _validate_capability_metadata(target, note_meta)
    body = normalize_article_body(body, str(note_meta.get("title") or Path(target).stem))
    tool_preimage = (
        accepted_path.read_bytes()
        if accepted_path.is_file() and str(note_meta.get("kind", "")).lower() == "tool"
        else None
    )
    write_note(target, note_meta, body)

    paired_skill = None
    companions = (
        _pending_skill_pairs(target.removesuffix(".md"))
        if str(note_meta.get("kind", "")).lower() == "tool"
        else []
    )
    if companions:
        try:
            paired_result = approve(companions[0].name)
        except Exception as exc:
            if tool_preimage is None:
                accepted_path.unlink(missing_ok=True)
            else:
                accepted_path.write_bytes(tool_preimage)
            raise ValueError(f"paired Skill approval failed: {exc}") from exc
        paired_skill = str(paired_result.get("approved", ""))

    if generated:
        if origin:
            def complete_matching_event(origin_meta: dict) -> None:
                if origin_meta.get("params") != generation_params:
                    return
                origin_meta["status"] = "completed"
                origin_meta["generated_runbook"] = f"[[{target[:-3]}]]"
                origin_meta["status_updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")

            mutate_note_metadata(origin, complete_matching_event)
    review_outcome = _record_review_decision(path.name, meta, target, "approved")
    path.unlink()
    reconcile_origin_review_task(str(meta.get("task", "")))
    git_commit(f"[review] approve: {target} (from {meta.get('agent', '?')})", [target])
    from .index import INDEX
    INDEX.sync()
    notify_link_review(path.name, {**meta, "review_class": review_class}, "approved", links=approved_links)
    return {
        "approved": target,
        "paired_skill": paired_skill,
        "for_agent": generation_params.get("target_agent") if generated else None,
        "evidence_warning": evidence_warning,
        "review_outcome": review_outcome,
    }


def reject(name: str, reason: str = "") -> dict:
    with _NOTE_WRITE_LOCK:
        return _reject(name, reason)


def _reject(name: str, reason: str = "") -> dict:
    path, meta, body = _load_proposal(name)
    meta["rejected_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    meta["rejected_reason"] = reason[:400]
    dest = f"_staging/_rejected/{path.name}"
    write_note(dest, meta, body)
    review_outcome = _record_review_decision(path.name, meta, str(meta.get("target", "")), "rejected")
    path.unlink()
    reconcile_origin_review_task(str(meta.get("task", "")))
    notify_link_review(path.name, meta, "rejected")
    return {
        "rejected": path.name,
        "moved_to": dest,
        "review_outcome": review_outcome,
    }

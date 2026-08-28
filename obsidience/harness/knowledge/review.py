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
import subprocess
import time
from collections import Counter
from pathlib import Path

import frontmatter

from ..config import CONFIG
from .tasks import task_triggers
from .vault import (
    Resolver,
    WIKILINK_RE,
    iter_notes,
    load_note,
    mutate_note_metadata,
    normalize_article_body,
    resolver,
    write_note,
)

REVIEW_CLASSES = frozenset({"article", "link"})


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


def _resolved_body_links(body: str, accepted_resolver: Resolver) -> set[str]:
    refs: set[str] = set()
    for raw in WIKILINK_RE.findall(body):
        target = accepted_resolver.resolve(raw)
        refs.add(target.ref if target else raw.strip())
    return refs


def git_commit(message: str, rel_paths: list[str]) -> None:
    if not CONFIG.git_commit:
        return
    try:
        root = CONFIG.project_root
        vault_prefix = CONFIG.vault_dir.relative_to(root)
        subprocess.run(["git", "-C", str(root), "add", "--"] +
                       [str(vault_prefix / p) for p in rel_paths],
                       check=False, capture_output=True, timeout=15)
        subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", message,
                        "--author", "Obsidience Harness <harness@obsidience.local>"],
                       check=False, capture_output=True, timeout=15)
    except Exception:  # noqa: BLE001 — audit trail must never break the run
        pass


def list_proposals() -> list[dict]:
    accepted = iter_notes()
    accepted_resolver = Resolver(accepted)
    out = []
    for p in sorted(CONFIG.staging_dir.glob("*.md")):
        post = frontmatter.load(p)
        meta = dict(post.metadata or {})
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
            before = _resolved_body_links(existing.body, accepted_resolver) if existing else set()
            after = _resolved_body_links(post.content, accepted_resolver)
            link_changes = {
                "added": sorted(after - before),
                "removed": sorted(before - after),
            }
        out.append({
            "file": p.name, "title": title, "review_class": review_class,
            "link_changes": link_changes,
            "action": meta.get("action", "create"), "target": target,
            "agent": meta.get("agent", "?"), "task": task_ref,
            "run_id": meta.get("run_id", ""),
            "reason": meta.get("reason", ""), "proposed_at": meta.get("proposed_at", ""),
            "body_preview": normalize_article_body(post.content, title)[:12_000],
            "base_sha256": meta.get("base_sha256", ""),
        })

    target_counts = Counter(str(row["target"]) for row in out)
    by_target: dict[str, list[dict]] = {}
    for row in out:
        by_target.setdefault(str(row["target"]), []).append(row)

    for row in out:
        target = str(row["target"])
        block = ""
        if target_counts[target] > 1:
            block = "Multiple pending proposals target this Article. Reject stale copies first."
        accepted_path = CONFIG.vault_dir / target
        base_sha256 = str(row.get("base_sha256", ""))
        if not block and base_sha256 and accepted_path.is_file():
            current_sha256 = hashlib.sha256(accepted_path.read_bytes()).hexdigest()
            if current_sha256 != base_sha256:
                block = "The accepted Article changed after this proposal was drafted. Reject it and rerun the Task."
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


def _load_proposal(name: str) -> tuple[Path, dict, str]:
    p = CONFIG.staging_dir / name
    if not p.exists() or p.parent != CONFIG.staging_dir:
        raise FileNotFoundError(name)
    post = frontmatter.load(p)
    return p, dict(post.metadata or {}), post.content


def _pending_skill_pairs(tool_ref: str) -> list[Path]:
    """Return pending leaf Skill proposals paired to one exact Tool ref."""
    matches: list[Path] = []
    for path in CONFIG.staging_dir.glob("*.md"):
        meta = dict(frontmatter.load(path).metadata or {})
        raw_tool = str(meta.get("tool", "")).strip().strip("[]").split("|", 1)[0]
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
    if not origin or origin.kind != "task":
        return ""
    status = str(origin.meta.get("status", ""))
    for pending in CONFIG.staging_dir.glob("*.md"):
        pending_meta = dict(frontmatter.load(pending).metadata or {})
        pending_origin = resolver().resolve(str(pending_meta.get("task", "")))
        if pending_origin and pending_origin.ref == origin.ref:
            return status
    if status != "review":
        return status

    def complete(meta: dict) -> None:
        if str(meta.get("status")) != "review":
            return
        meta["status"] = "completed"
        meta["status_updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        meta.pop("blocked_reason", None)

    mutate_note_metadata(origin, complete)
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
        if "sources" in meta:
            raise ValueError("Tool proposal must use one singular source field")
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
    path, meta, body = _load_proposal(name)
    target = str(meta.get("target", "")).strip()
    if not target or target.startswith(("_", "/")) or ".." in target:
        raise ValueError(f"invalid target: {target}")
    action = meta.get("action", "create")
    if action not in ("create", "update", "archive"):
        raise ValueError(f"invalid action: {action}")
    expected_review_class = review_class_for_task(str(meta.get("task", "")))
    review_class = str(meta.get("review_class") or expected_review_class)
    if review_class not in REVIEW_CLASSES or review_class != expected_review_class:
        raise ValueError("proposal review class does not match its accepted Task")
    existing = load_note(target)
    conflicts = []
    for pending in CONFIG.staging_dir.glob("*.md"):
        if pending == path:
            continue
        pending_meta = dict(frontmatter.load(pending).metadata or {})
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
    if action == "create" and existing:
        raise ValueError(f"target already exists: {target} (use action: update)")
    if action == "update" and not existing:
        raise ValueError(f"target does not exist: {target} (use action: create)")
    if action == "archive" and not existing:
        raise ValueError(f"target does not exist: {target}")
    if action == "archive":
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
        destination = CONFIG.vault_dir / "_archived" / target
        if destination.exists():
            raise ValueError(f"archive destination already exists: _archived/{target}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        (CONFIG.vault_dir / target).rename(destination)
        path.unlink()
        reconcile_origin_review_task(str(meta.get("task", "")))
        git_commit(
            f"[review] archive: {target} (from {meta.get('agent', '?')})",
            [target, f"_archived/{target}"],
        )
        from .index import INDEX

        INDEX.sync()
        return {"archived": target, "moved_to": f"_archived/{target}"}
    origin_ref = str(meta.get("task", "")).strip().strip("[]")
    origin = resolver().resolve(origin_ref) if origin_ref else None
    proposal_context = meta.get("event_context", {})
    generation_params = (
        proposal_context
        if origin and "task.checkout" in task_triggers(origin.meta)
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

        validate_generated_runbook(target, body, generation_params)

    # An update changes authored content, not the note's graph identity. Start
    # from accepted metadata so task edges, checkouts, source citations, and
    # other fields cannot disappear merely because vault.propose carries only
    # the common proposal envelope.
    note_meta = dict(existing.meta) if action == "update" and existing else {}
    note_meta.update({k: v for k, v in meta.items()
                      if k not in ("proposal", "action", "target", "reason", "proposed_at",
                                   "agent", "task", "run_id", "base_sha256", "event_context",
                                   "review_class")})
    if generated:
        note_meta["kind"] = "runbook"
        note_meta["task"] = f"[[{generation_params['target_task']}]]"
        note_meta["for_agent"] = f"[[{generation_params['target_agent']}]]"
        note_meta["skills"] = [f"[[{ref}]]" for ref in generation_params.get("skills", [])]
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

    checked_out_to = None
    if generated:
        identity = resolver().resolve(str(generation_params["target_agent"]))
        if identity and identity.kind == "agent":
            def attach_runbook(identity_meta: dict) -> None:
                runbooks = [str(value) for value in (
                    identity_meta.get("runbooks")
                    if isinstance(identity_meta.get("runbooks"), list)
                    else [identity_meta.get("runbooks")] if identity_meta.get("runbooks") else []
                )]
                if not any(str(value).strip().strip("[]").split("|", 1)[0] == target[:-3]
                           for value in runbooks):
                    runbooks.append(f"[[{target[:-3]}]]")
                identity_meta["runbooks"] = runbooks

            mutate_note_metadata(identity, attach_runbook)
            checked_out_to = identity.ref
        if origin:
            def complete_matching_event(origin_meta: dict) -> None:
                if origin_meta.get("params") != generation_params:
                    return
                origin_meta["status"] = "completed"
                origin_meta["generated_runbook"] = f"[[{target[:-3]}]]"
                origin_meta["status_updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")

            mutate_note_metadata(origin, complete_matching_event)
    path.unlink()
    reconcile_origin_review_task(str(meta.get("task", "")))
    git_commit(f"[review] approve: {target} (from {meta.get('agent', '?')})", [target])
    from .index import INDEX
    INDEX.sync()
    return {
        "approved": target,
        "paired_skill": paired_skill,
        "checked_out_to": checked_out_to,
    }


def reject(name: str, reason: str = "") -> dict:
    path, meta, body = _load_proposal(name)
    meta["rejected_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    meta["rejected_reason"] = reason[:400]
    dest = f"_staging/_rejected/{path.name}"
    write_note(dest, meta, body)
    path.unlink()
    reconcile_origin_review_task(str(meta.get("task", "")))
    return {"rejected": path.name, "moved_to": dest}

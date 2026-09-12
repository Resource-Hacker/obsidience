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

import base64
import hashlib
import json
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
    _atomic_write,
    _extract_links,
    iter_notes,
    load_note,
    mutate_note_metadata,
    normalize_article_body,
    resolver,
    write_note,
)

REVIEW_CLASSES = frozenset({"article", "link"})
MAX_REVIEW_MEMBERS = 24
MAX_REVIEW_TRANSACTION_BYTES = 16 * 1024 * 1024
MAX_PENDING_LINKS = 128


def _transaction_path(group: str) -> Path:
    return CONFIG.staging_dir / f".review-transaction-{group}.json"


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


def _transaction_plan(group: str, rows: list[dict], writes: list[tuple[Path, str | None]]) -> dict:
    return {
        "schema_version": 1, "review_group": group, "decisions": rows,
        "files": [{"path": str(path.relative_to(CONFIG.vault_dir)),
                   "before": base64.b64encode(path.read_bytes()).decode() if path.exists() else None,
                   "after_sha256": hashlib.sha256(material.encode()).hexdigest() if material is not None else None}
                  for path, material in writes],
    }


def _transaction_feed_continuation(plan: dict) -> dict | None:
    """The original pinned proposal carries continuation, including after a crash."""
    rows = plan.get("decisions") or []
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("Feed continuation decisions are invalid")
    if not rows or any(row.get("decision") != "approved" for row in rows):
        return None
    first = rows[0]
    if not all(isinstance(first.get(key), str) for key in ("proposal_id", "task_ref", "run_id")):
        raise ValueError("Feed continuation origin is invalid")
    if not isinstance(plan.get("files"), list) or any(not isinstance(file, dict) for file in plan["files"]):
        raise ValueError("Feed continuation preimages are invalid")
    original = next((file for file in plan.get("files", [])
                     if file.get("path") == "_staging/" + first["proposal_id"]), None)
    if not original or not original.get("before"):
        return None
    meta, _body = article_format.loads(base64.b64decode(original["before"], validate=True).decode())
    envelope = meta.get("feed_retention")
    if envelope is not None and (not isinstance(envelope, dict) or set(envelope) != {
            "feed_id", "destination_ref", "max_active_articles", "membership_sha256", "publication", "include_incoming"}):
        raise ValueError("Feed continuation controller envelope is invalid")
    if envelope is None or envelope.get("include_incoming") is not False:
        return None
    if (meta.get("review_group") != plan["review_group"] or meta.get("action") != "archive"
            or meta.get("review_members") != [row["proposal_id"] for row in rows]
            or meta.get("task", "") != first["task_ref"] or meta.get("run_id", "") != first["run_id"]):
        raise ValueError("Feed continuation does not match its committed Review")
    return {"envelope": envelope, "context": {key: meta.get(key, "") for key in ("agent", "task", "run_id")}}


def _recover_group_transaction(path: Path, *, retain_continuation: bool = False) -> tuple[bool, str]:
    """Rollback an undecided publication or finish an already committed one.

    The existing SQLite decision rows are the commit witness. Unexpected
    current bytes are never overwritten by a stale transaction preimage.
    """
    from .index import INDEX

    if path.stat().st_size > MAX_REVIEW_TRANSACTION_BYTES:
        raise ValueError("Review recovery manifest exceeds its bound")
    plan = json.loads(path.read_text(encoding="utf-8"))
    group, rows, files = plan.get("review_group"), plan.get("decisions"), plan.get("files")
    if (plan.get("schema_version") != 1 or not isinstance(group, str)
            or len(group) != 64 or any(char not in "0123456789abcdef" for char in group)
            or path != _transaction_path(group)
            or not isinstance(rows, list) or not 1 <= len(rows) <= MAX_REVIEW_MEMBERS
            or not isinstance(files, list) or not 1 <= len(files) <= MAX_REVIEW_MEMBERS * 3):
        raise ValueError("invalid Review recovery manifest")
    allowed, proposal_paths, decisions = set(), set(), []
    for row in rows:
        if (not isinstance(row, dict)
                or set(row) != {"proposal_id", "run_id", "task_ref", "target", "decision"}
                or any(not isinstance(value, str) for value in row.values())
                or row["decision"] not in {"approved", "rejected"}
                or Path(row["proposal_id"]).name != row["proposal_id"]
                or not row["proposal_id"].endswith(".md")):
            raise ValueError("invalid Review recovery disposition")
        target = _group_target(row["target"])
        proposal = "_staging/" + row["proposal_id"]
        if proposal in proposal_paths:
            raise ValueError("duplicate Review recovery member")
        proposal_paths.add(proposal)
        allowed.add(proposal)
        if row["decision"] == "approved":
            allowed.update({target, "_archived/" + target})
        else:
            allowed.add("_staging/_rejected/" + row["proposal_id"])
        existing = INDEX.review_decision(row["proposal_id"])
        if existing and any(existing.get(key) != value for key, value in row.items()):
            raise ValueError("Review recovery decision conflicts with its exact proposal")
        decisions.append(existing is not None)
    if len({row["decision"] for row in rows}) != 1 or len({(row["task_ref"], row["run_id"]) for row in rows}) != 1:
        raise ValueError("Review recovery members disagree about their disposition")
    if any(decisions) and not all(decisions):
        raise ValueError("Review recovery found a partial decision group")
    committed = all(decisions)
    restored, seen = [], set()
    for file in files:
        if not isinstance(file, dict) or set(file) != {"path", "before", "after_sha256"}:
            raise ValueError("invalid Review recovery file")
        rel = file["path"]
        archive_of = next((row["target"] for row in rows if row["decision"] == "approved"
                          and isinstance(rel, str)
                          and str(Path(rel).parent) == str(Path("_archived") / Path(row["target"]).parent)
                          and re.fullmatch(re.escape(Path(row["target"]).stem) + r"--[0-9a-f]{16}(?:-[0-9]{1,3})?\.md", Path(rel).name)), None)
        if not isinstance(rel, str) or (rel not in allowed and archive_of is None) or rel in seen:
            raise ValueError("Review recovery file is outside its exact member set")
        seen.add(rel)
        target = CONFIG.vault_dir / rel
        if any(parent.is_symlink() for parent in (target, *target.parents)):
            raise ValueError("Review recovery cannot follow symlinks")
        encoded = file["before"]
        if encoded is not None and not isinstance(encoded, str):
            raise ValueError("invalid Review recovery preimage")
        before = base64.b64decode(encoded, validate=True) if encoded is not None else None
        before_hash = hashlib.sha256(before).hexdigest() if before is not None else None
        after_hash = file["after_sha256"]
        if after_hash is not None and (not isinstance(after_hash, str) or len(after_hash) != 64
                                       or any(char not in "0123456789abcdef" for char in after_hash)):
            raise ValueError("invalid Review recovery postimage hash")
        current_hash = hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else None
        if current_hash not in {before_hash, after_hash}:
            raise ValueError(f"Review recovery preserves unexpected current Article bytes: {rel}")
        if committed and rel not in proposal_paths and current_hash != after_hash:
            raise ValueError(f"Review committed file does not match its publication: {rel}")
        if rel in proposal_paths and (before is None or after_hash is not None):
            raise ValueError("Review recovery must preserve exact pending proposal preimages")
        restored.append((target, before))
    if not proposal_paths <= seen:
        raise ValueError("Review recovery is missing a pending member preimage")
    by_path = {file["path"]: file for file in files}
    expected_archives = set()
    for row in rows:
        destination = row["target"] if row["decision"] == "approved" else "_staging/_rejected/" + row["proposal_id"]
        if destination not in by_path:
            raise ValueError("Review recovery is missing a publication file")
        if row["decision"] == "approved" and by_path[destination]["after_sha256"] is None:
            before = base64.b64decode(by_path[destination]["before"], validate=True)
            revision = hashlib.sha256(before).hexdigest()[:16]
            base = Path("_archived") / destination
            archived = [file for rel, file in by_path.items() if rel == str(base) or (
                str(Path(rel).parent) == str(base.parent)
                and re.fullmatch(re.escape(base.stem) + "--" + revision + r"(?:-[0-9]{1,3})?\.md", Path(rel).name))]
            if len(archived) != 1 or archived[0]["after_sha256"] is None or archived[0]["before"] is not None:
                raise ValueError("Review recovery is missing its archived Article")
            expected_archives.add(archived[0]["path"])
        elif row["decision"] == "rejected" and by_path[destination]["after_sha256"] is None:
            raise ValueError("Review recovery is missing its rejected proposal")
    if {rel for rel in seen if rel.startswith("_archived/")} != expected_archives:
        raise ValueError("Review recovery archive path does not attest its original revision")
    for target, before in restored:
        if committed:
            if str(target.relative_to(CONFIG.vault_dir)) in proposal_paths:
                target.unlink(missing_ok=True)
        elif before is None:
            target.unlink(missing_ok=True)
        else:
            _atomic_write(target, before.decode("utf-8"))
    if not (committed and retain_continuation and _transaction_feed_continuation(plan)):
        path.unlink()
    return committed, rows[0]["task_ref"]


def _recover_pending_publications() -> dict:
    """Finish older decisions before Review can supersede their pinned files.

    The caller holds the note lock across recovery and its subsequent writes.
    This is one bounded pass at admission, not background retry work.
    """
    from .index import INDEX

    rolled_back, finalized, origins = 0, 0, set()
    with INDEX.lock:
        for path in sorted(CONFIG.staging_dir.glob(".review-transaction-*.json")):
            committed, origin = _recover_group_transaction(path, retain_continuation=True)
            if committed:
                finalized += 1
                if not path.exists():
                    origins.add(origin)
            else:
                rolled_back += 1
    for origin in origins:
        reconcile_origin_review_task(origin)
    return {"rolled_back": rolled_back, "finalized": finalized}


def recover_groups() -> dict:
    """Run once at Harness startup, before index sync or Task admission."""
    discarded, discarded_tasks = 0, set()
    with _NOTE_WRITE_LOCK:
        recovered = _recover_pending_publications()
        pending = [_load_proposal(path.name) for path in CONFIG.staging_dir.glob("*.md")]
        builds = {meta.get("review_building") for _, meta, _ in pending if meta.get("review_building")}
        for group in builds:
            if not isinstance(group, str) or len(group) != 64 or any(char not in "0123456789abcdef" for char in group):
                raise ValueError("invalid interrupted Review build identity")
            building = [(path, meta, body) for path, meta, body in pending
                        if meta.get("review_building") == group or meta.get("review_group") == group]
            try:
                candidate = next(path.name for path, meta, _ in building if meta.get("review_group") == group)
                complete = _load_group(candidate, allow_building=True)
                if {path for path, _, _ in complete} != {path for path, _, _ in building}:
                    raise ValueError("Review build has incomplete membership")
            except (ValueError, OSError, StopIteration):
                # Preserve interrupted draft bytes in the existing rejected
                # staging lane; they never became independently reviewable.
                for path, meta, _ in building:
                    destination = CONFIG.staging_dir / "_rejected" / path.name
                    if destination.exists():
                        raise ValueError("interrupted Review build disposition already exists")
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    path.rename(destination)
                    if meta.get("task"):
                        discarded_tasks.add(str(meta["task"]))
                discarded += 1
            else:
                for path, meta, body in complete:
                    if meta.pop("review_building", None):
                        _atomic_write(path, article_format.dumps(meta, body))
    # Definitions precede the Article lock. Ordinary recovery above preserves
    # committed continuation journals until this owner has staged their successor.
    for path in sorted(CONFIG.staging_dir.glob(".review-transaction-*.json")):
        try:
            continuation = _resume_feed_retention(path)
            if continuation and continuation.get("staged"):
                _approve_retention_successors(continuation)
        except (ValueError, OSError) as exc:
            recovered.setdefault("blocked_continuations", []).append(str(exc)[:300])
    return {**recovered,
            **({"discarded_builds": discarded, "discarded_tasks": sorted(discarded_tasks)} if discarded else {})}


def _group_digest(members: list[tuple[Path, dict, str]]) -> str:
    material = [(path.name, {key: value for key, value in meta.items()
                            if key not in {"review_group_sha256", "review_building"}}, body)
                for path, meta, body in members]
    return hashlib.sha256(json.dumps(material, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _load_group(name: str, *, verify: bool = True, allow_building: bool = False) -> list[tuple[Path, dict, str]]:
    _path, first, _body = _load_proposal(name)
    group = first.get("review_group")
    names = first.get("review_members")
    if (not isinstance(group, str) or len(group) != 64
            or not isinstance(names, list) or not 1 <= len(names) <= MAX_REVIEW_MEMBERS
            or any(not isinstance(item, str) or Path(item).name != item
                   or not item.endswith(".md") for item in names)
            or len(set(names)) != len(names) or name not in names):
        raise ValueError("invalid Review group membership")
    members = [_load_proposal(item) for item in names]
    for pending in CONFIG.staging_dir.glob("*.md"):
        if pending.name not in names and _load_proposal(pending.name)[1].get("review_group") == group:
            raise ValueError("Review group has an unexpected additional member")
    for _path, meta, body in members:
        if meta.get("review_building") and not allow_building:
            raise ValueError("Review group is still being staged")
        if meta.get("review_group") != group or meta.get("review_members") != names:
            raise ValueError("Review group membership changed")
        if verify and meta.get("proposal_body_sha256") != hashlib.sha256(body.encode()).hexdigest():
            raise ValueError("Review group member body changed")
    if verify:
        digest = _group_digest(members)
        if any(meta.get("review_group_sha256") != digest for _, meta, _ in members):
            raise ValueError("Review group proposal metadata changed")
    return members


def _group_result(members: list[tuple[Path, dict, str]]) -> dict:
    path, meta, _body = members[0]
    return {
        "staged": str(path), "target": meta["target"], "action": meta["action"],
        "review_class": "article", "review_group": meta["review_group"],
        "member_count": len(members),
        "members": [{"file": p.name, "target": m["target"], "action": m["action"]}
                    for p, m, _ in members],
    }


def stage_group(specs: list[dict], context: dict, reason: str, batch_key: str) -> dict:
    """Stage one bounded Knowledge edition through ordinary Article proposals.

    The first member is its Review card. No member may publish independently.
    A repeated input reattaches the pinned group; generated.at is audit time,
    so its regeneration alone does not create a different edition.
    """
    from ..capabilities.vault.propose import stage_proposal

    if (not isinstance(specs, list) or not 1 <= len(specs) <= MAX_REVIEW_MEMBERS
            or any(not isinstance(spec, dict) for spec in specs)
            or not isinstance(batch_key, str) or not 1 <= len(batch_key) <= 512):
        raise ValueError("Review group requires 1-24 Knowledge changes and a bounded batch key")
    canonical = json.loads(json.dumps(specs, sort_keys=True))
    for spec in canonical:
        generated = (spec.get("metadata") or {}).get("generated")
        if isinstance(generated, dict):
            generated.pop("at", None)
    fingerprint = hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()
    group = hashlib.sha256(batch_key.encode()).hexdigest()
    with _NOTE_WRITE_LOCK:
        _recover_pending_publications()
        for pending in sorted(CONFIG.staging_dir.glob("*.md")):
            _, meta, _ = _load_proposal(pending.name)
            if meta.get("review_group") == group:
                members = _load_group(pending.name)
                if any(m.get("review_batch_sha256") != fingerprint for _, m, _ in members):
                    raise ValueError("Review batch key was reused for different Article changes")
                result = {**_group_result(members), "existing": True}
                context.setdefault("staged_proposals", []).append(result)
                return result
        targets = [str(spec.get("target", "")).removesuffix(".md") for spec in specs]
        if len(set(targets)) != len(targets):
            raise ValueError("Review group targets must be distinct")
        existing_names = {path.name for path in CONFIG.staging_dir.glob("*.md")}
        members = []
        child_context = {**context, "_group_staging": True, "_review_building": group,
                         "staged_proposals": []}
        try:
            for spec in specs:
                result = stage_proposal({**spec, "reason": reason}, child_context)
                path = Path(result["staged"])
                if path.name in existing_names or result.get("auto_approved"):
                    raise ValueError("Review group cannot adopt or publish an independent proposal")
                members.append(_load_proposal(path.name))
            names = [path.name for path, _, _ in members]
            for _path, meta, body in members:
                meta.update(review_group=group, review_members=names,
                            review_batch_sha256=fingerprint,
                            proposal_body_sha256=hashlib.sha256(body.encode()).hexdigest())
            digest = _group_digest(members)
            for path, meta, body in members:
                meta["review_group_sha256"] = digest
                _atomic_write(path, article_format.dumps(meta, body))
            _validate_group(members)
            for path, meta, body in members:
                meta.pop("review_building", None)
                _atomic_write(path, article_format.dumps(meta, body))
        except Exception:
            for path, _meta, _body in members:
                if path.name not in existing_names:
                    path.unlink(missing_ok=True)
            raise
        result = _group_result(members)
        context.setdefault("staged_proposals", []).append(result)
        return result


def _group_target(value: object) -> str:
    if not isinstance(value, str) or not value.endswith(".md"):
        raise ValueError("Review group target must be a Knowledge Article path")
    path = Path(value)
    if (path.is_absolute() or len(value) > 512
            or any(part.startswith((".", "_")) for part in path.parts)
            or path.parts[0] in {"Tools", "Skills", "Tasks", "Runbooks", "raw"}
            or path.name.casefold() in {"index.md", "log.md"}
            or any((CONFIG.vault_dir / parent).is_symlink() for parent in (path, *path.parents))):
        raise ValueError("Review group target must be an ordinary Knowledge Article path")
    return value


def _validate_group(members: list[tuple[Path, dict, str]], accepted: list[Note] | None = None) -> list[tuple[Path, str | None]]:
    """Validate base pins and all links against the complete proposed graph."""
    from ..capabilities.vault.propose import DOCUMENTARY_METADATA_FIELDS
    from .system import assert_system_article_writable

    accepted = iter_notes() if accepted is None else accepted
    from .curation import validate_feed_retention_group

    validate_feed_retention_group(members, accepted)
    candidates = {note.ref: note for note in accepted}
    names = {path.name for path, _, _ in members}
    targets = {_group_target(meta.get("target")) for _, meta, _ in members}
    if len(targets) != len(members):
        raise ValueError("Review group targets must be distinct")
    origins = {(meta.get("agent"), meta.get("task"), meta.get("run_id")) for _, meta, _ in members}
    if len(origins) != 1:
        raise ValueError("Review group members must have one originating execution")
    for path in CONFIG.staging_dir.glob("*.md"):
        if path.name not in names and _load_proposal(path.name)[1].get("target") in targets:
            raise ValueError("multiple pending proposals target this Review group")
    writes = []
    for _path, meta, body in members:
        target = _group_target(meta.get("target"))
        assert_system_article_writable(target)
        accepted_path = CONFIG.vault_dir / target
        action = meta.get("action")
        existing = candidates.get(target.removesuffix(".md"))
        if (meta.get("review_class") != "article"
                or review_class_for_task(str(meta.get("task", ""))) != "article"):
            raise ValueError("Review groups contain ordinary Knowledge Article proposals")
        if existing and (existing.kind != "knowledge" or existing.runtime_observation):
            raise ValueError("Review groups cannot change executable authority or runtime Observations")
        if action == "create":
            if existing or accepted_path.exists():
                raise ValueError(f"Review group create target already exists: {target}")
        elif action in {"update", "archive"}:
            if (not existing or not accepted_path.is_file()
                    or meta.get("base_sha256") != hashlib.sha256(accepted_path.read_bytes()).hexdigest()):
                raise ValueError(f"accepted Article changed or is missing: {target}")
        else:
            raise ValueError("Review group action must be create, update, or archive")
        if action == "archive":
            destination = _archive_destination(target)
            archive_meta = {**existing.meta, "article_status": "deprecated",
                            "archived_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            "archive_reason": str(meta.get("reason", ""))[:400]}
            writes.extend([(destination, article_format.dumps(archive_meta, existing.body)),
                           (accepted_path, None)])
            del candidates[existing.ref]
            continue
        fields = meta.get("authored_fields")
        allowed = (DOCUMENTARY_METADATA_FIELDS - {"status"}) | {"kind", "article_status"}
        if not isinstance(fields, list) or any(not isinstance(key, str) or key not in allowed for key in fields):
            raise ValueError("Review groups cannot author permission or executable metadata")
        note_meta = dict(existing.meta) if existing else {"kind": "knowledge"}
        note_meta.update({key: meta[key] for key in fields if key in meta})
        if note_meta.get("kind") != "knowledge":
            raise ValueError("Review groups contain only Knowledge Articles")
        note_meta.update(title=meta.get("title"), approved_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
                         provenance=f"proposed by {meta.get('agent', '?')} (task {meta.get('task', '-')})")
        material = article_format.dumps(note_meta, body)
        errors = article_format.validate_profile(article_format.parse(material)[0], target)
        if errors:
            raise ValueError("invalid Review group Article: " + "; ".join(errors))
        note = Note(target, str(note_meta["title"]), note_meta, body,
                    links=_extract_links(note_meta, body, target))
        candidates[note.ref] = note
        writes.append((accepted_path, material))
    res = Resolver(list(candidates.values()))
    previous_resolver = Resolver(accepted)
    previous_missing = {
        note.ref: {raw for raw in note.links if not previous_resolver.resolve(raw)}
        for note in accepted
    }
    for note in candidates.values():
        missing = [raw for raw in note.links if not res.resolve(raw)
                   and raw not in previous_missing.get(note.ref, set())]
        if missing:
            raise ValueError(f"Review group would leave unresolved Article links in {note.ref}: " + ", ".join(missing[:6]))
    return writes


def _resume_feed_retention(path: Path, *, definition_guard=None) -> dict | None:
    """Stage one successor before releasing the previous journal or originating Task."""
    from .curation import stage_feed_retention
    from ..connections.runtime import feed_destination_guard

    plan = json.loads(path.read_text())
    continuation = _transaction_feed_continuation(plan)
    if continuation is None:
        return None
    envelope, context = continuation["envelope"], continuation["context"]
    # The old batch is already accepted. A new cap can govern the remaining
    # work, while the original Inbox's destination is still exact authority.
    guard = definition_guard() if definition_guard else feed_destination_guard(envelope["feed_id"], expected_ref=envelope["destination_ref"])
    with guard as destination, _NOTE_WRITE_LOCK:
        if destination["destination_ref"] != envelope["destination_ref"]:
            raise ValueError("Feed continuation destination changed; its original Inbox remains retained")
        committed, origin = _recover_group_transaction(path, retain_continuation=True)
        if not committed:
            return None
        result = stage_feed_retention(envelope["feed_id"], destination, context, publication=envelope["publication"])
        # stage_group is idempotent. A crash before this unlink resumes the same
        # pending group; a crash afterward retains that group as visible Review.
        path.unlink()
        reconcile_origin_review_task(origin)
        return result


def resume_feed_retention(feed_id: str, *, definition_guard=None) -> dict | None:
    """Explicit policy edits resume already committed work before planning more."""
    result = None
    for path in sorted(CONFIG.staging_dir.glob(".review-transaction-*.json")):
        continuation = _transaction_feed_continuation(json.loads(path.read_text()))
        if not continuation or continuation["envelope"]["feed_id"] != feed_id:
            continue
        try:
            pending = _resume_feed_retention(path, definition_guard=definition_guard)
            if pending and pending.get("staged"):
                result = _approve_retention_successors(pending, definition_guard=definition_guard)
                if result.get("retention_pending") or result.get("retention_blocked"):
                    return result
        except (ValueError, OSError) as exc:
            return {"retention_blocked": str(exc)[:300]}
    return result


def _decide_group(name: str, decision: str, reason: str = "", *, definition_guard=None) -> dict:
    from .index import INDEX
    from .curation import feed_retention_guard, validate_feed_retention_group

    envelope = _load_proposal(name)[1].get("feed_retention") if decision == "approved" else None
    with feed_retention_guard(envelope, definition_guard=definition_guard) as destination, _NOTE_WRITE_LOCK:
        _recover_pending_publications()
        members = _load_group(name, verify=decision == "approved")
        root_path, root_meta, _body = members[0]
        if decision == "approved":
            if any(meta.get("feed_retention") != envelope for _path, meta, _body in members):
                raise ValueError("Feed retention binding changed before approval")
            if envelope is not None:
                validate_feed_retention_group(members, destination=destination)
            writes = _validate_group(members)
        else:
            writes = []
            for path, meta, body in members:
                destination = CONFIG.staging_dir / "_rejected" / path.name
                if destination.exists():
                    raise ValueError("rejected Review group destination already exists")
                rejected = {**meta, "rejected_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                            "rejected_reason": reason[:400]}
                writes.append((destination, article_format.dumps(rejected, body)))
        writes.extend((path, None) for path, _, _ in members)
        preimages = {path: path.read_bytes() if path.exists() else None for path, _ in writes}
        rows = [dict(proposal_id=path.name, run_id=str(meta.get("run_id", "")),
                     task_ref=str(meta.get("task", "")), target=meta["target"], decision=decision)
                for path, meta, _ in members]
        transaction_path = _transaction_path(root_meta["review_group"])
        if transaction_path.exists():
            raise ValueError("Review group has an unfinished publication; recover it before deciding again")
        material = json.dumps(_transaction_plan(root_meta["review_group"], rows, writes), sort_keys=True)
        if len(material.encode()) > MAX_REVIEW_TRANSACTION_BYTES:
            raise ValueError("Review transaction preimages exceed their bounded recovery envelope")
        _atomic_write(transaction_path, material)
        pending_paths = {path for path, _, _ in members}
        with INDEX.lock:
            INDEX.db.execute("BEGIN IMMEDIATE")
            try:
                for path, material in writes:
                    if path in pending_paths:
                        continue  # Retain every proposal until its decision is durable.
                    if material is None:
                        path.unlink()
                    else:
                        _atomic_write(path, material)
                INDEX.record_review_decisions(rows, commit=False)
                INDEX.db.commit()
            except Exception:
                INDEX.db.rollback()
                for path, material in preimages.items():
                    if material is None:
                        path.unlink(missing_ok=True)
                    else:
                        _atomic_write(path, material.decode("utf-8"))
                transaction_path.unlink()
                raise
        # The decision is now durable. Cleanup or index failures must never
        # report this accepted edition as an undecided proposal or replay it.
        warnings = []
        for path in pending_paths:
            try:
                path.unlink()
            except OSError as exc:
                warnings.append(f"proposal cleanup: {exc}"[:400])
        if decision == "approved":
            try:
                INDEX.sync()
            except Exception as exc:
                warnings.append(f"index refresh: {exc}"[:400])
            try:
                git_commit(f"[review] approve group: {root_meta['target']}",
                           [str(path.relative_to(CONFIG.vault_dir)) for path, _ in writes
                            if not str(path.relative_to(CONFIG.vault_dir)).startswith("_staging/")])
            except Exception as exc:
                warnings.append(f"audit commit: {exc}"[:400])
        continuation, continuation_error = None, ""
        if decision == "approved" and envelope and envelope["include_incoming"] is False:
            try:
                continuation = _resume_feed_retention(transaction_path, definition_guard=definition_guard)
            except (ValueError, OSError) as exc:
                continuation_error = str(exc)[:300]
                warnings.append("Feed continuation: " + continuation_error)
        try:
            reconcile_origin_review_task(str(root_meta.get("task", "")))
        except Exception as exc:
            warnings.append(f"Task reconciliation: {exc}"[:400])
        review_outcome = None
        try:
            review_outcome = INDEX.review_outcome(str(root_meta.get("run_id", "")))
        except Exception as exc:
            warnings.append(f"decision projection: {exc}"[:400])
        if not warnings:
            try:
                transaction_path.unlink(missing_ok=True)
            except OSError as exc:
                warnings.append(f"publication cleanup: {exc}"[:400])
        result = {
            ("approved" if decision == "approved" else "rejected"):
                root_meta["target"] if decision == "approved" else root_path.name,
            "review_group": root_meta["review_group"], "member_count": len(members),
            "members": [{"target": meta["target"], "action": meta["action"]} for _, meta, _ in members],
            **({"review_outcome": review_outcome} if review_outcome is not None else {}),
            "committed": True,
            **({"archived_count": sum(meta["action"] == "archive" for _, meta, _ in members)} if envelope else {}),
            **({"retention_pending": continuation} if continuation and continuation.get("staged") else {}),
            **({"retention_blocked": continuation_error} if continuation_error else {}),
        }
        if warnings:
            result["publication_warning"] = "; ".join(warnings)[:1600]
        return result


def _approve_retention_successors(pending: dict, *, definition_guard=None) -> dict:
    from .curation import enabled, feed_retention_guard

    archived, last = 0, {}
    while pending:
        name = Path(pending["staged"]).name
        try:
            envelope = _load_proposal(name)[1]["feed_retention"]
            with feed_retention_guard(envelope, definition_guard=definition_guard), _NOTE_WRITE_LOCK:
                if not all(enabled(member["target"]) for member in pending["members"]):
                    break
                last = _decide_group(name, "approved", definition_guard=definition_guard)
        except (ValueError, OSError) as exc:
            pending.update(auto_curate_blocked=str(exc)[:300], retention_status="blocked")
            break
        archived += last.get("archived_count", 0)
        pending = last.get("retention_pending")
        if last.get("retention_blocked"):
            break
    return {**last, "archived_count": archived, **({"retention_pending": pending} if pending else {})}


def approve_group(name: str, *, definition_guard=None) -> dict:
    result = _decide_group(name, "approved", definition_guard=definition_guard)
    if result.get("retention_pending"):
        following = _approve_retention_successors(result.pop("retention_pending"), definition_guard=definition_guard)
        result["archived_count"] = result.get("archived_count", 0) + following["archived_count"]
        result.update({key: following[key] for key in ("retention_pending", "retention_blocked") if key in following})
    return result


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
    if review_class != "link" or meta.get("review_group") or meta.get("review_building"):
        return
    from ..execution import activity
    from .index import INDEX

    run_id = str(meta.get("run_id", ""))
    if state == "pending":
        with _NOTE_WRITE_LOCK:
            # A concurrent owner decision may finish between staging and this
            # invalidation; never announce a removed proposal as pending.
            if (CONFIG.staging_dir / proposal_id).is_file() and INDEX.review_decision(proposal_id) is None:
                activity.emit_review_change(proposal_id, run_id, state)
        return
    decision = INDEX.review_decision(proposal_id)
    if (not decision or decision["decision"] != state
            or any(decision[key] != str(meta.get(field, "")) for key, field in (
                ("run_id", "run_id"), ("task_ref", "task"), ("target", "target")))):
        return
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


def _has_group_decision(name: str, meta: dict) -> bool:
    """A cleanup-only envelope cannot become pending work after commit."""
    if not meta.get("review_group"):
        return False
    from .index import INDEX

    decision = INDEX.review_decision(name)
    return bool(decision and decision.get("decision") in {"approved", "rejected"}
                and all(decision.get(key) == str(meta.get(field, ""))
                        for key, field in (("run_id", "run_id"), ("task_ref", "task"), ("target", "target"))))


def list_proposals() -> list[dict]:
    from .curation import feed_retention_guard

    # Read policy before the Article lock; approval independently revalidates
    # the exact current definition while holding both in their owner order.
    policies = {}
    for path in sorted(CONFIG.staging_dir.glob("*.md")):
        try:
            meta, _ = article_format.loads(path.read_text())
            envelope = meta.get("feed_retention")
            if envelope is not None:
                try:
                    with feed_retention_guard(envelope):
                        error = ""
                except (ValueError, OSError) as exc:
                    error = str(exc)
                policies[path.name] = (envelope, error)
        except OSError:
            continue  # A concurrent decision can remove this presentation row.
    with _NOTE_WRITE_LOCK:
        return _list_proposals(feed_policies=policies)


def _list_proposals(accepted: list[Note] | None = None, *, feed_policies=None) -> list[dict]:
    from ..execution.refinement import review_blocker
    from .system import assert_system_article_writable

    accepted = iter_notes() if accepted is None else accepted
    accepted_resolver = Resolver(accepted)
    out = []
    for p in sorted(CONFIG.staging_dir.glob("*.md")):
        meta, body = article_format.loads(p.read_text(encoding="utf-8"))
        if meta.get("review_building") or _has_group_decision(p.name, meta):
            continue
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
            **({"review_group": meta["review_group"], "review_members": meta.get("review_members", [])}
               if meta.get("review_group") else {}),
        })
        if blocker := review_blocker(Note(str(p.relative_to(CONFIG.vault_dir)), title, meta, body),
                                     accepted_resolver=accepted_resolver):
            out[-1]["blocked_reason"] = blocker
        try:
            assert_system_article_writable(target)
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

    # One ordinary Review card represents the complete candidate edition.
    # Per-member archive prerequisites are evaluated against that candidate,
    # rather than requiring the owner to publish a temporarily broken graph.
    collapsed = []
    seen_groups = set()
    by_file = {row["file"]: row for row in out}
    for row in out:
        group = row.get("review_group")
        if not group:
            collapsed.append(row)
            continue
        if group in seen_groups:
            continue
        seen_groups.add(group)
        root_name = next(iter(row.get("review_members") or []), row["file"])
        card = dict(by_file.get(root_name, row))
        try:
            members = _load_group(row["file"])
            _validate_group(members, accepted)
            envelope = members[0][1].get("feed_retention")
            if envelope is not None:
                captured = (feed_policies or {}).get(members[0][0].name)
                if not captured or captured[0] != envelope:
                    raise ValueError("Feed policy changed during the Review snapshot; refresh before deciding")
                if captured[1]:
                    raise ValueError(captured[1])
            card.update(approvable=True, blocked_reason="")
        except (ValueError, OSError) as exc:
            card.update(approvable=False, blocked_reason=str(exc))
            members = []
            for filename in row.get("review_members", []):
                if isinstance(filename, str) and filename in by_file:
                    members.append(_load_proposal(filename))
        card["members"] = [{"file": path.name, "target": meta.get("target", ""),
                            "action": meta.get("action", ""), "title": meta.get("title", "")}
                           for path, meta, _ in members]
        card["member_count"] = len(card["members"])
        card["body_preview"] = ("This Review decides the complete group together.\n\n" + "\n\n".join(
            f"## {meta.get('action', '').upper()}: {meta.get('title', '')}\n"
            f"{meta.get('target', '')}\n\n{body[:800]}"
            for _, meta, body in members
        ))[:12_000]
        collapsed.append(card)
    out = collapsed
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
                    or row.get("review_group") or review_class_for_task(row["task"], res) != "link"):
                continue
            source = by_path.get(row["target"])
            if not source or source.kind not in {"knowledge", "agent"} or source.runtime_observation:
                continue
            for target_ref in row["link_changes"]["added"]:
                target = by_ref.get(target_ref)
                if not target or target.kind not in {"knowledge", "agent"} or target.runtime_observation:
                    continue
                if (len(entries) == MAX_PENDING_LINKS or len(source.ref) > MAX_REVIEW_REF_CHARS
                        or len(target.ref) > MAX_REVIEW_REF_CHARS or len(row["file"]) > 512
                        or not isinstance(row["run_id"], str) or len(row["run_id"]) > 80):
                    truncated = True
                    continue
                entries.append({"proposal_id": row["file"], "run_id": row["run_id"],
                                "source": source.ref, "target": target.ref})
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
    if not origin or origin.kind != "task":
        return ""
    status = str(origin.meta.get("status", ""))
    for journal in CONFIG.staging_dir.glob(".review-transaction-*.json"):
        plan = json.loads(journal.read_text())
        continuation = _transaction_feed_continuation(plan)
        if continuation and continuation["context"]["task"] == origin.ref:
            return status
    pending_run_ids = set()
    for pending in CONFIG.staging_dir.glob("*.md"):
        pending_meta, _ = article_format.loads(pending.read_text(encoding="utf-8"))
        if _has_group_decision(pending.name, pending_meta):
            continue
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
    from .curation import feed_review_guard, validate_feed_proposal

    initial = _load_proposal(name)[1]
    if initial.get("review_group"):
        return approve_group(name)
    envelope = initial.get("feed_publication")
    with feed_review_guard(envelope) as destination:
        with _NOTE_WRITE_LOCK:
            _recover_pending_publications()
            _path, meta, body = _load_proposal(name)
            if meta.get("feed_publication") != envelope:
                raise ValueError("Feed proposal binding changed before approval")
            if envelope is not None:
                validate_feed_proposal(meta, body, destination=destination)
            return _approve(name)


def _approve(name: str) -> dict:
    from ..execution.refinement import review_blocker
    from .system import assert_system_article_writable

    path, meta, body = _load_proposal(name)
    if blocker := review_blocker(Note(str(path.relative_to(CONFIG.vault_dir)), str(meta.get("title") or path.stem), meta, body)):
        raise ValueError(blocker)
    if meta.get("review_building"):
        raise ValueError("Review group is still being staged")
    if meta.get("review_group"):
        return approve_group(name)
    target = str(meta.get("target", "")).strip()
    assert_system_article_writable(target)
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
    if existing and existing.runtime_observation:
        raise ValueError("runtime Observations are maintained by Compact and Promote, not wiki proposals")
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
    if action == "create" and existing:
        raise ValueError(f"target already exists: {target} (use action: update)")
    if action == "update" and not existing:
        raise ValueError(f"target does not exist: {target} (use action: create)")
    if action == "archive" and not existing:
        raise ValueError(f"target does not exist: {target}")
    evidence_warning = ""
    approved_links = []
    if review_class == "link":
        evidence_warning = _validate_link_evidence(meta, existing, body, Resolver(iter_notes()))
        approved_links = [{"source": existing.ref, "target": evidence["ref"]}
                          for evidence in meta["link_evidence"] if evidence["change"] == "added"]
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
                                       "review_class", "link_evidence", "proposal_body_sha256", "refinement")})
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
        _recover_pending_publications()
        return _reject(name, reason)


def _reject(name: str, reason: str = "") -> dict:
    path, meta, body = _load_proposal(name)
    if meta.get("review_building"):
        raise ValueError("Review group is still being staged")
    if meta.get("review_group"):
        return _decide_group(name, "rejected", reason)
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

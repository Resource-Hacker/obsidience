"""Adapter for ``vault.propose``."""

from __future__ import annotations

import hashlib
import re
import time

from obsidience.harness.config import CONFIG

PROPOSAL_METADATA_FIELDS = {
    "assignee", "binding", "kind", "owner_maintained", "reasoning_effort",
    "runbook", "skills", "source", "subrunbooks", "subskills", "subtasks",
    "subtools", "tool",
}
GENERATED_RUNBOOK_SECTIONS = (
    "Prerequisites",
    "Ordered Actions",
    "Bounded Branches",
    "Stop Conditions",
    "Completion Criteria",
    "Verification",
    "Recovery",
)


def _stage(meta: dict, body: str) -> str:
    from obsidience.harness.knowledge.vault import slugify, write_note

    timestamp = time.strftime("%Y%m%d-%H%M%S")
    nonce = f"{time.time_ns():x}"
    filename = (
        f"_staging/{timestamp}-"
        f"{slugify(meta.get('title') or meta.get('target') or 'proposal')}-{nonce}.md"
    )
    meta.setdefault("proposed_at", time.strftime("%Y-%m-%dT%H:%M:%S"))
    write_note(filename, meta, body)
    return filename


def validate_generated_runbook(target: str, body: str, params: dict) -> None:
    expected = str(params.get("output_runbook", "")).strip()
    if not expected or target != expected:
        raise ValueError(
            f"generated Runbook target must be the event output path: {expected or '(missing)'}"
        )
    if re.search(r"(?i)\btask\.checkout\b", body):
        raise ValueError(
            "generated Runbook must describe Task execution, not the internal task.checkout event"
        )
    if re.search(
        r"(?i)\b(?:chain[ -]of[ -]thought|hidden reasoning|internal reasoning|reasoning steps?)\b",
        body,
    ):
        raise ValueError(
            "generated Runbook must preserve findings and decisions, never hidden reasoning"
        )

    headings = {
        re.sub(r"[^a-z0-9]+", " ", heading.lower()).strip()
        for heading in re.findall(r"(?m)^#{1,6}\s+(.+?)\s*$", body)
    }
    missing = [
        section
        for section in GENERATED_RUNBOOK_SECTIONS
        if re.sub(r"[^a-z0-9]+", " ", section.lower()).strip() not in headings
    ]
    if missing:
        raise ValueError(
            "generated Runbook is missing required sections: " + ", ".join(missing)
        )

    allowed_skills = {
        str(ref).strip() for ref in params.get("skills", []) if str(ref).strip()
    }
    referenced_skills = set(re.findall(
        r"(?<![A-Za-z0-9_/-])Skills/[A-Za-z0-9._/-]*[A-Za-z0-9_-]",
        body,
    ))
    unknown_skills = sorted(referenced_skills - allowed_skills)
    if unknown_skills:
        raise ValueError(
            "generated Runbook names Skills outside the checkout: "
            + ", ".join(unknown_skills)
        )
    if allowed_skills and not referenced_skills:
        raise ValueError("generated Runbook must name its checked-out Skills explicitly")

    direct_tools = []
    for raw in params.get("tools", []):
        tool = str(raw).removeprefix("Tools/").strip()
        if tool and re.search(
            rf"(?<![A-Za-z0-9_.-]){re.escape(tool)}(?![A-Za-z0-9_.-])",
            body,
        ):
            direct_tools.append(tool)
    if direct_tools:
        raise ValueError(
            "generated Runbook grants Tools directly; name their paired Skills instead: "
            + ", ".join(sorted(set(direct_tools)))
        )


def stage_proposal(args: dict, context: dict) -> dict:
    from obsidience.harness.knowledge.review import review_class_for_task
    from obsidience.harness.knowledge.vault import (
        load_note,
        normalize_article_body,
    )

    target = str(args.get("target", "")).strip()
    if not target or target.startswith("_") or ".." in target:
        raise ValueError("invalid target path")
    if not target.endswith(".md"):
        target += ".md"
    action = str(args.get("action", "create")).strip().lower()
    if action not in {"create", "update", "archive"}:
        raise ValueError("action must be create, update, or archive")

    review_class = review_class_for_task(str(context.get("task", "")))
    if action == "archive":
        archive_target = load_note(target)
        if not archive_target or archive_target.kind != "knowledge":
            raise ValueError("archive target must be an accepted Knowledge Article")
    proposal_title = str(args.get("title") or target)[:200]
    body = normalize_article_body(str(args.get("body", "")), proposal_title)
    if action != "archive" and not body.strip():
        raise ValueError("create and update proposals require a nonempty body")
    if len(body) > 128 * 1024:
        raise ValueError("proposal body must contain 1-131072 characters")

    for pending_path in sorted(CONFIG.staging_dir.glob("*.md")):
        pending = load_note(pending_path.relative_to(CONFIG.vault_dir))
        if not pending or str(pending.meta.get("target", "")) != target:
            continue
        same_proposal = (
            str(pending.meta.get("action", "create")) == action
            and str(pending.meta.get("task", "")) == str(context.get("task", ""))
            and normalize_article_body(pending.body, pending.title) == body
        )
        if same_proposal:
            result = {
                "staged": str(pending_path),
                "target": target,
                "action": action,
                "review_class": str(pending.meta.get("review_class") or review_class),
                "existing": True,
            }
            context.setdefault("staged_proposals", []).append(result)
            return result
        raise ValueError(
            f"{target} already has a pending review proposal; decide it before staging another"
        )
    generation_params = (
        context.get("params")
        if context.get("event") == "task.checkout"
        and isinstance(context.get("params"), dict)
        else None
    )
    if generation_params is not None:
        if action not in {"create", "update"}:
            raise ValueError("checkout-generated Runbooks must use create or update")
        validate_generated_runbook(target, body, generation_params)
    proposal_meta = {
        "proposal": True,
        "action": action,
        "target": target,
        "title": proposal_title,
        "agent": str(context.get("agent", "interpreter"))[:80],
        "task": str(context.get("task", ""))[:300],
        "run_id": str(context.get("run_id", ""))[:80],
        "reason": str(args.get("reason", ""))[:400],
        "review_class": review_class,
    }
    accepted_path = CONFIG.vault_dir / target
    if action in {"update", "archive"} and accepted_path.is_file():
        proposal_meta["base_sha256"] = hashlib.sha256(accepted_path.read_bytes()).hexdigest()
    authored_meta = args.get("metadata", {})
    if not isinstance(authored_meta, dict):
        raise ValueError("metadata must be an object of safe authored frontmatter fields")
    unknown_meta = sorted(set(authored_meta) - PROPOSAL_METADATA_FIELDS)
    if unknown_meta:
        raise ValueError(f"invalid metadata fields: {', '.join(unknown_meta)}")
    accepted_note = load_note(target) if action == "update" else None
    effective_meta = dict(accepted_note.meta) if accepted_note else {}
    effective_meta.update(authored_meta)
    effective_meta.setdefault("title", proposal_title)
    if str(effective_meta.get("kind", "")).strip().lower() == "tool":
        if effective_meta.get("subtools"):
            if effective_meta.get("binding") or effective_meta.get("source"):
                raise ValueError(
                    "Tool index Articles cannot carry executable binding or source metadata"
                )
        else:
            from obsidience.harness.capabilities.registry import contract_error

            error = contract_error(
                effective_meta.get("title"),
                effective_meta.get("binding"),
                effective_meta.get("source"),
            )
            if error:
                raise ValueError(f"Tool proposal is not executable: {error}")
    proposal_meta.update({key: value for key, value in authored_meta.items()})
    if generation_params is not None:
        proposal_meta["kind"] = "runbook"
        proposal_meta["event_context"] = generation_params
    staged = _stage(proposal_meta, body)
    result = {
        "staged": staged,
        "target": target,
        "action": action,
        "review_class": review_class,
    }
    context.setdefault("staged_proposals", []).append(result)
    return result


def execute(args: dict, context: dict) -> str:
    try:
        result = stage_proposal(args or {}, context or {})
    except ValueError as exc:
        return f"Proposal rejected: {exc}."
    return f"Proposal staged for owner review at {result['staged']}."

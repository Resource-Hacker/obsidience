"""Adapter for ``vault.propose``."""

from __future__ import annotations

import hashlib
import re
import time

from obsidience.harness.config import CONFIG

DOCUMENTARY_METADATA_FIELDS = {
    "description", "resource", "sources", "generated", "status", "stale_after",
}
PROPOSAL_METADATA_FIELDS = {
    "acceptance", "assignee", "binding", "kind", "model", "owner_maintained",
    "reasoning_effort", "runbook", "skills", "source", "subrunbooks",
    "subskills", "subtasks", "subtools", "taxonomy_path", "tool", "triggers",
    "type", "obsidience",
} | DOCUMENTARY_METADATA_FIELDS | {"article_status"}
TASK_DEFINITION_METADATA_FIELDS = {
    "acceptance", "assignee", "kind", "model", "reasoning_effort", "runbook",
    "subtasks", "taxonomy_path", "triggers",
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
SKILL_REF_RE = re.compile(r"(?<![A-Za-z0-9_/-])/?Skills/[A-Za-z0-9._/-]*[A-Za-z0-9_-]")
TOOL_REF_RE = re.compile(r"(?<![A-Za-z0-9_/-])/?Tools/[A-Za-z0-9._/-]*[A-Za-z0-9_-]")
EVENT_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")


def _authored_metadata(value: object) -> dict:
    """Project native OKF input only after validating each authored field."""
    from obsidience.harness.knowledge.format import ARTICLE_TYPES, validate_profile

    if not isinstance(value, dict):
        raise ValueError("metadata must be an object of safe authored frontmatter fields")
    unknown = sorted(set(value) - (PROPOSAL_METADATA_FIELDS - {"article_status"}))
    if unknown:
        raise ValueError(f"invalid metadata fields: {', '.join(unknown)}")
    extension = value.get("obsidience", {})
    if not isinstance(extension, dict):
        raise ValueError("metadata obsidience must be an object")
    extension_fields = PROPOSAL_METADATA_FIELDS - DOCUMENTARY_METADATA_FIELDS - {"kind", "type", "obsidience", "article_status"}
    unknown_extension = sorted(set(extension) - extension_fields)
    if unknown_extension:
        raise ValueError("invalid metadata fields: " + ", ".join(
            f"obsidience.{field}" for field in unknown_extension
        ))
    projected = {key: item for key, item in value.items() if key not in {"type", "obsidience"}}
    for key, item in extension.items():
        if key in projected and projected[key] != item:
            raise ValueError(f"conflicting metadata field: {key}")
        projected[key] = item
    if "type" in value:
        native_type = value["type"]
        if not isinstance(native_type, str) or not native_type.strip():
            raise ValueError("metadata type must be a nonempty Article type")
        native_type = native_type.strip().lower()
        if "kind" in projected and str(projected["kind"]).strip().lower() != native_type:
            raise ValueError("conflicting metadata type and legacy kind")
        projected["kind"] = native_type
    if "kind" in projected and (
        not isinstance(projected["kind"], str) or projected["kind"] not in ARTICLE_TYPES
    ):
        raise ValueError("metadata type must be one of: " + ", ".join(sorted(ARTICLE_TYPES)))
    documentary = {key: value[key] for key in DOCUMENTARY_METADATA_FIELDS if key in value}
    errors = validate_profile({"type": projected.get("kind", "knowledge"), **documentary})
    if errors:
        raise ValueError("invalid documentary metadata: " + "; ".join(errors))
    if "status" in projected:
        projected["article_status"] = projected.pop("status")
    return projected


def _definition_ref(value: object) -> str:
    return str(value).strip().strip("[]").split("|", 1)[0].split("#", 1)[0].removesuffix(".md").lstrip("/")


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


def validate_generated_runbook(target: str, body: str, params: dict, skill_refs: object = None,
                               *, allow_implicit_completion: bool = False) -> None:
    expected = str(params.get("output_runbook", "")).strip()
    if not expected or target != expected:
        raise ValueError(
            f"generated Runbook target must be the event output path: {expected or '(missing)'}"
        )
    if re.search(r"(?i)\btask\.assigned\b", body):
        raise ValueError(
            "generated Runbook must describe Task execution, not the task.assigned event"
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
        _definition_ref(ref) for ref in params.get("skills", []) if str(ref).strip()
    }
    if not isinstance(skill_refs, list) or not skill_refs or any(
        not isinstance(ref, str) or not ref.strip() for ref in skill_refs
    ):
        raise ValueError("generated Runbook requires an explicit metadata.skills selection")
    selected_skills = {_definition_ref(ref) for ref in skill_refs}
    if not selected_skills <= allowed_skills:
        raise ValueError("generated Runbook selects Skills outside the shared Library catalog")
    referenced_skills = {_definition_ref(ref) for ref in SKILL_REF_RE.findall(body)}
    unknown_skills = sorted(referenced_skills - selected_skills)
    if unknown_skills:
        raise ValueError(
            "generated Runbook names Skills outside metadata.skills: "
            + ", ".join(unknown_skills)
        )
    if selected_skills - referenced_skills:
        raise ValueError("generated Runbook must explain every selected Skill explicitly")

    allowed_tools = {
        _definition_ref(raw).removeprefix("Tools/")
        for raw in params.get("tools", [])
        if _definition_ref(raw).removeprefix("Tools/")
    }
    unpaired_skills = sorted(
        ref.removeprefix("Skills/")
        for ref in selected_skills
        if ref.removeprefix("Skills/") not in allowed_tools
    )
    if unpaired_skills:
        raise ValueError(
            "generated Runbook selects Skills without paired Tools: "
            + ", ".join(unpaired_skills)
        )

    # Skill metadata, not prose, supplies executable authority. The procedure
    # may still name an authorized callable so the model knows what to invoke.
    # Check those names against the event's closed Tool set without treating a
    # body mention as a grant.
    from obsidience.harness.capabilities.registry import REGISTRY

    prose_without_skill_refs = SKILL_REF_RE.sub("", body)
    named_tools = {
        _definition_ref(ref).removeprefix("Tools/")
        for ref in TOOL_REF_RE.findall(prose_without_skill_refs)
    }
    named_tools.update(
        tool
        for tool in REGISTRY
        if re.search(
            rf"(?<![A-Za-z0-9_.-]){re.escape(tool)}(?![A-Za-z0-9_.-])",
            prose_without_skill_refs,
        )
    )
    selected_tools = {ref.removeprefix("Skills/") for ref in selected_skills}
    if allow_implicit_completion:
        # Existing procedures may use the executor's built-in completion Tool
        # without changing their accepted Skill metadata during a refinement.
        selected_tools.add("task.complete")
    unauthorized_tools = sorted(named_tools - selected_tools)
    if unauthorized_tools:
        raise ValueError(
            "generated Runbook names Tools outside its selected Skills: "
            + ", ".join(unauthorized_tools)
        )


def _nonempty_string_list(value: object, field: str, *, limit: int, item_limit: int) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"Task {field} must be a nonempty list")
    if len(value) > limit:
        raise ValueError(f"Task {field} may contain at most {limit} entries")
    values = [str(item).strip() if isinstance(item, str) else "" for item in value]
    if any(not item or len(item) > item_limit for item in values):
        raise ValueError(
            f"Task {field} entries must be nonempty strings of at most {item_limit} characters"
        )
    if len(set(values)) != len(values):
        raise ValueError(f"Task {field} entries must be unique")
    return values


def _validate_task_definition(
    target: str,
    metadata: dict,
    authored_metadata: dict,
    *,
    creating: bool,
    accepted_resolver,
) -> None:
    unexpected = sorted(set(authored_metadata) - TASK_DEFINITION_METADATA_FIELDS)
    if unexpected:
        raise ValueError(
            "invalid Task definition metadata fields: " + ", ".join(unexpected)
        )
    if not target.startswith("Tasks/"):
        raise ValueError("Task proposals must target Tasks/")
    if str(metadata.get("kind", "")).strip().lower() != "task":
        raise ValueError('Task proposals require metadata type "task"')

    if creating:
        missing = [
            field
            for field in ("assignee", "taxonomy_path", "acceptance")
            if not metadata.get(field)
        ]
        if missing:
            raise ValueError(
                "new Task definitions require: " + ", ".join(missing)
            )

    assignee = metadata.get("assignee")
    if assignee:
        resolved_assignee = accepted_resolver.resolve(str(assignee))
        if not resolved_assignee or resolved_assignee.kind != "agent":
            raise ValueError("Task assignee must resolve to one accepted Agent")

    taxonomy_path = metadata.get("taxonomy_path")
    if taxonomy_path:
        from obsidience.harness.knowledge.tasks import TASK_TAXONOMY_BY_PATH

        if not isinstance(taxonomy_path, str) or taxonomy_path not in TASK_TAXONOMY_BY_PATH:
            raise ValueError(f"unknown Task taxonomy path: {taxonomy_path}")

    runbook = metadata.get("runbook")
    subtasks = metadata.get("subtasks")
    if bool(runbook) == bool(subtasks):
        raise ValueError("Task definition requires exactly one of runbook or subtasks")
    if runbook:
        if not isinstance(runbook, str):
            raise ValueError("Task runbook must be one accepted Runbook reference")
        resolved_runbook = accepted_resolver.resolve(runbook)
        if not resolved_runbook or resolved_runbook.kind != "runbook":
            raise ValueError("Task runbook must resolve to one accepted Runbook")
    if subtasks:
        subtask_refs = _nonempty_string_list(
            subtasks, "subtasks", limit=32, item_limit=240,
        )
        for ref in subtask_refs:
            resolved_subtask = accepted_resolver.resolve(ref)
            if not resolved_subtask or resolved_subtask.kind != "task":
                raise ValueError(f"Task subtask must resolve to an accepted Task: {ref}")
            if resolved_subtask.ref == target.removesuffix(".md"):
                raise ValueError("Task cannot name itself as a subtask")

    if "acceptance" in metadata:
        _nonempty_string_list(
            metadata["acceptance"], "acceptance", limit=16, item_limit=400,
        )

    if "triggers" in metadata:
        triggers = _nonempty_string_list(
            metadata["triggers"], "triggers", limit=16, item_limit=80,
        )
        if invalid := [event for event in triggers if not EVENT_NAME_RE.fullmatch(event)]:
            raise ValueError("invalid Task triggers: " + ", ".join(invalid))

    if "model" in metadata:
        from obsidience.harness.models.runtime import MODELS

        model = metadata["model"]
        if not isinstance(model, str) or model not in MODELS:
            raise ValueError(f"Task model is not registered: {model}")

    if "reasoning_effort" in metadata:
        effort = metadata["reasoning_effort"]
        if effort not in {"none", "low", "medium", "high", "xhigh"}:
            raise ValueError(
                "Task reasoning_effort must be none, low, medium, high, or xhigh"
            )


def stage_proposal(args: dict, context: dict) -> dict:
    from obsidience.harness.knowledge.links import canonical_body
    from obsidience.harness.knowledge.review import link_evidence, review_class_for_task
    from obsidience.harness.knowledge.vault import (
        Resolver,
        iter_notes,
        load_note,
        normalize_article_body,
    )

    target = str(args.get("target", "")).strip()
    if not target or target.startswith("_") or ".." in target:
        raise ValueError("invalid target path")
    if not target.endswith(".md"):
        target += ".md"
    from obsidience.harness.knowledge.system import assert_system_article_writable

    assert_system_article_writable(target)
    action = str(args.get("action", "create")).strip().lower()
    if action not in {"create", "update", "archive"}:
        raise ValueError("action must be create, update, or archive")
    params = context.get("params")
    if (not context.get("_feed_compiling") and context.get("task") == "Tasks/ingest"
            and context.get("event") == "source.inbox" and isinstance(params, dict)
            and params.get("feed_binding")):
        return _stage_feed_article(args, context)
    if "source" in args:
        raise ValueError("proposal source is supported only for the active source-bound Feed Ingest")
    if "contextual_links" in args:
        raise ValueError("contextual_links is not a proposal field; use ordinary Article links")
    existing_target = load_note(target)
    if existing_target and existing_target.runtime_observation:
        raise ValueError("runtime Observations are maintained by Compact and Promote, not wiki proposals")

    review_class = review_class_for_task(str(context.get("task", "")))
    if action == "archive":
        archive_target = load_note(target)
        if not archive_target or archive_target.kind != "knowledge":
            raise ValueError("archive target must be an accepted Knowledge Article")
    proposal_title = str(args.get("title") or target)[:300 if context.get("_feed_compiling") else 200]
    # Canonicalize against the target before staging changes its filesystem
    # parent; pin the exact final newline emitted by the OKF serializer too.
    body = canonical_body(
        normalize_article_body(str(args.get("body", "")), proposal_title).strip(), target,
    )
    if action != "archive" and not body.strip():
        raise ValueError("create and update proposals require a nonempty body")
    if body:
        body += "\n"
    if len(body) > 128 * 1024:
        raise ValueError("proposal body must contain 1-131072 characters")
    authored_meta = _authored_metadata(args.get("metadata", {}))
    from obsidience.harness.execution.refinement import (
        candidate_staged, proposal_context, validate_candidate,
    )

    refinement = proposal_context(context)
    if refinement is not None:
        validate_candidate(target, action, proposal_title, body, authored_meta, refinement)

    for pending_path in sorted(CONFIG.staging_dir.glob("*.md")):
        pending = load_note(pending_path.relative_to(CONFIG.vault_dir))
        if not pending or str(pending.meta.get("target", "")) != target:
            continue
        pending_fields = pending.meta.get(
            "authored_fields", sorted(PROPOSAL_METADATA_FIELDS & pending.meta.keys()),
        )
        same_proposal = (
            str(pending.meta.get("action", "create")) == action
            and str(pending.meta.get("task", "")) == str(context.get("task", ""))
            and normalize_article_body(pending.body, pending.title) == body
            and isinstance(pending_fields, list)
            and all(isinstance(key, str) for key in pending_fields)
            and {key: pending.meta.get(key) for key in pending_fields} == authored_meta
            and pending.meta.get("refinement") == refinement
            and (not context.get("_feed_compiling")
                 or (pending.meta.get("feed_publication") == context.get("_feed_publication")
                     and pending.meta.get("feed_retention") == context.get("_feed_retention")))
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
            if refinement is not None:
                candidate_staged(str(pending_path), context)
            return result
        raise ValueError(
            f"{target} already has a pending review proposal; decide it before staging another"
        )
    generation_params = (
        context.get("params")
        if context.get("event") == "task.assigned"
        and isinstance(context.get("params"), dict)
        else None
    )
    if generation_params is not None:
        if action not in {"create", "update"}:
            raise ValueError("generated Runbooks must use create or update")
        validate_generated_runbook(target, body, generation_params, authored_meta.get("skills"))
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
    if context.get("_feed_compiling") and context.get("_feed_publication"):
        proposal_meta["feed_publication"] = dict(context["_feed_publication"])
    if context.get("_feed_compiling") and context.get("_feed_retention"):
        proposal_meta["feed_retention"] = dict(context["_feed_retention"])
    if context.get("_group_staging") and context.get("_review_building"):
        proposal_meta["review_building"] = str(context["_review_building"])
    accepted_path = CONFIG.vault_dir / target
    if action in {"update", "archive"} and accepted_path.is_file():
        proposal_meta["base_sha256"] = hashlib.sha256(accepted_path.read_bytes()).hexdigest()
    proposal_meta["authored_fields"] = sorted(authored_meta)
    if review_class == "link":
        if action != "update" or authored_meta:
            raise ValueError("Link updates an existing Article body, not its authority metadata")
        proposal_meta["link_evidence"] = link_evidence(
            existing_target, body, Resolver(iter_notes()),
        )
        proposal_meta["proposal_body_sha256"] = hashlib.sha256(body.encode()).hexdigest()
    accepted_note = load_note(target) if action == "update" else None
    effective_meta = dict(accepted_note.meta) if accepted_note else {}
    effective_meta.update(authored_meta)
    effective_meta.setdefault("title", proposal_title)
    if target.startswith("Tasks/") or str(effective_meta.get("kind", "")).lower() == "task":
        _validate_task_definition(
            target,
            effective_meta,
            authored_meta,
            creating=action == "create",
            accepted_resolver=Resolver(iter_notes()),
        )
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
    if refinement is not None:
        proposal_meta["refinement"] = refinement
    staged = _stage(proposal_meta, body)
    result = {
        "staged": staged,
        "target": target,
        "action": action,
        "review_class": review_class,
    }
    if refinement is not None:
        # Bind evaluation to the complete staged file, including its metadata.
        candidate_staged(staged, context)
    if not context.get("_group_staging") and not context.get("_feed_compiling"):
        from obsidience.harness.knowledge.curation import try_auto_approve
        result = try_auto_approve(result, args, context)
        if review_class == "link" and not result.get("auto_approved"):
            from pathlib import Path
            from obsidience.harness.knowledge.review import notify_link_review

            notify_link_review(Path(staged).name, proposal_meta, "pending")
    context.setdefault("staged_proposals", []).append(result)
    return result


def _stage_feed_article(args: dict, context: dict) -> dict:
    """Publish the exact summary and any bounded retention through one owner."""
    from obsidience.harness.knowledge import curation
    from obsidience.harness.knowledge.vault import _NOTE_WRITE_LOCK

    params = context.get("params") or {}
    binding = params.get("feed_binding") or {}
    from obsidience.harness.connections.runtime import feed_destination_guard

    with feed_destination_guard(binding.get("feed_id", ""), expected_ref=binding.get("destination_ref")) as destination:
        with _NOTE_WRITE_LOCK:
            plan = curation.prepare_feed_article(args, context)
            if plan["already_current"]:
                result = {"target": plan["article"]["target"], "feed_publication": True,
                          "already_current": True}
                context["feed_publication_result"] = result
                return result
            result = curation.apply_feed_retention(binding["feed_id"], destination, context, publication=plan["envelope"])
            result["target"] = plan["article"]["target"]
            context["feed_publication_result"] = result
            return result


def execute(args: dict, context: dict) -> str:
    from obsidience.harness.knowledge.scope import assert_proposal_scope
    from obsidience.harness.knowledge.vault import resolver
    try:
        assert_proposal_scope(str((args or {}).get("target", "")), context or {}, resolver())
        result = stage_proposal(args or {}, context or {})
    except (ValueError, PermissionError) as exc:
        return f"Proposal rejected: {exc}."
    if result.get("feed_publication") and result.get("already_current"):
        return f"Article already published at {result['target']} from this Feed item version. Accepted content and timestamps were preserved."
    if result.get("auto_approved"):
        if result.get("feed_publication"):
            warning = result.get("approval", {}).get("publication_warning", "")
            return (f"Article published at {result['target']} under owner Auto-curate policy {result['policy']}. "
                    f"{result.get('archived_count', 0)} older Feed Articles were archived with their complete content and Sources preserved."
                    + (f" Publication follow-up warning: {warning}" if warning else ""))
        return f"Article published at {result['target']} under owner Auto-curate policy {result['policy']}."
    reason = result.get("auto_curate_blocked")
    return f"Proposal staged for owner review at {result['staged']}." + (
        f" Auto-curate could not publish: {reason}" if reason else ""
    )

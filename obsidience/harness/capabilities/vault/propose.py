"""Adapter for ``vault.propose``."""

from __future__ import annotations

import hashlib
import json
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


def _merge_retention(target: str, action: str, body: str, context: dict) -> dict | None:
    """Bind archive to the canonical candidate actually staged by this run."""
    from obsidience.harness.knowledge.links import metadata_ref

    if context.get("task") != "Tasks/merge":
        return None
    params = context.get("params") or {}
    refs = params.get("candidate_refs", [])
    candidates = {metadata_ref(ref).removesuffix(".md") + ".md"
                  for ref in refs if isinstance(ref, str)} if isinstance(refs, list) else set()
    retained = context.get("_merge_retained_updates", {})
    if action != "archive":
        return {"target": target, "body_sha256": hashlib.sha256(body.strip().encode()).hexdigest()} if (
            action == "update" and target in candidates) else None
    if len(candidates) < 2 or target not in candidates:
        raise ValueError("Merge archive must target one of its exact bound duplicate candidates")
    if len(retained) != 1 or target in retained:
        raise ValueError("Merge archive requires one distinct retained candidate update staged by this execution first")
    retained_target, body_sha256 = next(iter(retained.items()))
    if retained_target not in candidates:
        raise ValueError("Merge retained Article must belong to its exact bound duplicate candidates")
    return {"target": retained_target, "body_sha256": body_sha256}


def _memory_source_citations(text):
    """Extract canonical Source UUIDs without surrounding Markdown punctuation."""
    citations = set()
    for token in re.findall(r"source://[^\s<>\[\]()\"'`]+", text):
        citation = token.rstrip(".,;:!?")
        if not re.fullmatch(r"source://[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", citation):
            raise ValueError("Memory recommendation contains a malformed Source citation")
        citations.add(citation)
    return citations


def _check_memory_recommendation_limit(context):
    from obsidience.harness.knowledge.index import INDEX
    from obsidience.harness.knowledge.vault import load_note

    run_id = str(context.get("run_id") or "")
    if not run_id:
        raise ValueError("Memory recommendation requires its exact originating run")
    row = INDEX.db.execute("SELECT activation_id FROM runs WHERE id=?", (run_id,)).fetchone()
    # The running attempt has no runs row until finalization. The executor owns
    # this private identity, so retries still count earlier attempts immediately.
    activation_id = str(context.get("_activation_id") or (row[0] if row else ""))
    if not activation_id or (row and row[0] != activation_id):
        raise ValueError("Memory recommendation requires its exact originating activation")
    run_ids = {run_id}
    run_ids.update(row[0] for row in INDEX.db.execute(
        "SELECT id FROM runs WHERE activation_id=?", (activation_id,)))
    placeholders = ",".join("?" for _ in run_ids)
    decided = {row[0] for row in INDEX.db.execute(
        "SELECT proposal_id FROM review_decisions WHERE run_id IN (" + placeholders + ")",
        tuple(run_ids))}
    for path in CONFIG.staging_dir.glob("*.md"):
        pending = load_note(path.relative_to(CONFIG.vault_dir))
        if pending and pending.meta.get("run_id") in run_ids:
            decided.add(path.name)
    if len(decided) >= 3:
        raise ValueError("Memory Curate occurrence permits at most three recommendations, including decided proposals")


def stage_proposal(args: dict, context: dict, *, validate_only: bool = False) -> dict:
    from .read import ARTICLE_BODY_END, INBOUND_REFERENCES_HEADING, editable_proposal_body
    from obsidience.harness.knowledge.links import canonical_body, metadata_ref
    from obsidience.harness.knowledge.review import link_evidence, review_class_for_task, validate_proposal_target
    from obsidience.harness.knowledge.vault import (
        Resolver,
        iter_notes,
        load_note,
        normalize_article_body,
    )

    context.pop("_proposal_read_prerequisite", None)
    # Scope already accepts typed Article links. Persist that same exact path,
    # never the wiki-link brackets as part of a filename.
    target = metadata_ref(str(args.get("target", "")))
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
    if "source" in args:
        raise ValueError("proposal source is not an authored field; cite immutable Sources in the body")
    if "contextual_links" in args:
        raise ValueError("contextual_links is not a proposal field; use ordinary Article links")
    existing_target = validate_proposal_target(target, action)
    if "body" in args:
        args = {**args, "body": editable_proposal_body(str(args["body"]), existing_target, context)}
    if any(line.strip() in {ARTICLE_BODY_END, INBOUND_REFERENCES_HEADING}
           for line in str(args.get("body", "")).splitlines()):
        raise ValueError(
            "body contains generated vault.read context; omit the end marker and "
            "Accepted inbound references section, preserve the Article body and its authored links, "
            "then submit the corrected body"
        )
    if context.get("event") == "observations.memory.ready":
        from obsidience.harness.memory.hindsight import promotion_source
        if target.startswith("Agents/"):
            raise ValueError("Memory promotion recommends ordinary Knowledge, not Agent branches or Observations")
        source = promotion_source({**(context.get("params") or {}),
                                   "origin_task_ref": context.get("task"), "event": context.get("event")})
        receipt = context.get("_source_reads", {}).get(source["citation"], {})
        if (receipt.get("content_sha256") != source["content_sha256"]
                or [0, len(source["content"])] not in receipt.get("ranges", [])):
            raise ValueError("Read the complete bound Hindsight Source before recommending Knowledge")
        if action not in {"create", "update"} or (existing_target and existing_target.kind != "knowledge"):
            raise ValueError("Memory promotion creates or updates Knowledge recommendations; it cannot archive or change executable definitions")
        if args.get("metadata"):
            raise ValueError("Memory promotion authors documentary bodies, not Agent or capability metadata")
        # A valid page citation in the reason cannot mask a new foreign URI.
        citations = _memory_source_citations(
            str(args.get("body", "")) + "\n" + str(args.get("reason", "")))
        if source["citation"] not in citations:
            raise ValueError("Memory recommendation must cite its bound mental-model Source")
        preserved = set()
        if existing_target:
            from obsidience.harness.knowledge.source import get_source
            old_citations = _memory_source_citations(existing_target.body)
            for citation in citations & old_citations:
                get_source(citation, restore=False)
                preserved.add(citation)
        if not citations - preserved <= {source["citation"]}:
            raise ValueError("New memory recommendation citations must exactly match its bound mental-model Source")
    if existing_target and existing_target.runtime_observation:
        raise ValueError("runtime Observations are maintained by Compact and Promote, not wiki proposals")

    review_class = review_class_for_task(str(context.get("task", "")))
    link_resolver = Resolver(iter_notes()) if review_class == "link" else None
    if action == "archive":
        archive_target = load_note(target)
        if not archive_target or archive_target.kind != "knowledge":
            raise ValueError("archive target must be an accepted Knowledge Article")
    proposal_title = str(args.get("title") or "").strip()
    if proposal_title in {target, target.removesuffix(".md")}:
        proposal_title = ""
    if not proposal_title:
        # An omitted title on a body/link update must preserve the Article name.
        # A new Article can use its authored heading, never its directory path.
        heading = re.search(r"^#{1,6}\s+(.+?)\s*#*\s*$", str(args.get("body", "")), re.M)
        proposal_title = (existing_target.title if existing_target else
                          heading.group(1) if heading else target.rsplit("/", 1)[-1].removesuffix(".md"))
    proposal_title = proposal_title[:200]
    # Canonicalize against the target before staging changes its filesystem
    # parent; pin the exact final newline emitted by the OKF serializer too.
    body = canonical_body(
        normalize_article_body(str(args.get("body", "")), proposal_title).strip(), target,
        accepted_refs=[note.ref for note in link_resolver.by_ref.values()] if link_resolver else None,
    )
    if action != "archive" and not body.strip():
        raise ValueError("create and update proposals require a nonempty body")
    if body:
        body += "\n"
    if len(body) > 128 * 1024:
        raise ValueError("proposal body must contain 1-131072 characters")
    authored_meta = _authored_metadata(args.get("metadata", {}))
    merge_retention = _merge_retention(target, action, body, context)
    from obsidience.harness.execution.optimization import proposal_binding
    optimization = proposal_binding(context, target, action, proposal_title, body, authored_meta)
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
            and pending.meta.get("optimization") == optimization
            and pending.meta.get("merge_retained") == (merge_retention if action == "archive" else None)
        )
        if same_proposal:
            if review_class == "link":
                # Revalidate old pending suggestions under the current hierarchy.
                link_evidence(existing_target, body, Resolver(iter_notes()))
            result = {
                "staged": str(pending_path),
                "target": target,
                "action": action,
                "review_class": str(pending.meta.get("review_class") or review_class),
                "existing": True,
            }
            if validate_only:
                return {"validated": True, "target": target, "action": action}
            context.setdefault("staged_proposals", []).append(result)
            if merge_retention and action == "update":
                context.setdefault("_merge_retained_updates", {})[target] = merge_retention["body_sha256"]
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
    accepted_path = CONFIG.vault_dir / target
    if action in {"update", "archive"} and accepted_path.is_file():
        proposal_meta["base_sha256"] = hashlib.sha256(accepted_path.read_bytes()).hexdigest()
    proposal_meta["authored_fields"] = sorted(authored_meta)
    if review_class == "link":
        if action != "update" or authored_meta:
            raise ValueError("Link updates an existing Article body, not its authority metadata")
        proposal_meta["link_evidence"] = link_evidence(existing_target, body, link_resolver)
        if context.get("_agent_ref"):
            from obsidience.harness.knowledge.scope import execution_scope
            _agent, readable = execution_scope(context, link_resolver)
            endpoints = {existing_target.ref, *(item["ref"] for item in proposal_meta["link_evidence"]
                                               if not item.get("source_citation"))}
            if not endpoints <= readable:
                raise PermissionError("Link endpoints must be within the executing Agent's Knowledge scope")
            reads = context.get("_article_reads", {})
            missing_reads = {}
            for ref in sorted(endpoints):
                endpoint = link_resolver.by_ref[ref.casefold()]
                receipt = reads.get(ref, {})
                expected = hashlib.sha256(endpoint.text().encode()).hexdigest()
                if receipt.get("complete") is not True or receipt.get("article_sha256") != expected:
                    missing_reads[ref] = expected
            if missing_reads:
                context["_proposal_read_prerequisite"] = missing_reads
                batch = list(missing_reads)[:10]
                remaining = len(missing_reads) - len(batch)
                raise ValueError(
                    "Link requires a complete current vault.read of each changed endpoint: "
                    + json.dumps({"refs": batch}, ensure_ascii=False)
                    + (f"; {remaining} further endpoints remain" if remaining else "")
                    + ". Complete these reads before retrying the proposal; unchanged arguments "
                    "are valid after the missing evidence is supplied"
                )
            for item in proposal_meta["link_evidence"]:
                if not item.get("source_citation") or item["change"] != "added":
                    continue
                receipt = context.get("_source_reads", {}).get(item["source_citation"], {})
                if (receipt.get("content_sha256") != item["endpoint_sha256"]
                        or [0, item["source_characters"]] not in receipt.get("ranges", [])):
                    raise ValueError("Link requires a complete source.read of the exact observation Source: "
                                     + item["source_citation"])
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
    if optimization is not None:
        proposal_meta["optimization"] = optimization
    if merge_retention and action == "archive":
        proposal_meta["merge_retained"] = merge_retention
    if validate_only:
        return {"validated": True, "target": target, "action": action}
    if context.get("event") == "observations.memory.ready":
        from obsidience.harness.knowledge.vault import _NOTE_WRITE_LOCK
        with _NOTE_WRITE_LOCK:
            _check_memory_recommendation_limit(context)
            staged = _stage(proposal_meta, body)
    else:
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
    from obsidience.harness.knowledge.curation import try_auto_approve
    result = try_auto_approve(result, args, context)
    if not result.get("auto_approved"):
        from pathlib import Path
        from obsidience.harness.knowledge.review import notify_link_review

        notify_link_review(Path(staged).name, proposal_meta, "pending")
    context.setdefault("staged_proposals", []).append(result)
    if merge_retention and action == "update":
        context.setdefault("_merge_retained_updates", {})[target] = merge_retention["body_sha256"]
    return result




def execute(args: dict, context: dict) -> str:
    from obsidience.harness.knowledge.scope import assert_proposal_scope
    from obsidience.harness.knowledge.vault import resolver
    context.pop("_proposal_read_prerequisite", None)
    try:
        assert_proposal_scope(str((args or {}).get("target", "")), context or {}, resolver())
        result = stage_proposal(args or {}, context or {})
    except (ValueError, PermissionError) as exc:
        if context.get("event") == "observations.memory.ready":
            context["_memory_proposal_rejection"] = str(exc)[:1000]
        if context.get("task") == "Tasks/link":
            context["_link_proposal_rejection"] = str(exc)[:1000]
        return f"Proposal rejected: {exc}."
    context.pop("_link_proposal_rejection", None)
    context.pop("_memory_proposal_rejection", None)
    if result.get("auto_approved"):
        return f"Article published at {result['target']} under owner Auto-curate policy {result['policy']}."
    reason = result.get("auto_curate_blocked")
    return f"Proposal staged for owner review at {result['staged']}." + (
        f" Auto-curate could not publish: {reason}" if reason else ""
    )

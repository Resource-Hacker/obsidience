"""Owner-selected, source-backed Ingest publication through ordinary review.

The branch's accepted metadata is the policy; Source text cannot grant it.
Other proposals remain in the same review queue. No second wiki writer.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath


from .auto_curate import enabled, policy_for, selection
from .source import get_source, validate_source_citations
from .vault import Resolver, folder_article_path, iter_notes, load_note
from .links import body_links

def publication_policy(target: str):
    path = PurePosixPath(target.removesuffix(".md"))
    for parent in path.parents:
        if str(parent) == ".":
            break
        note = load_note(folder_article_path(str(parent)))
        if note and note.meta.get("curation_task"):
            return note
    return None


def try_auto_approve(result: dict, args: dict, context: dict) -> dict:
    from ..capabilities.vault.propose import _authored_metadata
    from ..memory.hindsight import observation_links

    if (context.get("event") == "observations.memory.ready"
            or observation_links(str(args.get("body", "")), str(result["target"]))):
        return result  # Hindsight evidence produces recommendations for owner Review.

    try:
        args = {**args, "metadata": _authored_metadata(args.get("metadata") or {})}
    except ValueError:
        return result
    if not enabled(str(result["target"])):
        return result
    policy = publication_policy(str(result["target"]))
    if not policy:
        return _approve_scoped_knowledge(result, args, context)
    curation_task = str(policy.meta.get("curation_task", "")).strip("[]")
    research_task = str(policy.meta.get("research_task", "")).strip("[]")
    active_task = load_note(curation_task + ".md")
    if (
        context.get("task") != curation_task
        or context.get("agent") != "Alexandria"
        or context.get("event") != "source.inbox"
        or not context.get("run_id")
        or not active_task
        or active_task.kind != "task"
        or active_task.meta.get("status") != "running"
        or active_task.meta.get("last_run") != context.get("run_id")
        or result["action"] not in {"create", "update"}
        or result["target"] == policy.path
    ):
        return result
    # Tool proposals may not author permission, trigger, provenance, or role
    # metadata. The ordinary review remains available if this check fails.
    metadata = args.get("metadata") or {}
    existing = load_note(result["target"])
    if (
        not isinstance(metadata, dict)
        or set(metadata) - {"kind"}
        or metadata.get("kind", "knowledge") != "knowledge"
        or existing
        and (existing.kind != "knowledge" or existing.runtime_observation)
    ):
        return result
    params = context.get("params") or {}
    if not isinstance(params, dict) or params.get("research_task") != research_task:
        return result
    try:
        from .index import INDEX
        from .review import approve
        from .source import _research_owner

        handoff = get_source(str(params.get("source_citation", "")))
        row = INDEX.source(handoff["id"])
        task = str(params["research_task"])
        run_id = str(params.get("research_run_id", ""))
        expected = f"source.inbox:research:{run_id}:{task}:"
        row_path = str(row.get("path", "")) if row else ""
        event_key = str(row.get("event_key", "")) if row else ""
        expected_params = {
            "activation_key": event_key,
            "source_id": handoff["id"],
            "source_citation": handoff["citation"],
            "source_path": f"obsidience/evidence/{row_path}",
            "source_type": handoff["source_type"],
            "source_ref": handoff["source_ref"],
            "source_media_type": handoff["media_type"],
            "source_captured_at": handoff["captured_at"],
            "source_sha256": handoff["content_sha256"],
        }
        if (
            not row
            or not row_path.startswith("inbox/")
            or not event_key.startswith(expected)
            or any(params.get(key) != value for key, value in expected_params.items())
            or handoff["source_type"] != "research"
            or handoff["media_type"] != "text/markdown"
            or not _research_owner(task, run_id)
        ):
            return result
        evidence = validate_source_citations(handoff["content"], required=True)
        evidence_citations = [item["citation"] for item in evidence]
        if params.get("source_citations") != evidence_citations:
            return result
        allowed = set(evidence_citations)
        allowed.add(handoff["citation"])
        body = str(args.get("body", ""))
        citations = {item["citation"] for item in validate_source_citations(body, required=True)}
        if handoff["citation"] not in citations or not citations <= allowed:
            return {**result, "auto_curate_blocked": "Proposal citations exceed the current research handoff or omit its Inbox citation."}
        accepted = Resolver(iter_notes())
        if any(not accepted.resolve(match) for match in body_links(body, str(result["target"]))):
            return result
        approved = approve(Path(result["staged"]).name)
        return {
            **result,
            "auto_approved": True,
            "approval": approved,
            "policy": policy.ref,
        }
    except (ValueError, OSError) as exc:
        return {**result, "auto_curate_blocked": str(exc)[:300]}


def _approve_scoped_knowledge(result: dict, args: dict, context: dict) -> dict:
    """Publish ordinary Knowledge through the same validator and review ledger.

    The author may maintain its own knowledge; the Curator may maintain an
    owner-enabled destination. Permission never permits authoring authority,
    modifying runtime observations, or silently accepting unsupported claims.
    """
    from .review import approve

    target = str(result["target"])
    policy = policy_for(target)
    existing = load_note(target)
    task = load_note(str(context.get("task", "")) + ".md")
    agent = str(context.get("agent", ""))
    metadata = args.get("metadata") or {}
    if (
        selection(policy) is not True
        or result["action"] not in {"create", "update"}
        or not task or task.kind != "task"
        or task.meta.get("status") != "running"
        or not context.get("run_id")
        or task.meta.get("last_run") != context["run_id"]
        or str(task.meta.get("assignee", "")).strip("[]") != f"Agents/{agent}/{agent}"
        or (agent != "Alexandria" and not target.startswith(f"Agents/{agent}/"))
        or target.split("/", 1)[0] in {"Tools", "Skills", "Tasks", "Runbooks"}
        or not isinstance(metadata, dict) or set(metadata) - {"kind", "type"}
        or metadata.get("type", metadata.get("kind", "knowledge")) != "knowledge"
        or existing and (existing.kind != "knowledge" or existing.runtime_observation)
    ):
        return result
    try:
        body = str(args.get("body", ""))
        sources = validate_source_citations(body)
        accepted = Resolver(iter_notes())
        links = body_links(body, target)
        if any(not accepted.resolve(link) for link in links) or not (sources or links):
            return result
        approval = approve(Path(result["staged"]).name)
        return {**result, "auto_approved": True, "approval": approval, "policy": policy.ref}
    except (ValueError, OSError) as exc:
        return {**result, "auto_curate_blocked": str(exc)[:300]}

"""Adapter for ``vault.propose``."""

from __future__ import annotations

from obsidience.harness.knowledge.proposals import stage_proposal


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

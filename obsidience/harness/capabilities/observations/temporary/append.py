"""Write one bounded observation under the executing Agent's own graph."""
from __future__ import annotations


def execute(args: dict, context: dict) -> str:
    from obsidience.harness.conversation.observations import append_temporary_observation
    from obsidience.harness.knowledge.scope import execution_scope
    from obsidience.harness.knowledge.vault import resolver
    from obsidience.harness.knowledge.links import metadata_ref

    context = context or {}
    agent, allowed = execution_scope(context, resolver())
    params = context.get("params") or {}
    own = agent.ref.rsplit("/", 1)[0] + "/Observations/Temporary Observations"
    runtime = {**params, "origin_task_ref": str(context.get("task", ""))}
    if runtime.get("curation_mode") not in {"temporary", "compaction"}:
        if not context.get("run_id"):
            raise ValueError("Observation requires its originating execution")
        runtime.update(curation_mode="temporary", target_path=own, turn_id=context["run_id"])
    if str(runtime.get("target_path", "")).rstrip("/") != own:
        raise PermissionError("An Agent cannot write another Agent's Observations")
    for raw in (args or {}).get("related_refs", []):
        if metadata_ref(str(raw)) not in allowed:
            raise PermissionError("Observation links must remain within the Agent's checked-out graph")
    result = append_temporary_observation(args or {}, runtime)
    return (f"Temporary observation {result['status']} at [[{result['ref']}]] "
            f"({result['retained']} retained).")

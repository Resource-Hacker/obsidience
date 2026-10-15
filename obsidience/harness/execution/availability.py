"""One Tool-availability policy for a specialist Task's next model decision.

Each rule narrows the Task's granted Tools to what its contract still permits.
The preconditions stay with their owners, which still enforce them at dispatch
and completion: the bound Source read (capabilities/source/read.py), Repair's
fresh inspection (execution/repair.py), Curate's topic search
(execution/completion.py) and the bound AutoSaddler case (harness.optimize).
"""

from __future__ import annotations


def available_tools(allowed: list[str], context: dict) -> list[str]:
    """The Tools this step advertises; the rules apply in this order."""
    names = _bound_source(allowed, context)
    names = _repair(names, context)
    names = _curate_search(names, context)
    return _optimization_case(names, context)


def _bound_source(allowed: list[str], context: dict) -> list[str]:
    """Learn's activating Source is read completely before any independent work."""
    from ..capabilities.source.read import bound_read_error

    if bound_read_error(context) is None:
        return allowed
    return [name for name in allowed if name in {"source.read", "task.complete"}]


def _repair(allowed: list[str], context: dict) -> list[str]:
    """Expose the same fresh-inspection prerequisite as Repair completion."""
    from .repair import PASS_ATTEMPT_LIMIT, REPAIR_TASK, eligible_rows, repair_attempt_count

    if context.get("task") == REPAIR_TASK and "harness.status" in allowed:
        if not isinstance(context.get("_harness_snapshot"), dict):
            return ["harness.status"]
        if repair_attempt_count(context) >= PASS_ATTEMPT_LIMIT or not eligible_rows(context):
            return [name for name in allowed if name != "harness.repair"]
    return allowed


def _curate_search(allowed: list[str], context: dict) -> list[str]:
    """Expose the required memory topic search before a terminal decision.

    A real unsuccessful attempt leaves failure reporting available; merely
    deciding the Source is uninteresting is not a failed search.
    """
    if (context.get("event") != "observations.memory.ready" or context.get("_vault_searches")
            or "vault.search" not in allowed):
        return allowed
    from ..capabilities.source.read import bound_read_error

    if bound_read_error(context) or any(row.get("tool") == "vault.search"
                                      for row in context.get("trace", []) if isinstance(row, dict)):
        return allowed
    return ["vault.search"]


def _optimization_case(allowed: list[str], context: dict) -> list[str]:
    """A bound Audit optimization case runs harness.optimize, then only completes."""
    if context.get("task") == "Tasks/audit" and (context.get("params") or {}).get("optimization_case"):
        required = "task.complete" if context.get("_harness_optimization_attempted") else "harness.optimize"
        return [name for name in allowed if name == required]
    return allowed

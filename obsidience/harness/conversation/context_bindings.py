"""Ephemeral facts for an interactive Executive, without additional authority."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..knowledge.dependencies import assigned_tasks, dependency_resolver
from ..knowledge.tasks import task_triggers
from ..knowledge.vault import Note, Resolver

EXECUTIVE_REF = "Agents/Executive/Executive"
MAX_TASKS = 8
MAX_TOOLS = 12
MAX_DESCRIPTION = 300


def local_clock() -> dict[str, str]:
    """Read the workstation clock in its configured system timezone."""
    try:
        timezone = str(Path("/etc/localtime").resolve().relative_to("/usr/share/zoneinfo"))
        now = datetime.now(ZoneInfo(timezone))
    except (OSError, ValueError, ZoneInfoNotFoundError):
        now = datetime.now().astimezone()
        timezone = now.tzname() or now.strftime("UTC%z")
    return {"iso": now.isoformat(timespec="seconds"), "timezone": timezone,
            "weekday": now.strftime("%A")}


def _bounded_name(value: object, limit: int) -> bool:
    return isinstance(value, str) and 0 < len(value) <= limit and not any(
        ord(char) < 32 for char in value
    )


def _description(body: str) -> dict:
    # A compact copy of the accepted first prose paragraph, never synthesized
    # functionality or a grant extracted from incidental later examples.
    paragraph = next((part for part in body.strip().split("\n\n")
                      if part.strip() and not part.lstrip().startswith("#")), "")
    paragraph = " ".join(paragraph.split())
    truncated = len(paragraph) > MAX_DESCRIPTION
    return {"description": paragraph[:MAX_DESCRIPTION - 1] + "…" if truncated else paragraph,
            "description_truncated": truncated}


def executive_context(
    agent: Note | None, res: Resolver, resolve_spine: Callable[[Note, Resolver], dict],
) -> dict:
    """Describe accepted assigned leaf Tasks using this activation's resolver.

    The caller owns interactive admission. Event/scheduled work and unresolved
    procedures are omitted; omission counts make this a partial catalog, never
    a claim that every absent capability is unavailable globally.
    """
    if agent is None or agent.ref != EXECUTIVE_REF or agent.kind != "agent":
        return {}
    accepted = dependency_resolver(res)
    identity = accepted.resolve(EXECUTIVE_REF)
    if identity is None or identity.kind != "agent":
        return {}
    assigned = assigned_tasks(identity, accepted)
    tasks = []
    for task in sorted(assigned, key=lambda item: item.ref):
        if (len(tasks) >= MAX_TASKS or task.children or task.meta.get("schedule")
                or task_triggers(task.meta) or not _bounded_name(task.ref, 256)
                or not _bounded_name(task.title, 256)):
            continue
        # A shared Task selects the Executive's exact accepted specialization;
        # its stored assignee and the active Task's Tool set remain unchanged.
        spine = resolve_spine(replace(task, meta={**task.meta, "assignee": identity.ref}), accepted)
        if "error" in spine or "subtasks" in spine:
            continue
        articles = [tool for tool in spine["tool_articles"] if not tool.children]
        tools = [{"tool": tool.title, **_description(tool.body)}
                 for tool in sorted(articles, key=lambda item: item.title)
                 if _bounded_name(tool.title, 96)][:MAX_TOOLS]
        tasks.append({"task_ref": task.ref, "title": task.title, "tools": tools,
                      "omitted_tool_count": len(articles) - len(tools)})
    return {
        "local_clock": local_clock(),
        "assigned_task_catalog": {
            "catalog_only": True, "grants_authority": False,
            "tasks": tasks, "omitted_task_count": len(assigned) - len(tasks),
        },
    }

"""Ordinary task.assigned events prepare missing Task-owned procedures."""

from __future__ import annotations

import hashlib

from ..capabilities.registry import contract_error
from ..knowledge.dependencies import (
    dependency_resolver, paired_leaf_skills, resolve_task_dependencies,
    task_descendants, task_exclusions, task_is_excluded,
)
from ..knowledge.tasks import task_triggers
from ..knowledge.vault import Note, Resolver, slugify


def library_candidates(res: Resolver) -> dict[str, list[str]]:
    """Accepted shared executable Tool/Skill pairs, never an Agent grant list."""
    res = dependency_resolver(res)
    pairs = []
    for tool in res.by_ref.values():
        if tool.kind != "tool" or tool.children or not tool.ref.startswith("Tools/"):
            continue
        if contract_error(tool.title, tool.meta.get("binding"), tool.meta.get("source")):
            continue
        skills = paired_leaf_skills(tool, res)
        if len(skills) == 1 and skills[0].ref.startswith("Skills/"):
            pairs.append((tool.ref, skills[0].ref))
    return {"tools": sorted(tool for tool, _skill in pairs),
            "skills": sorted(skill for _tool, skill in pairs)}


def ensure_task_runbook(task: Note, res: Resolver, *, agent_ref: str | None = None) -> dict:
    """Return ready/queued/blocked; never rewrite the requested Task or its inputs.

    The existing Generate/Runbook Task owns its durable FIFO and idempotency.
    A missing procedure is work for that Task, not permission to run a model
    without a Runbook. An invalid existing binding is not a generation request.
    """
    res = dependency_resolver(res)
    if task.kind != "task" or res.resolve(task.ref) is None:
        return {"status": "blocked", "error": "assignment requires an accepted physical Task"}
    agent = res.resolve(agent_ref or str(task.meta.get("assignee") or "Agents/Executive/Executive"))
    if not agent or agent.kind != "agent":
        return {"status": "blocked", "error": "assignment requires an exact accepted Agent"}
    descendants, error = task_descendants(task, res)
    exclusions, exclusion_error = task_exclusions(task, res, {note.ref for note in descendants})
    if error or exclusion_error:
        return {"status": "blocked", "error": error or exclusion_error}
    if task.children:
        results = []

        def prepare_children(parent: Note, inherited: set[str]) -> None:
            descendants, error = task_descendants(parent, res)
            excluded, exclusion_error = task_exclusions(parent, res, {note.ref for note in descendants})
            if error or exclusion_error:
                results.append({"status": "blocked", "error": error or exclusion_error})
                return
            for raw in parent.children:
                child = res.resolve(raw)
                if not child or task_is_excluded(child, inherited | excluded, res):
                    continue
                if child.children:
                    prepare_children(child, inherited | excluded)
                else:
                    results.append(ensure_task_runbook(child, res, agent_ref=agent.ref))

        prepare_children(task, set())
        blocked = next((result for result in results if result["status"] == "blocked"), None)
        waiting = next((result for result in results if result["status"] == "queued"), None)
        return blocked or waiting or {"status": "ready"}
    dependency = resolve_task_dependencies(task, res, agent_ref=agent.ref)
    if not dependency.get("error"):
        return {"status": "ready", "runbook": dependency["runbook"].ref}
    if not dependency.get("missing"):
        return {"status": "blocked", "error": dependency["error"]}
    subscribers = [note for note in res.by_ref.values() if note.kind == "task"
                   and "task.assigned" in task_triggers(note.meta)
                   and str(note.meta.get("enabled", True)).lower() not in {"false", "0", "off", "no"}]
    if len(subscribers) != 1:
        return {"status": "blocked", "error": f"task.assigned requires exactly one enabled graph Task; found {len(subscribers)}"}
    generation = subscribers[0]
    generator_dependencies = resolve_task_dependencies(generation, res)
    if generation.ref == task.ref or generator_dependencies.get("error"):
        return {"status": "blocked", "error": "Generate/Runbook requires its own valid accepted procedure"}
    catalog = library_candidates(res)
    if "Tools/task.complete" not in catalog["tools"]:
        return {"status": "blocked", "error": "shared Library is missing the task.complete Tool/Skill pair"}
    identity = hashlib.sha256(f"{task.ref}\0{agent.ref}".encode()).hexdigest()
    task_path = task.ref.removeprefix("Tasks/")
    agent_path = slugify(str(agent.meta.get("role") or agent.ref.removeprefix("Agents/")))
    output_path = "/".join(slugify(part) for part in task_path.split("/"))
    params = {
        "event": "task.assigned", "activation_key": f"assignment-{identity}",
        "assignment_event_id": f"assignment-{identity}",
        "target_task": task.ref, "target_task_title": task.title,
        "target_task_article": task.body.strip()[:8_000],
        "target_task_hierarchy": [task.ref],
        "target_agent": agent.ref, "target_agent_name": agent.title,
        **catalog, "output_runbook": f"Runbooks/Generated/{agent_path}/{output_path}.md",
        "queue_after_review": True,
    }
    from .scheduler import enqueue_event

    queued = enqueue_event(generation, params)
    if queued.get("state") == "processed" and queued.get("status") in {"failed", "blocked", "completed"}:
        return {"status": "blocked", "generator_task": generation.ref,
                "error": "Runbook generation already finished without an accepted applicable procedure", "queue": queued}
    return {"status": "queued", "generator_task": generation.ref, "queue": queued,
            "error": "awaiting-runbook: ordinary Runbook generation is pending"}

"""Read-only Agent capability and Task procedure dependencies.

Accepted Articles and exact metadata bindings are the only input. Agent Task
assignments select reusable work; Agent Skills supply its conversational catalog.
Related Knowledge links never grant capabilities. Execution and presentation
use this same projection.
"""

from __future__ import annotations

from collections import Counter

from ..capabilities.registry import ALWAYS_ALLOWED, contract_error
from .links import metadata_ref
from .tasks import CANONICAL_TASK_BY_PATH, TASK_TAXONOMY_BY_PATH, task_triggers
from .vault import Note, Resolver, expand_primitive


def _links(value) -> list[str]:
    return [str(item) for item in (value if isinstance(value, list) else [value]) if item] if value else []


class DependencyResolver(Resolver):
    """No draft proposal, hidden Article, title guess, or ambiguous path binding."""

    def __init__(self, notes: list[Note]):
        accepted = [note for note in notes if not any(
            part.startswith(("_", ".")) for part in note.path.split("/")
        ) and not note.path.startswith("raw/")]
        super().__init__(accepted)
        counts = Counter(note.ref.casefold() for note in accepted)
        self.ambiguous = {ref for ref, count in counts.items() if count > 1}

    def resolve(self, target: str) -> Note | None:
        ref = metadata_ref(target)
        if not ref or "/" not in ref or ref.startswith("@") or ref.casefold() in self.ambiguous:
            return None
        return self.by_ref.get(ref.lower())


def dependency_resolver(res: Resolver) -> DependencyResolver:
    return res if isinstance(res, DependencyResolver) else DependencyResolver(list(res.by_ref.values()))


def select_runbook(task: Note, res: Resolver, *, agent_ref: str | None = None) -> tuple[Note | None, str | None]:
    """Select one exact Task/Agent specialization, then an applicable authored fallback."""
    res = dependency_resolver(res)
    agent_ref = metadata_ref(agent_ref or str(task.meta.get("assignee") or "Agents/Executive/Executive"))
    candidates = [note for note in res.by_ref.values() if note.kind == "runbook"
                  and metadata_ref(str(note.meta.get("task", ""))) == task.ref
                  and metadata_ref(str(note.meta.get("for_agent", ""))) == agent_ref]
    if len(candidates) > 1:
        return None, f"ambiguous Runbook for {task.ref} and {agent_ref}: {', '.join(sorted(n.ref for n in candidates))}"
    if candidates:
        agent = res.resolve(agent_ref)
        if not agent or agent.kind != "agent":
            return None, f"Runbook {candidates[0].ref} has no accepted matching Agent: {agent_ref}"
        return candidates[0], None
    raw = task.meta.get("runbook")
    if not raw:
        return None, None
    refs = _links(raw)
    if len(refs) != 1:
        return None, f"Task {task.ref} must reference exactly one authored Runbook"
    fallback = res.resolve(refs[0])
    if not fallback or fallback.kind != "runbook":
        return None, f"authored Runbook not found or wrong kind: {refs[0]}"
    bound_task = metadata_ref(str(fallback.meta.get("task", "")))
    if bound_task and bound_task != task.ref:
        return None, f"authored Runbook {fallback.ref} belongs to another Task: {bound_task}"
    bound_agent = metadata_ref(str(fallback.meta.get("for_agent", "")))
    if bound_agent:
        agent = res.resolve(bound_agent)
        if not agent or agent.kind != "agent":
            return None, f"authored Runbook {fallback.ref} has an invalid for_agent binding"
    if bound_agent and bound_agent != agent_ref:
        return None, None  # A different Agent needs its own ordinary procedure.
    return fallback, None


def paired_leaf_skills(tool: Note, res: Resolver) -> list[Note]:
    return [note for note in res.by_ref.values() if note.kind == "skill" and not note.children
            and not note.meta.get("tools")
            and len(_links(note.meta.get("tool"))) == 1
            and res.resolve(_links(note.meta.get("tool"))[0]) is tool]


def resolve_dependencies(task: Note, res: Resolver, *, agent_ref: str | None = None) -> dict:
    """Resolve an Agent catalog or Task procedure through the same paired Skills."""
    res = dependency_resolver(res)
    if task.kind == "agent":
        if (not isinstance(task.meta.get("skills"), list) or not task.meta["skills"]
                or task.meta.get("runbook") or task.meta.get("runbooks") or task.meta.get("tools")):
            return {"error": "Agent conversation requires its direct Skill catalog and identity instructions"}
        runbook, runbooks, contracts = None, [], [task]
        agent_ref = task.ref
    elif task.kind == "task":
        runbook, error = select_runbook(task, res, agent_ref=agent_ref)
        if error or not runbook:
            return {"error": error or "awaiting-runbook: leaf task has no applicable runbook", "missing": not error}
        runbooks, error = expand_primitive(runbook, res, "runbook")
        if error:
            return {"error": error}
        contracts = runbooks
    else:
        return {"error": "Only an accepted Agent or Task owns an execution contract"}
    skills: dict[str, Note] = {}
    tools: dict[str, Note] = {}

    def add_skill(skill: Note) -> str | None:
        parts, error = expand_primitive(skill, res, "skill")
        if error:
            return error
        for part in parts:
            if part.ref in skills:
                continue
            if part.meta.get("tools"):
                return f"skill {part.ref} cannot grant plural tools; use its exact singular tool binding"
            skills[part.ref] = part
            if part.children:
                continue
            refs = _links(part.meta.get("tool"))
            tool = res.resolve(refs[0]) if len(refs) == 1 else None
            if not tool or tool.kind != "tool" or tool.children:
                return f"skill {part.ref} must reference exactly one leaf tool"
            error = contract_error(tool.title, tool.meta.get("binding"), tool.meta.get("source"))
            if error:
                return f"Tool [[{tool.ref}]] is not executable: {error}"
            paired = paired_leaf_skills(tool, res)
            if len(paired) != 1:
                return f"Tool [[{tool.ref}]] requires exactly one paired Skill; found {len(paired)}"
            tree, error = expand_primitive(tool, res, "tool")
            if error:
                return error
            tools.update((item.ref, item) for item in tree)
        return None

    for part in contracts:
        scope = metadata_ref(str(part.meta.get("for_agent", "")))
        effective_agent = metadata_ref(agent_ref or str(task.meta.get("assignee") or "Agents/Executive/Executive"))
        if scope and scope != effective_agent:
            return {"error": f"inapplicable Runbook dependency {part.ref} for {effective_agent}"}
        if _links(part.meta.get("tools")):
            return {"error": f"runbook {part.ref} grants tools directly; reference each Tool's paired Skill instead"}
        for raw in _links(part.meta.get("skills")):
            skill = res.resolve(raw)
            if not skill or skill.kind != "skill":
                return {"error": f"skill not found or wrong kind: {raw}"}
            error = add_skill(skill)
            if error:
                return {"error": error}
    for name in ALWAYS_ALLOWED:
        tool = res.resolve(f"Tools/{name}")
        if not tool or tool.kind != "tool" or tool.children:
            return {"error": f"always-available Tool is missing: Tools/{name}"}
        paired = paired_leaf_skills(tool, res)
        if len(paired) != 1:
            return {"error": f"always-available Tool {tool.ref} requires exactly one paired Skill; found {len(paired)}"}
        error = add_skill(paired[0])
        if error:
            return {"error": error}
    return {"runbook": runbook, "runbooks": runbooks, "skills": list(skills.values()),
            "tool_articles": list(tools.values())}


def resolve_task_dependencies(task: Note, res: Resolver, *, agent_ref: str | None = None) -> dict:
    """Task-only entry point retained for assignment and specialist procedures."""
    if task.kind != "task":
        return {"error": "Task dependencies require a Task Article"}
    return resolve_dependencies(task, res, agent_ref=agent_ref)


def scheduled_assignment(task: Note, agent: Note, res: Resolver) -> bool:
    """Implicit ownership from exact assignee and scheduled, triggered, or live work."""
    return bool(task.kind == "task" and metadata_ref(str(task.meta.get("assignee", ""))) == agent.ref
                and (task.meta.get("schedule") or task_triggers(task.meta)
                     or task.meta.get("status") in {"pending", "running", "review", "blocked"}))


def assigned_tasks(agent: Note, res: Resolver) -> list[Note]:
    res = dependency_resolver(res)
    tasks = {task.ref: task for raw in _links(agent.meta.get("tasks"))
             if (task := res.resolve(raw)) and task.kind == "task"}
    tasks.update((task.ref, task) for task in res.by_ref.values() if scheduled_assignment(task, agent, res))
    return list(tasks.values())


def agent_dependencies(agent: Note, res: Resolver) -> dict:
    res = dependency_resolver(res)
    fields = {name: set() for name in ("tasks", "runbooks", "skills", "tools")}
    errors: list[str] = []

    # Direct Agent Skills supply the router catalog without an intermediate hub.
    if agent.meta.get("skills"):
        dependency = resolve_dependencies(agent, res, agent_ref=agent.ref)
        if dependency.get("error"):
            errors.append(f"{agent.ref}: {dependency['error']}")
        else:
            for field, key in (("runbooks", "runbooks"), ("skills", "skills"), ("tools", "tool_articles")):
                fields[field].update(note.ref for note in dependency[key])

    def visit(task: Note, inherited: set[str], stack: tuple[str, ...]) -> None:
        if task_is_excluded(task, inherited, res):
            return
        if task.ref in stack:
            errors.append(f"cyclic task hierarchy: {' -> '.join((*stack, task.ref))}")
            return
        fields["tasks"].add(task.ref)
        descendants, error = task_descendants(task, res)
        excluded, exclusion_error = task_exclusions(task, res, {note.ref for note in descendants})
        if error or exclusion_error:
            errors.append(error or exclusion_error)
            return
        if task.children:
            for raw in task.children:
                child = res.resolve(raw)
                if child:
                    visit(child, inherited | excluded, (*stack, task.ref))
            return
        dependency = resolve_task_dependencies(task, res, agent_ref=agent.ref)
        if dependency.get("error"):
            errors.append(f"{task.ref}: {dependency['error']}")
            return
        for field, key in (("runbooks", "runbooks"), ("skills", "skills"), ("tools", "tool_articles")):
            fields[field].update(note.ref for note in dependency[key])

    for task in assigned_tasks(agent, res):
        visit(task, set(), ())
    return {**{field: sorted(refs) for field, refs in fields.items()}, "errors": sorted(set(errors))}


TASK_TAXONOMY_PATH_BY_REF = {ref: path for path, ref in CANONICAL_TASK_BY_PATH.items()}


def task_taxonomy_path(task: Note) -> str:
    return str(task.meta.get("taxonomy_path") or TASK_TAXONOMY_PATH_BY_REF.get(task.ref, ""))


def task_exclusion_path(raw: str, res: Resolver) -> str:
    ref = metadata_ref(raw)
    if ref.startswith("@library/Tasks/"):
        path = ref.removeprefix("@library/Tasks/")
        return path if path in TASK_TAXONOMY_BY_PATH else ""
    target = res.resolve(ref)
    return task_taxonomy_path(target) if target and target.kind == "task" else ""


def task_is_excluded(task: Note, exclusions: set[str], res: Resolver) -> bool:
    task_path = task_taxonomy_path(task)
    for raw in exclusions:
        ref = metadata_ref(raw)
        if ref == task.ref:
            return True
        excluded_path = task_exclusion_path(ref, res)
        if task_path and excluded_path and (
            task_path == excluded_path or task_path.startswith(excluded_path + "/")
        ):
            return True
    return False


def task_exclusions(task: Note, res: Resolver, authored_descendants: set[str]) -> tuple[set[str], str | None]:
    root_path = task_taxonomy_path(task)
    excluded: set[str] = set()
    for raw in _links(task.meta.get("exclude_subtasks")):
        ref = metadata_ref(raw)
        if ref.startswith("@library/Tasks/"):
            path = task_exclusion_path(ref, res)
            if root_path and path.startswith(root_path + "/"):
                excluded.add(ref)
                continue
            return excluded, f"excluded subtask is not a descendant: {raw}"
        child = res.resolve(ref)
        if child and child.kind == "task" and child.ref in authored_descendants:
            excluded.add(child.ref)
            continue
        path = task_exclusion_path(ref, res)
        if root_path and path.startswith(root_path + "/"):
            excluded.add(ref)
            continue
        return excluded, f"excluded subtask is not a descendant: {raw}"
    return excluded, None


def task_descendants(task: Note, res: Resolver) -> tuple[list[Note], str | None]:
    """Return the ordered authored descendant closure for one Task."""
    ordered: list[Note] = []
    seen: set[str] = {task.ref}

    def add(note: Note, stack: tuple[str, ...]) -> str | None:
        if note.ref in stack:
            return f"cyclic task hierarchy: {' -> '.join((*stack, note.ref))}"
        for raw in _links(note.meta.get("subtasks")):
            child = res.resolve(raw)
            if not child or child.kind != "task":
                return f"subtask not found or not a task: {raw}"
            chain = (*stack, note.ref)
            if child.ref in chain:
                return f"cyclic task hierarchy: {' -> '.join((*chain, child.ref))}"
            if child.ref not in seen:
                seen.add(child.ref)
                ordered.append(child)
                error = add(child, chain)
                if error:
                    return error
        return None

    return ordered, add(task, ())

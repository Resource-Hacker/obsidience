"""The interpreter. Not a graph primitive — it performs:

    Task -> choose Runbook (leaf) | expand Subtasks (container, in order)
         -> load required Skills -> authorize and invoke Tools
         -> collect evidence -> update Task state

Spine resolution is edge-exact (wikilinks); retrieval only fills the packet's
Relevant Articles section.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
import uuid
from dataclasses import dataclass

from . import activity as knowledge_activity
from . import trace as action_trace
from ..config import CONFIG
from ..knowledge import retrieval, source
from ..knowledge.index import INDEX
from ..knowledge.tasks import CANONICAL_TASK_BY_PATH, TASK_TAXONOMY_BY_PATH, task_triggers
from ..knowledge.vault import Note, Resolver, resolver, update_status
from ..models import llm
from ..models import runtime as model_runtime
from ..capabilities.registry import (
    ALWAYS_ALLOWED,
    MODEL_RESOURCE_TOOLS,
    REGISTRY,
    contract_error,
    execute as execute_capability,
)

from .ledger import runbook_tree_hash

MAX_TASK_DEPTH = 16
MAX_REALTIME_BASE_PACKET_CHARS = 4_800
PROMPT_SAFETY_TOKENS = 256
_NON_BINDING_PARAMETERS = {
    "event",
    "request",
    "response_contract",
    "source",
}

LAWS = """\
## Laws
1. Follow the runbook exactly. If it cannot be followed, complete with status "failed" and say why.
2. You cannot edit the vault; you can only stage proposals for owner review.
3. Use only the authorized tools. Prefer searching the vault over assuming; cite notes as [[wikilinks]].
"""


def _is_agent_identity(note: Note | None) -> bool:
    return bool(note and (note.kind == "agent" or note.ref == "Agents/Executive/Executive"))


def _agent_graph_id(agent: Note | None) -> str:
    if not agent or agent.ref == "Agents/Executive/Executive":
        return "main"
    return agent.ref.split("/")[1] if agent.ref.startswith("Agents/") else agent.title


def _skill_tools(skills: list[Note], res: Resolver) -> list[Note]:
    """Resolve the exact Tool Article paired to each selected Skill Article."""

    tools: list[Note] = []
    for skill in skills:
        if skill.children:
            continue
        for raw in _links(skill.meta.get("tool")):
            tool = res.resolve(raw)
            if (
                tool
                and tool.kind == "tool"
                and not tool.children
                and tool.ref not in {item.ref for item in tools}
            ):
                tools.append(tool)
    return tools


@dataclass(frozen=True)
class ActivationBinding:
    """The exact runtime Objective and semantic bindings for one Task activation."""

    objective: str
    bindings: dict[str, object]


def build_activation_binding(
    task: Note,
    runbooks: list[Note],
    params: dict,
) -> ActivationBinding:
    """Preserve a live request verbatim or derive one deterministic Task objective."""

    request = str(params.get("request") or "").strip()
    objective = request or " ".join([task.title, *(part.title for part in runbooks)])
    bindings = {
        str(key): value
        for key, value in params.items()
        if key not in _NON_BINDING_PARAMETERS
    }
    return ActivationBinding(objective=objective, bindings=bindings)


def _immediate_observations_section(observations: str) -> str:
    if not observations.strip():
        return ""
    from ..conversation.observations import IMMEDIATE_OBSERVATIONS_REF

    return (
        "## Immediate Observations\n"
        f"### [[{IMMEDIATE_OBSERVATIONS_REF}]] — Immediate Observations\n"
        + observations.strip()
    )


def _activation_packet(task: Note, agent: Note | None, spine: dict,
                       activation: ActivationBinding,
                       observations: str, brief: str,
                       conversation: str = "") -> tuple[str, list[str]]:
    """Compile the one semantic packet consumed and displayed for every leaf Task."""
    runbooks: list[Note] = spine["runbooks"]
    skills: list[Note] = spine["skills"]
    tools = _skill_tools(skills, resolver())

    identity = agent if _is_agent_identity(agent) else None
    refs = [
        *([identity.ref] if identity else []),
        task.ref,
        *(runbook.ref for runbook in runbooks),
        *(skill.ref for skill in skills),
        *(tool.ref for tool in tools),
    ]
    task_text = f"### [[{task.ref}]] — {task.title}\n{task.body.strip()}"
    if acceptance := task.meta.get("acceptance"):
        task_text += "\n\nAcceptance: " + json.dumps(acceptance, default=str)
    bindings = json.dumps(activation.bindings, default=str, sort_keys=True)
    sections = [
        "# Thinking Packet",
        "## Agent Identity\n" + (
            f"### [[{identity.ref}]] — {identity.title}\n{identity.body.strip()}"
            + (f"\n\n{observations}" if observations else "")
            if identity else "Obsidience interpreter"
        ),
        "## Task\n" + task_text,
        "## Objective\n" + activation.objective,
        "## Tools\n" + ("\n\n".join(
            f"### [[{tool.ref}]] — {tool.title}\n{tool.body.strip()}" for tool in tools
        ) or "No external capability is authorized."),
        "## Skills\n" + ("\n\n".join(
            f"### [[{skill.ref}]] — {skill.title}\n{skill.body.strip()}" for skill in skills
        ) or "No procedural Tool guidance is required."),
        "## Runbook\n" + "\n\n".join(
            f"### [[{runbook.ref}]] — {runbook.title}\n{runbook.body.strip()}"
            for runbook in runbooks
        ),
        "## Bindings\n" + (bindings if activation.bindings else "None."),
        "## Relevant Knowledge\n" + (brief or "None."),
        _immediate_observations_section(conversation),
        "Begin. Follow the Runbook and use only the packet's exact capabilities.",
    ]
    return "\n\n".join(section for section in sections if section), refs


def _compact(value: str, maximum: int) -> str:
    """Return readable bounded prose without allowing one Article to crowd out its peers."""

    compact = " ".join(value.split())
    if len(compact) <= maximum:
        return compact
    return compact[: maximum - 1].rstrip() + "…"


def _realtime_activation_packet(
    task: Note,
    agent: Note | None,
    spine: dict,
    activation: ActivationBinding,
    observations: str,
    brief: str,
    conversation: str = "",
) -> str:
    """Project the canonical packet into the selected Realtime model's live context.

    This is a bounded projection, not a second ontology.  The selected Articles and
    their order are identical to the full executor packet; only their prose is
    condensed so the 2K planner window still has room to answer.
    """

    runbooks: list[Note] = spine["runbooks"]
    skills: list[Note] = spine["skills"]
    tools = _skill_tools(skills, resolver())
    identity = agent if _is_agent_identity(agent) else None

    def article_line(note: Note, budget: int) -> str:
        return f"[[{note.ref}]] {note.title}: {_compact(note.body, budget)}"

    identity_text = (
        article_line(identity, 300)
        if identity
        else "Obsidience interpreter"
    )
    if observations:
        identity_text += "\nTemporary observations: " + _compact(observations, 260)
    acceptance = task.meta.get("acceptance")
    task_text = article_line(task, 380)
    if acceptance:
        task_text += "\nAcceptance: " + _compact(json.dumps(acceptance, default=str), 260)
    bindings = (
        _compact(json.dumps(activation.bindings, default=str, sort_keys=True), 240)
        if activation.bindings
        else "None."
    )

    def article_list(notes: list[Note], total_budget: int) -> str:
        if not notes:
            return "None."
        per_article = max(100, total_budget // len(notes))
        return "\n".join(article_line(note, per_article) for note in notes)

    base_packet = "\n\n".join(
        (
            "# Thinking Packet",
            "## Agent Identity\n" + identity_text,
            "## Task\n" + task_text,
            "## Objective\n" + _compact(activation.objective, 500),
            "## Tools\n" + article_list(tools, 420),
            "## Skills\n" + article_list(skills, 420),
            "## Runbook\n" + article_list(runbooks, 680),
            "## Bindings\n" + bindings,
            "## Relevant Knowledge\n" + _compact(brief, 760),
            (
                "Use this exact graph-selected packet. Return a concise reply when no Tool is "
                "observation, then return the concise verified reply. Never narrate reasoning, "
                "Task state, the packet, or internal errors."
            ),
        )
    )
    if len(base_packet) > MAX_REALTIME_BASE_PACKET_CHARS:
        raise RuntimeError("the bounded real-time activation packet exceeded its hard limit")
    return "\n\n".join(
        filter(None, [base_packet, _immediate_observations_section(conversation)])
    )


_REALTIME_TOOL_HINTS = {
    "computer.observe": (
        "click", "press", "play", "tap", "select", "choose", "screen", "button",
    ),
    "computer.act": (
        "click", "press", "play", "tap", "select", "choose", "screen", "button",
    ),
    "application.launch": ("open", "launch", "start", "run application", "app"),
    "harness.status": ("status", "health", "running", "harness"),
    "model.inspect": ("model", "inspect model", "model details"),
    "model.benchmark": ("benchmark", "tokens per second", "tok/s", "speed test"),
    "model.configure": ("configure model", "model setting", "context tokens", "gpu"),
    "model.source": ("register model", "model source", "add model"),
    "observations.temporary.append": ("remember temporarily", "temporary observation", "short term"),
    "source.ingest": ("capture source", "ingest source", "save source"),
    "source.read": ("read source", "source file", "blob"),
    "task.create": ("delegate", "ask darwin", "ask alexandria", "ask heimdall", "create task", "issue task"),
    "vault.list": ("list articles", "list vault", "files", "folders"),
    "vault.maintenance": ("duplicates", "missing links", "maintenance", "curate"),
    "vault.propose": ("edit", "change article", "propose", "write article"),
    "vault.read": ("read article", "show article", "article content"),
    "vault.search": ("search knowledge", "find article", "knowledge graph", "recall"),
    "vault.validate": ("validate vault", "validate graph", "check links"),
    "web.fetch": ("fetch page", "open url", "read website", "web page"),
    "web.search": ("search web", "look online", "internet", "current", "latest"),
}


def _select_realtime_skills(query: str, skills: list[Note], res: Resolver) -> list[Note]:
    """Project Realtime's authored capability pool to a tiny relevant subset."""

    words = set(re.findall(r"[a-z0-9.]+", query.casefold()))
    lowered = query.casefold()
    scored: list[tuple[int, int, Note]] = []
    for order, skill in enumerate(skills):
        tools = _skill_tools([skill], res)
        if len(tools) != 1:
            continue
        tool = tools[0]
        capability = tool.title
        haystack = " ".join(
            (skill.title, skill.body, tool.title, tool.body, capability)
        ).casefold()
        score = 3 * len(words & set(re.findall(r"[a-z0-9.]+", haystack)))
        score += sum(
            12 for hint in _REALTIME_TOOL_HINTS.get(capability, ()) if hint in lowered
        )
        if score >= 12:
            scored.append((score, -order, skill))
    scored.sort(reverse=True, key=lambda item: (item[0], item[1]))
    return [item[2] for item in scored[:4]]


async def compile_activation(
    task: Note,
    *,
    spine: dict | None = None,
    agent: Note | None = None,
    params: dict | None = None,
    runtime_params: dict[str, str] | None = None,
    emit_activity: bool = True,
    include_realtime: bool = False,
    conversation_context: str = "",
) -> dict:
    """Resolve and retrieve the canonical packet without starting model execution.

    Live voice, live text, scheduled Tasks, and event Tasks all use this compiler.
    The optional real-time projection contains the same selected Articles as the
    full packet and cannot add capabilities or alter the Task spine. Ordinary
    Task execution does not inherit a speech transport size bound.
    """

    res = resolver()
    resolved_spine = spine or resolve_spine(task, res)
    if "error" in resolved_spine:
        raise RuntimeError(str(resolved_spine["error"]))
    if "subtasks" in resolved_spine:
        raise ValueError("a container Task must expand its subtasks before activation")

    requested_agent = agent
    if requested_agent is None:
        requested_agent = (
            res.resolve(str(task.meta.get("assignee", "")))
            if task.meta.get("assignee")
            else res.resolve("Agents/Executive/Executive")
        )
    stored_params = task.meta.get("params") or {}
    bound_params = (
        dict(params)
        if params is not None
        else {
            **(stored_params if isinstance(stored_params, dict) else {}),
            **(runtime_params or {}),
        }
    )
    runbooks: list[Note] = resolved_spine["runbooks"]
    skills: list[Note] = resolved_spine["skills"]
    activation = build_activation_binding(task, runbooks, bound_params)
    retrieval_query = activation.objective
    exclude = {task.ref, *(part.ref for part in runbooks)} | {skill.ref for skill in skills}
    preferred_context = set(source.article_refs_for_trees(
        requested_agent.meta.get("source_trees")
        if _is_agent_identity(requested_agent)
        else []
    ))
    retrieval_started = time.perf_counter()
    brief, context_refs = await asyncio.to_thread(
        retrieval.fast_context_with_refs,
        retrieval_query,
        exclude,
        1_200,
        5,
        preferred_context,
    )
    retrieval_ms = (time.perf_counter() - retrieval_started) * 1_000

    from ..conversation.observations import read_temporary_observations

    observations = (
        read_temporary_observations(requested_agent.ref)
        if _is_agent_identity(requested_agent)
        and not include_realtime
        and not conversation_context
        else ""
    )
    packet, packet_refs = _activation_packet(
        task, requested_agent, resolved_spine, activation, observations, brief,
        conversation_context,
    )
    realtime_packet = None
    realtime_tools: list[str] = []
    realtime_refs: list[str] = []
    if include_realtime:
        live_skills = _select_realtime_skills(retrieval_query, skills, res)
        live_spine = {**resolved_spine, "skills": live_skills}
        realtime_packet = _realtime_activation_packet(
            task, requested_agent, live_spine, activation, observations, brief,
            conversation_context,
        )
        live_tools = _skill_tools(live_skills, res)
        realtime_tools = [
            tool.title
            for tool in live_tools
            if tool.title in REGISTRY
        ]
        realtime_refs = [
            *([requested_agent.ref] if _is_agent_identity(requested_agent) else []),
            task.ref,
            *(part.ref for part in runbooks),
            *(skill.ref for skill in live_skills),
            *(tool.ref for tool in live_tools),
        ]
    selected_refs = realtime_refs if include_realtime else packet_refs
    selected_refs.extend(ref for ref in context_refs if ref not in selected_refs)
    if conversation_context:
        from ..conversation.observations import IMMEDIATE_OBSERVATIONS_REF

        if IMMEDIATE_OBSERVATIONS_REF not in selected_refs:
            selected_refs.append(IMMEDIATE_OBSERVATIONS_REF)
    activity_query = activation.objective
    graph_id = _agent_graph_id(requested_agent)
    if emit_activity:
        knowledge_activity.emit(
            "path", selected_refs, query=activity_query, graph_id=graph_id,
            retrieval_ms=retrieval_ms,
        )
        action_trace.emit(
            "activation",
            f"{requested_agent.title if _is_agent_identity(requested_agent) else 'Obsidience'} "
            f"packet for {task.title}",
            selected_refs,
        )
    return {
        "packet": packet,
        "realtime_packet": realtime_packet,
        "realtime_tools": realtime_tools,
        "refs": selected_refs,
        "retrieval_ms": retrieval_ms,
        "agent": requested_agent,
        "params": bound_params,
        "objective": activation.objective,
        "bindings": activation.bindings,
        "spine": resolved_spine,
        "brief": brief,
    }


def _links(value) -> list[str]:
    if not value:
        return []
    return [str(v) for v in (value if isinstance(value, list) else [value])]


def _link_name(value: str) -> str:
    return value.strip().strip("[]").split("|", 1)[0].split("#", 1)[0].rsplit("/", 1)[-1]


def _link_ref(value: str) -> str:
    return value.strip().strip("[]").split("|", 1)[0].split("#", 1)[0]


TASK_TAXONOMY_PATH_BY_REF = {ref: path for path, ref in CANONICAL_TASK_BY_PATH.items()}


def _task_taxonomy_path(task: Note) -> str:
    return str(task.meta.get("taxonomy_path") or TASK_TAXONOMY_PATH_BY_REF.get(task.ref, ""))


def _task_exclusion_path(raw: str, res: Resolver) -> str:
    ref = _link_ref(raw)
    if ref.startswith("@library/Tasks/"):
        path = ref.removeprefix("@library/Tasks/")
        return path if path in TASK_TAXONOMY_BY_PATH else ""
    target = res.resolve(ref)
    return _task_taxonomy_path(target) if target and target.kind == "task" else ""


def _task_is_excluded(task: Note, exclusions: set[str], res: Resolver) -> bool:
    task_path = _task_taxonomy_path(task)
    for raw in exclusions:
        ref = _link_ref(raw)
        if ref == task.ref:
            return True
        excluded_path = _task_exclusion_path(ref, res)
        if task_path and excluded_path and (
            task_path == excluded_path or task_path.startswith(excluded_path + "/")
        ):
            return True
    return False


def _task_exclusions(task: Note, res: Resolver, authored_descendants: set[str]) -> tuple[set[str], str | None]:
    root_path = _task_taxonomy_path(task)
    excluded: set[str] = set()
    for raw in _links(task.meta.get("exclude_subtasks")):
        ref = _link_ref(raw)
        if ref.startswith("@library/Tasks/"):
            path = _task_exclusion_path(ref, res)
            if root_path and path.startswith(root_path + "/"):
                excluded.add(ref)
                continue
            return excluded, f"excluded subtask is not a descendant: {raw}"
        child = res.resolve(ref)
        if child and child.kind == "task" and child.ref in authored_descendants:
            excluded.add(child.ref)
            continue
        path = _task_exclusion_path(ref, res)
        if root_path and path.startswith(root_path + "/"):
            excluded.add(ref)
            continue
        return excluded, f"excluded subtask is not a descendant: {raw}"
    return excluded, None


def _runbook_ref_for_task(task: Note, res: Resolver) -> str | None:
    """Prefer the newest accepted Runbook generated for this Task and agent."""
    agent = (res.resolve(str(task.meta.get("assignee", "")))
             if task.meta.get("assignee") else res.resolve("Agents/Executive/Executive"))
    if _is_agent_identity(agent):
        for raw in reversed(_links(agent.meta.get("runbooks"))):
            candidate = res.resolve(raw)
            if (candidate and candidate.kind == "runbook"
                    and _link_ref(str(candidate.meta.get("task", ""))) == task.ref):
                return candidate.ref
    value = task.meta.get("runbook")
    return str(value) if value else None


def _expand_primitive(root: Note, res: Resolver, kind: str) -> tuple[list[Note], str | None]:
    """Resolve the selected primitive's ancestor path and descendant tree.

    Selecting a leaf retains its parent context without also selecting its
    siblings. Selecting a container still expands its complete authored tree.
    """
    ordered: list[Note] = []
    seen: set[str] = set()
    parents: dict[str, list[Note]] = {}
    for candidate in res.by_ref.values():
        if candidate.kind != kind:
            continue
        for raw in candidate.children:
            child = res.resolve(raw)
            if child and child.kind == kind:
                parents.setdefault(child.ref, []).append(candidate)

    def add_ancestors(note: Note, stack: tuple[str, ...]) -> str | None:
        if note.ref in stack:
            return f"cyclic {kind} hierarchy: {' -> '.join((*stack, note.ref))}"
        for parent in parents.get(note.ref, []):
            error = add_ancestors(parent, (*stack, note.ref))
            if error:
                return error
        if note.ref not in seen:
            seen.add(note.ref)
            ordered.append(note)
        return None

    def add_descendants(note: Note, stack: tuple[str, ...]) -> str | None:
        if note.ref in stack:
            return f"cyclic {kind} hierarchy: {' -> '.join((*stack, note.ref))}"
        if note.ref not in seen:
            seen.add(note.ref)
            ordered.append(note)
        for raw in note.children:
            child = res.resolve(raw)
            if not child or child.kind != kind:
                return f"{kind} child not found or wrong kind: {raw}"
            error = add_descendants(child, (*stack, note.ref))
            if error:
                return error
        return None

    error = add_ancestors(root, ())
    if not error:
        error = add_descendants(root, ())
    return ordered, error


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


def _paired_leaf_skills(tool: Note, res: Resolver) -> list[Note]:
    """Return every accepted leaf Skill that claims one exact Tool Article."""
    paired: list[Note] = []
    for note in res.by_ref.values():
        if note.kind != "skill" or note.children:
            continue
        target = res.resolve(str(note.meta.get("tool", "")))
        if target and target.ref == tool.ref:
            paired.append(note)
    return paired


def _tool_bindings(refs: list[str], res: Resolver) -> tuple[set[str], str | None]:
    names: set[str] = set()
    seen: set[str] = set()
    for raw in refs:
        root = res.resolve(raw)
        if not root:
            return names, f"tool not found: {raw}"
        if root.kind != "tool":
            return names, f"tool reference is not a tool: {raw}"
        tools, error = _expand_primitive(root, res, "tool")
        if error:
            return names, error
        for tool in tools:
            if tool.ref in seen:
                continue
            seen.add(tool.ref)
            if tool.children:
                continue
            error = contract_error(
                tool.title,
                tool.meta.get("binding"),
                tool.meta.get("source"),
            )
            if error:
                return names, f"Tool [[{tool.ref}]] is not executable: {error}"
            paired = _paired_leaf_skills(tool, res)
            if len(paired) != 1:
                return names, (
                    f"Tool [[{tool.ref}]] requires exactly one paired Skill; "
                    f"found {len(paired)}"
                )
            names.add(tool.title)
    return names, None


def resolve_spine(task: Note, res: Resolver) -> dict:
    """Edge-exact resolution: runbook -> skills -> authorized tool set."""
    subtask_refs = _links(task.meta.get("subtasks"))
    descendants, descendant_error = task_descendants(task, res)
    if descendant_error:
        return {"error": descendant_error}
    excluded, exclusion_error = _task_exclusions(
        task, res, {child.ref for child in descendants}
    )
    if exclusion_error:
        return {"error": exclusion_error}
    if subtask_refs:
        subtasks = []
        for ref in subtask_refs:
            child = res.resolve(ref)
            if not child or child.kind != "task":
                return {"error": f"subtask not found or not a task: {ref}"}
            subtasks.append(child)
        return {"subtasks": subtasks, "excluded_subtasks": excluded}

    rb_ref = _runbook_ref_for_task(task, res)
    if not rb_ref:
        return {"error": "awaiting-runbook: leaf task has no runbook"}
    runbook = res.resolve(str(rb_ref))
    if not runbook or runbook.kind != "runbook":
        return {"error": f"awaiting-runbook: {rb_ref} not found"}

    runbooks, error = _expand_primitive(runbook, res, "runbook")
    if error:
        return {"error": error}

    skills: list[Note] = []
    seen_skills: set[str] = set()
    tool_names: set[str] = set()
    tool_refs: list[str] = []
    for runbook_part in runbooks:
        if _links(runbook_part.meta.get("tools")):
            return {"error": (
                f"runbook {runbook_part.ref} grants tools directly; "
                "reference each Tool's paired Skill instead"
            )}
        for skill_ref in _links(runbook_part.meta.get("skills")):
            skill = res.resolve(skill_ref)
            if not skill or skill.kind != "skill":
                return {"error": f"skill not found or wrong kind: {skill_ref}"}
            skill_tree, error = _expand_primitive(skill, res, "skill")
            if error:
                return {"error": error}
            for skill_part in skill_tree:
                if skill_part.ref in seen_skills:
                    continue
                seen_skills.add(skill_part.ref)
                skills.append(skill_part)
                if skill_part.children:
                    continue
                paired_tool = _links(skill_part.meta.get("tool"))
                if len(paired_tool) != 1:
                    return {"error": (
                        f"skill {skill_part.ref} must reference exactly one tool"
                    )}
                tool_refs.extend(paired_tool)

    # task.complete is always available, but its Tool and Skill Articles still
    # ride in the same packet as every other Capability contract.
    for capability in ALWAYS_ALLOWED:
        tool = res.resolve(f"Tools/{capability}")
        if not tool or tool.kind != "tool" or tool.children:
            return {"error": f"always-available Tool is missing: Tools/{capability}"}
        paired = _paired_leaf_skills(tool, res)
        if len(paired) != 1:
            return {"error": (
                f"always-available Tool {tool.ref} requires exactly one paired Skill; "
                f"found {len(paired)}"
            )}
        skill_tree, error = _expand_primitive(paired[0], res, "skill")
        if error:
            return {"error": error}
        for skill_part in skill_tree:
            if skill_part.ref not in seen_skills:
                seen_skills.add(skill_part.ref)
                skills.append(skill_part)
        tool_refs.append(tool.ref)
    resolved_tools, error = _tool_bindings(tool_refs, res)
    if error:
        return {"error": error}
    tool_names.update(resolved_tools)
    unknown = sorted(t for t in tool_names if t not in REGISTRY)
    if unknown:
        return {"error": f"unbound tools (no registry implementation): {unknown}"}
    return {
        "runbook": runbook,
        "runbooks": runbooks,
        "skills": skills,
        "tools": sorted(tool_names),
        "excluded_subtasks": excluded,
    }


async def _execute_session(
    task: Note,
    model: model_runtime.ModelSpec,
    messages: list[dict],
    allowed: list[str],
    ctx: dict,
    agent_name: str,
    effort: str,
) -> tuple[list[dict], str, str]:
    trace: list[dict] = []
    realtime = ctx.get("realtime") is True
    status, summary = (
        ("failed", "Realtime turn ended without a public reply")
        if realtime
        else ("failed", "session ended without task.complete")
    )
    active_lease = None
    try:
        for step in range(CONFIG.max_steps):
            if active_lease is None:
                model = model_runtime.configured_spec(model.id)
                active_lease = model_runtime.lease(model)
                await active_lease.__aenter__()
            try:
                completion = await llm.chat(
                    messages,
                    reasoning_effort=effort,
                    model=model,
                )
            except Exception as exc:  # noqa: BLE001 — preserve transport failures in the run ledger
                status, summary = "failed", f"LLM error: {exc}"
                action_trace.emit("error", f"{task.title} LLM error", [str(exc)])
                break
            reply = completion.content
            messages.append({"role": "assistant", "content": reply})
            action = llm.parse_action(reply, allow_reply=realtime)
            if not action:
                parse_error = llm.action_parse_error(reply, allow_reply=realtime)
                trace.append({
                    "invalid": reply[:400],
                    "parse_error": parse_error,
                    "finish_reason": completion.finish_reason,
                    "completion_tokens": completion.completion_tokens,
                    "reply_chars": len(reply),
                    "reply_sha256": hashlib.sha256(reply.encode()).hexdigest(),
                })
                invalids = sum(1 for item in trace[-3:] if "invalid" in item)
                if invalids >= 3:
                    status, summary = (
                        "failed",
                        "three consecutive replies without a valid Realtime response"
                        if realtime
                        else "three consecutive replies without a valid action block",
                    )
                    action_trace.emit(
                        "error", f"{agent_name} produced no valid action",
                        [summary, parse_error, f"finish: {completion.finish_reason}"],
                    )
                    break
                messages.append({
                    "role": "user",
                    "content": (
                        f"No valid response object found: {parse_error}. Reply with exactly one "
                        + (
                            "top-level JSON object containing either reply, or tool and args. "
                            if realtime
                            else "top-level JSON object containing tool and args. "
                        )
                        + "Put no commentary or Markdown in the public response."
                    ),
                })
                continue
            if realtime and "reply" in action:
                status = "completed"
                summary = " ".join(str(action["reply"]).split())[:2000]
                trace.append({
                    "reply_chars": len(summary),
                    "reply_sha256": hashlib.sha256(summary.encode()).hexdigest(),
                })
                break
            name, args = action.get("tool"), action.get("args") or {}
            if name == "task.complete":
                decision = await asyncio.to_thread(
                    execute_capability, name, args, {**ctx, "task_note": task},
                )
                if not isinstance(decision, dict) or not decision.get("accepted"):
                    error = (
                        str(decision.get("error", "invalid completion result"))
                        if isinstance(decision, dict)
                        else "invalid completion result"
                    )
                    observation = f"Completion rejected: {error}."
                    trace.append({
                        "tool": "task.complete",
                        "args": args,
                        "obs": observation,
                        "completion_rejected": True,
                    })
                    action_trace.emit("result", "task.complete rejected", [error])
                    messages.append({"role": "user", "content": f"Observation:\n{observation}"})
                    continue
                status = str(decision["status"])
                summary = str(decision["summary"])
                trace.append({"tool": "task.complete", "args": {"status": status}})
                action_trace.emit("status", f"{agent_name} completed {task.title}: {status}", [summary])
                break
            action_trace.emit("tool", f"{agent_name} → {name}", [json.dumps(args, default=str)[:1000]])
            call_sig = f"{name}:{json.dumps(args, sort_keys=True)}"
            repeats = sum(1 for item in trace if item.get("sig") == call_sig)
            if repeats >= 2:
                observation = (
                    "You have repeated this exact call three times; the result will not change. "
                    + (
                        "Return a concise reply now."
                        if realtime
                        else "Vary your approach or call task.complete now with your best status."
                    )
                )
            elif name not in allowed:
                observation = f"Tool '{name}' is not authorized for this task."
            else:
                if name in MODEL_RESOURCE_TOOLS and active_lease is not None:
                    await active_lease.__aexit__(None, None, None)
                    active_lease = None
                try:
                    result = await asyncio.to_thread(
                        execute_capability, name, args, ctx,
                    )
                    observation = (
                        result
                        if isinstance(result, str)
                        else json.dumps(result, sort_keys=True, default=str)
                    )
                except Exception as exc:  # noqa: BLE001
                    observation = f"Tool error: {exc}"
            trace.append({"tool": name, "args": args, "obs": observation[:600], "sig": call_sig})
            action_trace.emit("result", f"{name} returned", str(observation).splitlines()[:12])
            remaining = CONFIG.max_steps - step - 1
            nudge = (
                "\n\n(FINAL STEP — return one concise reply object now.)"
                if realtime and remaining == 1
                else "\n\n(FINAL STEP — call task.complete now with your best status and summary.)"
                if remaining == 1
                else f"\n\n({remaining} steps remain — wrap up soon.)"
                if remaining <= 3
                else ""
            )
            messages.append({"role": "user", "content": f"Observation:\n{observation}{nudge}"})
    finally:
        if active_lease is not None:
            await active_lease.__aexit__(None, None, None)
    return trace, status, summary


async def run_task(task: Note, depth: int = 0, reasoning_effort: str | None = None,
                   model: str | None = None,
                   runtime_params: dict[str, str] | None = None,
                   emit_turn_event: bool = True,
                   excluded_task_refs: frozenset[str] | None = None,
                   keep_task_open: bool = False,
                   realtime_projection: bool = False,
                   conversation_context: str = "") -> dict:
    run_id = uuid.uuid4().hex[:12]
    started = time.time()
    res = resolver()
    spine = resolve_spine(task, res)
    requested_agent = (
        res.resolve(str(task.meta.get("assignee", "")))
        if task.meta.get("assignee") else res.resolve("Agents/Executive/Executive")
    )
    stored_params = task.meta.get("params") or {}
    params = {
        **(stored_params if isinstance(stored_params, dict) else {}),
        **(runtime_params or {}),
    }
    objective = build_activation_binding(
        task,
        list(spine.get("runbooks", [])),
        params,
    ).objective
    graph_id = _agent_graph_id(requested_agent)
    knowledge_activity.emit(
        "query_started", [task.ref], query=objective, graph_id=graph_id,
    )
    effort = llm.normalize_reasoning_effort(
        reasoning_effort if reasoning_effort is not None else task.meta.get("reasoning_effort")
    )

    if "error" in spine:
        action_trace.emit("error", f"{task.title} blocked", [spine["error"]])
        if not keep_task_open:
            update_status(task, "blocked", {"summary": spine["error"], "last_run": run_id})
        INDEX.record_run(id=run_id, task_ref=task.ref, agent="interpreter", started=started,
                         finished=time.time(), status="blocked", summary=spine["error"],
                         trace="[]", reasoning_effort=effort, objective=objective)
        knowledge_activity.emit(
            "query_completed", [task.ref], query=objective, graph_id=graph_id,
        )
        return {
            "run_id": run_id,
            "status": "blocked",
            "summary": spine["error"],
            "objective": objective,
        }

    if not keep_task_open:
        update_status(task, "running", {"last_run": run_id})
    active_exclusions = set(excluded_task_refs or ())
    active_exclusions.update(spine.get("excluded_subtasks", set()))

    # ---- container task: its subtasks are how it completes ----
    if "subtasks" in spine:
        action_trace.emit(
            "run", f"{task.title} started",
            [f"{len(spine['subtasks'])} subtasks", f"{len(active_exclusions)} exclusions"],
        )
        if depth >= MAX_TASK_DEPTH:
            update_status(task, "failed", {"summary": "max task depth exceeded"})
            return {"run_id": run_id, "status": "failed", "summary": "max task depth exceeded"}
        results, worst = [], "completed"
        order = {"excluded": 0, "completed": 0, "review": 1, "blocked": 2, "failed": 3}
        for child in spine["subtasks"]:
            if _task_is_excluded(child, active_exclusions, res):
                action_trace.emit("status", f"{task.title} excluded {child.title}")
                results.append({
                    "task": child.ref,
                    "status": "excluded",
                    "summary": "excluded from this parent Task",
                })
                continue
            action_trace.emit("run", f"{task.title} → {child.title}")
            child_model = model
            if child_model is None:
                parent_preference = model_runtime.normalize_model(task.meta.get("model"))
                child_preference = model_runtime.normalize_model(child.meta.get("model"))
                if parent_preference != model_runtime.AUTO_MODEL and child_preference == model_runtime.AUTO_MODEL:
                    child_model = parent_preference
            child_result = await run_task(
                # Reasoning is owned by the executable child Task. A container
                # supplies scope and order, never an implicit reasoning override.
                child, depth + 1, None, child_model, runtime_params,
                emit_turn_event, frozenset(active_exclusions), False, False,
                conversation_context,
            )
            results.append({"task": child.ref, **{k: child_result[k] for k in ("status", "summary")}})
            if order.get(child_result["status"], 3) > order[worst]:
                worst = child_result["status"]
            if child_result["status"] in ("failed", "blocked"):
                break  # later subtasks depend on earlier ones — stop the chain
        summary = "; ".join(f"[[{r['task']}]] {r['status']}" for r in results)
        finished = time.time()
        update_status(task, worst, {"summary": summary})
        INDEX.record_run(id=run_id, task_ref=task.ref, agent="interpreter", started=started,
                         finished=finished, status=worst, summary=summary[:2000],
                         trace=json.dumps(results)[:20000],
                         reasoning_effort=effort, objective=objective)
        INDEX.sync()
        action_trace.emit("status", f"{task.title} {worst}", [summary])
        knowledge_activity.emit(
            "query_completed", [task.ref, *(child.ref for child in spine["subtasks"])],
            query=objective, graph_id=graph_id,
        )
        return {
            "run_id": run_id,
            "status": worst,
            "summary": summary,
            "objective": objective,
        }

    # ---- leaf task: runbook + skills + authorized tools ----
    runbook: Note = spine["runbook"]
    runbooks: list[Note] = spine["runbooks"]
    runbook_sha256 = runbook_tree_hash(runbooks)
    skills: list[Note] = spine["skills"]
    allowed: list[str] = spine["tools"]
    if active_exclusions:
        params["excluded_subtasks"] = sorted(active_exclusions)

    # Agent identity: the task's assignee is a literal agent note; the
    # interpreter executes the session AS that agent (Obsidience model).
    agent = requested_agent
    agent_name = agent.title if _is_agent_identity(agent) else "Obsidience"
    model_spec = model_runtime.resolve_model(
        model if model is not None else task.meta.get("model"),
        agent.ref if _is_agent_identity(agent) else "Agents/Executive/Executive",
    )
    action_trace.emit(
        "run", f"{agent_name} started {task.title}",
        [f"model: {model_spec.label}", f"reasoning: {effort}"],
    )
    if _is_agent_identity(agent) and agent.meta.get("tools"):
        grant, grant_error = _tool_bindings(_links(agent.meta.get("tools")), res)
        if grant_error:
            grant = set()
            action_trace.emit("error", f"{agent_name} tool hierarchy invalid", [grant_error])
        grant.update(ALWAYS_ALLOWED)
        allowed = [t for t in allowed if t in grant]

    activation = await compile_activation(
        task,
        spine=spine,
        agent=agent,
        params=params,
        include_realtime=realtime_projection,
        conversation_context=conversation_context,
    )
    packet = str(
        activation["realtime_packet"]
        if realtime_projection
        else activation["packet"]
    )
    if realtime_projection:
        live_tools = set(activation["realtime_tools"])
        allowed = [tool for tool in allowed if tool in live_tools]
    packet_refs = list(activation["refs"])
    retrieval_ms = float(activation["retrieval_ms"])
    objective = str(activation["objective"])
    system = "\n\n".join(filter(None, [
        f"You are {agent_name}, executing one graph-selected Task in Obsidience.",
        LAWS,
        llm.REALTIME_PROTOCOL if realtime_projection else llm.PROTOCOL,
        str(params.get("response_contract") or "") if realtime_projection else "",
    ]))
    user = "\n\n".join(filter(None, [
        packet,
        ("Excluded Task scopes: " + ", ".join(sorted(active_exclusions))
         + ". Do not perform these Tasks or anything beneath them."
         if active_exclusions else ""),
    ]))

    input_capacity_tokens = max(
        1,
        model_spec.context_tokens - model_spec.max_output_tokens - PROMPT_SAFETY_TOKENS,
    )
    prompt_tokens_estimate = (len(system) + len(user) + 7) // 4
    conversation_tokens_estimate = (len(conversation_context.strip()) + 3) // 4
    if prompt_tokens_estimate > input_capacity_tokens:
        raise ValueError(
            "the Thinking Packet exceeds the selected model's usable input context; "
            "run Compact or lower the packet size"
        )

    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    ctx = {
        "agent": agent_name,
        "task": task.ref,
        "run_id": run_id,
        "objective": objective,
        "event": params.get("event") or next(iter(task_triggers(task.meta)), None),
        "params": params,
        "realtime": realtime_projection,
    }

    trace, status, summary = await _execute_session(
        task, model_spec, messages, allowed, ctx, agent_name, effort,
    )
    trace.insert(0, {
        "activation_packet": packet_refs,
        "retrieval_ms": round(retrieval_ms, 3),
    })

    # acceptance criteria present and successful -> owner confirms unless auto_done
    if (not keep_task_open and status == "completed"
            and task.meta.get("acceptance") and not task.meta.get("auto_done")):
        status = "review"

    finished = time.time()
    transient_run = task.meta.get("transient") is True
    recorded_summary = "Temporary observations maintained." if transient_run else summary
    if not keep_task_open:
        update_status(task, status, {"summary": summary})
    if not keep_task_open and status == "review" and ctx.get("staged_proposals"):
        # The owner can decide a proposal as soon as it reaches Review, while
        # the model may still be composing task.complete. Reconcile after the
        # status write so a decision made during ``running`` cannot be
        # overwritten by this execution's stale final ``review`` projection.
        from ..knowledge.review import reconcile_origin_review_task

        reconciled_status = reconcile_origin_review_task(task.ref)
        if reconciled_status == "completed":
            status = "completed"
    INDEX.record_run(id=run_id, task_ref=task.ref, agent=agent_name, started=started,
                     finished=finished, status=status, summary=recorded_summary,
                     trace="[]" if transient_run else json.dumps(trace)[:20000],
                     runbook_ref=runbook.ref, runbook_sha256=runbook_sha256,
                     reasoning_effort=effort, model=model_spec.id,
                     objective=objective)
    INDEX.sync()
    action_trace.emit(
        "status",
        f"{agent_name} replied in {task.title}"
        if realtime_projection and status == "completed"
        else f"{task.title} ended {status}",
        [summary],
    )
    knowledge_activity.emit(
        "query_completed", packet_refs, query=objective, graph_id=graph_id,
        retrieval_ms=retrieval_ms,
    )
    if (emit_turn_event and _is_agent_identity(agent)
            and "turn.complete" not in task_triggers(task.meta)):
        from ..conversation.observations import queue_turn_complete

        queue_turn_complete(
            agent.ref,
            user=f"Task: {task.title}\nParams: {json.dumps(params, default=str)}",
            assistant=summary,
            source=f"task:{task.ref}",
            turn_id=run_id,
        )
    return {
        "run_id": run_id,
        "status": status,
        "summary": summary,
        "objective": objective,
        "reply": summary if realtime_projection and status == "completed" else "",
        "activation_refs": packet_refs,
        "retrieval_ms": round(retrieval_ms, 3),
        "model": model_spec.id,
        "prompt_tokens_estimate": prompt_tokens_estimate,
        "conversation_tokens_estimate": conversation_tokens_estimate,
        "input_capacity_tokens": input_capacity_tokens,
    }

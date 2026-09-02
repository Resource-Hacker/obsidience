"""FastAPI daemon: REST + WebSocket surface for the UI and CLI."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import threading
import time
import uuid
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from croniter import croniter

from ...conversation.store import CONVERSATION
from ...execution import activity as knowledge_activity
from ...execution import scheduler, trace
from ...execution.executor import compile_activation, run_task, task_descendants
from ...host import inventory
from ...knowledge import retrieval, review, source
from ...knowledge.index import INDEX
from ...knowledge.tasks import (
    CANONICAL_TASK_BY_PATH,
    TASK_TAXONOMY_BY_PATH,
    TASK_TAXONOMY_NODES,
    canonical_members as task_taxonomy_members,
    child_ids as task_taxonomy_child_ids,
    descendant_count as task_taxonomy_descendant_count,
    node_id as task_taxonomy_node_id,
    task_triggers,
)
from ...knowledge.skills import (
    build_skill_mirror,
    descendant_count as skill_mirror_descendant_count,
    namespace_title,
    node_id as skill_mirror_node_id,
)
from ...knowledge.vault import (
    Note,
    iter_notes,
    load_note,
    move_vault_item,
    mutate_note_metadata,
    resolver,
    slugify,
    write_note,
)
from ...config import CONFIG
from ...models import llm
from ...models import runtime as model_runtime
from ...realtime import media as media_runtime
from ...realtime import runtime as realtime
from obsidience.shell.applications import packagekit as application_packages


# Each principal owns typed links to the capabilities it currently carries.
# The shared Library exposes paired Tool+Skill capabilities and Tasks;
# synthesized Runbooks use the same identity field but are attached by the
# validated runbook-generation path.
CHECKOUT_AGENTS = {
    "executive": "Agents/Executive/Executive",
    "guardian": "Agents/Heimdall/Heimdall",
    "curator": "Agents/Alexandria/Alexandria",
    "researcher": "Agents/Darwin/Darwin",
}
CHECKOUT_FIELDS = {
    "tool": "tools",
    "skill": "skills",
    "runbook": "runbooks",
    "task": "tasks",
}
LIBRARY_KINDS = ("tool", "task")
SOURCE_SCOPE_FIELD = "source_trees"
TASK_TAXONOMY_PATH_BY_REF = {ref: path for path, ref in CANONICAL_TASK_BY_PATH.items()}
_CHECKOUT_LOCK = threading.RLock()
_REVIEW_LOCK = threading.RLock()

EXECUTIVE_AGENT_SUBJECTS = {
    "Architecture": "How the executive is wired into Obsidience and the local workstation.",
    "Subagents": "The named specialist agents coordinated by the executive.",
    "Observations": "Distilled notes about the executive, its preferences, and its own runs.",
    "Temporary Observations": (
        "The executive's transient, unverified bounded working-memory cache."
    ),
}
EXECUTIVE_SYSTEM_ROOTS = frozenset({"Agents", "Tools", "Skills", "Runbooks", "Tasks"})
SATELLITE_AGENT_SUBJECTS = {
    "architecture": ("Architecture", "How this agent is wired into Obsidience."),
    "knowledge": ("Knowledge", "Knowledge branches related to checked-out Source trees."),
    "other-agents": ("Other Agents", "The executive and sibling agents: who they are and what they do."),
    "observations": ("Observations", "The agent's distilled notes, preferences, and run observations."),
    "temporary-observations": (
        "Temporary Observations",
        "The agent's transient, unverified bounded working-memory cache.",
    ),
}
SATELLITE_ROLE_SUBJECTS = {
    "Alexandria": {},
    "Darwin": {
        "sources": ("Sources", "Darwin's direct-source evidence and research material."),
        "source-observations": ("Source Observations", "Distilled notes about research-source quality and behavior."),
        "acquisition": ("Acquisition", "Fetching and filing: research tasks, runbooks, and inbox conventions."),
        "acquisition-observations": ("Acquisition Observations", "Distilled notes from acquisition runs."),
        "sites": ("Sites", "How specific sites and feeds are researched effectively."),
        "site-observations": ("Site Observations", "Distilled notes on source quality, paywalls, and feeds."),
    },
    "Heimdall": {
        "verification": ("Verification", "Task auditing and claim verification: runbooks and formats."),
        "verification-observations": ("Verification Observations", "Distilled notes from verify and audit cycles."),
        "merge-gate": ("Merge Gate", "The review gate: rules, checks, and proposals."),
        "gate-observations": ("Gate Observations", "Distilled notes from merge-gate reviews."),
        "task-board": ("Task Board", "The fleet's scheduled task calendar and taskmaster working surface."),
    },
}
SATELLITE_ROLE_CHILDREN = {
    "Alexandria": {},
    "Darwin": {
        "sources": ["source-observations"],
        "acquisition": ["acquisition-observations"],
        "sites": ["site-observations"],
    },
    "Heimdall": {"verification": ["verification-observations"], "merge-gate": ["gate-observations"]},
}


def _link_values(value) -> list[str]:
    if not value:
        return []
    return [str(item) for item in (value if isinstance(value, list) else [value])]


def _link_ref(value: str) -> str:
    return (value.strip().removeprefix("[[").removesuffix("]]")
            .split("|", 1)[0].split("#", 1)[0].strip())


def _task_taxonomy_path(note: Note) -> str:
    return str(note.meta.get("taxonomy_path") or TASK_TAXONOMY_PATH_BY_REF.get(note.ref, ""))


def _task_taxonomy_ref_path(ref: str, res) -> str:
    if ref.startswith("@library/Tasks/"):
        path = ref.removeprefix("@library/Tasks/")
        return path if path in TASK_TAXONOMY_BY_PATH else ""
    target = res.resolve(ref)
    return _task_taxonomy_path(target) if target and target.kind == "task" else ""


def _note_doc(note):
    return {"ref": note.ref, "title": note.title, "kind": note.kind,
            "meta": {k: str(v) for k, v in note.meta.items()}, "body": note.body,
            "children": [_link_ref(str(child)) for child in note.children]}


def _folder_index(folder: str):
    """Resolve the authored hub a graph subject absorbs, if one exists."""
    return load_note(f"{folder}/index.md") or load_note(f"{folder}/README.md")


def _reader_override_path(ref: str) -> str:
    """Stable hidden backing article for a generated Reader node."""
    digest = hashlib.sha256(ref.encode()).hexdigest()[:12]
    return f".reader/{slugify(ref) or 'node'}-{digest}.md"


def _reader_overrides() -> dict[str, Note]:
    root = CONFIG.vault_dir / ".reader"
    out = {}
    if not root.exists():
        return out
    for path in root.glob("*.md"):
        note = load_note(path.relative_to(CONFIG.vault_dir))
        ref = str(note.meta.get("reader_ref", "")) if note else ""
        if note and ref.startswith("@"):
            out[ref] = note
    return out


def _apply_reader_override(doc: dict, overrides: dict[str, Note] | None = None) -> dict:
    override = (overrides or _reader_overrides()).get(str(doc.get("ref", "")))
    if not override:
        return doc
    return {
        **doc,
        "title": override.title,
        "body": override.body,
        "meta": {**doc.get("meta", {}), "owner_edited": "true"},
    }


def _tags(value: object) -> list[str]:
    values = value if isinstance(value, list) else [value] if value else []
    return [str(item).strip() for item in values if str(item).strip()]


def _is_enabled(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"false", "no", "off", "0"}
    return value is not False


def _auto_curate_tasks() -> list[Note]:
    return [
        note for note in iter_notes()
        if note.kind == "task" and note.meta.get("auto_curate_target")
    ]


def _auto_curate_state(request_ref: str, doc: dict) -> tuple[bool, str | None]:
    task = next(
        (note for note in _auto_curate_tasks()
         if str(note.meta.get("auto_curate_target", "")) == request_ref),
        None,
    )
    enabled = bool(task and _is_enabled(task.meta.get("enabled", True)))
    if not enabled:
        target = load_note(str(doc.get("ref", "")) + ".md")
        if target:
            enabled = "auto-curate" in _tags(target.meta.get("tags"))
        elif request_ref.startswith("@"):
            override = _reader_overrides().get(request_ref)
            enabled = bool(override and "auto-curate" in _tags(override.meta.get("tags")))
    return enabled, task.ref if task else None


def _article_with_curation(request_ref: str, doc: dict) -> dict:
    enabled, task_ref = _auto_curate_state(request_ref, doc)
    return {**doc, "auto_curate": enabled, "auto_curate_task": task_ref}


def _auto_curate_agent_ref(ref: str, doc: dict) -> str:
    if ref.startswith("@sat/"):
        name = ref.split("/", 3)[2]
        return f"Agents/{name}/{name}"
    target_ref = str(doc.get("ref", ref))
    if target_ref.startswith("Agents/"):
        name = target_ref.split("/", 2)[1]
        return f"Agents/{name}/{name}"
    if ref.startswith("@library") or target_ref.split("/", 1)[0] in {"Tools", "Skills", "Tasks"}:
        return CHECKOUT_AGENTS["curator"]
    return CHECKOUT_AGENTS["executive"]


def _auto_curate_target_path(ref: str, doc: dict) -> str:
    if ref == "@agent/Temporary Observations":
        return "Agents/Executive/Observations/Temporary Observations"
    if ref == "@agent/Observations":
        return "Agents/Executive/Observations"
    if ref.startswith("@agent/"):
        return f"Agents/Executive/{ref.removeprefix('@agent/')}"
    if ref.startswith("@sat/"):
        _, name, key = ref.split("/", 2)
        labels = {
            "observations": "Observations",
            "temporary-observations": "Observations/Temporary Observations",
            "architecture": "Architecture",
            "other-agents": "Other Agents",
        }
        return f"Agents/{name}/{labels.get(key, key.replace('-', ' ').title())}"
    if ref.startswith("@branch/"):
        return ref.removeprefix("@branch/")
    if ref == "@library":
        return ""
    if ref.startswith("@library/"):
        return ref.removeprefix("@library/").replace("Tools + Skills", "Tools")
    target_ref = str(doc.get("ref", ref))
    note = load_note(target_ref + ".md")
    return note.path if note else target_ref


def _auto_curate_runbook(agent_ref: str) -> Note:
    res = resolver()
    identity = res.resolve(agent_ref)
    if not identity:
        raise HTTPException(500, f"auto-curation identity missing: {agent_ref}")
    for raw in _link_values(identity.meta.get("runbooks")):
        runbook = res.resolve(raw)
        if runbook and runbook.kind == "runbook" and runbook.meta.get("purpose") == "auto-curate":
            return runbook
    raise HTTPException(409, f"{identity.title} has no checked-out auto-curation Runbook")


def _set_auto_curate_tag(ref: str, doc: dict, enabled: bool) -> None:
    target_ref = str(doc.get("ref", ""))
    note = load_note(target_ref + ".md") if target_ref and not target_ref.startswith("@") else None
    if note:
        meta = dict(note.meta)
        tags = [tag for tag in _tags(meta.get("tags")) if tag != "auto-curate"]
        if enabled:
            tags.append("auto-curate")
        if tags:
            meta["tags"] = tags
        else:
            meta.pop("tags", None)
        write_note(note.path, meta, note.body)
        return

    override = _reader_overrides().get(ref)
    meta = dict(override.meta) if override else {
        "title": str(doc.get("title", ref)),
        "kind": str(doc.get("kind", "index")),
        "reader_ref": ref,
        "owner_maintained": True,
    }
    tags = [tag for tag in _tags(meta.get("tags")) if tag != "auto-curate"]
    if enabled:
        tags.append("auto-curate")
    if tags:
        meta["tags"] = tags
    else:
        meta.pop("tags", None)
    write_note(
        _reader_override_path(ref),
        meta,
        override.body if override else str(doc.get("body", "")),
    )


def _tool_namespace_catalog():
    tools = [note for note in iter_notes() if note.kind == "tool"]
    res = resolver()
    explicit_children = {
        child.ref
        for parent in tools for raw in parent.children
        if (child := res.resolve(raw)) and child.kind == "tool"
    }
    eligible = {
        note.ref.rsplit("/", 1)[-1]: note
        for note in tools
        if note.ref not in explicit_children and "." in note.ref.rsplit("/", 1)[-1]
    }
    namespaces = {
        ".".join(name.split(".")[:depth])
        for name in eligible for depth in range(1, len(name.split(".")))
    }
    return eligible, namespaces


def _tool_namespace_members(namespace: str) -> list:
    eligible, _namespaces = _tool_namespace_catalog()
    prefix = namespace + "."
    return [note for name, note in eligible.items() if name.startswith(prefix)]


def _tool_namespace_article(ref: str, namespace: str | None = None) -> dict:
    eligible, namespaces = _tool_namespace_catalog()
    prefix_parts = namespace.split(".") if namespace else []
    child_namespaces = sorted(
        child for child in namespaces
        if (not namespace or child.startswith(namespace + "."))
        and len(child.split(".")) == len(prefix_parts) + 1
    )
    child_tools = sorted(
        (name, note) for name, note in eligible.items()
        if name.split(".")[:len(prefix_parts)] == prefix_parts
        and len(name.split(".")) == len(prefix_parts) + 1
    )
    lines = [
        f"- [[@library/Tools/{child}|{namespace_title(child.rsplit('.', 1)[-1])}]] · tool index"
        for child in child_namespaces
    ]
    lines.extend(
        f"- [[{note.ref}|{name.rsplit('.', 1)[-1]}]] · tool"
        for name, note in child_tools
    )
    title = namespace_title(namespace.rsplit(".", 1)[-1]) if namespace else "Tools + Skills"
    summary = (f"The `{namespace}` Tool namespace." if namespace
               else "The Library's accepted tools shelf, grouped by callable namespace.")
    body = summary + "\n\n## Indexed articles\n\n" + ("\n".join(lines) or "*No tools are indexed here.*")
    article_count = len(_tool_namespace_members(namespace)) if namespace else len(eligible)
    children = [
        *(f"@library/Tools/{child}" for child in child_namespaces),
        *(note.ref for _name, note in child_tools),
    ]
    return {"ref": ref, "title": title, "kind": "tool",
            "meta": {"node": "true", "articles": str(article_count)},
            "body": body, "children": children}


def _task_taxonomy_article(ref: str, path: str | None = None) -> dict:
    task_notes = [note for note in iter_notes() if note.kind == "task"]
    known = {note.ref for note in task_notes}
    if path is None:
        children = [node for node in TASK_TAXONOMY_NODES if "/" not in node.path]
        title = "Tasks"
        summary = (
            "The Task shelf, organized by the owner-defined observations, "
            "executive, wiki, and research taxonomy."
        )
        article_count = len(TASK_TAXONOMY_NODES)
    else:
        node = TASK_TAXONOMY_BY_PATH[path]
        children = [TASK_TAXONOMY_BY_PATH[child] for child in node.children]
        title = node.title
        summary = node.summary or f"The `{path}` Task taxonomy node."
        article_count = task_taxonomy_descendant_count(path)
    child_refs = [task_taxonomy_node_id(child.path, known) for child in children]
    lines = [
        f"- [[{child_ref}|{child.title}]] · {child.kind} article"
        for child_ref, child in zip(child_refs, children)
    ]
    if path is not None:
        lines.extend(
            f"- [[{note.ref}|{note.title}]] · event task"
            for note in task_notes
            if str(note.meta.get("taxonomy_path", "")) == path
        )
    body = summary + "\n\n## Indexed subtasks\n\n" + (
        "\n".join(lines)
        if lines else "This is a terminal Task article with no subtasks."
    )
    meta = {"node": "true", "articles": str(article_count), "generated": "true"}
    if path is not None and TASK_TAXONOMY_BY_PATH[path].triggers:
        triggers = TASK_TAXONOMY_BY_PATH[path].triggers
        meta["triggers"] = list(triggers)
        body += "\n\n## Triggers\n\n" + "\n".join(
            f"- `{trigger}`" for trigger in triggers
        )
    if path is not None and TASK_TAXONOMY_BY_PATH[path].routing:
        meta["routing"] = TASK_TAXONOMY_BY_PATH[path].routing
        body += (
            "\n\n## Routing\n\nSelect and activate only the relevant child task families "
            "for the current request."
        )
    return {
        "ref": ref,
        "title": title,
        "kind": TASK_TAXONOMY_BY_PATH[path].kind if path is not None else "knowledge",
        "meta": meta,
        "body": body,
        "children": child_refs,
    }


def _skill_mirror_catalog():
    notes = iter_notes()
    nodes = build_skill_mirror(notes)
    return notes, nodes, {node.path: node for node in nodes}


def _paired_skill_checkouts(tool_refs: set[str]) -> set[str]:
    """Return the Skill mirror leaf paired to every selected callable Tool."""
    _notes, nodes, _by_path = _skill_mirror_catalog()
    return {
        skill_mirror_node_id(node.path)
        for node in nodes if node.tool_ref in tool_refs
    }


def _canonical_skills_for_tools(tool_refs: set[str]) -> list[str]:
    """Resolve the one canonical Skill article paired to each Tool."""
    res = resolver()
    by_tool: dict[str, str] = {}
    for skill in (note for note in iter_notes() if note.kind == "skill"):
        target = res.resolve(str(skill.meta.get("tool", "")))
        if target and target.ref in tool_refs:
            by_tool[target.ref] = skill.ref
    return [by_tool[ref] for ref in sorted(tool_refs) if ref in by_tool]


def _activate_task_checkout_event(agent: str, identity, task_ref: str, identity_meta: dict) -> dict:
    """Queue the ordinary graph Task that handles Task-checkout events."""
    res = resolver()
    subscribers = [note for note in iter_notes()
                   if note.kind == "task" and "task.checkout" in task_triggers(note.meta)]
    if len(subscribers) != 1:
        raise HTTPException(
            500,
            f"task.checkout must resolve to exactly one graph Task; found {len(subscribers)}",
        )
    generation = subscribers[0]
    target = res.resolve(task_ref)
    if target and target.kind == "task":
        task_title = target.title
        task_path = target.ref.removeprefix("Tasks/")
        task_article = target.body.strip()[:8_000]
        task_hierarchy = [target.ref, *(child.ref for child in task_descendants(target, res)[0])]
    elif task_ref.startswith("@library/Tasks/"):
        task_path = task_ref.removeprefix("@library/Tasks/")
        article = _task_taxonomy_article(task_ref, task_path)
        task_title = str(article["title"])
        task_article = str(article["body"])[:8_000]
        task_hierarchy = [
            path for path in TASK_TAXONOMY_BY_PATH
            if path == task_path or path.startswith(task_path + "/")
        ]
    else:
        task_path = task_ref.rsplit("/", 1)[-1]
        task_title = task_path
        task_article = ""
        task_hierarchy = [task_path]

    selected_tools = {
        tool.ref
        for raw in _link_values(identity_meta.get("tools"))
        if (tool := res.resolve(raw)) and tool.kind == "tool"
    }
    canonical_skills = _canonical_skills_for_tools(selected_tools)
    output_segments = [slugify(segment) for segment in task_path.split("/") if segment]
    output_runbook = f"Runbooks/Generated/{agent}/{'/'.join(output_segments)}.md"
    params = {
        "checkout_event_id": f"checkout-{time.time_ns():x}",
        "queued_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "target_task": task_ref,
        "target_task_title": task_title,
        "target_task_article": task_article,
        "target_task_hierarchy": task_hierarchy,
        "target_agent": identity.ref,
        "target_agent_name": identity.title,
        "tools": sorted(selected_tools),
        "skills": canonical_skills,
        "output_runbook": output_runbook,
    }
    queued = scheduler.enqueue_event(generation, params)
    return {"task": generation.ref, **queued}


def _skill_mirror_article(ref: str, path: str | None = None) -> dict:
    notes, nodes, by_path = _skill_mirror_catalog()
    by_ref = {note.ref: note for note in notes}
    if path is None:
        children = [node for node in nodes if "/" not in node.path]
        title = "Skills"
        summary = "Skills mirror the Tool shelf: each callable Tool has one article explaining how to use it."
        article_count = len(nodes)
    else:
        node = by_path[path]
        children = [by_path[child] for child in node.children]
        title = node.title
        article_count = skill_mirror_descendant_count(path, nodes)
        if node.tool_ref:
            tool = by_ref[node.tool_ref]
            guidance = [by_ref[skill_ref] for skill_ref in node.source_skills if skill_ref in by_ref]
            sections = [
                f"How to use [[{tool.ref}|{tool.title}]].",
                f"## Tool contract\n\n{tool.body.strip()}",
            ]
            if guidance:
                sections.append("## Authored guidance\n\n" + "\n\n".join(
                    f"### [[{skill.ref}|{skill.title}]]\n\n{skill.body.strip()}" for skill in guidance
                ))
            else:
                sections.append(
                    "## Usage guidance\n\nFollow the Tool contract exactly and verify its returned observation "
                    "before treating the action as complete."
                )
            return {
                "ref": ref,
                "title": title,
                "kind": "skill",
                "meta": {
                    "node": "true",
                    "generated": "true",
                    "tool": tool.ref,
                    "source_skills": ", ".join(node.source_skills),
                },
                "body": "\n\n".join(sections),
                "children": [],
            }
        summary = f"Usage Skills for the `{path.replace('/', '.')}` Tool namespace."
    lines = [
        f"- [[{skill_mirror_node_id(child.path)}|{child.title}]] · skill node"
        for child in children
    ]
    body = summary + "\n\n## Indexed subskills\n\n" + (
        "\n".join(lines) if lines else "*No callable Tool is indexed here.*"
    )
    return {
        "ref": ref,
        "title": title,
        "kind": "skill",
        "meta": {"node": "true", "articles": str(article_count), "generated": "true"},
        "body": body,
        "children": [skill_mirror_node_id(child.path) for child in children],
    }


def _primitive_closure(roots, catalog) -> list:
    """Project a checked-out/assigned primitive with all same-kind descendants."""
    by_ref = {note.ref.lower(): note for note in catalog}
    by_leaf = {note.ref.rsplit("/", 1)[-1].lower(): note for note in catalog}
    closure = {note.ref: note for note in roots}
    queue = list(closure.values())
    while queue:
        parent = queue.pop(0)
        for raw in parent.children:
            target = str(raw).strip().strip("[]").split("|", 1)[0].split("#", 1)[0]
            child = by_ref.get(target.lower()) or by_leaf.get(target.rsplit("/", 1)[-1].lower())
            if not child or child.kind != parent.kind or child.ref in closure:
                continue
            closure[child.ref] = child
            queue.append(child)
    return list(closure.values())


def _virtual_index(ref: str, title: str, summary: str, children, *, kind: str = "knowledge") -> dict:
    unique = {note.ref: note for note in children}
    ordered = sorted(unique.values(), key=lambda note: (note.title.lower(), note.ref.lower()))
    by_ref = {note.ref.lower(): note for note in ordered}
    by_leaf = {note.ref.rsplit("/", 1)[-1].lower(): note for note in ordered}
    child_rows: dict[str, list] = {note.ref: [] for note in ordered}
    parent_of: dict[str, str] = {}

    def resolve_child(raw):
        target = str(raw).strip().strip("[]").split("|", 1)[0].split("#", 1)[0]
        target = target[:-3] if target.lower().endswith(".md") else target
        return by_ref.get(target.lower()) or by_leaf.get(target.rsplit("/", 1)[-1].lower())

    for parent in ordered:
        for raw in parent.children:
            child = resolve_child(raw)
            if not child or child.kind != parent.kind or child.ref == parent.ref or child.ref in parent_of:
                continue
            cursor, cyclic = parent.ref, False
            while cursor in parent_of:
                cursor = parent_of[cursor]
                if cursor == child.ref:
                    cyclic = True
                    break
            if cyclic:
                continue
            parent_of[child.ref] = parent.ref
            child_rows[parent.ref].append(child)

    lines, seen = [], set()

    def excerpt(note: Note) -> str:
        paragraph = []
        for raw in note.body.splitlines():
            line = raw.strip()
            if not line:
                if paragraph:
                    break
                continue
            if line.startswith(("#", "```")):
                continue
            paragraph.append(line)
        text = " ".join(paragraph)
        return text if len(text) <= 180 else text[:177].rstrip() + "…"

    def add(note, depth=0):
        if note.ref in seen:
            return
        seen.add(note.ref)
        condensation = excerpt(note)
        suffix = f" — {condensation}" if condensation else ""
        lines.append(f"{'  ' * depth}- [[{note.ref}|{note.title}]] · {note.kind}{suffix}")
        for child in child_rows[note.ref]:
            add(child, depth + 1)

    for note in ordered:
        if note.ref not in parent_of:
            add(note)
    for note in ordered:
        add(note)
    contents = "\n".join(lines)
    body = summary
    if contents:
        body += f"\n\n## Indexed articles\n\n{contents}"
    else:
        body += "\n\n*No articles are currently indexed beneath this node.*"
    direct_children = [note.ref for note in ordered if note.ref not in parent_of]
    return {"ref": ref, "title": title, "kind": kind,
            "meta": {"node": "true", "articles": str(len(ordered))},
            "body": body, "children": direct_children}


def _virtual_subject(ref: str, title: str, summary: str, subnodes=(), children=()) -> dict:
    """Reader article for a renderer subject without inventing vault bytes."""
    subnodes = tuple(subnodes)
    children = tuple(children)
    doc = _virtual_index(ref, title, summary, children)
    if subnodes:
        rows = "\n".join(f"- [[{child_ref}|{label}]] · node" for child_ref, label in subnodes)
        doc["body"] = f"{summary}\n\n## Subnodes\n\n{rows}"
        indexed = doc["body"].split("\n\n## Indexed articles\n\n", 1)
        if len(indexed) == 2:
            doc["body"] += f"\n\n## Indexed articles\n\n{indexed[1]}"
        elif children:
            child_doc = _virtual_index(ref, title, summary, children)
            if "\n\n## Indexed articles\n\n" in child_doc["body"]:
                doc["body"] += "\n\n## Indexed articles\n\n" + child_doc["body"].split("\n\n## Indexed articles\n\n", 1)[1]
    doc["meta"]["subnodes"] = str(len(tuple(subnodes)))
    doc["children"] = list(dict.fromkeys([
        *(child_ref for child_ref, _label in subnodes),
        *doc.get("children", []),
    ]))
    return doc


def _branch_index_summary(title: str, child_folders=(), article_count: int = 0) -> str:
    """Human reading copy for generated folder indexes."""
    labels = [str(label).strip() for label in child_folders if str(label).strip()]
    if labels:
        if len(labels) == 1:
            scope = labels[0]
        elif len(labels) == 2:
            scope = f"{labels[0]} and {labels[1]}"
        else:
            scope = f"{', '.join(labels[:-1])}, and {labels[-1]}"
        return (
            f"{title} is the overview for {scope}. "
            "Use this index to move through the subject and read the articles filed beneath it."
        )
    if article_count:
        noun = "article" if article_count == 1 else "articles"
        return (
            f"{title} brings together {article_count} {noun} in this part of the knowledge graph. "
            "Use the entries below to open the underlying knowledge directly."
        )
    return f"{title} is an empty knowledge index ready for articles."


def _navigation_subject(ref: str, parent_ref: str | None, overrides: dict[str, Note]) -> dict:
    """One generated subject whose title is identical everywhere it renders."""
    article = _apply_reader_override(_base_article(ref), overrides)
    return {
        "id": ref,
        "title": str(article["title"]),
        "parent_id": parent_ref,
    }


def _navigation_manifest(overrides: dict[str, Note]) -> dict:
    """Canonical naming and subject topology for every graph/UI projection."""
    groups = []
    executive_subjects = [
        ("@agent/Architecture", None),
        ("@branch/Tools", None),
        ("@branch/Skills", None),
        ("@branch/Runbooks", None),
        ("@branch/Tasks", None),
        ("@agent/Subagents", None),
        ("@agent/Observations", None),
        ("@agent/Temporary Observations", "@agent/Observations"),
    ]
    satellite_base = [
        ("tools", None),
        ("skills", None),
        ("runbooks", None),
        ("tasks", None),
        ("architecture", None),
        ("knowledge", None),
        ("other-agents", None),
        ("observations", None),
        ("temporary-observations", "observations"),
    ]

    for group_id, identity_ref in CHECKOUT_AGENTS.items():
        identity = resolver().resolve(identity_ref)
        if not identity:
            continue
        role = str(identity.meta.get("role") or group_id).strip().lower()
        if group_id == "executive":
            subjects = [
                _navigation_subject(ref, parent_ref, overrides)
                for ref, parent_ref in executive_subjects
            ]
        else:
            agent_name = identity_ref.split("/")[1]
            role_subjects = SATELLITE_ROLE_SUBJECTS.get(agent_name, {})
            role_parent = {
                child: parent
                for parent, children in SATELLITE_ROLE_CHILDREN.get(agent_name, {}).items()
                for child in children
            }
            subject_rows = [
                *satellite_base,
                *((key, role_parent.get(key)) for key in role_subjects),
            ]
            subjects = [
                _navigation_subject(
                    f"@sat/{agent_name}/{key}",
                    f"@sat/{agent_name}/{parent}" if parent else None,
                    overrides,
                )
                for key, parent in subject_rows
            ]
        groups.append({
            "id": group_id,
            "title": identity.title,
            "subtitle": role.replace("-", " ").title(),
            "role": role,
            "root_ref": identity.ref,
            "subjects": subjects,
        })

    library = _apply_reader_override(_base_article("@library"), overrides)
    library_subjects = [
        _navigation_subject(ref, None, overrides)
        for ref in library.get("children", [])
    ]
    groups.append({
        "id": "library",
        "title": str(library["title"]),
        "subtitle": "Shared assets",
        "role": "library",
        "root_ref": "@library",
        "subjects": library_subjects,
    })
    return {"groups": groups}


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.reconcile_interrupted_runs()
    source.list_sources()  # attest/restore registered raw evidence before serving it
    INDEX.sync()
    await asyncio.to_thread(retrieval.prewarm_fast_context)
    model_events = await model_runtime.initialize()
    task = asyncio.create_task(scheduler.loop())
    for params in model_events:
        scheduler.enqueue_named_event("model.added", params)
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        await scheduler.shutdown()
        await realtime.RUNTIME.shutdown()
        await model_runtime.shutdown()


app = FastAPI(title="Obsidience", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount(
    "/shell/knowledge",
    StaticFiles(
        directory=CONFIG.project_root / "obsidience" / "ui" / "out" / "renderer",
        html=True,
        check_dir=False,
    ),
    name="shell-knowledge",
)


@app.get("/api/status")
def status():
    notes = iter_notes()
    tasks = [n for n in notes if n.kind == "task"]
    source_status = source.list_source_files()
    residency = model_runtime.settings()
    active_specs = [
        model_runtime.configured_spec(model_id)
        for model_id in residency["active_models"]
        if model_id in model_runtime.MODELS
    ]
    return {
        "name": "obsidience", "vault": str(CONFIG.vault_dir),
        "notes": len(notes), "tasks": len(tasks),
        "tasks_by_status": _count_by(tasks),
        "proposals_pending": len(review.list_proposals()),
        "sources": len(source_status["files"]),
        "source_issues": len(source_status["issues"]),
        "speech": media_runtime.speech_runtime(),
        "llm": {
            "base_url": active_specs[0].base_url if len(active_specs) == 1 else None,
            "model": ",".join(spec.id for spec in active_specs) or "none",
            "models": [spec.id for spec in active_specs],
            "residency_policy": residency["residency_policy"],
        },
        "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


@app.get("/api/models")
def models():
    """Installed and live inference targets for the Models and Task editors."""
    return {"models": model_runtime.catalog()}


@app.get("/api/model-settings")
def model_settings():
    """Compatibility surface for live hardware-slot residency."""
    return model_runtime.settings()


@app.get("/api/hardware")
def hardware():
    """Physical compute, audio endpoints, and preferred camera."""
    return {
        **model_runtime.hardware_catalog(),
        **model_runtime.settings(),
        "interfaces": media_runtime.interface_catalog(),
        "speech": media_runtime.speech_runtime(),
    }


@app.get("/api/system")
def system():
    """Actual host, application, and network inventory behind Source."""
    return inventory.system_snapshot()


@app.get("/api/applications")
def applications():
    """Installed desktop applications projected from the real local system."""
    return application_packages.installed_applications()


@app.get("/api/applications/search")
def search_applications(q: str):
    """Search the native PackageKit catalog without inventing an app database."""
    try:
        return application_packages.search_packages(q)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc


@app.post("/api/applications/install")
async def install_application(payload: dict):
    """Install one exact PackageKit result through the system policy boundary."""
    try:
        return await asyncio.to_thread(application_packages.install_package, payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/applications/remove")
async def remove_application(payload: dict):
    """Remove one installed desktop application without dependency autoremove."""
    try:
        return await asyncio.to_thread(application_packages.remove_application, payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.patch("/api/hardware")
async def update_hardware(payload: dict):
    try:
        await model_runtime.set_hardware(payload.get("device"), payload.get("component"))
        return {
            **model_runtime.hardware_catalog(),
            **model_runtime.settings(),
            "interfaces": media_runtime.interface_catalog(),
            "speech": media_runtime.speech_runtime(),
        }
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(400, str(exc)) from exc


@app.patch("/api/hardware/interfaces")
def update_hardware_interface(payload: dict):
    """Persist one exact audio endpoint or preferred physical camera."""

    try:
        media_runtime.set_interface(payload.get("interface"), payload.get("selection"))
        return {
            **model_runtime.hardware_catalog(),
            **model_runtime.settings(),
            "interfaces": media_runtime.interface_catalog(),
            "speech": media_runtime.speech_runtime(),
        }
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.patch("/api/hardware/voice")
def update_voice(payload: dict):
    """Select the Pocket character voice; the speech engine itself is fixed."""
    try:
        return media_runtime.set_voice(payload.get("voice"))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/hardware/camera")
def hardware_camera():
    """Return the physical OBSBOT camera power state."""

    try:
        return media_runtime.obsbot_camera_state()
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc


@app.post("/api/hardware/camera")
def update_hardware_camera(payload: dict):
    """Power the physical OBSBOT camera without creating a video pipeline."""

    active = payload.get("active")
    if active is False and realtime.RUNTIME.snapshot()["enabled"]:
        raise HTTPException(409, "Realtime owns the camera while it is active")
    try:
        return media_runtime.set_obsbot_camera_active(active)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc


@app.get("/api/realtime")
def realtime_status():
    """Return the Task-selected live-session state."""

    return realtime.RUNTIME.snapshot()


@app.post("/api/realtime/start")
async def realtime_start():
    try:
        return await realtime.RUNTIME.start()
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc


@app.patch("/api/realtime/mode")
async def realtime_mode(payload: dict):
    try:
        return await realtime.RUNTIME.set_proactive(payload.get("proactive"))
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/realtime/stop")
async def realtime_stop():
    return await realtime.RUNTIME.stop()


@app.websocket("/ws/realtime")
async def realtime_ws(ws: WebSocket):
    queue = realtime.RUNTIME.subscribe()
    await ws.accept()
    try:
        await ws.send_json({"type": "state", "state": realtime.RUNTIME.snapshot()})
        while True:
            await ws.send_json(await queue.get())
    except (WebSocketDisconnect, asyncio.CancelledError):
        return
    finally:
        realtime.RUNTIME.unsubscribe(queue)


@app.get("/api/models/{model_id}")
def model(model_id: str):
    try:
        return model_runtime.model_document(model_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.patch("/api/models/{model_id}")
async def update_model(model_id: str, payload: dict):
    try:
        return await model_runtime.update_model(model_id, payload)
    except (TypeError, ValueError, RuntimeError) as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/models/{model_id}/benchmark")
async def benchmark_model(model_id: str, payload: dict):
    try:
        return await model_runtime.benchmark(model_id, payload.get("devices"))
    except (ValueError, RuntimeError, httpx.HTTPError) as exc:
        raise HTTPException(400, str(exc)) from exc


def _count_by(tasks):
    out: dict[str, int] = {}
    for t in tasks:
        s = str(t.meta.get("status", "draft"))
        out[s] = out.get(s, 0) + 1
    return out


@app.get("/api/graph")
def graph():
    doc = INDEX.graph()
    overrides = _reader_overrides()
    for node in doc["nodes"]:
        override = overrides.get(node["id"])
        if override:
            node["title"] = override.title
    auto_curated = {
        node["id"] for node in doc["nodes"]
        if "auto-curate" in _tags(node.get("tags"))
    }
    auto_curated.update(
        ref for ref, override in overrides.items()
        if "auto-curate" in _tags(override.meta.get("tags"))
    )
    auto_curated.update(
        str(task.meta.get("auto_curate_target"))
        for task in _auto_curate_tasks()
        if _is_enabled(task.meta.get("enabled", True))
    )
    return {
        **doc,
        "auto_curated": sorted(auto_curated),
        "navigation": _navigation_manifest(overrides),
    }


def _base_article(ref: str):
    """Resolve real notes and graph subject nodes through one Reader path."""
    # Presentation IDs are exact graph nodes. Never let the resolver's useful
    # leaf-title fallback turn @library/.../generate into Runbooks/generate.
    note = None if ref.startswith("@") else load_note(ref + ".md") or resolver().resolve(ref)
    if note:
        return _note_doc(note)

    # Match the main graph's visible knowledge pool. Raw sources are excluded
    # by iter_notes() and are available only through the Source surface.
    notes = [
        item for item in iter_notes()
        if not item.ref.startswith("Agents/") or item.ref.startswith("Agents/Executive/")
    ]
    if ref == "@vault":
        identity = load_note("Agents/Executive/Executive.md")
        if identity:
            knowledge_branches = sorted({
                item.ref.split("/", 1)[0]
                for item in notes
                if "/" in item.ref and item.ref.split("/", 1)[0] not in EXECUTIVE_SYSTEM_ROOTS
            })
            doc = _note_doc(identity)
            doc["ref"] = ref
            doc["children"] = [
                "@agent/Architecture",
                "@branch/Tools",
                "@branch/Skills",
                "@branch/Runbooks",
                "@branch/Tasks",
                "@agent/Subagents",
                "@agent/Observations",
                *(f"@branch/{branch}" for branch in knowledge_branches),
            ]
            return doc
        return _virtual_index(ref, "Obsidience", "The root Agent Brain Article.", notes, kind="agent")
    if ref == "@library":
        primitives = [item for item in notes if item.kind in LIBRARY_KINDS]
        body = (
            "The curated shared repository for paired Tools and Skills, plus Tasks. "
            "Runbooks are synthesized for and retained by individual agents.\n\n"
            "## Indexed shelves\n\n"
            "- [[@library/Tools|Tools + Skills]]\n"
            "- [[@library/Tasks|Tasks]]"
        )
        return {"ref": ref, "title": "Library", "kind": "knowledge",
                "meta": {"node": "true", "articles": str(len(primitives))},
                "body": body, "children": ["@library/Tools", "@library/Tasks"]}
    if ref.startswith("@library/"):
        relative = ref.removeprefix("@library/").strip("/")
        if relative == "Tools":
            return _tool_namespace_article(ref)
        if relative.startswith("Tools/"):
            namespace = relative.removeprefix("Tools/")
            if namespace not in _tool_namespace_catalog()[1]:
                raise HTTPException(404, f"tool namespace not found: {namespace}")
            return _tool_namespace_article(ref, namespace)
        if relative == "Skills":
            return _skill_mirror_article(ref)
        if relative.startswith("Skills/"):
            path = relative.removeprefix("Skills/")
            _notes, _nodes, by_path = _skill_mirror_catalog()
            if path not in by_path:
                raise HTTPException(404, f"skill mirror node not found: {path}")
            return _skill_mirror_article(ref, path)
        if relative == "Tasks":
            return _task_taxonomy_article(ref)
        if relative.startswith("Tasks/"):
            path = relative.removeprefix("Tasks/")
            if path not in TASK_TAXONOMY_BY_PATH:
                raise HTTPException(404, f"task taxonomy node not found: {path}")
            return _task_taxonomy_article(ref, path)
        folder = relative
        kind = folder.rstrip("s").lower()
        if kind not in LIBRARY_KINDS:
            raise HTTPException(404, f"library node not found: {ref}")
        authored = _folder_index(folder)
        if authored:
            return _note_doc(authored)
        return _virtual_index(
            ref, f"Library · {folder}",
            f"The Library's accepted {folder.lower()} shelf.",
            [item for item in notes if item.kind == kind],
        )
    if ref.startswith("@branch/"):
        folder = ref.removeprefix("@branch/").strip("/")
        authored = _folder_index(folder)
        if authored:
            return _note_doc(authored)
        kind = folder.rstrip("s").lower()
        if kind in CHECKOUT_FIELDS:
            res = resolver()
            identity = res.resolve(CHECKOUT_AGENTS["executive"])
            raw_checkouts = _link_values(identity.meta.get(CHECKOUT_FIELDS[kind])) if identity else []
            roots = [target for raw in raw_checkouts
                     if (target := res.resolve(raw)) and target.kind == kind]
            children = _primitive_closure(roots, [item for item in notes if item.kind == kind])
        else:
            prefix = f"{folder}/"
            descendants = [item for item in notes if item.ref.startswith(prefix)]
            children = [item for item in descendants
                        if item.ref.rsplit("/", 1)[0] == folder]
            child_folders = sorted({
                item.ref.removeprefix(prefix).split("/", 1)[0]
                for item in descendants
                if "/" in item.ref.removeprefix(prefix)
            })
            if child_folders:
                title = folder.rsplit("/", 1)[-1]
                subnodes = [(f"@branch/{folder}/{child}", child) for child in child_folders]
                return _virtual_subject(
                    ref, title,
                    _branch_index_summary(title, child_folders, len(descendants)),
                    subnodes, descendants,
                )
        return _virtual_index(ref, folder.rsplit("/", 1)[-1],
                              _branch_index_summary(
                                  folder.rsplit("/", 1)[-1], article_count=len(children)
                              ), children)
    if ref.startswith("@agent/"):
        key = ref.removeprefix("@agent/").strip("/")
        summary = EXECUTIVE_AGENT_SUBJECTS.get(key)
        if not summary:
            raise HTTPException(404, f"executive agent node not found: {ref}")
        if key == "Architecture":
            children = [item for item in notes if item.ref.startswith("Agents/Executive/Architecture/")]
        elif key == "Subagents":
            children = [item for item in notes if item.ref.startswith("Agents/Executive/Subagents/")]
            children.extend(item for item in iter_notes() if item.kind == "agent")
        elif key == "Observations":
            children = [item for item in notes
                        if item.ref.startswith("Agents/Executive/Observations/")
                        and "/Temporary Observations/" not in item.ref]
        elif key == "Temporary Observations":
            children = [item for item in notes
                        if item.ref.startswith(
                            "Agents/Executive/Observations/Temporary Observations/"
                        )]
        else:
            children = []
        return _virtual_subject(ref, key, summary, children=children)
    if ref.startswith("@sat/"):
        parts = ref.split("/")
        if len(parts) != 3:
            raise HTTPException(404, f"agent node not found: {ref}")
        _, agent_name, folder_key = parts
        folder = folder_key.capitalize()
        kind = folder.rstrip("s").lower()
        identity = resolver().resolve(f"Agents/{agent_name}/{agent_name}")
        if not identity:
            raise HTTPException(404, f"agent not found: {agent_name}")
        if kind not in CHECKOUT_FIELDS:
            subject = SATELLITE_AGENT_SUBJECTS.get(folder_key)
            role_subjects = SATELLITE_ROLE_SUBJECTS.get(agent_name, {})
            subject = subject or role_subjects.get(folder_key)
            if not subject:
                raise HTTPException(404, f"agent node not found: {ref}")
            title, summary = subject
            child_keys = list(SATELLITE_ROLE_CHILDREN.get(agent_name, {}).get(folder_key, []))
            if folder_key == "observations":
                child_keys.insert(0, "temporary-observations")
            subject_lookup = {**SATELLITE_AGENT_SUBJECTS, **role_subjects}
            subnodes = [
                (f"@sat/{agent_name}/{child_key}", subject_lookup[child_key][0])
                for child_key in child_keys if child_key in subject_lookup
            ]
            if folder_key == "other-agents":
                children = [item for item in iter_notes()
                            if item.kind == "agent" and item.ref != identity.ref]
                executive = resolver().resolve("Agents/Executive/Executive")
                if executive:
                    children.append(executive)
            elif folder_key == "observations":
                children = [item for item in iter_notes()
                            if item.ref.startswith(f"Agents/{agent_name}/")
                            and "/Observations/Temporary Observations/" not in item.ref
                            and item.ref != identity.ref]
            elif folder_key == "temporary-observations":
                children = [item for item in iter_notes()
                            if item.ref.startswith(
                                f"Agents/{agent_name}/Observations/Temporary Observations/"
                            )]
            elif agent_name == "Darwin" and folder_key == "sources":
                children = [item for item in iter_notes()
                            if item.ref.startswith("Sources/")
                            and item.ref.rsplit("/", 1)[-1].lower() not in {"readme", "index"}]
            else:
                children = []
            return _virtual_subject(ref, title, summary, subnodes, children)
        res = resolver()
        children = [target for raw in _link_values(identity.meta.get(CHECKOUT_FIELDS[kind]))
                    if (target := res.resolve(raw)) and target.kind == kind]
        if kind == "task":
            children.extend(item for item in notes if item.kind == "task" and
                            f"Agents/{agent_name}" in str(item.meta.get("assignee", "")))
        children = _primitive_closure(children, [item for item in notes if item.kind == kind])
        return _virtual_index(
            ref, folder,
            f"{agent_name}'s active and checked-out {folder.lower()}.",
            children,
        )
    raise HTTPException(404, f"article not found: {ref}")


@app.get("/api/articles/{ref:path}")
def get_article(ref: str):
    return _article_with_curation(ref, _apply_reader_override(_base_article(ref)))


@app.put("/api/articles/{ref:path}/auto-curate")
def set_article_auto_curate(ref: str, payload: dict):
    """Owner toggle: mark a node and provision its ordinary turn event Task."""
    enabled = payload.get("enabled")
    if not isinstance(enabled, bool):
        raise HTTPException(400, "enabled must be boolean")
    doc = _apply_reader_override(_base_article(ref))
    existing = next(
        (note for note in _auto_curate_tasks()
         if str(note.meta.get("auto_curate_target", "")) == ref),
        None,
    )
    if existing and str(existing.meta.get("status", "")) == "running":
        raise HTTPException(409, "auto-curation cannot change while its Task is running")

    task_ref = existing.ref if existing else None
    if enabled:
        agent_ref = _auto_curate_agent_ref(ref, doc)
        runbook = _auto_curate_runbook(agent_ref)
        target_path = _auto_curate_target_path(ref, doc)
        temporary = target_path.endswith("Observations/Temporary Observations")
        digest = hashlib.sha256(ref.encode()).hexdigest()[:12]
        folder = "temporary" if temporary else "durable"
        task_path = (
            existing.path if existing else
            f"Tasks/observations/{folder}/{slugify(str(doc['title'])) or 'node'}-{digest}.md"
        )
        meta = dict(existing.meta) if existing else {}
        meta.update({
            "title": f"Maintain {doc['title']}",
            "kind": "task",
            # An event Task waits as a definition until a real turn.complete
            # occurrence binds its parameters and moves it to pending.
            "status": "draft",
            "triggers": ["turn.complete"],
            "enabled": True,
            "assignee": f"[[{agent_ref}]]",
            "runbook": f"[[{runbook.ref}]]",
            "reasoning_effort": "low",
            "auto_done": True,
            "auto_curate_target": ref,
            "target_path": target_path,
            "curation_mode": "temporary" if temporary else "reviewed",
            "taxonomy_path": (
                "observations/temporary/maintain"
                if temporary else "observations/durable/maintain"
            ),
        })
        if temporary:
            meta["transient"] = True
        else:
            meta.pop("transient", None)
        meta.pop("event", None)
        for runtime_field in (
            "blocked_reason", "event_queue", "last_run", "params", "summary",
            "triggered_at", "status_updated",
        ):
            meta.pop(runtime_field, None)
        body = (
            f"Maintain [[{ref}|{doc['title']}]] after each completed turn by its assigned agent. "
            "The trigger is Obsidience's completed-turn memory boundary; this is not a schedule."
        )
        write_note(task_path, meta, body)
        task_ref = task_path[:-3]
    elif existing:
        meta = dict(existing.meta)
        meta["enabled"] = False
        meta["status"] = "draft"
        write_note(existing.path, meta, existing.body)

    _set_auto_curate_tag(ref, doc, enabled)
    INDEX.sync()
    return {"article": ref, "enabled": enabled, "task": task_ref}


@app.patch("/api/articles/{ref:path}")
def update_article(ref: str, payload: dict):
    """Direct owner edit for any Reader article, including generated nodes."""
    title = str(payload.get("title", "")).strip()
    body = str(payload.get("body", ""))
    if not title:
        raise HTTPException(400, "title required")
    if len(title) > 160:
        raise HTTPException(400, "title is too long")
    if len(body) > 200_000:
        raise HTTPException(400, "article body is too large")

    base = _base_article(ref)
    target_ref = str(base["ref"])
    note = None if target_ref.startswith("@") else load_note(target_ref + ".md")
    if note:
        if note.kind == "task" and str(note.meta.get("status", "draft")) == "running":
            raise HTTPException(409, "cannot edit a running task")
        meta = dict(note.meta)
        meta["title"] = title
        write_note(note.path, meta, body)
        saved_ref = note.ref
    else:
        if not target_ref.startswith("@"):
            raise HTTPException(404, f"article not found: {ref}")
        write_note(
            _reader_override_path(target_ref),
            {
                "title": title,
                "kind": str(base.get("kind", "note")),
                "reader_ref": target_ref,
                "owner_maintained": True,
            },
            body,
        )
        saved_ref = target_ref
    INDEX.sync()
    return {"article": saved_ref, "updated": True}


@app.get("/api/files")
def files():
    """Accepted vault tree for the Reader's Obsidian-style explorer."""
    return [
        {"ref": note.ref, "path": note.path, "title": note.title, "kind": note.kind}
        for note in iter_notes()
    ]


@app.get("/api/sources")
def sources():
    """Registered evidence records retained for provenance and Tool access."""
    try:
        return source.list_sources()
    except source.SourceError as cause:
        raise HTTPException(409, str(cause)) from cause


@app.get("/api/source-files")
def source_files():
    """Exact physical wiki, code, System, and raw-source paths in one view."""
    try:
        return source.list_source_files()
    except source.SourceError as cause:
        raise HTTPException(409, str(cause)) from cause


@app.get("/api/source-files/{key:path}")
def read_source_file(key: str):
    try:
        return source.get_source_file(key)
    except source.SourceError as cause:
        raise HTTPException(404, str(cause)) from cause


@app.get("/api/source-checkouts")
def source_checkouts():
    """Return independent Source-tree Knowledge scopes for all principals."""
    res = resolver()
    assignments = []
    for agent, identity_ref in CHECKOUT_AGENTS.items():
        identity = res.resolve(identity_ref)
        if not identity:
            continue
        for raw in _link_values(identity.meta.get(SOURCE_SCOPE_FIELD)):
            try:
                tree = source.normalize_source_tree(raw)
            except source.SourceError:
                continue
            assignments.append({"agent": agent, "tree": tree})
    return {"assignments": assignments}


@app.put("/api/source-checkouts/{tree:path}")
def set_source_checkout(tree: str, payload: dict):
    """Assign one Source subtree as bounded Knowledge context for one Agent."""
    agent = str(payload.get("agent") or "").strip().lower()
    if agent not in CHECKOUT_AGENTS:
        raise HTTPException(400, f"unknown checkout agent: {agent or '(empty)'}")
    checked_out = payload.get("checked_out")
    if not isinstance(checked_out, bool):
        raise HTTPException(400, "checked_out must be boolean")
    try:
        normalized = source.normalize_source_tree(tree)
        if not source.source_tree_exists(normalized, folder_only=True):
            raise source.SourceError("source checkout must name an existing Source folder")
    except source.SourceError as cause:
        raise HTTPException(404, str(cause)) from cause

    with _CHECKOUT_LOCK:
        identity = resolver().resolve(CHECKOUT_AGENTS[agent])
        if not identity:
            raise HTTPException(500, f"checkout identity missing: {CHECKOUT_AGENTS[agent]}")

        changed = False

        def mutate(meta: dict) -> None:
            nonlocal changed
            current = []
            for raw in _link_values(meta.get(SOURCE_SCOPE_FIELD)):
                try:
                    candidate = source.normalize_source_tree(raw)
                except source.SourceError:
                    continue
                if candidate not in current:
                    current.append(candidate)
            present = normalized in current
            changed = present != checked_out
            if checked_out and not present:
                if len(current) >= source.MAX_SOURCE_TREE_SCOPES:
                    raise source.SourceError("Agent Source checkout limit reached")
                current.append(normalized)
            elif not checked_out and present:
                current.remove(normalized)
            if current:
                meta[SOURCE_SCOPE_FIELD] = sorted(current)
            else:
                meta.pop(SOURCE_SCOPE_FIELD, None)

        try:
            mutate_note_metadata(identity, mutate)
        except source.SourceError as cause:
            raise HTTPException(409, str(cause)) from cause
        INDEX.sync()
    return {
        "agent": agent,
        "tree": normalized,
        "checked_out": checked_out,
        "checkout_changed": changed,
        "article_refs": source.article_refs_for_trees([normalized]),
    }


@app.get("/api/sources/{source_id}")
def read_source(source_id: str):
    try:
        return source.get_source(source_id)
    except source.SourceError as cause:
        raise HTTPException(404, str(cause)) from cause


@app.post("/api/sources")
def capture_source(payload: dict):
    """Capture Source and emit source.added only when the object is new."""
    try:
        return source.ingest_source(
            source_type=str(payload.get("source_type", "tool")),
            source_ref=str(payload.get("source_ref", "")),
            media_type=str(payload.get("media_type", "text/markdown")),
            captured_at=str(payload["captured_at"]) if payload.get("captured_at") else None,
            content=str(payload.get("content", "")),
        )
    except source.SourceError as cause:
        raise HTTPException(400, str(cause)) from cause


@app.post("/api/files/move")
def move_file(payload: dict):
    """Owner filesystem operation for Reader rename and drag/drop."""
    source = str(payload.get("source", ""))
    destination_parent = str(payload.get("destination_parent", ""))
    raw_name = payload.get("new_name")
    new_name = str(raw_name) if raw_name is not None else None
    try:
        result = move_vault_item(source, destination_parent, new_name)
    except ValueError as cause:
        raise HTTPException(400, str(cause)) from cause
    INDEX.sync()
    return result


@app.get("/api/actions/wiki")
def wiki_actions():
    """Runbook-backed Wiki tasks exposed as direct owner actions."""
    by_ref = {note.ref: note for note in iter_notes() if note.kind == "task"}
    rows = []
    seen = set()
    for path, ref in CANONICAL_TASK_BY_PATH.items():
        note = by_ref.get(ref)
        if not path.startswith("wiki/") or not note or note.ref in seen:
            continue
        if note.children or not note.meta.get("runbook"):
            continue
        seen.add(note.ref)
        agent = resolver().resolve(str(note.meta.get("assignee", "")))
        rows.append({
            "ref": note.ref,
            "title": note.title,
            "path": path,
            "status": str(note.meta.get("status", "draft")),
            "agent": agent.ref if agent else "Agents/Executive/Executive",
            "agent_label": agent.title if agent else "Executive",
            "reasoning_effort": llm.normalize_reasoning_effort(
                note.meta.get("reasoning_effort")
            ),
        })
    return rows


@app.get("/api/library/checkouts")
def library_checkouts():
    """Return exact shared-Library assignments for all four principals."""
    res = resolver()
    assignments = []
    for agent, identity_ref in CHECKOUT_AGENTS.items():
        identity = res.resolve(identity_ref)
        if not identity:
            continue
        for kind in LIBRARY_KINDS:
            field = CHECKOUT_FIELDS[kind]
            selected = set()
            for raw in _link_values(identity.meta.get(field)):
                raw_ref = _link_ref(raw)
                if kind == "task" and raw_ref.startswith("@library/Tasks/"):
                    path = raw_ref.removeprefix("@library/Tasks/")
                    taxonomy_node = TASK_TAXONOMY_BY_PATH.get(path)
                    if taxonomy_node and taxonomy_node.kind == "task":
                        assignments.append({"agent": agent, "ref": raw_ref, "kind": kind})
                    continue
                target = res.resolve(raw)
                if target and target.kind == kind:
                    assignments.append({"agent": agent, "ref": target.ref, "kind": kind})
                    selected.add(target.ref)
            if kind == "tool":
                _eligible, namespaces = _tool_namespace_catalog()
                for namespace in sorted(namespaces):
                    members = {note.ref for note in _tool_namespace_members(namespace)}
                    if members and members <= selected:
                        assignments.append({
                            "agent": agent,
                            "ref": f"@library/Tools/{namespace}",
                            "kind": "tool",
                        })
            if kind == "task":
                known = {note.ref for note in iter_notes() if note.kind == "task"}
                for path, taxonomy_node in TASK_TAXONOMY_BY_PATH.items():
                    if taxonomy_node.kind != "task":
                        continue
                    synthetic_ref = f"@library/Tasks/{path}"
                    if task_taxonomy_node_id(path, known) != synthetic_ref:
                        continue
                    members = set(task_taxonomy_members(path, known))
                    if members and members <= selected:
                        assignments.append({
                            "agent": agent,
                            "ref": synthetic_ref,
                            "kind": "task",
                        })
    return {"assignments": assignments}


def _set_library_checkout(ref: str, payload: dict):
    """Owner toggle for one typed Library item on one principal."""
    agent = str(payload.get("agent") or "").strip().lower()
    if agent not in CHECKOUT_AGENTS:
        raise HTTPException(400, f"unknown checkout agent: {agent or '(empty)'}")
    checked_out = payload.get("checked_out")
    if not isinstance(checked_out, bool):
        raise HTTPException(400, "checked_out must be boolean")

    res = resolver()
    namespace = ref.removeprefix("@library/Tools/") if ref.startswith("@library/Tools/") else None
    if ref.startswith("@library/Skills/"):
        raise HTTPException(
            404, "Skills are checked out automatically with their paired Tool"
        )
    task_path = ref.removeprefix("@library/Tasks/") if ref.startswith("@library/Tasks/") else None
    if task_path and task_path not in TASK_TAXONOMY_BY_PATH:
        raise HTTPException(404, f"task taxonomy node not found: {task_path}")
    if task_path and TASK_TAXONOMY_BY_PATH[task_path].kind != "task":
        raise HTTPException(
            400,
            f"{TASK_TAXONOMY_BY_PATH[task_path].title} is a Knowledge Article and cannot be checked out",
        )
    if namespace:
        targets = _tool_namespace_members(namespace)
    else:
        targets = []
    if namespace and namespace not in _tool_namespace_catalog()[1]:
        raise HTTPException(404, f"tool namespace not found: {namespace}")
    target = res.resolve(ref) if not namespace and not task_path else None
    if not namespace and not task_path and (not target or target.kind not in LIBRARY_KINDS):
        raise HTTPException(404, f"library item not found: {ref}")
    identity = res.resolve(CHECKOUT_AGENTS[agent])
    if not identity:
        raise HTTPException(500, f"checkout identity missing: {CHECKOUT_AGENTS[agent]}")

    kind = "tool" if namespace else "task" if task_path else target.kind
    field = CHECKOUT_FIELDS[kind]
    current = _link_values(identity.meta.get(field))
    retained = []
    target_refs = ({ref} if task_path else {item.ref for item in targets}
                   if namespace else {target.ref})
    def checkout_ref(raw: str) -> str:
        raw_ref = _link_ref(raw)
        if raw_ref.startswith("@library/"):
            return raw_ref
        resolved = res.resolve(raw)
        return resolved.ref if resolved else raw_ref

    current_refs = {checkout_ref(raw) for raw in current}
    was_checked_out = bool(target_refs) and target_refs <= current_refs
    checkout_changed = checked_out != was_checked_out
    for raw in current:
        current_ref = checkout_ref(raw)
        if current_ref not in target_refs:
            retained.append(raw)
    if checked_out:
        retained.extend(f"[[{target_ref}]]" for target_ref in sorted(target_refs))

    meta = dict(identity.meta)
    if retained:
        meta[field] = retained
    else:
        meta.pop(field, None)

    paired_skills: list[str] = []
    if kind == "tool":
        selected_tools = {
            tool.ref
            for raw in _link_values(meta.get("tools"))
            if (tool := res.resolve(raw)) and tool.kind == "tool"
        }
        paired_skills = sorted(_paired_skill_checkouts(selected_tools))
        if paired_skills:
            meta["skills"] = [f"[[{skill_ref}]]" for skill_ref in paired_skills]
        else:
            meta.pop("skills", None)

    write_note(identity.path, meta, identity.body)
    activation = None
    activation_error = None
    if checkout_changed and checked_out and kind == "task":
        try:
            activation = _activate_task_checkout_event(agent, identity, ref, meta)
        except HTTPException as exc:
            activation_error = str(exc.detail)
        except Exception as exc:  # noqa: BLE001 — assignment remains a successful owner action
            activation_error = f"runbook generation could not be queued: {exc}"
    INDEX.sync()
    return {"agent": agent, "ref": ref if namespace or task_path else target.ref,
            "kind": kind, "checked_out": checked_out,
            "checkout_changed": checkout_changed,
            "paired_skills": paired_skills,
            "activated_task": activation["task"] if activation else None,
            "activation_state": activation["state"] if activation else None,
            "queue_position": activation["position"] if activation else None,
            "queue_depth": activation["queue_depth"] if activation else 0,
            "activation_error": activation_error}


@app.put("/api/library/checkouts/{ref:path}")
def set_library_checkout(ref: str, payload: dict):
    """Serialize checkout mutations so rapid clicks cannot lose identity edges."""
    with _CHECKOUT_LOCK:
        return _set_library_checkout(ref, payload)


@app.get("/api/notes/{ref:path}")
def get_note(ref: str):
    note = load_note(ref + ".md") or resolver().resolve(ref)
    if not note:
        raise HTTPException(404, f"note not found: {ref}")
    return _note_doc(note)


@app.get("/api/search")
def search(q: str):
    return retrieval.search(q)


@app.post("/api/proposals")
def stage_proposal(payload: dict):
    """Local Codex/agent boundary for one ordinary owner-review proposal."""
    from ...capabilities.vault.propose import stage_proposal as stage

    try:
        return stage(
            payload,
            {"agent": "Codex", "task": "codex:knowledge-handoff"},
        )
    except ValueError as cause:
        raise HTTPException(400, str(cause)) from cause


@app.post("/api/turns/complete")
async def completed_turn(payload: dict):
    """Queue a completed external turn through Obsidience's graph event Tasks."""
    user = payload.get("user")
    assistant = payload.get("assistant")
    thread_id = payload.get("thread_id")
    external_turn_id = payload.get("turn_id")
    if not all(isinstance(value, str) for value in (user, assistant, thread_id, external_turn_id)):
        raise HTTPException(400, "turn fields must be strings")
    if not user.strip() or not assistant.strip() or not thread_id or not external_turn_id:
        raise HTTPException(400, "completed turn is incomplete")
    if len(user) > 256 * 1024 or len(assistant) > 256 * 1024:
        raise HTTPException(413, "completed turn exceeds the bounded handoff size")
    turn_id = hashlib.sha256(
        f"codex\0{thread_id}\0{external_turn_id}".encode()
    ).hexdigest()[:24]
    from ...conversation.observations import queue_turn_complete

    queued = queue_turn_complete(
        "Agents/Executive/Executive",
        user,
        assistant,
        source="codex",
        turn_id=turn_id,
    )
    return {
        "accepted": True,
        "queued_tasks": queued,
        "raw_persisted": False,
        "turn_hash": turn_id,
    }


@app.get("/api/tasks")
def tasks():
    out = []
    for n in iter_notes():
        if n.kind != "task":
            continue
        subtasks = n.meta.get("subtasks") or []
        refs = [_link_ref(str(x)) for x in subtasks] if isinstance(subtasks, list) else []
        excluded = n.meta.get("exclude_subtasks") or []
        excluded_refs = (
            [_link_ref(str(x)) for x in excluded]
            if isinstance(excluded, list) else [_link_ref(str(excluded))]
        )
        effort = str(n.meta.get("reasoning_effort", "medium")).lower()
        if effort not in llm.REASONING_BUDGETS:
            effort = "medium"
        status = str(n.meta.get("status", "draft"))
        try:
            model = model_runtime.normalize_model(n.meta.get("model"))
        except ValueError:
            model = model_runtime.AUTO_MODEL
        assignee_ref = _link_ref(str(n.meta.get("assignee", "")))
        resolved_model = model_runtime.resolve_model(
            model,
            assignee_ref or "Agents/Executive/Executive",
        )
        resolved_model = resolved_model.id
        schedule = n.meta.get("schedule")
        next_run = None
        if schedule and status in ("pending", "completed", "failed", "running"):
            try:
                next_run = croniter(str(schedule), time.time()).get_next(float)
            except (ValueError, KeyError):
                pass
        out.append({"ref": n.ref, "title": n.title,
                    "status": n.meta.get("status", "draft"),
                    "assignee": str(n.meta.get("assignee", "")),
                    "runbook": str(n.meta.get("runbook", "")),
                    "subtasks": len(refs),
                    "subtask_refs": refs,
                    "excluded_subtask_refs": excluded_refs,
                    "taxonomy_path": str(
                        n.meta.get("taxonomy_path") or TASK_TAXONOMY_PATH_BY_REF.get(n.ref, "")
                    ),
                    "reasoning_effort": effort,
                    "model": model,
                    "resolved_model": resolved_model,
                    "triggers": list(task_triggers(n.meta)),
                    "queue_depth": len(n.meta.get("event_queue", []))
                    if isinstance(n.meta.get("event_queue"), list) else 0,
                    "enabled": _is_enabled(n.meta.get("enabled", True)),
                    "schedule": schedule,
                    "next_run": next_run,
                    "blocked_reason": n.meta.get("blocked_reason"),
                    "last_run": n.meta.get("last_run")})
    return out


@app.post("/api/tasks")
async def create_task(payload: dict):
    """Activate or schedule one accepted Library Task from the Tasks pane."""
    from ...knowledge.vault import write_note

    requested = str(payload.get("task", "")).strip()
    task = resolver().resolve(requested)
    if not requested or not task or task.kind != "task":
        raise HTTPException(400, f"task not found: {requested or '(empty)'}")
    if str(task.meta.get("status", "draft")) == "running":
        raise HTTPException(409, "task is already running")
    schedule = str(payload.get("schedule") or "").strip()
    if schedule:
        try:
            croniter(schedule, time.time()).get_next(float)
        except (ValueError, KeyError) as exc:
            raise HTTPException(400, f"invalid cron schedule: {schedule}") from exc
    raw_params = payload.get("params") or {}
    if not isinstance(raw_params, dict) or len(raw_params) > 8:
        raise HTTPException(400, "params must be an object with at most 8 fields")
    meta = dict(task.meta)
    if schedule:
        meta["schedule"] = schedule
        state = "scheduled"
    else:
        meta.pop("schedule", None)
        meta["triggered_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        state = "started"
    if raw_params:
        meta["params"] = raw_params
    else:
        meta.pop("params", None)
    meta["status"] = "pending"
    write_note(task.path, meta, task.body)
    INDEX.sync()
    return {"task": task.ref, "state": state, "status": meta["status"]}


@app.patch("/api/tasks/{ref:path}/reasoning")
async def set_task_reasoning(ref: str, payload: dict):
    """Persist an owner-selected inference setting on one task."""
    from ...knowledge.vault import write_note

    note = load_note(ref + ".md") or resolver().resolve(ref)
    if not note or note.kind != "task":
        raise HTTPException(404, f"task not found: {ref}")
    if str(note.meta.get("status", "draft")) == "running":
        raise HTTPException(409, "cannot edit a running task")
    try:
        effort = llm.normalize_reasoning_effort(payload.get("reasoning_effort"))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    meta = dict(note.meta)
    meta["reasoning_effort"] = effort
    write_note(note.path, meta, note.body)
    INDEX.sync()
    return {"task": note.ref, "reasoning_effort": effort}


@app.patch("/api/tasks/{ref:path}/assignee")
async def set_task_assignee(ref: str, payload: dict):
    """Persist an owner-selected agent on one executable task."""
    from ...knowledge.vault import write_note

    note = load_note(ref + ".md") or resolver().resolve(ref)
    if not note or note.kind != "task":
        raise HTTPException(404, f"task not found: {ref}")
    if str(note.meta.get("status", "draft")) == "running":
        raise HTTPException(409, "cannot edit a running task")
    requested = str(payload.get("assignee", "")).strip()
    agent = resolver().resolve(requested)
    if not requested or not agent or agent.kind != "agent":
        raise HTTPException(400, f"agent not found: {requested or '(empty)'}")
    assignee = f"[[{agent.ref}]]"
    meta = dict(note.meta)
    meta["assignee"] = assignee
    write_note(note.path, meta, note.body)
    INDEX.sync()
    return {"task": note.ref, "assignee": assignee}


@app.patch("/api/tasks/{ref:path}/model")
async def set_task_model(ref: str, payload: dict):
    """Persist one model preference on one Task Article."""
    from ...knowledge.vault import write_note

    note = load_note(ref + ".md") or resolver().resolve(ref)
    if not note or note.kind != "task":
        raise HTTPException(404, f"task not found: {ref}")
    if str(note.meta.get("status", "draft")) == "running":
        raise HTTPException(409, "cannot edit a running task")
    try:
        model = model_runtime.normalize_model(payload.get("model"))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    meta = dict(note.meta)
    meta["model"] = model
    write_note(note.path, meta, note.body)
    INDEX.sync()
    agent_ref = _link_ref(str(meta.get("assignee", ""))) or "Agents/Executive/Executive"
    return {
        "task": note.ref,
        "model": model,
        "resolved_model": model_runtime.resolve_model(model, agent_ref).id,
    }


@app.patch("/api/tasks/{ref:path}/exclusions")
async def set_task_exclusions(ref: str, payload: dict):
    """Persist explicit descendant-subtree exclusions on one parent Task."""
    note = load_note(ref + ".md") or resolver().resolve(ref)
    if not note or note.kind != "task":
        raise HTTPException(404, f"task not found: {ref}")
    if str(note.meta.get("status", "draft")) == "running":
        raise HTTPException(409, "cannot edit a running task")
    requested = payload.get("excluded_subtask_refs", [])
    if not isinstance(requested, list) or len(requested) > 64:
        raise HTTPException(400, "excluded_subtask_refs must be a list of at most 64 refs")

    res = resolver()
    descendants, error = task_descendants(note, res)
    if error:
        raise HTTPException(400, error)
    by_ref = {child.ref: child for child in descendants}
    root_path = _task_taxonomy_path(note)
    selected: list[str] = []
    for raw in requested:
        ref = _link_ref(str(raw))
        if ref.startswith("@library/Tasks/"):
            path = _task_taxonomy_ref_path(ref, res)
            if not root_path or not path.startswith(root_path + "/"):
                raise HTTPException(400, f"excluded subtask is not a descendant: {raw}")
            canonical = ref
        else:
            child = res.resolve(ref)
            if child and child.kind == "task" and child.ref in by_ref:
                canonical = child.ref
            else:
                path = _task_taxonomy_ref_path(ref, res)
                if not root_path or not path.startswith(root_path + "/"):
                    raise HTTPException(400, f"excluded subtask is not a descendant: {raw}")
                canonical = ref
        if canonical not in selected:
            selected.append(canonical)

    ordered = selected
    meta = dict(note.meta)
    if ordered:
        meta["exclude_subtasks"] = [f"[[{child_ref}]]" for child_ref in ordered]
    else:
        meta.pop("exclude_subtasks", None)
    write_note(note.path, meta, note.body)
    INDEX.sync()
    return {"task": note.ref, "excluded_subtask_refs": ordered}


@app.patch("/api/tasks/{ref:path}")
async def update_task(ref: str, payload: dict):
    """Owner editor for task instructions and scheduler-facing fields."""
    from ...knowledge.vault import write_note

    note = load_note(ref + ".md") or resolver().resolve(ref)
    if not note or note.kind != "task":
        raise HTTPException(404, f"task not found: {ref}")
    if str(note.meta.get("status", "draft")) == "running":
        raise HTTPException(409, "cannot edit a running task")
    meta = dict(note.meta)

    if "title" in payload:
        title = str(payload["title"]).strip()
        if not title:
            raise HTTPException(400, "title required")
        meta["title"] = title

    if "schedule" in payload:
        schedule = str(payload.get("schedule") or "").strip()
        if schedule:
            try:
                croniter(schedule, time.time()).get_next(float)
            except (ValueError, KeyError) as exc:
                raise HTTPException(400, f"invalid cron schedule: {schedule}") from exc
            meta["schedule"] = schedule
            if str(meta.get("status", "draft")) == "draft":
                meta["status"] = "pending"
        else:
            meta.pop("schedule", None)

    res = resolver()
    if "assignee" in payload:
        requested = str(payload.get("assignee") or "").strip()
        if requested:
            agent = res.resolve(requested)
            if not agent or agent.kind != "agent":
                raise HTTPException(400, f"agent not found: {requested}")
            meta["assignee"] = f"[[{agent.ref}]]"
        else:
            meta.pop("assignee", None)

    if "runbook" in payload:
        requested = str(payload.get("runbook") or "").strip()
        if requested:
            runbook = res.resolve(requested)
            if not runbook or runbook.kind != "runbook":
                raise HTTPException(400, f"runbook not found: {requested}")
            meta["runbook"] = f"[[{runbook.ref}]]"
        else:
            meta.pop("runbook", None)

    if "reasoning_effort" in payload:
        try:
            meta["reasoning_effort"] = llm.normalize_reasoning_effort(payload["reasoning_effort"])
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    if "model" in payload:
        try:
            meta["model"] = model_runtime.normalize_model(payload.get("model"))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    body = str(payload["body"]) if "body" in payload else note.body
    write_note(note.path, meta, body)
    INDEX.sync()
    return {"task": note.ref, "updated": True}


@app.post("/api/tasks/{ref:path}/run")
async def run_now(ref: str, payload: dict | None = None):
    note = load_note(ref + ".md") or resolver().resolve(ref)
    if not note or note.kind != "task":
        raise HTTPException(404, f"task not found: {ref}")
    if str(note.meta.get("status", "draft")) == "running":
        raise HTTPException(409, "task is already running")
    try:
        requested_effort = (payload or {}).get("reasoning_effort", note.meta.get("reasoning_effort"))
        effort = llm.normalize_reasoning_effort(requested_effort)
        requested_model = (payload or {}).get("model")
        model = (
            model_runtime.normalize_model(requested_model)
            if requested_model is not None else None
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    raw_params = (payload or {}).get("params") or {}
    if not isinstance(raw_params, dict):
        raise HTTPException(400, "params must be an object")
    if len(raw_params) > 8:
        raise HTTPException(400, "too many runtime params")
    runtime_params: dict[str, str] = {}
    for raw_key, raw_value in raw_params.items():
        key = str(raw_key).strip()
        value = str(raw_value).strip()
        if not key or len(key) > 64 or len(value) > 500:
            raise HTTPException(400, "runtime params are invalid")
        runtime_params[key] = value
    try:
        scheduler.launch(
            note,
            reasoning_effort=effort,
            model=model,
            runtime_params=runtime_params,
        )
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    preference = model or model_runtime.normalize_model(note.meta.get("model"))
    agent_ref = _link_ref(str(note.meta.get("assignee", ""))) or "Agents/Executive/Executive"
    return {
        "started": note.ref,
        "reasoning_effort": effort,
        "model": preference,
        "resolved_model": model_runtime.resolve_model(preference, agent_ref).id,
    }


@app.get("/api/runs")
def runs():
    return INDEX.runs()


@app.get("/api/trace")
def action_trace():
    return trace.history()


@app.websocket("/ws/trace")
async def action_trace_ws(ws: WebSocket):
    await ws.accept()
    queue = trace.subscribe()
    try:
        await ws.send_json({"type": "snapshot", "entries": trace.history()})
        while True:
            await ws.send_json({"type": "entry", "entry": await queue.get()})
    except (WebSocketDisconnect, asyncio.CancelledError):
        return
    finally:
        trace.unsubscribe(queue)


@app.websocket("/ws/activity")
async def knowledge_activity_ws(ws: WebSocket):
    """Every Task activation, independent of how the Task was started."""
    await ws.accept()
    queue = knowledge_activity.subscribe()
    try:
        await ws.send_json({"type": "snapshot", "entries": knowledge_activity.history()})
        while True:
            await ws.send_json({"type": "activity", **await queue.get()})
    except (WebSocketDisconnect, asyncio.CancelledError):
        return
    finally:
        knowledge_activity.unsubscribe(queue)


@app.get("/api/reviews")
def reviews():
    return review.list_proposals()


@app.post("/api/reviews/{name}/approve")
def approve(name: str):
    try:
        with _REVIEW_LOCK:
            return review.approve(name)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/reviews/{name}/reject")
def reject(name: str, reason: str = ""):
    try:
        with _REVIEW_LOCK:
            return review.reject(name, reason)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


LIVE_APPLICATION_ALIASES = {
    "tft": "teamfight_tactics",
    "teamfight tactics": "teamfight_tactics",
    "world of warcraft": "world_of_warcraft",
    "wow": "world_of_warcraft",
    "battle net": "battle_net",
    "battlenet": "battle_net",
    "microsoft edge": "microsoft_edge",
    "edge": "microsoft_edge",
}


def _live_application_request(text: str) -> str | None:
    """Recognize only an explicit, current launch imperative—not a discussion about launching."""
    normalized = re.sub(r"\s+", " ", text.strip().casefold())
    if re.search(r"\b(?:do not|don't|never)\b", normalized):
        return None
    match = re.fullmatch(
        r"(?:please\s+)?(?:(?:can|could|would|will)\s+(?:you|we)\s+)?"
        r"(?:open|launch|start|run)\s+(?:up\s+)?(?:the\s+)?(.+?)(?:\s+for me)?[.!?]*",
        normalized,
    )
    if not match:
        return None
    requested = match.group(1).strip().replace("battle.net", "battle net")
    return LIVE_APPLICATION_ALIASES.get(requested)


def _live_application_mention(text: str) -> str | None:
    normalized = re.sub(r"\s+", " ", text.strip().casefold()).replace("battle.net", "battle net")
    for label in sorted(LIVE_APPLICATION_ALIASES, key=len, reverse=True):
        if re.search(rf"(?<!\w){re.escape(label)}(?!\w)", normalized):
            return LIVE_APPLICATION_ALIASES[label]
    return None


def _live_computer_request(text: str) -> bool:
    """Recognize a current computer-control imperative, never a discussion about one."""
    normalized = re.sub(r"\s+", " ", text.strip().casefold())
    if re.search(r"\b(?:do not|don't|never)\b", normalized):
        return False
    prefix = (
        r"(?:please\s+)?(?:"
        r"(?:(?:can|could|would|will)\s+(?:you|we)\s+)|"
        r"(?:i(?:'d| would)\s+like\s+you\s+to\s+)"
        r")?"
    )
    action = (
        r"(?:click|press|hit|tap|type|enter|scroll|drag|drop|select|choose|hover|"
        r"focus|move|control|interact|play)\b.+"
    )
    menu_open = r"open\b.+\b(?:menu|dialog|panel|tab|button|control)\b.*"
    return re.fullmatch(prefix + rf"(?:{action}|{menu_open})[.!?]*", normalized) is not None


def _live_task_selection(
    text: str,
    source_name: str,
    *,
    realtime_active: bool = False,
) -> tuple[Note | None, dict, str]:
    """Select one existing Task Article for live Executive interaction."""

    event = "voice.activation" if source_name == "voice" else "chat.request"
    application = _live_application_request(text)
    computer_use = _live_computer_request(text)
    mentioned_application = application or (_live_application_mention(text) if computer_use else None)
    task = resolver().resolve(
        "Tasks/executive/realtime"
        if realtime_active
        else "Tasks/executive/operate" if application or computer_use else "Tasks/query"
    )
    runtime_params = {"request": text, "source": source_name, "event": event}
    if application:
        runtime_params.update({"operation": "launch", "application": application})
    elif computer_use:
        runtime_params["operation"] = "computer_use"
        if mentioned_application:
            runtime_params["application"] = mentioned_application
    return task, runtime_params, event


@app.websocket("/ws/chat")
async def chat_ws(ws: WebSocket):
    """Project the one persisted Executive conversation into every Chat pane."""
    await ws.accept()
    queue = CONVERSATION.subscribe()
    queue.put_nowait(realtime.RUNTIME.context_status())

    async def send_events() -> None:
        while True:
            await ws.send_json(await queue.get())

    async def receive_requests() -> None:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if msg.get("type") == "new_conversation":
                outgoing_conversation = CONVERSATION.conversation_id
                if realtime.RUNTIME.scheduler_paused():
                    realtime.RUNTIME.defer_observation_session(outgoing_conversation)
                else:
                    try:
                        await realtime.RUNTIME.finalize_observation_session(
                            outgoing_conversation,
                            session_boundary="chat.new_conversation",
                        )
                    except (ValueError, RuntimeError) as exc:
                        queue.put_nowait({"type": "error", "text": str(exc)[:512]})
                        continue
                await CONVERSATION.new_conversation()
                realtime.RUNTIME.publish_context()
                continue
            if msg.get("type") == "set_compact_threshold":
                try:
                    await realtime.RUNTIME.set_context_threshold(msg.get("percent"))
                except (ValueError, RuntimeError) as exc:
                    queue.put_nowait({"type": "error", "text": str(exc)[:512]})
                continue
            if msg.get("type") == "compact":
                queue.put_nowait({"type": "start", "source": "compact"})
                try:
                    await realtime.RUNTIME.compact_conversation(force=True)
                except (ValueError, RuntimeError) as exc:
                    queue.put_nowait({"type": "error", "text": str(exc)[:512]})
                finally:
                    queue.put_nowait({"type": "end"})
                continue
            text = " ".join(str(msg.get("text", "")).split())[:4_000]
            if not text:
                continue
            queue.put_nowait({"type": "start", "source": "text"})
            try:
                realtime_state = realtime.RUNTIME.snapshot()
                if realtime.RUNTIME.scheduler_paused():
                    if not realtime_state["ready"]:
                        await CONVERSATION.append(role="user", source="text", text=text)
                        raise RuntimeError("Realtime is still starting")
                    await realtime.RUNTIME.submit_text(text)
                    continue

                user_turn = await CONVERSATION.append(
                    role="user",
                    source="text",
                    text=text,
                )
                task, runtime_params, event = _live_task_selection(text, "text")
                if task is None:
                    raise RuntimeError("the selected Executive Task Article is missing")
                trace.emit("event", f"{task.title} activated", [task.ref, event])
                context = await realtime.RUNTIME.prepare_immediate_observations(
                    user_turn,
                    context_task_ref=task.ref,
                )
                result = await run_task(
                    task,
                    runtime_params=runtime_params,
                    emit_turn_event=False,
                    conversation_context=context,
                )
                realtime.RUNTIME.record_prompt_usage(result, request_text=text)
                summary = str(result.get("summary") or "").strip()
                if result.get("status") != "completed" or not summary:
                    raise RuntimeError(summary or "the Executive Task produced no public reply")
                assistant_turn = await CONVERSATION.append(
                    role="assistant",
                    source="text",
                    text=summary,
                    run_id=str(result.get("run_id") or "") or None,
                    conversation_id=user_turn["conversation_id"],
                    reply_to=user_turn["id"],
                )
                realtime.RUNTIME.publish_context()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - report a bounded runtime failure
                message = f"Executive turn failed: {type(exc).__name__}: {exc}"[:512]
                trace.emit("error", message)
                queue.put_nowait({"type": "error", "text": message})
            finally:
                queue.put_nowait({"type": "end"})

    sender = asyncio.create_task(send_events(), name="obsidience-chat-send")
    receiver = asyncio.create_task(receive_requests(), name="obsidience-chat-receive")
    try:
        done, pending = await asyncio.wait(
            {sender, receiver}, return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            try:
                task.result()
            except (WebSocketDisconnect, asyncio.CancelledError):
                pass
    finally:
        sender.cancel()
        receiver.cancel()
        await asyncio.gather(sender, receiver, return_exceptions=True)
        CONVERSATION.unsubscribe(queue)


def main():
    import uvicorn
    # The Electron projection keeps trace/activity WebSockets open for its
    # lifetime. Development restarts must cancel those stale subscribers after
    # a short drain instead of waiting forever for the old renderer connection.
    uvicorn.run(
        app,
        host=CONFIG.host,
        port=CONFIG.port,
        log_level="warning",
        timeout_graceful_shutdown=5,
    )


if __name__ == "__main__":
    main()

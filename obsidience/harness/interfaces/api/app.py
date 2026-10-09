"""FastAPI daemon: REST + WebSocket surface for the UI and CLI."""

from __future__ import annotations

import asyncio
import hashlib
import json
import threading
from pathlib import Path
import time
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import replace

import httpx
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import PlainTextResponse, Response
from starlette.datastructures import Headers
from croniter import croniter

from ...conversation.store import CONVERSATION
from ...conversation import runtime as conversation_runtime
from ...execution import activity as knowledge_activity
from ...execution import scheduler, trace
from ...execution.assignments import ensure_task_runbook
from ...execution.ledger import current_task_issue
from ...knowledge.dependencies import agent_dependencies, dependency_resolver
from ...execution.executor import task_descendants
from ...host import inventory, monitor, scene as shell_scene
from ...knowledge import retrieval, review, source, system as system_knowledge
from ...knowledge.index import INDEX
from ...knowledge.links import metadata_ref
from ...knowledge.tasks import (
    CANONICAL_TASK_BY_PATH,
    TASK_TAXONOMY_BY_PATH,
    TASK_TAXONOMY_NODES,
    descendant_count as task_taxonomy_descendant_count,
    node_id as task_taxonomy_node_id,
    task_triggers,
)
from ...knowledge.skills import (
    build_skill_mirror,
    callable_namespace,
    descendant_count as skill_mirror_descendant_count,
    namespace_title,
    node_id as skill_mirror_node_id,
)
from ...knowledge.vault import (
    Note, Resolver,
    folder_article_path,
    is_folder_article,
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
from obsidience.shell.adapter.hyprland import input as input_adapter
from obsidience.shell import command_token as shell_command_token


# Tasks are the only authored capability assignments. The dependency graph
# supplies the effective Runbooks, Skills and Tools; Source scopes stay separate.
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
LIBRARY_KINDS = ("knowledge", "agent", "task", "runbook", "tool", "skill")
SOURCE_SCOPE_FIELD = "source_trees"
TASK_TAXONOMY_PATH_BY_REF = {ref: path for path, ref in CANONICAL_TASK_BY_PATH.items()}
_CHECKOUT_LOCK = threading.RLock()
_REVIEW_LOCK = threading.RLock()

EXECUTIVE_AGENT_SUBJECTS = {
    "Architecture": "How the executive is wired into Obsidience and the local workstation.",
    "Specialists": "The named specialist agents coordinated by the executive.",
    "Observations": "Distilled notes about the executive, its preferences, and its own runs.",
}
SATELLITE_AGENT_SUBJECTS = {
    "architecture": ("Architecture", "How this agent is wired into Obsidience."),
    "knowledge": ("Knowledge", "Knowledge branches related to checked-out Source trees."),
    "other-agents": ("Other Agents", "The executive and sibling agents: who they are and what they do."),
    "observations": ("Observations", "The agent's distilled notes, preferences, and run observations."),
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
    return metadata_ref(value)


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
    return load_note(folder_article_path(folder))


def _executive_folder_ref(folder: str) -> str:
    """Keep existing subject identities while deriving descendants from disk."""
    roots = {
        "Agents/Executive/Architecture": "@agent/Architecture",
        "Agents/Executive/Observations": "@agent/Observations",
    }
    return roots.get(folder, f"@branch/{folder}")


def _folder_article(folder: str, ref: str, notes: list[Note] | None = None) -> dict:
    """One real folder hub and its direct children, never duplicate descendants."""
    notes = iter_notes() if notes is None else notes
    by_path = {note.path: note for note in notes}
    def hub_at(path: str):
        return by_path.get(folder_article_path(path))

    prefix = folder + "/"
    descendants = [note for note in notes if note.ref.startswith(prefix)]
    children = [note for note in descendants if str(Path(note.path).parent) == folder
                and not is_folder_article(note)]
    child_folders = sorted({note.ref[len(prefix):].split("/", 1)[0]
                            for note in descendants if "/" in note.ref[len(prefix):]})
    subnodes = []
    for child in child_folders:
        path = f"{folder}/{child}"
        hub = hub_at(path)
        subnodes.append((hub.ref if hub else _executive_folder_ref(path), hub.title if hub else child))
    hub = hub_at(folder)
    if hub:
        return {**_note_doc(hub), "children": [
            *(child_ref for child_ref, _label in subnodes),
            *(note.ref for note in children),
        ]}
    doc = _virtual_subject(ref, folder.rsplit("/", 1)[-1],
                           _branch_index_summary(folder.rsplit("/", 1)[-1], child_folders,
                                                 len(descendants)), subnodes, children)
    return doc


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
    override = (_reader_overrides() if overrides is None else overrides).get(str(doc.get("ref", "")))
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


def _auto_curate_state(request_ref: str, doc: dict) -> tuple[bool, str | None]:
    from ...knowledge.auto_curate import policy_for, selection

    if doc.get("managed_by") == "hindsight":
        # Native memory consolidation is automatic. It does not grant wiki
        # publication permission to the containing Knowledge branch.
        return doc.get("auto_curate") is True, None
    if not _auto_curate_supported(request_ref, doc):
        return False, None
    policy = policy_for(_auto_curate_target_path(request_ref, doc))
    return selection(policy) is True, None


def _article_with_curation(request_ref: str, doc: dict) -> dict:
    enabled, task_ref = _auto_curate_state(request_ref, doc)
    system_managed = system_knowledge.is_system_article(str(doc.get("ref", request_ref)))
    return {**doc, "auto_curate": enabled, "auto_curate_task": task_ref,
            "auto_curate_supported": _auto_curate_supported(request_ref, doc),
            **({"read_only": True, "managed_by": "system"} if system_managed else {})}


def _auto_curate_supported(ref: str, doc: dict) -> bool:
    if ref.startswith("@memory/"):
        return False
    if system_knowledge.is_system_article(str(doc.get("ref", ref))):
        return False
    if doc.get("kind") not in {"knowledge", "agent", "index"} or ref.startswith("@library"):
        return False
    if ref.startswith("@sat/") and ref.split("/")[-1] in {"tools", "skills", "tasks", "runbooks", "other-agents"}:
        return False
    return not _auto_curate_target_path(ref, doc).split("/", 1)[0] in {"Tools", "Skills", "Tasks", "Runbooks"}


def _auto_curate_target_path(ref: str, doc: dict) -> str:
    if ref == "@vault":
        return "Agents/Executive/Executive.md"
    if ref == "@agent/Observations":
        return "Agents/Executive/Observations"
    if ref.startswith("@agent/"):
        return f"Agents/Executive/{ref.removeprefix('@agent/')}"
    if ref.startswith("@sat/"):
        _, name, key = ref.split("/", 2)
        labels = {
            "observations": "Observations",
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
    if note and is_folder_article(note):
        return str(Path(note.path).parent)
    return note.path if note else target_ref


def _set_auto_curate_tag(ref: str, doc: dict, enabled: bool) -> None:
    target = _auto_curate_target_path(ref, doc)
    path = target if target.endswith(".md") else folder_article_path(target)
    note = load_note(path)
    meta = dict(note.meta) if note else {"title": doc["title"], "kind": "knowledge"}
    tags = [tag for tag in _tags(meta.get("tags")) if tag != "auto-curate"]
    if tags:
        meta["tags"] = tags
    else:
        meta.pop("tags", None)
    meta["auto_curate"] = enabled
    write_note(path, meta, note.body if note else str(doc.get("body", "")))


def _tool_namespace_catalog():
    tools = [note for note in iter_notes() if note.kind == "tool"]
    res = resolver()
    explicit_children = {
        child.ref
        for parent in tools for raw in parent.children
        if (child := res.resolve(_link_ref(raw))) and child.kind == "tool"
    }
    eligible = {
        note.ref.rsplit("/", 1)[-1]: note
        for note in tools
        if note.ref not in explicit_children and "." in note.ref.rsplit("/", 1)[-1]
    }
    namespaces = {
        ".".join(parent.split(".")[:depth])
        for name in eligible for parent in [callable_namespace(name)]
        for depth in range(1, len(parent.split(".")) + 1)
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
        if callable_namespace(name) == namespace
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


def _virtual_index(ref: str, title: str, summary: str, children, *, kind: str = "knowledge") -> dict:
    unique = {note.ref: note for note in children}
    ordered = sorted(unique.values(), key=lambda note: (note.title.lower(), note.ref.lower()))
    by_ref = {note.ref.lower(): note for note in ordered}
    by_leaf = {note.ref.rsplit("/", 1)[-1].lower(): note for note in ordered}
    child_rows: dict[str, list] = {note.ref: [] for note in ordered}
    parent_of: dict[str, str] = {}

    def resolve_child(raw):
        target = _link_ref(str(raw))
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
    # Navigation needs labels, not complete Reader bodies or checkout closure.
    # Reuse _base_article's subject vocabulary without reparsing every Article
    # for each label on every graph refresh.
    if ref.startswith("@sat/"):
        _, agent, key = ref.split("/", 2)
        subject = SATELLITE_AGENT_SUBJECTS.get(key) or SATELLITE_ROLE_SUBJECTS.get(agent, {}).get(key)
        title = subject[0] if subject else key.capitalize()
    else:
        title = ref.rsplit("/", 1)[-1]
        if ref == "@library/Tools":
            title = "Tools + Skills"
    folder = _auto_curate_target_path(ref, {"ref": ref}) if ref.startswith("@sat/") else None
    authored = _folder_index(folder) if folder else None
    article = _apply_reader_override({"ref": ref, "title": authored.title if authored else title}, overrides)
    return {
        "id": ref,
        "title": str(article["title"]),
        "parent_id": parent_ref,
        **({"path": folder, "article_ref": authored.ref} if authored else {}),
    }


def _scoped_knowledge_subjects(identity: Note | None, notes: list[Note], base: list[dict], overrides: dict) -> list[dict]:
    """Folder proxies follow the same exact Knowledge scope as model reads."""
    from ...knowledge.scope import knowledge_refs
    if identity is None:  # The owner's Library sees all accepted Knowledge.
        selected = [note for note in notes if note.kind == "knowledge"]
    else:
        try:
            allowed = knowledge_refs(identity, Resolver(notes))
        except ValueError:
            allowed = set()
        selected = [note for note in notes if note.ref in allowed]
    folders = set()
    for note in selected:
        parts = Path(note.path).parts[:-1]
        first = (2 if identity is None else 3) if parts and parts[0] == "Agents" else 1
        folders.update("/".join(parts[:depth]) for depth in range(first, len(parts)+1))
    if identity is None:
        folders.update(str(Path(note.path).parent) for note in notes if note.kind == "agent")
    ids = {folder: _executive_folder_ref(folder) for folder in folders}
    subjects = [item for item in base if not item.get("path") and (
        item["id"].rsplit("/", 1)[-1].lower() in {"tools", "skills", "runbooks", "tasks", "other-agents"})]
    for folder in sorted(folders):
        authored = next((note for note in selected if note.path == folder_article_path(folder)), None)
        agent_folder = identity is None and folder.startswith("Agents/") and folder.count("/") == 1
        if agent_folder:
            authored = next((note for note in notes if note.path == folder_article_path(folder)), None)
            if not authored or authored.kind != "agent":
                continue
            ids[folder] = authored.ref
        parent_id = "@library/Agents" if agent_folder else ids.get(str(Path(folder).parent))
        subjects.append({"id": ids[folder], "title": authored.title if authored else folder.rsplit("/",1)[-1],
            "parent_id": parent_id, "path": folder,
            **({"article_ref": authored.ref} if authored else {}), "scope_proxy": authored is None})
    return subjects


def _navigation_manifest(overrides: dict[str, Note]) -> dict:
    """Canonical naming and subject topology for every graph/UI projection."""
    notes = iter_notes()
    by_ref = {note.ref: note for note in notes}
    groups = []
    executive_subjects = [
        ("@branch/Tools", None),
        ("@branch/Skills", None),
        ("@branch/Runbooks", None),
        ("@branch/Tasks", None),
    ]
    for group_id, identity_ref in CHECKOUT_AGENTS.items():
        identity = by_ref.get(identity_ref)
        if not identity:
            continue
        role = str(identity.meta.get("role") or group_id).strip().lower()
        if group_id == "executive":
            subjects = [_navigation_subject(ref, parent, overrides) for ref, parent in executive_subjects]
        else:
            name = identity_ref.split("/")[1]
            subjects = [_navigation_subject(f"@sat/{name}/{key}", None, overrides)
                        for key in ("tools", "skills", "runbooks", "tasks", "other-agents")]
        subjects = _scoped_knowledge_subjects(identity, notes, subjects, overrides)
        if group_id == "executive":
            subjects.append({"id": "@agent/Specialists", "title": "Specialists", "parent_id": None})
        from ...knowledge.scope import readable_refs
        try:
            access_refs = sorted(readable_refs(identity, Resolver(notes)))
        except ValueError:
            access_refs = []
        groups.append({
            "id": group_id,
            "title": identity.title,
            "subtitle": role.replace("-", " ").title(),
            "role": role,
            "root_ref": identity.ref,
            "access_refs": access_refs,
            "subjects": subjects,
        })

    library = _apply_reader_override({"ref": "@library", "title": "Library"}, overrides)
    library_subjects = [
        _navigation_subject(ref, None, overrides)
        for ref in ("@library/Tools", "@library/Tasks", "@library/Runbooks", "@library/Agents")
    ]
    groups.append({
        "id": "library",
        "title": str(library["title"]),
        "subtitle": "Shared assets",
        "role": "library",
        "root_ref": "@library",
        "subjects": _scoped_knowledge_subjects(None, notes, library_subjects, overrides)
                    + [item for item in library_subjects if item["id"] == "@library/Agents"],
    })
    return {"groups": groups}


@asynccontextmanager
async def lifespan(app: FastAPI):
    from ...models import llm
    from ...knowledge.intake import SourceIntake

    async def stop_scheduler(task):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        await scheduler.shutdown()

    async with AsyncExitStack() as resources:
        trace.start(INDEX)
        resources.callback(trace.stop)
        await llm.start_provider_client()
        resources.push_async_callback(llm.close_provider_client)
        from ...memory.hindsight import MEMORY
        await MEMORY.start()
        resources.push_async_callback(MEMORY.close)
        from ...graphs.api import lifespan as graph_views_lifespan
        await resources.enter_async_context(graph_views_lifespan())
        scheduler.reconcile_interrupted_runs()
        source.list_sources()  # attest raw evidence before serving it
        # System facts are a deterministic projection of recorded evidence.
        # Publish before retrieval warming; this creates no model work or Task.
        await asyncio.to_thread(system_knowledge.refresh_system_knowledge, sync=False)
        INDEX.sync()
        await asyncio.to_thread(retrieval.prewarm_fast_context)
        resources.push_async_callback(model_runtime.shutdown)
        model_events = await model_runtime.initialize()
        from ...execution.loops import sessions as executive_sessions
        conversation_log = executive_sessions()
        await conversation_log.start()
        resources.push_async_callback(conversation_log.stop)
        await conversation_log.reconcile(CONVERSATION)
        resources.push_async_callback(shell_scene.SCENE.stop)
        shell_scene.SCENE.start()
        intake = SourceIntake()
        resources.push_async_callback(asyncio.to_thread, intake.stop)
        await asyncio.to_thread(intake.start)
        app.state.shell_scene = shell_scene.SCENE
        resources.push_async_callback(realtime.RUNTIME.shutdown)
        from ...realtime import tracking as camera_tracking
        resources.push_async_callback(asyncio.to_thread, camera_tracking.stop)
        await realtime.RUNTIME.restore()
        await asyncio.to_thread(camera_tracking.restore)
        resources.push_async_callback(conversation_runtime.RUNTIME.cancel)
        task = asyncio.create_task(scheduler.loop())
        resources.push_async_callback(stop_scheduler, task)
        for params in model_events:
            scheduler.enqueue_named_event("model.added", params)
        yield


app = FastAPI(title="Obsidience", lifespan=lifespan)
from ...memory.api import router as memory_router
app.include_router(memory_router)
from ...graphs.api import router as graph_views_router
app.include_router(graph_views_router)

# Workstation browsers visit arbitrary sites. Only non-browser local clients
# (Quickshell, CLI, turn bridges, Hindsight; no Origin) and pages served by
# this Harness may drive it. A loopback Host defeats DNS rebinding; a browser
# Origin or cross-site fetch must belong to this exact origin.
_LOCAL_HOSTS = frozenset(f"{host}:{CONFIG.port}" for host in (CONFIG.host, "127.0.0.1", "localhost"))
_LOCAL_ORIGINS = frozenset("http://" + host for host in _LOCAL_HOSTS)


class LocalClientsOnly:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in {"http", "websocket"}:
            headers = Headers(scope=scope)
            origin = headers.get("origin")
            if (headers.get("host") not in _LOCAL_HOSTS
                    or (origin is not None and origin not in _LOCAL_ORIGINS)
                    or headers.get("sec-fetch-site", "none") not in {"same-origin", "none"}):
                if scope["type"] == "websocket":
                    await send({"type": "websocket.close", "code": 1008})
                else:
                    await PlainTextResponse("Forbidden", status_code=403)(scope, receive, send)
                return
        await self.app(scope, receive, send)


app.add_middleware(CORSMiddleware, allow_origins=sorted(_LOCAL_ORIGINS), allow_methods=["*"], allow_headers=["*"])
app.add_middleware(LocalClientsOnly)


class ShellKnowledgeFiles(StaticFiles):
    """Revalidate the mutable entry page while retaining hashed asset caching."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if path in {".", "", "index.html"} or response.headers.get("content-type", "").startswith("text/html"):
            response.headers["Cache-Control"] = "no-cache"
        return response


app.mount(
    "/shell/knowledge",
    ShellKnowledgeFiles(
        directory=CONFIG.project_root / "obsidience" / "ui" / "out" / "renderer",
        html=True,
        check_dir=False,
    ),
    name="shell-knowledge",
)


@app.get("/api/shell/command-token")
def shell_command_token_for_pages():
    """Give pages served above the Shell credential that browsers cannot read.

    LocalClientsOnly admits only this origin's pages and non-browser local
    clients, which can read the user-only runtime file anyway."""
    try:
        token = shell_command_token.read_token()
    except OSError as exc:
        raise HTTPException(503, "Shell command token unavailable") from exc
    return Response(json.dumps({"token": token}), media_type="application/json",
                    headers={"Cache-Control": "no-store"})


_STATUS_LISTING_TTL_SECONDS = 10.0
_status_listings: tuple[float, dict] | None = None
_status_listings_lock = threading.Lock()


def _status_listing_counts() -> dict:
    """Source and Review listings dominate /api/status; reuse their counts briefly."""
    global _status_listings
    with _status_listings_lock:
        if (_status_listings is None
                or time.monotonic() - _status_listings[0] >= _STATUS_LISTING_TTL_SECONDS):
            source_status = source.list_source_files()
            _status_listings = (time.monotonic(), {
                "proposals_pending": len(review.list_reviews()),
                "sources": len(source_status["files"]),
                "source_issues": len(source_status["issues"]),
                "source_coverage": source_status.get("coverage", {}),
            })
        return dict(_status_listings[1])


@app.get("/api/status")
def status():
    notes = iter_notes()
    tasks = [n for n in notes if n.kind == "task"]
    listings = _status_listing_counts()
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
        "proposals_pending": listings["proposals_pending"],
        "sources": listings["sources"],
        "source_issues": listings["source_issues"],
        "source_coverage": listings["source_coverage"],
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


@app.get("/api/hardware/monitor")
def hardware_monitor():
    """Bounded read-only measurements shared by visible Hardware panes."""
    return monitor.snapshot()


@app.get("/api/system")
def system():
    """Actual host, application, and network inventory behind Source."""
    return inventory.system_snapshot()


@app.get("/api/system/knowledge")
def system_knowledge_status():
    """Read the last System publication without collecting or changing files."""
    return system_knowledge.system_knowledge_status()


@app.post("/api/system/refresh")
def refresh_system_knowledge():
    """Owner refresh of immutable System evidence and its workstation Articles."""
    return system_knowledge.refresh_system_knowledge()


@app.get("/api/input")
def input_state():
    """Live mouse and keyboard state from the compositor adapter."""
    return input_adapter.input_snapshot()


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


@app.get("/api/hardware/camera/tracking")
def camera_tracking_status():
    from ...realtime import tracking
    return tracking.snapshot()


@app.get("/api/hardware/camera/frame")
async def camera_owner_frame():
    """One private, uncached owner preview through the same capture boundary."""
    from ...realtime.camera import CameraCaptureError, capture_selected_camera
    try:
        frame = await capture_selected_camera()
    except CameraCaptureError as error:
        raise HTTPException(503, str(error)) from error
    return Response(frame.image_png, media_type="image/png", headers={
        "Cache-Control": "no-store", "X-Captured-At-Ns": str(frame.captured_at_unix_ns),
        "X-Camera-Recognition": json.dumps(frame.recognition, separators=(",", ":")),
    })


@app.post("/api/hardware/camera/tracking/enroll")
def camera_owner_enroll():
    """Explicit local owner enrollment; never a model-exposed Tool."""
    from ...realtime import tracking
    try:
        return tracking.enroll()
    except ValueError as error:
        raise HTTPException(409, str(error)) from error


@app.get("/api/realtime")
def realtime_status():
    """Return speech transport state, independent of the selected work Task."""

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
        if "mode" in payload:
            return await realtime.RUNTIME.set_listening_mode(payload["mode"])
        return await realtime.RUNTIME.set_proactive(payload.get("proactive"))
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/realtime/stop")
async def realtime_stop():
    return await realtime.RUNTIME.stop()


async def _serve_websocket_events(ws: WebSocket, send_events):
    """Join both halves of a presentation stream on disconnect or cancellation."""
    async def receive_disconnect():
        while True:
            if (await ws.receive())["type"] == "websocket.disconnect":
                return

    tasks = [asyncio.create_task(send_events()), asyncio.create_task(receive_disconnect())]
    try:
        done, _pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            await task
    except (WebSocketDisconnect, asyncio.CancelledError):
        return
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@app.websocket("/ws/realtime")
async def realtime_ws(ws: WebSocket):
    await ws.accept()
    queue = realtime.RUNTIME.subscribe()

    async def send_events():
        await ws.send_json({"type": "state", "state": realtime.RUNTIME.snapshot()})
        while True:
            await ws.send_json(await queue.get())

    try:
        await _serve_websocket_events(ws, send_events)
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


def _graph_article_membership(nodes: list[dict], groups: list[dict]) -> dict[str, list[str]]:
    """One read-only Agent/Library selection for Reader and graph presentation."""
    by_id = {node["id"]: node for node in nodes}
    aliases = {node["article_ref"]: node["id"] for node in nodes if node.get("article_ref")}

    def resolve(raw: str) -> str:
        ref = raw if raw in by_id else _link_ref(raw)
        return aliases.get(ref, ref)

    def primitive_kind(node: dict) -> str | None:
        if "task-taxonomy" in node.get("tags", []):
            return "task"
        return node["kind"] if node["kind"] in CHECKOUT_FIELDS else None

    primitives = {ref: node for ref, node in by_id.items()
                  if primitive_kind(node) and ref not in aliases}
    children = {ref: [child for raw in node.get("children", [])
                      if (child := resolve(raw)) in primitives and child != ref
                      and primitive_kind(primitives[child]) == primitive_kind(node)]
                for ref, node in primitives.items()}
    parent_of = {}
    for parent, refs in children.items():
        for child in refs:
            cursor = parent
            while cursor in parent_of and cursor != child:
                cursor = parent_of[cursor]
            if child not in parent_of and cursor != child:
                parent_of[child] = parent

    def closure(roots: set[str]) -> set[str]:
        selected = roots & primitives.keys()
        # Dependencies already contain the execution closure. Only add display
        # ancestors here; descending from inherited guidance would select siblings.
        for ref in list(selected):
            while ref in parent_of:
                ref = parent_of[ref]
                if ref in selected:
                    break
                selected.add(ref)
        return selected

    memberships = {}
    for group in groups:
        root = group["root_ref"]
        if group["id"] == "library":
            selected = set(by_id)
        else:
            readable = set(group.get("access_refs", []))
            selected = {resolve(ref) for ref in readable if resolve(ref) in by_id}
            selected.update(closure(selected))
        selected.add(root)
        selected.update(subject["id"] for subject in group["subjects"])
        selected.update(by_id[ref]["article_ref"] for ref in list(selected)
                        if ref in by_id and by_id[ref].get("article_ref"))
        memberships[group["id"]] = sorted(selected)
    return memberships


@app.get("/api/graph")
def graph():
    # The indexed graph and its filesystem navigation describe one accepted
    # publication, including a complete multi-Article news edition.
    from ...knowledge.vault import _NOTE_WRITE_LOCK

    with _NOTE_WRITE_LOCK:
        return _graph_snapshot()


def _graph_snapshot():
    doc = INDEX.graph()
    overrides = _reader_overrides()
    navigation = _navigation_manifest(overrides)
    subjects = [subject for group in navigation["groups"] for subject in group["subjects"]]
    folders = {subject["path"]: subject for subject in subjects if subject.get("path")}
    for node in doc["nodes"]:
        override = overrides.get(node["id"])
        if override:
            node["title"] = override.title
        subject = folders.get(str(Path(node["id"]).parent))
        if subject and node["kind"] == "knowledge":
            node["parent_id"] = subject["id"]
            if node["id"] == subject.get("article_ref"):
                node["navigation_ref"] = subject["id"]
    from ...knowledge.auto_curate import enabled
    notes_by_ref = {note.ref: note for note in iter_notes()}
    auto_curated = {ref for ref, note in notes_by_ref.items()
                    if note.kind in {"knowledge", "agent"} and enabled(ref, notes_by_ref)}
    membership = _graph_article_membership(doc["nodes"], navigation["groups"])
    for group in navigation["groups"]:
        group["article_refs"] = membership[group["id"]]
        for subject in group["subjects"]:
            ref = subject["id"]
            target = subject.get("path") or _auto_curate_target_path(ref, {"ref": ref})
            if _auto_curate_supported(ref, {"ref": ref, "kind": "knowledge"}) and enabled(target, notes_by_ref):
                auto_curated.add(ref)
    from ...memory.hindsight import MEMORY
    # Memory has its own native graph view. Accepted Source citations remain
    # readable evidence; a recalled observation is not an accepted wiki Article.
    return {
        **doc,
        "memory": MEMORY.status(),
        "auto_curated": sorted(auto_curated),
        "auto_curate_resolved": True,
        "navigation": navigation,
        "link_proposals": review.link_proposals(list(notes_by_ref.values())),
    }


def _base_article(ref: str):
    """Resolve real notes and graph subject nodes through one Reader path."""
    if ref.startswith("@memory/"):
        from ...memory.hindsight import MEMORY
        doc = MEMORY.article(ref)
        if doc is None:
            raise HTTPException(404, "Hindsight memory record is unavailable")
        return doc
    # Presentation IDs are exact graph nodes. Never let the resolver's useful
    # leaf-title fallback turn @library/.../generate into Runbooks/generate.
    note = None if ref.startswith("@") else load_note(ref + ".md") or resolver().resolve(ref)
    if note:
        if note.kind in {"knowledge", "agent"} and is_folder_article(note):
            return _folder_article(str(Path(note.path).parent), ref)
        return _note_doc(note)

    # Reader is an owner surface. Agent execution uses the separate, mandatory
    # access resolver; the Library must not hide other Agents from its owner.
    notes = list(iter_notes())
    if ref == "@vault":
        identity = load_note("Agents/Executive/Executive.md")
        if identity:
            group = next(item for item in _navigation_manifest(_reader_overrides())["groups"]
                         if item["id"] == "executive")
            doc = _note_doc(identity)
            doc["ref"] = ref
            doc["children"] = [item.get("article_ref") or item["id"] for item in group["subjects"]
                               if item["parent_id"] is None]
            return doc
        return _virtual_index(ref, "Obsidience", "The root Agent Brain Article.", notes, kind="agent")
    if ref == "@library":
        group = next(item for item in _navigation_manifest(_reader_overrides())["groups"]
                     if item["id"] == "library")
        children = [item.get("article_ref") or item["id"] for item in group["subjects"]
                    if item["parent_id"] is None]
        return {"ref": ref, "title": "Library", "kind": "knowledge",
                "meta": {"node": "true", "articles": str(len(notes))},
                "body": "All accepted Knowledge, Agents, Tasks, Runbooks, and paired Tools and Skills. "
                        "Use the Reader's Agent icons to check out shared Knowledge or assign Tasks. "
                        "Each Agent searches only its own checked-out graph and owns its Observations. "
                        "The Library is the owner's complete catalog, not an Agent with global search authority.",
                "children": children}
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
        kind = folder.rstrip("s").lower()
        if kind not in CHECKOUT_FIELDS:
            return _folder_article(folder, ref)
        if kind in CHECKOUT_FIELDS:
            res = resolver()
            identity = res.resolve(CHECKOUT_AGENTS["executive"])
            refs = agent_dependencies(identity, res)[CHECKOUT_FIELDS[kind]] if identity else []
            children = [target for raw in refs
                        if (target := res.resolve(raw)) and target.kind == kind]
        return _virtual_index(ref, folder.rsplit("/", 1)[-1],
                              _branch_index_summary(
                                  folder.rsplit("/", 1)[-1], article_count=len(children)
                              ), children)
    if ref.startswith("@agent/"):
        key = ref.removeprefix("@agent/").strip("/")
        summary = EXECUTIVE_AGENT_SUBJECTS.get(key)
        if not summary:
            raise HTTPException(404, f"executive agent node not found: {ref}")
        if key != "Specialists":
            return _folder_article(f"Agents/Executive/{key}", ref)
        children = [item for item in iter_notes() if item.kind == "agent"
                    and item.ref != CHECKOUT_AGENTS["executive"]]
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
            target_folder = _auto_curate_target_path(ref, {"ref": ref})
            if _folder_index(target_folder):
                return _folder_article(target_folder, ref)
            child_keys = list(SATELLITE_ROLE_CHILDREN.get(agent_name, {}).get(folder_key, []))
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
                            if item.ref.startswith(f"Agents/{agent_name}/Observations/")
                            and item.ref != identity.ref]
            elif agent_name == "Darwin" and folder_key == "sources":
                children = [item for item in iter_notes()
                            if item.ref.startswith("Sources/")
                            and not is_folder_article(item)]
            else:
                children = []
            return _virtual_subject(ref, title, summary, subnodes, children)
        res = resolver()
        refs = agent_dependencies(identity, res)[CHECKOUT_FIELDS[kind]]
        children = [target for raw in refs
                    if (target := res.resolve(raw)) and target.kind == kind]
        return _virtual_index(
            ref, folder,
            f"{agent_name}'s {folder.lower()} supplied by assigned Tasks.",
            children,
        )
    raise HTTPException(404, f"article not found: {ref}")


@app.get("/api/articles/{ref:path}")
def get_article(ref: str, graph_id: str = "", activity: bool = False):
    doc = _get_article(ref, graph_id)
    if activity:
        knowledge_activity.emit_operation("read", "returned", [str(doc["ref"])],
            label="Reading memory" if ref.startswith("@memory/") else "Reading · " + str(doc["title"]),
            graph_id="memory:" + ref.split("/", 2)[1] if ref.startswith("@memory/") else graph_id or "*")
    return doc


def _get_article(ref: str, graph_id: str = ""):
    doc = _article_with_curation(ref, _apply_reader_override(_base_article(ref)))
    snapshot = graph()
    selected_graph = graph_id or "library"
    group = next((item for item in snapshot["navigation"]["groups"] if selected_graph in {
        item["id"], item["root_ref"], item["root_ref"].split("/")[1]
        if "/" in item["root_ref"] else "library", "main" if item["id"] == "executive" else item["id"]}), None)
    if group is None:
        raise HTTPException(404, "Agent graph is unavailable")
    members = set(group["article_refs"])
    subject = next((item for item in group["subjects"] if ref in {item["id"], item.get("article_ref")}), None)
    from ...memory.hindsight import MEMORY
    # Evidence records remain readable in their owner's bank even though they
    # are not nodes in the Article graph. Presentation never grants bank access.
    memory_owned = ref.startswith("@memory/") and MEMORY.owns(ref, group["root_ref"])
    if selected_graph == "library":
        return doc
    if subject and subject.get("scope_proxy"):
        children = [item.get("article_ref") or item["id"] for item in group["subjects"]
                    if item["parent_id"] == subject["id"]]
        children += [node["id"] for node in snapshot["nodes"] if node["id"] in members
                     and node["kind"] == "knowledge" and str(Path(node["id"]).parent) == subject["path"]]
        return {"ref":ref, "title":subject["title"], "kind":"knowledge", "meta":{"scope_proxy":"true"},
                "body":"Navigation for this Agent's checked-out descendants. The unselected parent Article is not supplied to the Agent.",
                "children":sorted(set(children)), "read_only":True, "auto_curate_supported":False}
    if (ref not in members and doc["ref"] not in members and not memory_owned
            and ref != "@vault" and doc.get("kind") != "agent"):
        raise HTTPException(404, "Article is outside this Agent graph; open it from Library")
    return {**doc, "children":[child for child in doc.get("children", []) if child in members]}


@app.put("/api/articles/{ref:path}/auto-curate")
def set_article_auto_curate(ref: str, payload: dict):
    """Owner permission, inherited by children; Task triggers stay independent."""
    enabled = payload.get("enabled")
    if not isinstance(enabled, bool):
        raise HTTPException(400, "enabled must be boolean")
    doc = _apply_reader_override(_base_article(ref))
    if not _auto_curate_supported(ref, doc):
        raise HTTPException(400, "Auto-curate applies to Knowledge branches, not capability definitions or checkouts")
    _set_auto_curate_tag(ref, doc, enabled)
    INDEX.sync()
    knowledge_activity.emit_operation("edit", "completed", [str(doc["ref"])],
        label="Auto-curate enabled" if enabled else "Auto-curate disabled", refresh=True)
    return {"article": ref, "enabled": enabled, "task": None}


@app.patch("/api/articles/{ref:path}")
def update_article(ref: str, payload: dict):
    try:
        return _update_article(ref, payload)
    except HTTPException:
        knowledge_activity.emit_operation("edit", "rejected", [ref], label="Edit rejected")
        raise


def _update_article(ref: str, payload: dict):
    """Direct owner edit for authored Articles and editable navigation nodes."""
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
    if target_ref.startswith("@memory/"):
        raise HTTPException(409, "Hindsight owns this observation; durable changes are Alexandria recommendations")
    try:
        system_knowledge.assert_system_article_writable(target_ref)
    except ValueError as cause:
        raise HTTPException(409, str(cause)) from cause
    note = None if target_ref.startswith("@") else load_note(target_ref + ".md")
    if note:
        if note.runtime_observation:
            raise HTTPException(409, "runtime Observations are lifecycle-owned")
        if note.kind == "task" and str(note.meta.get("status", "draft")) == "running":
            raise HTTPException(409, "cannot edit a running task")
        meta = dict(note.meta)
        meta["title"] = title
        if note.kind == "agent":
            meta["name"] = title
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
    knowledge_activity.emit_operation("edit", "completed", [saved_ref],
        label="Saved · " + title, refresh=True)
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
def source_files(scope: str | None = None, after: str | None = None, limit: int = 2000):
    """Exact physical wiki, code, System, and raw-source paths in one view."""
    try:
        return source.list_source_files(scope=scope, after=after, limit=limit)
    except source.SourceError as cause:
        raise HTTPException(409, str(cause)) from cause


@app.get("/api/source-files/{key:path}")
def read_source_file(key: str, activity: bool = False):
    try:
        record = source.get_source_file(key)
    except source.SourceError as cause:
        raise HTTPException(404, str(cause)) from cause
    if activity and record.get("storage") == "code":
        from ...graphs.api import CODE_PROJECT
        from ...execution.activity import emit_operation
        project = str(CONFIG.extras.get("graphs", {}).get("codebase_project", CODE_PROJECT))
        emit_operation("read", "returned", ["file:" + key], label="Reading source",
                       graph_id="code:" + project)
    return record


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
        if changed:
            knowledge_activity.emit("graph_changed", [identity.ref])
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
    knowledge_activity.emit_operation("edit", "completed", list(result["refs"].values()),
        label="Articles moved", refresh=True)
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
        agent = resolver().resolve(_link_ref(str(note.meta.get("assignee", ""))))
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


def _assignment_row(agent: str, identity: Note, task: Note, res) -> dict:
    selected = _link_values(identity.meta.get("tasks"))
    remaining = [raw for raw in selected
                 if not ((target := res.resolve(raw)) and target.ref == task.ref)]
    direct = len(remaining) != len(selected)
    without_direct = replace(identity, meta={**identity.meta, "tasks": remaining})
    inherited = task.ref in agent_dependencies(without_direct, res)["tasks"]
    return {"agent": agent, "ref": task.ref, "kind": "task",
            "direct": direct, "inherited": inherited}


@app.get("/api/library/assignments")
def library_assignments():
    """Task assignments and their read-only shared Library dependencies."""
    res = dependency_resolver(resolver())
    from ...knowledge.scope import checkout_state, revision
    assignments, dependencies, knowledge, revisions = [], [], [], {}
    for agent, identity_ref in CHECKOUT_AGENTS.items():
        identity = res.resolve(identity_ref)
        if not identity:
            continue
        revisions[agent] = revision(identity)
        try:
            knowledge.extend({**checkout_state(note, identity, res), "agent": agent}
                             for note in res.by_ref.values() if note.kind == "knowledge")
        except ValueError as exc:
            knowledge.append({"agent": agent, "error": str(exc)})
        effective = agent_dependencies(identity, res)
        for kind, field in CHECKOUT_FIELDS.items():
            for ref in effective[field]:
                dependencies.append({"agent": agent, "ref": ref, "kind": kind})
                if kind == "task" and (task := res.resolve(ref)) and task.kind == "task":
                    row = _assignment_row(agent, identity, task, res)
                    if not row["direct"] and not row["inherited"]:
                        row["inherited"] = True  # Parent/descendant Task scope.
                    assignments.append(row)
    return {"assignments": assignments, "dependencies": dependencies,
            "knowledge": knowledge, "revisions": revisions}


def _set_knowledge_assignment(agent: str, identity: Note, note: Note, checked: bool, res) -> dict:
    """Owner mutation of exact Knowledge scope, never a capability grant."""
    from ...knowledge.scope import MAX_CHECKOUTS, checkout_state, revision, _within, _roots
    try:
        before = checkout_state(note, identity, res)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    if not before["editable"]:
        raise HTTPException(400, "Own Articles remain owned; another Agent's Observations cannot be checked out")
    # Toggling a branch is one subtree operation, not a hidden collection of
    # descendant grants that survive unchecking their parent.
    selected = [item for item in _roots(identity, res, "knowledge") if not _within(item, note)]
    excluded = [item for item in _roots(identity, res, "exclude_knowledge") if not _within(item, note)]
    if checked:
        if any(_within(note, item) for item in excluded):
            raise HTTPException(409, "A parent scope is excluded; enable that parent first")
        if not any(_within(note, item) for item in selected):
            selected.append(note)
    elif any(_within(note, item) for item in selected):
        excluded.append(note)
    if max(len(selected), len(excluded)) > MAX_CHECKOUTS:
        raise HTTPException(400, "Knowledge checkout limit reached")
    meta = {**identity.meta, "knowledge": [f"[[{item.ref}]]" for item in selected],
            "exclude_knowledge": [f"[[{item.ref}]]" for item in excluded]}
    changed = meta != identity.meta
    if changed:
        write_note(identity.path, meta, identity.body)
        INDEX.sync()
        knowledge_activity.emit("graph_changed", [identity.ref, note.ref])
    updated = replace(identity, meta=meta)
    return {**checkout_state(note, updated, res), "agent": agent, "assigned": checked,
            "assignment_changed": changed, "revision": revision(updated)}


@app.put("/api/library/assignments/{ref:path}")
def set_library_assignment(ref: str, payload: dict):
    """Assign one accepted Task; its dependencies are never separate grants."""
    agent = str(payload.get("agent") or "").strip().lower()
    if agent not in CHECKOUT_AGENTS:
        raise HTTPException(400, f"unknown agent: {agent or '(empty)'}")
    assigned = payload.get("assigned")
    if not isinstance(assigned, bool):
        raise HTTPException(400, "assigned must be boolean")
    from ...knowledge.vault import _NOTE_WRITE_LOCK
    with _CHECKOUT_LOCK, _NOTE_WRITE_LOCK:
        res = dependency_resolver(resolver())
        identity = res.resolve(CHECKOUT_AGENTS[agent])
        if not identity:
            raise HTTPException(500, "Agent Article missing")
        from ...knowledge.scope import revision
        expected = payload.get("expected_revision")
        if expected is not None and expected != revision(identity):
            raise HTTPException(409, "Agent checkout changed; refresh before assigning")
        task = res.resolve(ref)
        if task and task.kind == "knowledge":
            if expected is None:
                raise HTTPException(409, "Knowledge checkout requires expected_revision")
            return _set_knowledge_assignment(agent, identity, task, assigned, res)
        if not task or task.kind != "task":
            raise HTTPException(400, "Only an accepted Task Article can be assigned")
        identity = res.resolve(CHECKOUT_AGENTS[agent])
        if not identity:
            raise HTTPException(500, f"Agent Article missing: {CHECKOUT_AGENTS[agent]}")
        before = _assignment_row(agent, identity, task, res)
        retained = [raw for raw in _link_values(identity.meta.get("tasks"))
                    if not ((target := res.resolve(raw)) and target.ref == task.ref)]
        if assigned:
            retained.append(f"[[{task.ref}]]")
        meta = dict(identity.meta)
        if retained:
            meta["tasks"] = retained
        else:
            meta.pop("tasks", None)
        changed = before["direct"] != assigned
        if changed:
            write_note(identity.path, meta, identity.body)
        activation = ensure_task_runbook(task, res, agent_ref=identity.ref) if assigned else {}
        if changed:
            INDEX.sync()
            knowledge_activity.emit("graph_changed", [identity.ref, task.ref])
        row = _assignment_row(agent, replace(identity, meta=meta), task, res)
        return {
            **row, "assigned": assigned or row["inherited"],
            "assignment_changed": changed,
            "activated_task": activation.get("generator_task"),
            "activation_state": activation.get("status"),
            "activation_error": activation.get("error"),
        }


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


@app.post("/api/harness/optimizations")
def prepare_executive_optimization(payload: dict):
    """Local owner registration; model Tools cannot author evaluation criteria."""
    from ...execution.optimization import prepare
    try:
        return prepare(payload)
    except (ValueError, KeyError, OSError) as cause:
        raise HTTPException(400, str(cause)) from cause


@app.post("/api/harness/optimizations/{case_id}/run")
def queue_executive_optimization(case_id: str):
    from ...execution.optimization import queue
    try:
        return queue(case_id)
    except (ValueError, KeyError, OSError) as cause:
        raise HTTPException(409, str(cause)) from cause


@app.get("/api/harness/optimizations/{case_id}")
def executive_optimization_status(case_id: str):
    from ...execution.optimization import status
    try:
        return status(case_id)
    except (ValueError, KeyError, OSError) as cause:
        raise HTTPException(404, str(cause)) from cause


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
    # The external developer agent that completed the turn; Codex is the
    # historical default, so existing Codex turn identities are unchanged.
    source = payload.get("source", "codex")
    if source not in {"codex", "claude-code"}:
        raise HTTPException(400, "unsupported completed-turn source")
    turn_id = hashlib.sha256(
        f"{source}\0{thread_id}\0{external_turn_id}".encode()
    ).hexdigest()[:24]
    from ...memory.hindsight import queue_turn_complete

    timestamp = payload.get("timestamp")
    if timestamp is not None:
        from datetime import datetime
        try:
            if not isinstance(timestamp, str) or datetime.fromisoformat(timestamp).tzinfo is None:
                raise ValueError("timezone required")
        except ValueError as cause:
            raise HTTPException(400, "timestamp must be an ISO date with timezone") from cause
    queued = queue_turn_complete(
        "Agents/Executive/Executive",
        user,
        assistant,
        source=source,
        turn_id=turn_id,
        timestamp=timestamp,
    )
    return {
        "accepted": True,
        "queued_tasks": queued,
        "raw_persisted": False,
        "turn_hash": turn_id,
    }


def task_execution_state(note: Note, accepted_resolver: Resolver) -> dict:
    """Present current admission separately from the immutable last attempt."""
    status = str(note.meta.get("status", "draft"))
    issue = current_task_issue(note)
    previous = INDEX.run(str(note.meta.get("last_run") or ""))
    if previous and previous.get("task_ref") != note.ref:
        previous = None
    last_run = ({key: previous.get(key) for key in ("id", "status", "finished", "summary")}
                if previous else None)
    result = {"state": "idle", "reason": "", "last_run": last_run,
              "retry_allowed": False, "retry_blocked_reason": ""}
    if status == "cancelled":
        result["reason"] = str(note.meta.get("summary") or "Cancelled by the owner.")
    elif status in {"running", "review"}:
        result.update(state=status, reason=str(note.meta.get("blocked_reason") or ""))
    elif issue:
        if issue["kind"] == "unresolved_occurrence":
            blocked = scheduler.retry_blocked_reason(note, previous)
        elif issue["kind"] == "scheduled_draft":
            blocked = "Resolve the scheduled Task's draft state before running it."
        else:
            blocked = "Resolve the Task configuration before running it."
        result.update(state="needs_attention", reason=issue["reason"],
                      retry_allowed=not blocked, retry_blocked_reason=blocked)
    elif (status == "pending" or (
        status in {"completed", "failed"} and note.meta.get("schedule")
        and str(note.meta.get("blocked_reason", "")).startswith(scheduler.RESOURCE_WAIT_PREFIX)
    )):
        if scheduler.memory_curation_paused(note):
            result.update(state="waiting", label="Paused: memory curation",
                          reason="The owner paused Hindsight-to-Knowledge curation; this occurrence and its FIFO remain retained.")
        elif not scheduler._realtime_allows(note, accepted_resolver):
            result.update(state="waiting", label="Paused: Realtime" if realtime.RUNTIME.scheduler_paused() else "Paused: foreground",
                          reason="Background work is paused while Realtime or foreground input owns execution.")
        else:
            error = scheduler._resource_error(note, accepted_resolver=accepted_resolver)
            if error:
                result.update(state="waiting", label=("Waiting: GPU memory" if isinstance(
                    error, model_runtime.ModelMemoryUnavailable) else "Waiting: hardware"),
                    reason=scheduler.RESOURCE_WAIT_PREFIX + str(error), resource=error.as_dict())
            else:
                result.update(state="ready", reason="Waiting for its turn in the existing execution queue.")
    return result


@app.get("/api/tasks")
def tasks():
    out = []
    accepted_resolver = resolver(include_system=False)
    for n in accepted_resolver.by_ref.values():
        if n.kind != "task":
            continue
        subtasks = n.meta.get("subtasks") or []
        refs = [_link_ref(str(x)) for x in subtasks] if isinstance(subtasks, list) else []
        excluded = n.meta.get("exclude_subtasks") or []
        excluded_refs = (
            [_link_ref(str(x)) for x in excluded]
            if isinstance(excluded, list) else [_link_ref(str(excluded))]
        )
        try:
            effort = llm.normalize_reasoning_effort(n.meta.get("reasoning_effort"))
        except ValueError:
            effort = llm.normalize_reasoning_effort(None)
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
                    "assignee": assignee_ref,
                    "runbook": _link_ref(str(n.meta.get("runbook", ""))),
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
                    "last_run": n.meta.get("last_run"),
                    "execution": task_execution_state(n, accepted_resolver)})
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
    readiness = ensure_task_runbook(load_note(task.path), resolver())
    INDEX.sync()
    knowledge_activity.emit_operation("edit", "completed", [task.ref], label="Task queued", refresh=True)
    return {"task": task.ref, "state": state, "status": meta["status"],
            "dependencies": readiness}


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
    knowledge_activity.emit_operation("edit", "completed", [note.ref], label="Task reasoning saved", refresh=True)
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
    readiness = ensure_task_runbook(load_note(note.path), resolver())
    INDEX.sync()
    knowledge_activity.emit_operation("edit", "completed", [note.ref, agent.ref], label="Task assignment saved", refresh=True)
    return {"task": note.ref, "assignee": assignee, "dependencies": readiness}


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
    knowledge_activity.emit_operation("edit", "completed", [note.ref], label="Task model saved", refresh=True)
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
    knowledge_activity.emit_operation("edit", "completed", [note.ref], label="Task exclusions saved", refresh=True)
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
    readiness = ensure_task_runbook(load_note(note.path), resolver())
    INDEX.sync()
    knowledge_activity.emit_operation("edit", "completed", [note.ref], label="Task saved", refresh=True)
    return {"task": note.ref, "updated": True, "dependencies": readiness}


@app.post("/api/tasks/{ref:path}/cancel")
async def cancel_occurrences(ref: str, payload: dict | None = None):
    """Owner cancellation of a Task's unresolved head and waiting occurrences."""
    note = load_note(ref + ".md") or resolver(include_system=False).resolve(ref)
    if not note or note.kind != "task" or note.ref.startswith(("_", ".")):
        raise HTTPException(404, f"task not found: {ref}")
    payload = payload or {}
    reason, expected, event = payload.get("reason"), payload.get("expected_last_run"), payload.get("event")
    if set(payload) - {"reason", "expected_last_run", "event"}:
        raise HTTPException(400, "only reason, expected_last_run and event are accepted")
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 500:
        raise HTTPException(400, "reason is required and limited to 500 characters")
    if not isinstance(expected, str) or not expected:
        raise HTTPException(400, "expected_last_run must name the Task's current last run")
    if event is not None and (not isinstance(event, str) or not event):
        raise HTTPException(400, "event must be an exact event name")
    try:
        return scheduler.cancel_task_occurrences(note, reason=reason, expected_last_run=expected, event=event)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/tasks/{ref:path}/run")
async def run_now(ref: str, payload: dict | None = None):
    note = load_note(ref + ".md") or resolver(include_system=False).resolve(ref)
    if (not note or note.kind != "task" or note.ref.startswith(("_", "."))
            or note.meta.get("article_status") == "deprecated"):
        raise HTTPException(404, f"task not found: {ref}")
    if str(note.meta.get("status", "draft")) == "running":
        raise HTTPException(409, "task is already running")
    if "retry_run_id" in (payload or {}):
        expected = (payload or {}).get("retry_run_id")
        if not isinstance(expected, str) or not expected:
            raise HTTPException(400, "retry_run_id must name the exact previous attempt")
        if any(key in (payload or {}) for key in ("params", "model")):
            raise HTTPException(400, "retry preserves the occurrence inputs and Task model")
        try:
            return scheduler.retry_failed_occurrence(note, expected)
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(409, str(exc)) from exc
    if str(note.meta.get("status", "draft")) == "review":
        raise HTTPException(409, "resolve the pending Review before running this Task")
    stored = note.meta.get("params")
    if str(note.meta.get("status", "")) in {"failed", "blocked"} and isinstance(stored, dict) and (
        stored.get("activation_key") or stored.get("event")
    ):
        raise HTTPException(409, "retry must name the exact failed attempt; its inputs and waiting queue are retained")
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
    from ...capabilities.task.complete import validate_computer_outcome

    stored_params = note.meta.get("params")
    preserve_pending = str(note.meta.get("status", "")) == "pending" and "params" not in (payload or {})
    expected_key = (payload or {}).get("expected_activation_key")
    if expected_key is not None:
        if not isinstance(expected_key, str) or not expected_key:
            raise HTTPException(400, "expected_activation_key must identify the pending occurrence")
        if (not preserve_pending or not isinstance(stored_params, dict)
                or expected_key != stored_params.get("activation_key")):
            raise HTTPException(409, "pending occurrence changed; refresh its activation key")
    bound_params = {**(stored_params if isinstance(stored_params, dict) else {}), **runtime_params}
    outcome_error = validate_computer_outcome(
        bound_params.get("computer_outcome"), bound_params.get("computer_scope"),
    )
    if outcome_error:
        raise HTTPException(400, outcome_error)
    try:
        scheduler.launch(
            note,
            owner_requested=True,
            reasoning_effort=effort,
            model=model,
            runtime_params=None if preserve_pending else runtime_params,
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
    raw_cursor = ws.query_params.get("after")
    if raw_cursor is not None and (not raw_cursor.isascii() or not raw_cursor.isdecimal() or len(raw_cursor) > 16):
        await ws.close(code=1008, reason="Invalid trace cursor")
        return
    after = int(raw_cursor) if raw_cursor is not None else None
    queue = trace.subscribe()

    async def send_events():
        frame = trace.replay(after)
        cursor = frame["cursor"]
        await ws.send_json(frame)
        while True:
            entry = await queue.get()
            sequence = entry.get("seq")
            if sequence is not None and sequence <= cursor:
                continue
            if sequence is not None and sequence != cursor + 1:
                frame = trace.replay(cursor)
                await ws.send_json(frame)
                cursor = frame["cursor"]
            else:
                await ws.send_json({"type": "entry", "entry": entry, "cursor": sequence or cursor})
                cursor = sequence or cursor

    try:
        await _serve_websocket_events(ws, send_events)
    finally:
        trace.unsubscribe(queue)


@app.websocket("/ws/activity")
async def knowledge_activity_ws(ws: WebSocket):
    """Every Task activation, independent of how the Task was started."""
    await ws.accept()
    queue = knowledge_activity.subscribe()

    async def send_events():
        await ws.send_json({"type": "snapshot", "entries": knowledge_activity.history(),
                            "playback": knowledge_activity.playback(),
                            "operations": knowledge_activity.operations()})
        while True:
            await ws.send_json({"type": "activity", **await queue.get()})

    try:
        await _serve_websocket_events(ws, send_events)
    finally:
        knowledge_activity.unsubscribe(queue)


@app.get("/api/reviews")
def reviews():
    with _REVIEW_LOCK:
        return review.list_reviews()


@app.post("/api/reviews/{name}/acknowledge")
def acknowledge_review(name: str):
    try:
        with _REVIEW_LOCK:
            return review.acknowledge_notification(name)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


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


@app.websocket("/ws/chat")
async def chat_ws(ws: WebSocket):
    """Project the one persisted Executive conversation into every Chat pane."""
    await ws.accept()
    queue = CONVERSATION.subscribe()
    queue.put_nowait(conversation_runtime.RUNTIME.active_turn())

    async def send_events() -> None:
        # Deliver the conversation immediately, even if tokenization is cold.
        while not queue.empty():
            await ws.send_json(queue.get_nowait())
        queue.put_nowait(await conversation_runtime.RUNTIME.context_status())
        while True:
            await ws.send_json(await queue.get())

    async def receive_requests() -> None:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(msg, dict):
                continue
            if msg.get("type") == "steer":
                try:
                    result = await conversation_runtime.RUNTIME.steer(
                        str(msg.get("text", "")), expected_turn_id=str(msg.get("expected_turn_id", "")),
                    )
                    queue.put_nowait({"type": "steering", **result})
                except (ValueError, RuntimeError) as exc:
                    queue.put_nowait({"type": "error", "text": str(exc)[:512]})
                continue
            if msg.get("type") == "new_conversation":
                try:
                    await conversation_runtime.RUNTIME.new_conversation(
                        defer=realtime.RUNTIME.scheduler_paused(),
                    )
                except (ValueError, RuntimeError) as exc:
                    queue.put_nowait({"type": "error", "text": str(exc)[:512]})
                continue
            if msg.get("type") == "set_compact_threshold":
                try:
                    await conversation_runtime.RUNTIME.set_context_threshold(msg.get("percent"))
                except (ValueError, RuntimeError) as exc:
                    queue.put_nowait({"type": "error", "text": str(exc)[:512]})
                continue
            if msg.get("type") == "compact":
                try:
                    await conversation_runtime.RUNTIME.compact_conversation(force=True, wait=False)
                except (ValueError, RuntimeError) as exc:
                    queue.put_nowait({"type": "error", "text": str(exc)[:512]})
                continue
            text = str(msg.get("text", "")).strip()
            if not text:
                continue
            try:
                await conversation_runtime.RUNTIME.submit(
                    text, source="text", wait=False,
                    memory_writeback=msg.get("memory_writeback") is not False)
            except (ValueError, RuntimeError) as exc:
                queue.put_nowait({"type": "error", "text": str(exc)[:512]})

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

    class HarnessServer(uvicorn.Server):
        def handle_exit(self, sig, frame):
            # Uvicorn drains connections before exiting the lifespan. Disarm
            # admission now so that drain cannot start another scheduled run.
            scheduler.stop_admission()
            super().handle_exit(sig, frame)

    # The native projection keeps trace/activity WebSockets open for its
    # lifetime. Development restarts must cancel those stale subscribers after
    # a short drain instead of waiting forever for the old renderer connection.
    HarnessServer(uvicorn.Config(
        app,
        host=CONFIG.host,
        port=CONFIG.port,
        log_level="warning",
        timeout_graceful_shutdown=5,
    )).run()


if __name__ == "__main__":
    main()

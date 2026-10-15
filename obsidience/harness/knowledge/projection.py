"""Reader and graph projection of accepted Articles.

Navigation subjects, generated Library/Agent indexes, Reader overrides and the
graph snapshot are a presentation of the Vault: they own no knowledge, grant no
capability and never replace the Article writer. The Task taxonomy here is only
displayed; its exclusion and taxonomy_path semantics belong to dependencies.py.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from ..config import CONFIG
from . import review, system as system_knowledge
from .dependencies import agent_dependencies
from .index import INDEX, callable_namespace, namespace_title
from .links import metadata_ref
from .tasks import (
    TASK_TAXONOMY_BY_PATH,
    TASK_TAXONOMY_NODES,
    descendant_count as task_taxonomy_descendant_count,
    node_id as task_taxonomy_node_id,
)
from .vault import (
    NOTE_WRITE_LOCK,
    Note, Resolver,
    folder_article_path,
    is_folder_article,
    iter_notes,
    load_note,
    resolver,
    slugify,
    write_note,
)


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

EXECUTIVE_AGENT_SUBJECTS = {
    "Architecture": "How the executive is wired into Obsidience and the local workstation.",
    "Specialists": "The named specialist agents coordinated by the executive.",
    "Observations": "Distilled notes about the executive, its preferences, and its own runs.",
}
SATELLITE_AGENT_SUBJECTS = {
    "other-agents": ("Other Agents", "The executive and sibling agents: who they are and what they do."),
}


class NotFound(LookupError):
    """No Article, generated subject or Agent graph has this identity."""


def note_doc(note):
    return {"ref": note.ref, "title": note.title, "kind": note.kind,
            "meta": {k: str(v) for k, v in note.meta.items()}, "body": note.body,
            "children": [metadata_ref(str(child)) for child in note.children]}


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
        return {**note_doc(hub), "children": [
            *(child_ref for child_ref, _label in subnodes),
            *(note.ref for note in children),
        ]}
    doc = _virtual_subject(ref, folder.rsplit("/", 1)[-1],
                           _branch_index_summary(folder.rsplit("/", 1)[-1], child_folders,
                                                 len(descendants)), subnodes, children)
    return doc


def reader_override_path(ref: str) -> str:
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


def apply_reader_override(doc: dict, overrides: dict[str, Note] | None = None) -> dict:
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


def _auto_curate_state(request_ref: str, doc: dict) -> tuple[bool, str | None]:
    from .curation import policy_for, selection

    if doc.get("managed_by") == "hindsight":
        # Native memory consolidation is automatic. It does not grant wiki
        # publication permission to the containing Knowledge branch.
        return doc.get("auto_curate") is True, None
    if not auto_curate_supported(request_ref, doc):
        return False, None
    policy = policy_for(_auto_curate_target_path(request_ref, doc))
    return selection(policy) is True, None


def article_with_curation(request_ref: str, doc: dict) -> dict:
    enabled, task_ref = _auto_curate_state(request_ref, doc)
    system_managed = system_knowledge.is_system_article(str(doc.get("ref", request_ref)))
    return {**doc, "auto_curate": enabled, "auto_curate_task": task_ref,
            "auto_curate_supported": auto_curate_supported(request_ref, doc),
            **({"read_only": True, "managed_by": "system"} if system_managed else {})}


def auto_curate_supported(ref: str, doc: dict) -> bool:
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


def set_auto_curate_tag(ref: str, doc: dict, enabled: bool) -> None:
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
        if (child := res.resolve(metadata_ref(raw))) and child.kind == "tool"
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


def _virtual_index(ref: str, title: str, summary: str, children, *, kind: str = "knowledge") -> dict:
    unique = {note.ref: note for note in children}
    ordered = sorted(unique.values(), key=lambda note: (note.title.lower(), note.ref.lower()))
    by_ref = {note.ref.lower(): note for note in ordered}
    by_leaf = {note.ref.rsplit("/", 1)[-1].lower(): note for note in ordered}
    child_rows: dict[str, list] = {note.ref: [] for note in ordered}
    parent_of: dict[str, str] = {}

    def resolve_child(raw):
        target = metadata_ref(str(raw))
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
    # Reuse base_article's subject vocabulary without reparsing every Article
    # for each label on every graph refresh.
    if ref.startswith("@sat/"):
        key = ref.split("/", 2)[2]
        subject = SATELLITE_AGENT_SUBJECTS.get(key)
        title = subject[0] if subject else key.capitalize()
    else:
        title = ref.rsplit("/", 1)[-1]
        if ref == "@library/Tools":
            title = "Tools + Skills"
    folder = _auto_curate_target_path(ref, {"ref": ref}) if ref.startswith("@sat/") else None
    authored = _folder_index(folder) if folder else None
    article = apply_reader_override({"ref": ref, "title": authored.title if authored else title}, overrides)
    return {
        "id": ref,
        "title": str(article["title"]),
        "parent_id": parent_ref,
        **({"path": folder, "article_ref": authored.ref} if authored else {}),
    }


def _scoped_knowledge_subjects(identity: Note | None, notes: list[Note], base: list[dict], overrides: dict) -> list[dict]:
    """Folder proxies follow the same exact Knowledge scope as model reads."""
    from .scope import knowledge_refs
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
        from .scope import readable_refs
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

    library = apply_reader_override({"ref": "@library", "title": "Library"}, overrides)
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


def _graph_article_membership(nodes: list[dict], groups: list[dict]) -> dict[str, list[str]]:
    """One read-only Agent/Library selection for Reader and graph presentation."""
    by_id = {node["id"]: node for node in nodes}
    aliases = {node["article_ref"]: node["id"] for node in nodes if node.get("article_ref")}

    def resolve(raw: str) -> str:
        ref = raw if raw in by_id else metadata_ref(raw)
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


def graph():
    # The indexed graph and its filesystem navigation describe one accepted
    # publication, including a complete multi-Article news edition.
    with NOTE_WRITE_LOCK:
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
    from .curation import enabled
    notes_by_ref = {note.ref: note for note in iter_notes()}
    auto_curated = {ref for ref, note in notes_by_ref.items()
                    if note.kind in {"knowledge", "agent"} and enabled(ref, notes_by_ref)}
    membership = _graph_article_membership(doc["nodes"], navigation["groups"])
    for group in navigation["groups"]:
        group["article_refs"] = membership[group["id"]]
        for subject in group["subjects"]:
            ref = subject["id"]
            target = subject.get("path") or _auto_curate_target_path(ref, {"ref": ref})
            if auto_curate_supported(ref, {"ref": ref, "kind": "knowledge"}) and enabled(target, notes_by_ref):
                auto_curated.add(ref)
    from ..memory.hindsight import MEMORY
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


def base_article(ref: str):
    """Resolve real notes and graph subject nodes through one Reader path."""
    if ref.startswith("@memory/"):
        from ..memory.hindsight import MEMORY
        doc = MEMORY.article(ref)
        if doc is None:
            raise NotFound("Hindsight memory record is unavailable")
        return doc
    # Presentation IDs are exact graph nodes. Never let the resolver's useful
    # leaf-title fallback turn @library/.../generate into Runbooks/generate.
    note = None if ref.startswith("@") else load_note(ref + ".md") or resolver().resolve(ref)
    if note:
        if note.kind in {"knowledge", "agent"} and is_folder_article(note):
            return _folder_article(str(Path(note.path).parent), ref)
        return note_doc(note)

    # Reader is an owner surface. Agent execution uses the separate, mandatory
    # access resolver; the Library must not hide other Agents from its owner.
    notes = list(iter_notes())
    if ref == "@vault":
        identity = load_note("Agents/Executive/Executive.md")
        if identity:
            group = next(item for item in _navigation_manifest(_reader_overrides())["groups"]
                         if item["id"] == "executive")
            doc = note_doc(identity)
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
                raise NotFound(f"tool namespace not found: {namespace}")
            return _tool_namespace_article(ref, namespace)
        if relative == "Tasks":
            return _task_taxonomy_article(ref)
        if relative.startswith("Tasks/"):
            path = relative.removeprefix("Tasks/")
            if path not in TASK_TAXONOMY_BY_PATH:
                raise NotFound(f"task taxonomy node not found: {path}")
            return _task_taxonomy_article(ref, path)
        folder = relative
        kind = folder.rstrip("s").lower()
        if kind not in LIBRARY_KINDS:
            raise NotFound(f"library node not found: {ref}")
        authored = _folder_index(folder)
        if authored:
            return note_doc(authored)
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
            raise NotFound(f"executive agent node not found: {ref}")
        if key != "Specialists":
            return _folder_article(f"Agents/Executive/{key}", ref)
        children = [item for item in iter_notes() if item.kind == "agent"
                    and item.ref != CHECKOUT_AGENTS["executive"]]
        return _virtual_subject(ref, key, summary, children=children)
    if ref.startswith("@sat/"):
        parts = ref.split("/")
        if len(parts) != 3:
            raise NotFound(f"agent node not found: {ref}")
        _, agent_name, folder_key = parts
        folder = folder_key.capitalize()
        kind = folder.rstrip("s").lower()
        identity = resolver().resolve(f"Agents/{agent_name}/{agent_name}")
        if not identity:
            raise NotFound(f"agent not found: {agent_name}")
        if kind not in CHECKOUT_FIELDS:
            subject = SATELLITE_AGENT_SUBJECTS.get(folder_key)
            if not subject:
                raise NotFound(f"agent node not found: {ref}")
            title, summary = subject
            target_folder = _auto_curate_target_path(ref, {"ref": ref})
            if _folder_index(target_folder):
                return _folder_article(target_folder, ref)
            children = [item for item in iter_notes()
                        if item.kind == "agent" and item.ref != identity.ref]
            executive = resolver().resolve("Agents/Executive/Executive")
            if executive:
                children.append(executive)
            return _virtual_subject(ref, title, summary, children=children)
        res = resolver()
        refs = agent_dependencies(identity, res)[CHECKOUT_FIELDS[kind]]
        children = [target for raw in refs
                    if (target := res.resolve(raw)) and target.kind == kind]
        return _virtual_index(
            ref, folder,
            f"{agent_name}'s {folder.lower()} supplied by assigned Tasks.",
            children,
        )
    raise NotFound(f"article not found: {ref}")


def agent_article(ref: str, graph_id: str = ""):
    """One Reader Article as the selected Agent graph (default: Library) presents it."""
    doc = article_with_curation(ref, apply_reader_override(base_article(ref)))
    snapshot = graph()
    selected_graph = graph_id or "library"
    group = next((item for item in snapshot["navigation"]["groups"] if selected_graph in {
        item["id"], item["root_ref"], item["root_ref"].split("/")[1]
        if "/" in item["root_ref"] else "library", "main" if item["id"] == "executive" else item["id"]}), None)
    if group is None:
        raise NotFound("Agent graph is unavailable")
    members = set(group["article_refs"])
    subject = next((item for item in group["subjects"] if ref in {item["id"], item.get("article_ref")}), None)
    from ..memory.hindsight import MEMORY
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
        raise NotFound("Article is outside this Agent graph; open it from Library")
    return {**doc, "children":[child for child in doc.get("children", []) if child in members]}

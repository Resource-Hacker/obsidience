"""Generated Skill articles that mirror the callable Tool hierarchy.

Tools say what can be called. These read-only Skill mirrors say how to use that
one callable and surface its one canonical authored Skill. A Skill is never a
general procedure: it is the exact operating contract paired to one Tool.
"""

from __future__ import annotations

from dataclasses import dataclass

from .vault import Note, Resolver


def _values(value) -> list[str]:
    if not value:
        return []
    return [str(item) for item in (value if isinstance(value, list) else [value])]


@dataclass(frozen=True)
class SkillMirrorNode:
    path: str
    title: str
    children: tuple[str, ...]
    tool_ref: str | None = None
    source_skills: tuple[str, ...] = ()


def namespace_title(segment: str) -> str:
    """Human title for a generated namespace index; callable leaves stay exact."""
    return segment[:1].upper() + segment[1:]


def callable_namespace(name: str) -> str:
    """Library grouping, independent of the callable's exact stable identity."""
    namespace = name.rsplit(".", 1)[0]
    # Observation operations are direct peers; Temporary describes their
    # target data, not another level of executable work or guidance.
    return "observations" if namespace == "observations.temporary" else namespace


def build_skill_mirror(notes: list[Note]) -> tuple[SkillMirrorNode, ...]:
    """Project one Skill leaf per callable Tool under its Library group."""
    tools = [note for note in notes if note.kind == "tool"]
    skills = [note for note in notes if note.kind == "skill"]
    resolver = Resolver(notes)
    explicit_children = {
        child.ref
        for parent in tools for raw in parent.children
        if (child := resolver.resolve(raw)) and child.kind == "tool"
    }
    eligible = {
        note.ref.rsplit("/", 1)[-1]: note
        for note in tools
        if note.ref not in explicit_children and "." in note.ref.rsplit("/", 1)[-1]
    }
    parents = {name: callable_namespace(name).replace(".", "/") for name in eligible}
    namespaces = sorted({
        "/".join(parent.split("/")[:depth])
        for parent in parents.values() for depth in range(1, len(parent.split("/")) + 1)
    })
    namespace_set = set(namespaces)

    guidance: dict[str, list[str]] = {note.ref: [] for note in eligible.values()}
    for skill in skills:
        for raw in _values(skill.meta.get("tool")):
            target = resolver.resolve(raw)
            if target and target.ref in guidance and skill.ref not in guidance[target.ref]:
                guidance[target.ref].append(skill.ref)

    nodes: list[SkillMirrorNode] = []
    for namespace in namespaces:
        depth = len(namespace.split("/"))
        child_namespaces = sorted(
            child for child in namespace_set
            if child.startswith(namespace + "/") and len(child.split("/")) == depth + 1
        )
        child_leaves = sorted(
            "/".join(name.split(".")) for name in eligible
            if parents[name] == namespace
        )
        nodes.append(SkillMirrorNode(
            path=namespace,
            title=namespace_title(namespace.rsplit("/", 1)[-1]),
            children=tuple((*child_namespaces, *child_leaves)),
        ))

    for name, tool in sorted(eligible.items()):
        path = "/".join(name.split("."))
        nodes.append(SkillMirrorNode(
            path=path,
            title=name.rsplit(".", 1)[-1],
            children=(),
            tool_ref=tool.ref,
            source_skills=tuple(sorted(guidance[tool.ref])),
        ))
    return tuple(nodes)


def node_id(path: str) -> str:
    return f"@library/Skills/{path}"


def descendant_count(path: str, nodes: tuple[SkillMirrorNode, ...]) -> int:
    prefix = path + "/"
    return sum(1 for node in nodes if node.path.startswith(prefix))

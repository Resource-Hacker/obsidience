"""Owner-defined Task article tree projected into the knowledge graph.

``index`` is never a semantic kind.  A Task Article with children is an index
because it has children; a terminal Task Article is a leaf.  The top-level
Wiki, Research, Executive, and Harness Articles are Knowledge Articles
that describe and organize their Task descendants without becoming runnable
work themselves. Generate remains an outcome family. Historical memory is Hindsight-owned;
conversation compaction is a native DeepSeek backend operation.
"""

from __future__ import annotations

from dataclasses import dataclass


Tree = dict[str, "Tree"]


def _leaves(*names: str) -> Tree:
    return {name: {} for name in names}


TASK_TAXONOMY: Tree = {
    # Live conversation is Agent-owned; Query remains independently queueable.
    "executive": _leaves("query"),
    # The wiki loop exposes only outcome-bearing operations. Collection,
    # extraction, copyediting, classification, and contradiction checks are
    # procedural Runbook steps rather than fake independently
    # scheduled Tasks or an empty Lint coordinator. Wiki outcomes remain peers.
    # Curate may activate Merge or Link, but that causal edge does not
    # alter either Task's authored hierarchy.
    "wiki": {
        "ingest": {},
        "curate": {},
        "merge": {},
        "link": {},
        "improve": {},
        "archive": {},
    },
    # Framing, discovery, collection, screening, assessment, extraction,
    # analysis, and verification are the Research Runbook's procedure. The
    # Task tree keeps distinct research outcomes. Model operation belongs
    # to Heimdall alongside Harness/Agent Audit and Repair.
    "research": _leaves("question", "learn"),
    "harness": _leaves("audit", "repair", "model"),
    "generate": _leaves("tool", "skill", "task", "runbook"),
}

TASK_TRIGGERS = {
    "wiki/curate": ("observations.memory.ready",),
    "wiki/ingest": ("source.inbox",),
    "harness/repair": ("harness.degraded",),
    "research/question": ("task.create",),
    "research/learn": ("source.added", "task.create"),
    "harness/model": ("model.added",),
    "generate/runbook": ("task.assigned",),
}

TASK_KNOWLEDGE_PATHS = frozenset({
    "wiki",
    "research",
    "executive",
    "harness",
})

TASK_SUMMARIES = {
    "executive": (
        "Typed Chat and speech use the Executive Agent directly; specialist Query remains separately queueable."
    ),
    "executive/query": "Answer a question through an assigned specialist's applicable Runbook; Executive Chat and voice use Executive directly.",
    "wiki": (
        "The graph-native wiki Tasks: Ingest, Curate, Merge, Link, "
        "Improve, and Archive."
    ),
    "wiki/ingest": (
        "Alexandria transforms one source-backed handoff from the physical Source Inbox into coherent wiki Knowledge."
    ),
    "wiki/curate": (
        "Alexandria curates new Hindsight observations or one bounded wiki-maintenance snapshot, using existing peer Tasks and Review for durable recommendations."
    ),
    "wiki/merge": (
        "Alexandria confirms and consolidates one exact duplicate candidate without losing unique knowledge or relationships."
    ),
    "wiki/link": (
        "Alexandria confirms and adds one missing, meaningful relationship between exact Knowledge Articles."
    ),
    "wiki/improve": (
        "Alexandria improves one bounded Article from accepted evidence and validates the revision."
    ),
    "wiki/archive": (
        "Alexandria proposes one explicitly deprecated or demonstrably superseded Knowledge Article for reviewed archival."
    ),
    "harness": "Heimdall maintains the Harness and Agents through Audit, Repair and Model characterization.",
    "harness/audit": (
        "Heimdall audits Harness and Agent execution, definitions and capability wiring, preserving exact evidence."
    ),
    "harness/repair": (
        "Heimdall applies supported recovery to current harness findings and reports verified disposition and remaining blockers."
    ),
    "research": "Darwin's evidence-producing outcomes: Question and Learn.",
    "research/question": (
        "Darwin answers one bounded research question with preserved direct-source evidence."
    ),
    "research/learn": (
        "Darwin closes one useful knowledge gap or researches one newly added Source, then drops a source-backed handoff into the physical Source Inbox."
    ),
    "harness/model": (
        "Heimdall characterizes one added local model across its valid hardware layouts and preserves the results."
    ),
    "generate": (
        "Darwin synthesizes quality shared Tools, paired Skills, Tasks, and agent-specific Runbooks "
        "after the relevant research is complete."
    ),
}

TASK_TITLES = {}


# Existing persisted Tasks absorb their closest semantic Task Article.
# Knowledge roots remain navigation-only while descendant Tasks stay checkoutable.
CANONICAL_TASK_BY_PATH = {
    "executive/query": "Tasks/query",
    "wiki/ingest": "Tasks/ingest",
    "wiki/curate": "Tasks/curate",
    "wiki/merge": "Tasks/merge",
    "wiki/link": "Tasks/link",
    "wiki/improve": "Tasks/improve",
    "wiki/archive": "Tasks/archive",
    "harness/audit": "Tasks/audit",
    "harness/repair": "Tasks/repair",
    "research/question": "Tasks/research/question",
    "research/learn": "Tasks/research/learn",
    "harness/model": "Tasks/research/model",
    "generate/runbook": "Tasks/generate/runbook",
    "generate/tool": "Tasks/generate/tool",
    "generate/skill": "Tasks/generate/skill",
    "generate/task": "Tasks/generate/task",
}


@dataclass(frozen=True)
class TaskTaxonomyNode:
    path: str
    title: str
    kind: str
    children: tuple[str, ...]
    triggers: tuple[str, ...] = ()
    routing: str | None = None
    summary: str | None = None


def _flatten(tree: Tree, parent: str = "") -> tuple[TaskTaxonomyNode, ...]:
    rows: list[TaskTaxonomyNode] = []
    for segment, children in tree.items():
        path = f"{parent}/{segment}" if parent else segment
        rows.append(TaskTaxonomyNode(
            path=path,
            title=TASK_TITLES.get(path, segment.title()),
            kind="knowledge" if path in TASK_KNOWLEDGE_PATHS else "task",
            children=tuple(f"{path}/{child}" for child in children),
            triggers=TASK_TRIGGERS.get(path, ()),
            summary=TASK_SUMMARIES.get(path),
        ))
        rows.extend(_flatten(children, path))
    return tuple(rows)


TASK_TAXONOMY_NODES = _flatten(TASK_TAXONOMY)
TASK_TAXONOMY_BY_PATH = {node.path: node for node in TASK_TAXONOMY_NODES}


def node_id(path: str, known_refs: set[str]) -> str:
    canonical = CANONICAL_TASK_BY_PATH.get(path)
    return canonical if canonical in known_refs else f"@library/Tasks/{path}"


def child_ids(path: str, known_refs: set[str]) -> list[str]:
    return [node_id(child, known_refs) for child in TASK_TAXONOMY_BY_PATH[path].children]


def canonical_members(path: str, known_refs: set[str]) -> list[str]:
    prefix = path + "/"
    return sorted({
        ref for member_path, ref in CANONICAL_TASK_BY_PATH.items()
        if ref in known_refs and (member_path == path or member_path.startswith(prefix))
    })


def descendant_count(path: str) -> int:
    prefix = path + "/"
    return sum(1 for node in TASK_TAXONOMY_NODES if node.path.startswith(prefix))


def task_triggers(meta: dict) -> tuple[str, ...]:
    """Return a Task's ordered event triggers from the canonical list."""
    raw = meta.get("triggers")
    values = list(raw) if isinstance(raw, list) else [raw] if raw else []
    return tuple(dict.fromkeys(
        normalized
        for value in values
        if (normalized := str(value).strip())
    ))

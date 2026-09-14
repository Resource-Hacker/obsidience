"""Owner-defined Task article tree projected into the knowledge graph.

``index`` is never a semantic kind.  A Task Article with children is an index
because it has children; a terminal Task Article is a leaf.  The top-level
Wiki, Research, Executive, and Observations Articles are Knowledge Articles
that describe and organize their Task descendants without becoming runnable
work themselves. Generate remains an outcome family; Observations exposes
only the two real context-lifecycle transition Tasks.
"""

from __future__ import annotations

from dataclasses import dataclass


Tree = dict[str, "Tree"]


def _leaves(*names: str) -> Tree:
    return {name: {} for name in names}


TASK_TAXONOMY: Tree = {
    # The outcome family exposes its two runnable transitions as direct peers.
    "observations": _leaves("compact", "promote"),
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
        "audit": {},
        "check": {},
        "repair": {},
    },
    # Framing, discovery, collection, screening, assessment, extraction,
    # analysis, and verification are the Research Runbook's procedure. The
    # Task tree keeps only distinct evidence-producing outcomes. Model is a
    # real queueable hardware-characterization result, not a procedural stage.
    "research": _leaves("question", "learn", "distill", "model"),
    "generate": _leaves("tool", "skill", "task", "runbook"),
}

TASK_TRIGGERS = {
    "observations/promote": ("observations.temporary.ready",),
    "wiki/ingest": ("source.inbox",),
    "wiki/repair": ("harness.degraded",),
    "research/question": ("task.create",),
    "research/learn": ("source.added", "task.create"),
    "research/distill": ("source.added",),
    "research/model": ("model.added",),
    "generate/runbook": ("task.assigned",),
}

TASK_KNOWLEDGE_PATHS = frozenset({
    "observations",
    "wiki",
    "research",
    "executive",
})

TASK_SUMMARIES = {
    "observations": (
        "The Executive memory lifecycle: raw Immediate Observations are compacted into cumulative Temporary Observations, then selected material is proposed into the ordinary reviewed knowledge graph."
    ),
    "observations/compact": "Condense the completed Immediate Observations prefix into one cumulative Temporary Observation.",
    "observations/promote": "Alexandria archives one closed session's Temporary Observations in Source and stages only justified durable Knowledge changes.",
    "executive": (
        "The owner's interactive work through one Executive Task and standing Runbook, shared by typed Chat and speech."
    ),
    "executive/query": "Answer a question through an assigned specialist's applicable Runbook; Executive Chat and voice use Executive directly.",
    "wiki": (
        "The graph-native wiki Tasks: Ingest, Curate, Merge, Link, "
        "Improve, Archive, Audit, Check, and Repair."
    ),
    "wiki/ingest": (
        "Alexandria transforms one source-backed handoff from the physical Source Inbox into coherent wiki Knowledge."
    ),
    "wiki/curate": (
        "Alexandria inspects one bounded maintenance snapshot and activates at most one exact accepted peer Task required by the Curate Runbook."
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
        "Alexandria proposes one stale, superseded Knowledge Article for independently reviewed archival."
    ),
    "wiki/audit": (
        "Heimdall audits one bounded evidence or graph-integrity question and stages at most one grounded finding."
    ),
    "wiki/check": (
        "Heimdall checks one deterministic harness snapshot and reports the observed state."
    ),
    "wiki/repair": (
        "Heimdall applies supported recovery to current harness findings and reports verified disposition and remaining blockers."
    ),
    "research": "The four evidence-producing outcomes owned by Darwin: Question, Learn, Distill, and Model.",
    "research/question": (
        "Darwin answers one bounded research question with preserved direct-source evidence."
    ),
    "research/learn": (
        "Darwin closes one useful knowledge gap or researches one newly added Source, then drops a source-backed handoff into the physical Source Inbox."
    ),
    "research/distill": (
        "Darwin distills one captured Feed item into a source-cited handoff for its configured Feed destination."
    ),
    "research/model": (
        "Darwin characterizes one added local model across its valid hardware layouts and preserves the results."
    ),
    "generate": (
        "Darwin synthesizes quality shared Tools, paired Skills, Tasks, and agent-specific Runbooks "
        "after the relevant research is complete."
    ),
}

TASK_TITLES = {
    # Stable stored identity; one user-facing label across graph, Reader, and Tasks.
}


# Existing persisted Tasks absorb their closest semantic Task Article.
# Knowledge roots remain navigation-only while descendant Tasks stay checkoutable.
CANONICAL_TASK_BY_PATH = {
    "executive/query": "Tasks/query",
    "observations/compact": "Tasks/observations/immediate/compact",
    "observations/promote": "Tasks/observations/durable/promote",
    "wiki/ingest": "Tasks/ingest",
    "wiki/curate": "Tasks/curate",
    "wiki/merge": "Tasks/merge",
    "wiki/link": "Tasks/link",
    "wiki/improve": "Tasks/improve",
    "wiki/archive": "Tasks/archive",
    "wiki/audit": "Tasks/audit",
    "wiki/check": "Tasks/check",
    "wiki/repair": "Tasks/repair",
    "research/question": "Tasks/research/question",
    "research/learn": "Tasks/research/learn",
    "research/distill": "Tasks/research/distill",
    "research/model": "Tasks/research/model",
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

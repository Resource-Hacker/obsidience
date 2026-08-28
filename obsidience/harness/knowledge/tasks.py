"""Owner-defined Task article tree projected into the knowledge graph.

``index`` is never a semantic kind.  A Task Article with children is an index
because it has children; a terminal Task Article is a leaf.  The top-level
Wiki and Research Articles are Knowledge Articles that describe and organize
their Task descendants without becoming runnable work themselves. Observations,
Executive and Generate remain Tasks because each names a completable outcome
family whose descendants define that work. Observations is Knowledge: its
children describe the context lifecycle and expose only the two real
transition Tasks.
"""

from __future__ import annotations

from dataclasses import dataclass


Tree = dict[str, "Tree"]


def _leaves(*names: str) -> Tree:
    return {name: {} for name in names}


TASK_TAXONOMY: Tree = {
    # Each level is an Article that condenses the one below it. Immediate is
    # the raw context window, Temporary is its cumulative compaction layer,
    # and Durable is the ordinary accepted knowledge graph. Only transitions
    # with bounded outcomes are Tasks.
    "observations": {
        "immediate": _leaves("compact"),
        "temporary": {},
        "durable": _leaves("promote"),
    },
    # Executive outcomes stay shallow. Computer Use absorbs the stable
    # ``operate`` identity; observe, act, and launch remain Tool/Skill details.
    "executive": _leaves(
        "realtime", "respond", "operate", "recall", "delegate", "plan", "schedule", "monitor"
    ),
    # The wiki loop exposes only outcome-bearing operations. Collection,
    # extraction, copyediting, classification, and contradiction checks are
    # procedural Runbook steps rather than fake independently
    # scheduled Tasks or an empty Lint coordinator. Wiki outcomes remain peers.
    # Curate may activate Merge or Link, but that causal edge does not
    # alter either Task's authored hierarchy.
    "wiki": {
        "ingest": {},
        "query": {},
        "curate": {},
        "merge": {},
        "link": {},
        "improve": {},
        "archive": {},
        "audit": {},
        "check": {},
    },
    # Framing, discovery, collection, screening, assessment, extraction,
    # analysis, and verification are the Research Runbook's procedure. The
    # Task tree keeps only distinct evidence-producing outcomes. Model is a
    # real queueable hardware-characterization result, not a procedural stage.
    "research": _leaves("question", "learn", "news", "model"),
    "generate": _leaves("tool", "skill", "task", "runbook"),
}

TASK_TRIGGERS = {
    "executive": ("voice.activation",),
    "observations/durable/promote": ("observations.temporary.ready",),
    "wiki/ingest": ("source.inbox",),
    "research/learn": ("source.added",),
    "research/model": ("model.added",),
    "generate/runbook": ("task.checkout",),
}

TASK_ROUTING = {
    "executive": "adaptive",
}

TASK_KNOWLEDGE_PATHS = frozenset({
    "observations",
    "observations/immediate",
    "observations/temporary",
    "observations/durable",
    "wiki",
    "research",
})

TASK_SUMMARIES = {
    "observations": (
        "The Executive memory lifecycle: raw Immediate Observations are compacted into cumulative Temporary Observations, then selected material is proposed into the ordinary reviewed knowledge graph."
    ),
    "observations/immediate": "The Executive's raw active context window: the latest cumulative summary plus exact completed dialogue after it.",
    "observations/immediate/compact": "Condense the completed Immediate Observations prefix into one cumulative Temporary Observation.",
    "observations/temporary": "The bounded sequence of cumulative, transient, unverified compaction summaries for closed and active Executive context.",
    "observations/durable": "The ordinary accepted knowledge graph after owner-reviewed promotion; it is not a separate memory store.",
    "observations/durable/promote": "Alexandria archives one closed session's Temporary Observations in Source and stages only justified durable Knowledge changes.",
    "executive": (
        "The voice-activated Task family owned by Executive. "
        "It selects the relevant child task families automatically for each request."
    ),
    "executive/respond": "Deliver the concise, verified owner-facing result or clarification.",
    "executive/realtime": (
        "Maintain one low-latency interruptible Executive session with direct Tool steps and explicit peer-Task delegation."
    ),
    "executive/operate": "Produce and verify one requested computer effect through checked-out executable Tools.",
    "executive/recall": "Retrieve accepted graph knowledge needed for the current request.",
    "executive/delegate": "Assign one bounded outcome to the appropriate specialist agent.",
    "executive/plan": "Produce one bounded plan with explicit outcome and acceptance conditions.",
    "executive/schedule": "Attach or revise one Task activation schedule.",
    "executive/monitor": "Observe one active or recurring Task against its expected outcome.",
    "wiki": (
        "The graph-native wiki Tasks: Ingest, Query, Curate, Merge, Link, "
        "Improve, Archive, Audit, and Check."
    ),
    "wiki/ingest": (
        "Alexandria transforms one source-backed handoff from the physical Source Inbox into coherent wiki Knowledge."
    ),
    "wiki/query": "Executive answers the owner from the current graph and activation packet.",
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
    "research": "The four evidence-producing outcomes owned by Darwin: Question, Learn, News, and Model.",
    "research/question": (
        "Darwin answers one bounded research question with preserved direct-source evidence."
    ),
    "research/learn": (
        "Darwin closes one useful knowledge gap or researches one newly added Source, then drops a source-backed handoff into the physical Source Inbox."
    ),
    "research/news": (
        "Darwin produces one bounded current-events finding from unique direct article sources."
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
    "executive/operate": "Computer Use",
}


# Existing persisted Tasks absorb their closest semantic Task Article.
# Knowledge roots remain navigation-only while descendant Tasks stay checkoutable.
CANONICAL_TASK_BY_PATH = {
    "executive/realtime": "Tasks/executive/realtime",
    "observations/immediate/compact": "Tasks/observations/immediate/compact",
    "observations/durable/promote": "Tasks/observations/durable/promote",
    "executive/operate": "Tasks/executive/operate",
    "wiki/ingest": "Tasks/ingest",
    "wiki/query": "Tasks/query",
    "wiki/curate": "Tasks/curate",
    "wiki/merge": "Tasks/merge",
    "wiki/link": "Tasks/link",
    "wiki/improve": "Tasks/improve",
    "wiki/archive": "Tasks/archive",
    "wiki/audit": "Tasks/audit",
    "wiki/check": "Tasks/check",
    "research/question": "Tasks/research/question",
    "research/learn": "Tasks/research/learn",
    "research/news": "Tasks/research/news",
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
            routing=TASK_ROUTING.get(path),
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

"""Owner-defined Task taxonomy projected as stateless Library index articles.

The taxonomy is presentation and placement, not executable control flow. Real
Task notes may occupy a matching leaf; their authored ``subtasks`` remain the
only edges the interpreter dispatches.
"""

from __future__ import annotations

from dataclasses import dataclass


Tree = dict[str, "Tree"]


def _leaves(*names: str) -> Tree:
    return {name: {} for name in names}


TASK_TAXONOMY: Tree = {
    "wiki": {
        "ingest": _leaves("collect", "extract", "normalize", "resolve", "index", "stage"),
        "curate": {
            "compose": _leaves("create", "expand", "summarize", "translate"),
            "edit": _leaves("copy", "clarify", "condense", "neutralize", "restructure"),
            "evidence": _leaves("source", "cite", "verify", "update"),
            "graph": _leaves("link", "classify", "dedupe", "merge", "split", "redirect"),
            "integrity": {
                "links": _leaves("detect", "validate", "repair"),
                "claims": _leaves("detect", "verify", "repair"),
                "conflicts": _leaves("detect", "compare", "resolve"),
                "schema": _leaves("validate", "migrate"),
            },
            "lifecycle": _leaves("rename", "supersede", "archive", "restore"),
        },
        # The detailed Guardian hierarchy supersedes the shorter guard sketch.
        "guard": {
            "review": {
                "intake": _leaves("manifest", "identity", "scope", "risk"),
                "inspect": _leaves("intent", "diff", "content", "evidence", "graph", "policy"),
                "verify": _leaves(
                    "claims", "citations", "provenance", "links", "schema", "index", "retrieval", "tests"
                ),
                "decide": _leaves("approve", "return", "reject", "hold", "escalate"),
                "attest": _leaves("sign", "record", "release"),
            },
            "audit": {
                "jobs": _leaves("completion", "outputs", "effects", "compliance"),
                "articles": _leaves("quality", "freshness", "evidence", "consistency", "history"),
                "graph": _leaves("orphans", "duplicates", "conflicts", "integrity", "drift"),
                "index": _leaves("coverage", "freshness", "summaries", "retrieval"),
                "agents": _leaves("behavior", "errors", "drift", "authority"),
            },
            "monitor": {
                "jobs": _leaves("failures", "stalls", "retries"),
                "wiki": _leaves("changes", "staleness", "degradation"),
                "agents": _leaves("behavior", "failures"),
                "risks": _leaves("detect", "classify", "alert"),
            },
            "moderate": {
                "protect": _leaves("apply", "release"),
                "quarantine": _leaves("apply", "release"),
                "lifecycle": _leaves("archive", "restore", "supersede", "purge"),
                "disputes": _leaves("open", "adjudicate", "escalate"),
            },
            "recover": _leaves("revert", "rollback", "restore", "rebuild", "reindex"),
        },
    },
    "research": {
        "frame": _leaves("question", "scope", "criteria", "hypotheses", "plan"),
        "discover": {
            "web": _leaves("search", "browse"),
            "literature": _leaves("search", "backward", "forward"),
            "graph": _leaves("search", "expand"),
            "files": _leaves("search", "inspect"),
            "gaps": _leaves("detect"),
        },
        "collect": {
            "sources": _leaves("fetch", "preserve", "normalize", "dedupe"),
            "data": _leaves("acquire", "clean", "sample"),
            "metadata": _leaves("extract", "enrich"),
        },
        "screen": _leaves("relevance", "eligibility", "quality", "duplicates"),
        "assess": {
            "sources": _leaves("authority", "independence", "recency", "bias", "reliability"),
            "evidence": _leaves("relevance", "strength", "consistency", "sufficiency"),
        },
        "extract": _leaves(
            "claims", "evidence", "entities", "relations", "methods", "results", "assumptions", "limitations"
        ),
        "analyze": _leaves(
            "compare", "synthesize", "quantify", "classify", "contradictions", "gaps", "causes", "trends",
            "uncertainty",
        ),
        "verify": _leaves("claims", "citations", "provenance", "quotations", "calculations", "reproduction"),
        "produce": _leaves("answer", "brief", "report", "review", "dossier", "bibliography", "dataset"),
        "monitor": _leaves("topic", "query", "source", "claim", "changes"),
    },
}


# Existing executable tasks occupy their closest semantic taxonomy leaf. This
# is a Library projection only; the notes keep their stable refs and runtime
# history, and Tasks/wiki keeps its authored operational subtask list.
CANONICAL_TASK_BY_PATH = {
    "wiki": "Tasks/wiki",
    "wiki/ingest/stage": "Tasks/ingest",
    "wiki/curate/compose/expand": "Tasks/improve",
    "wiki/curate/edit/copy": "Tasks/copyedit",
    "wiki/curate/graph/classify": "Tasks/categorize-notes",
    "wiki/guard/review/verify/links": "Tasks/validate-links",
    "wiki/guard/audit/graph/conflicts": "Tasks/contradictions",
}


@dataclass(frozen=True)
class TaskTaxonomyNode:
    path: str
    title: str
    children: tuple[str, ...]


def _flatten(tree: Tree, parent: str = "") -> tuple[TaskTaxonomyNode, ...]:
    rows: list[TaskTaxonomyNode] = []
    for title, children in tree.items():
        path = f"{parent}/{title}" if parent else title
        rows.append(TaskTaxonomyNode(
            path=path,
            title=title,
            children=tuple(f"{path}/{child}" for child in children),
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

"""Frozen Runbook cases for AutoSaddler, kept in the evaluation-artifact store."""

from __future__ import annotations

import json
from dataclasses import asdict

from ...config import CONFIG
from ...knowledge import format as article_format
from ...knowledge.index import INDEX
from ...knowledge.vault import Note, Resolver, resolver
from .. import revision
from . import store


def _code_revision() -> str:
    return store.sha256(store.canonical_json({name: store.sha256((revision.ROOT / name).read_bytes())
                                              for name in revision.REFINEMENT}).encode())


def model_contract(task: Note, agent_ref: str, *, session: bool = False) -> dict:
    """``session``: the model answering optimizer sessions, which may be a cloud CLI."""
    from ...models import llm, runtime
    resolve = runtime.resolve_session_model if session else runtime.resolve_model
    spec = resolve(task.meta.get("model"), agent_ref)
    return {"spec": json.loads(json.dumps(asdict(spec), default=str)),
            "profile": runtime._read_settings()["models"].get(spec.id, {}),
            "reasoning_effort": llm.normalize_reasoning_effort(task.meta.get("reasoning_effort")),
            "temperature": CONFIG.llm_temperature, "executor_max_steps": CONFIG.max_steps}


def frozen_notes(document: dict) -> list[Note]:
    out = []
    for ref, raw in document["articles"].items():
        meta, body = article_format.loads(raw)
        out.append(Note(ref + ".md", str(meta.get("title") or ref.rsplit("/", 1)[-1]), meta, body))
    return out


def prepare_case(specification: dict) -> dict:
    """Developer-owned fixture registration; no model-authored expectations.

    Freeze exact accepted dependencies and a real originating execution. This
    is an explicit reconstruction, never a claim that clipped trace is replay.
    """
    from .evaluation import validate_suite
    from ..executor import resolve_spine
    validate_suite(specification["suite"])
    required = {"schema_version", "task", "runbook", "origin_run_id", "problem", "suite"}
    if set(specification) != required or specification["schema_version"] != 1:
        raise ValueError("Invalid case specification fields")
    if not isinstance(specification["problem"], str) or not 1 <= len(specification["problem"]) <= 2000:
        raise ValueError("Case requires a bounded problem statement")
    res = resolver()
    task = res.resolve(specification["task"])
    if task is None or task.kind != "task" or task.ref != specification["task"]:
        raise ValueError("Case requires one exact accepted Task")
    spine = resolve_spine(task, res)
    books = spine.get("runbooks", [])
    if "error" in spine or len(books) != 1 or books[0].ref != specification["runbook"] or books[0].children:
        raise ValueError("Case requires one applicable leaf Runbook")
    agent = res.resolve(str(task.meta.get("assignee", "")))
    if agent is None or agent.kind != "agent":
        raise ValueError("Case Task requires one accepted Agent")
    origin = INDEX.run(str(specification["origin_run_id"]))
    if not origin or origin.get("task_ref") != task.ref or origin.get("status") not in {"failed", "blocked", "completed"}:
        raise ValueError("Case requires a real terminal execution of its exact Task")
    if origin.get("runbook_ref") != books[0].ref:
        raise ValueError("Origin execution must identify the subject Runbook")
    selected = [agent, task, *books, *spine["skills"], *spine["tool_articles"]]
    articles = {note.ref: (CONFIG.vault_dir / note.path).read_text() for note in selected}
    allowed = {tool.title for tool in spine["tool_articles"]} | {"task.complete"}
    for case in specification["suite"]["cases"]:
        named = {response["tool"] for response in case["responses"]} | set(case["expected"]["required_tools"])
        if named - allowed:
            raise ValueError("Fixture names Tools outside the accepted Task authority")
    document = {**specification, "agent": agent.ref, "articles": articles,
                "base_sha256": store.sha256(articles[books[0].ref].encode()),
                "model_contract": model_contract(task, agent.ref),
                "evaluator_revision": _code_revision(),
                "origin": {key: origin.get(key) for key in (
                    "id", "task_ref", "runbook_ref", "runbook_sha256", "status", "summary")},
                "evidence_scope": "Explicit regression reconstruction from a recorded execution; not complete historical replay."}
    identity = store.save("cases", document)
    return {"case_id": identity, "task": task.ref, "runbook": books[0].ref,
            "source_path": str((store.root() / "cases" / (identity + ".json")).relative_to(CONFIG.project_root))}


def current_case(case_id: str) -> dict:
    document = store.load("cases", case_id)
    from .evaluation import validate_suite
    validate_suite(document["suite"])
    for ref, raw in document["articles"].items():
        if (CONFIG.vault_dir / (ref + ".md")).read_text() != raw:
            raise ValueError(f"Frozen Article changed: {ref}; prepare a fresh case")
    notes = Resolver(frozen_notes(document))
    from ..executor import resolve_spine
    current = resolver()
    current_task = current.resolve(document["task"])
    current_spine = resolve_spine(current_task, current)
    frozen_spine = resolve_spine(notes.resolve(document["task"]), notes)
    def identities(spine):
        return {key: [note.ref for note in spine.get(key, [])]
                for key in ("runbooks", "skills", "tool_articles")}
    if "error" in current_spine or identities(current_spine) != identities(frozen_spine):
        raise ValueError("Current Task dependency selection changed after case preparation")
    if model_contract(notes.resolve(document["task"]), document["agent"]) != document["model_contract"]:
        raise ValueError("Task model configuration changed after case preparation")
    if _code_revision() != document["evaluator_revision"]:
        raise ValueError("Evaluator implementation changed; prepare a fresh case")
    return document

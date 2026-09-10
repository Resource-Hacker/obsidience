"""Source-triggered Learn cannot substitute unrelated ambient desktop context."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace as NS

import pytest

from obsidience.harness.capabilities.source import handoff, read
from obsidience.harness.capabilities.task import complete
from obsidience.harness.execution import executor
from obsidience.harness.knowledge import source
from obsidience.harness.knowledge.vault import Note, Resolver
from obsidience.tests.test_execution_cancellation import execution  # noqa: F401

SOURCE_ID = "a2d726f3-39e9-4164-b347-954cb885a788"
CITATION = "source://" + SOURCE_ID
OTHER = "source://f95a9235-fd6a-47fc-87e0-4284087e9774"


@pytest.fixture
def capture(monkeypatch):
    content = json.dumps({"title": "Police investigate donations", "summary": "A reported inquiry.",
                          "reporting_url": "https://example.com/report"})
    document = {"citation": CITATION, "content": content, "source_type": "document",
                "captured_at": "2026-09-09T16:11:34Z", "source_ref": "feed://opaque/item",
                "content_sha256": "sha256:" + hashlib.sha256(content.encode()).hexdigest()}
    params = {"event": "source.added", "activation_key": "source.added:" + SOURCE_ID,
              "source_id": SOURCE_ID, "source_citation": CITATION,
              "source_sha256": document["content_sha256"], "source_ref": document["source_ref"]}
    ctx = {"task": "Tasks/research/learn", "agent": "Darwin", "event": "source.added",
           "run_id": "isolated-research", "params": params,
           "task_note": NS(ref="Tasks/research/learn", kind="task", meta={"auto_done": True})}
    calls = []

    def get(value):
        calls.append(value)
        if value in (CITATION, SOURCE_ID):
            return document
        if value == OTHER:
            return {**document, "citation": OTHER}
        raise source.SourceError("Source unavailable")

    monkeypatch.setattr(source, "get_source", get)
    return NS(document=document, params=params, ctx=ctx, calls=calls)


def test_compiled_source_objective_omits_unrelated_scene_and_observations(capture, monkeypatch):
    agent = Note("Agents/Darwin/Darwin.md", "Darwin", {"kind": "agent"}, "Researcher")
    task = Note("Tasks/research/learn.md", "Learn", {"kind": "task"}, "Read the activating Source first.")
    book = Note("Runbooks/research/learn.md", "Learn procedure", {"kind": "runbook"}, "Exact procedure")
    accepted = Resolver([agent, task, book])
    monkeypatch.setattr(executor.shell_scene, "SCENE", NS(activation_binding=lambda: pytest.fail("read unrelated desktop")))
    from obsidience.harness.conversation import observations
    monkeypatch.setattr(observations, "read_temporary_observations", lambda *_: pytest.fail("read unrelated observations"))
    monkeypatch.setattr(source, "article_refs_for_trees", lambda *_: [])
    queries = []
    monkeypatch.setattr(executor.retrieval, "fast_context_with_refs",
                        lambda query, *_args, **_kwargs: (queries.append(query) or "", []))
    params = {**capture.params, "request": "Stale research topic"}
    result = asyncio.run(executor.compile_activation(task, agent=agent,
        spine={"runbooks": [book], "skills": []}, params=params,
        accepted_resolver=accepted, emit_activity=False))
    assert CITATION in result["objective"] and queries == [result["objective"]]
    assert result["bindings"]["event"] == "source.added"
    assert result["bindings"]["required_source"]["content_sha256"] == capture.document["content_sha256"]
    assert "shell_scene" not in result["bindings"]
    assert "Stale research topic" not in result["provider_user"]
    assert CITATION not in result["provider_system"]  # input stays after fixed instructions
    assert not capture.calls  # compiler does not perform an invisible source.read


@pytest.mark.parametrize("field,value", [
    ("source_id", "invalid"), ("source_citation", OTHER), ("source_sha256", "fake"),
    ("activation_key", "source.added:other"), ("source_id", None),
])
def test_malformed_activation_fails_closed_and_still_allows_failure(capture, field, value):
    capture.params[field] = value
    task = NS(ref="Tasks/research/learn", title="Learn")
    with pytest.raises(source.SourceError):
        executor.build_activation_binding(task, [], capture.params)
    assert read.precondition_error("web.search", {}, capture.ctx)
    assert read.precondition_error("task.complete", {"status": "failed"}, capture.ctx) is None
    assert complete.execute({"status": "failed", "summary": "Source binding invalid."}, capture.ctx)["accepted"]
    assert not complete.execute({"status": "completed", "summary": "Done."}, capture.ctx)["accepted"]


@pytest.mark.parametrize("name,args", [
    ("web.fetch", {"url": "https://example.com/unrelated"}),
    ("web.search", {"query": "Unrelated topic"}),
    ("vault.search", {"query": "Unrelated topic"}),
    ("source.handoff", {}), ("task.complete", {"status": "completed"}),
    ("source.read", {"source": OTHER}), ("source.read", {"source": {}}),
    ("source.read", {"sources": [CITATION, OTHER]}),
])
def test_unread_source_blocks_independent_work(capture, name, args):
    assert "Read the complete activating Source first" in read.precondition_error(name, args, capture.ctx)
    assert not capture.calls


def test_paged_and_single_item_batch_reads_unlock_only_complete_matching_bytes(capture):
    assert "Next offset: 12" in read.execute({"sources": [CITATION], "limit": 12}, capture.ctx)
    assert read.bound_read_error(capture.ctx)
    assert "End of Source" in read.execute({"source": SOURCE_ID, "offset": 12}, capture.ctx)
    assert read.bound_read_error(capture.ctx) is None
    assert read.precondition_error("web.fetch", {}, capture.ctx) is None
    assert "End of Source" in read.execute({"sources": [CITATION, OTHER]}, capture.ctx)


def test_wrong_hash_or_other_run_receipt_cannot_unlock_source(capture):
    read.execute({"source": CITATION}, capture.ctx)
    next_ctx = {key: value for key, value in capture.ctx.items() if key != "_source_reads"}
    assert read.bound_read_error(next_ctx)
    capture.ctx["_source_reads"][CITATION]["content_sha256"] = "sha256:" + "a" * 64
    assert read.bound_read_error(capture.ctx)
    read.execute({"source": CITATION}, capture.ctx)
    assert read.bound_read_error(capture.ctx) is None
    capture.ctx["_source_reads"][CITATION]["ranges"] = [[0, 12], [13, len(capture.document["content"])]]
    assert read.bound_read_error(capture.ctx)


def test_failed_or_cancelled_reads_do_not_leave_success_receipts(capture, monkeypatch):
    import threading

    read.execute({"source": CITATION}, capture.ctx)
    cancelled = threading.Event()
    cancelled.set()
    capture.ctx["_capability_cancel_event"] = cancelled
    assert "cancelled" in read.execute({"source": SOURCE_ID}, capture.ctx)
    assert read.bound_read_error(capture.ctx)
    cancelled.clear()
    read.execute({"source": CITATION}, capture.ctx)
    monkeypatch.setattr(source, "get_source", lambda _: (_ for _ in ()).throw(source.SourceError("missing")))
    assert "unavailable" in read.execute({"source": SOURCE_ID}, capture.ctx)
    assert read.bound_read_error(capture.ctx)


def test_handoff_requires_actual_read_and_citation_before_any_inbox_write(capture, monkeypatch):
    writes = []
    monkeypatch.setattr(source, "handoff_source", lambda **kwargs: writes.append(kwargs) or {
        "id": "inbox", "path": "inbox/research.md", "citation": "source://inbox",
        "content_sha256": "hash", "created": True})
    args = {"title": "Finding", "content": "A finding from " + CITATION}
    assert "rejected" in handoff.execute(args, capture.ctx) and not writes
    read.execute({"source": CITATION}, capture.ctx)
    assert "must cite its exact activating Source" in handoff.execute({**args, "content": "Other " + OTHER}, capture.ctx)
    assert not writes
    assert "Research dropped" in handoff.execute(args, capture.ctx)
    assert writes == [{"title": "Finding", "content": args["content"],
                       "research_task": "Tasks/research/learn", "research_run_id": "isolated-research"}]
    assert capture.ctx["handoff_source_id"] == "inbox"
    assert complete.execute({"status": "completed", "summary": "Handoff delivered."}, capture.ctx)["accepted"]


def test_no_change_needs_complete_source_read_and_exact_source_evidence(capture):
    args = {"status": "completed", "summary": "No useful gap.", "outcome": "no_change", "evidence": [CITATION]}
    assert not complete.execute(args, capture.ctx)["accepted"]
    read.execute({"source": CITATION}, capture.ctx)
    assert not complete.execute({**args, "evidence": [OTHER]}, capture.ctx)["accepted"]
    assert complete.execute(args, capture.ctx)["accepted"]


def test_task_create_research_keeps_current_objective_and_tools(capture):
    capture.params["event"] = capture.ctx["event"] = "task.create"
    capture.params["request"] = "Research the requested question"
    task = NS(ref="Tasks/research/learn", title="Learn")
    assert executor.build_activation_binding(task, [], capture.params).objective == capture.params["request"]
    assert read.precondition_error("web.search", {}, capture.ctx) is None


@pytest.mark.parametrize("evidence", [CITATION + "-different", CITATION + "0", "prefix" + CITATION,
                                      "source://malformed", CITATION + " and source://malformed"])
def test_no_change_rejects_malformed_source_citations(capture, evidence):
    read.execute({"source": CITATION}, capture.ctx)
    result = complete.execute({"status": "completed", "summary": "No gap.",
                               "outcome": "no_change", "evidence": [evidence]}, capture.ctx)
    assert not result["accepted"] and "evidence is invalid" in result["error"]


def test_executor_rejects_hallucinated_fetch_then_reads_exact_source(execution, capture, monkeypatch):
    execution.task.ref = "Tasks/research/learn"
    execution.task.title = "Learn"
    execution.task.meta["params"] = deepcopy(capture.params)
    execution.tools.extend(["web.fetch", "source.read"])
    actions = iter([
        {"tool": "web.fetch", "args": {"url": "https://example.com/unrelated"}},
        {"tool": "source.read", "args": {"source": CITATION}},
        {"tool": "web.fetch", "args": {"url": "https://example.com/report"}},
        {"tool": "task.complete", "args": {"status": "failed", "summary": "Bounded fixture end."}},
    ])

    async def response(*_args, **_kwargs):
        return NS(content=json.dumps(next(actions)), prompt_tokens=100)

    def dispatch(name, args, ctx):
        execution.calls.append((name, args))
        if name == "source.read":
            return read.execute(args, ctx)
        if name == "task.complete":
            return complete.execute(args, ctx)
        return "Reporting source fetched."

    monkeypatch.setattr(executor.llm, "chat", response)
    monkeypatch.setattr(executor, "execute_capability", dispatch)
    result = asyncio.run(execution.run(interactive=False, runtime_params=None))
    assert result["status"] == "failed"
    assert [name for name, _args in execution.calls] == ["source.read", "web.fetch", "task.complete"]
    rows = json.loads(execution.records[0]["trace"])
    refused = next(row for row in rows if row.get("not_dispatched"))
    assert refused["tool"] == "web.fetch" and "activating Source" in refused["obs"]

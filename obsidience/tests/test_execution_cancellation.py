from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace as NS

import pytest

from obsidience.harness.execution import executor


@pytest.fixture
def execution(monkeypatch):
    """Real executor, with no live model, Tool, retrieval, status or ledger writes."""
    task = NS(ref="Tasks/query", title="Query", kind="task", meta={})
    agent = NS(ref="Agents/Executive/Executive", title="Executive", kind="agent", meta={}, body="Isolated role")
    book = NS(ref="Runbooks/query", title="Query procedure")
    model = NS(id="isolated", label="Isolated", context_tokens=10000, max_output_tokens=1000)
    state = NS(task=task, events=[], records=[], calls=[], statuses=[], contexts=[], live_meta={}, releases=0)
    tools = ["task.complete", "window.place", *executor.MODEL_RESOURCE_TOOLS]
    state.tools = tools
    spine = dict(runbook=book, runbooks=[book], skills=[], tools=tools)

    async def compile_packet(*_args, **kwargs):
        state.events.append(dict(phase="path", refs=[task.ref, book.ref]))
        return dict(
            packet="Isolated packet", refs=[task.ref, book.ref], spine=spine,
            params=dict(kwargs.get("params") or {}),
            provider_system="Isolated fixed instructions",
            provider_user="Move the requested application",
            retrieval_ms=1.25, objective="Move the requested application",
        )

    async def reply(*_args, **_kwargs):
        return NS(content='{"tool":"task.complete","args":{"status":"completed","summary":"Done."}}',
                  prompt_tokens=100)

    @asynccontextmanager
    async def lease(*_args, **_kwargs):
        try:
            yield model
        finally:
            state.releases += 1

    def tool(name, args, ctx):
        state.calls.append((name, args))
        state.contexts.append(ctx)
        if name == "task.complete":
            from obsidience.harness.capabilities.task.complete import execute

            return execute(args, ctx)
        return dict(status="completed", effect_applied=True, must_not_replay=True)

    def status(_task, value, fields):
        state.live_meta.update({"status": value, **fields})
        state.statuses.append(value)

    def mutate(_task, callback):
        before = dict(state.live_meta)
        callback(state.live_meta)
        if state.live_meta != before:
            state.statuses.append(state.live_meta["status"])
        return state.live_meta

    monkeypatch.setattr(executor, "resolver", lambda **_kwargs: NS(resolve=lambda _ref: agent))
    monkeypatch.setattr(executor, "resolve_spine", lambda *_args: spine)
    # Scope is tested with real accepted snapshots separately; this fixture
    # isolates cancellation after compiler authorization.
    monkeypatch.setattr(executor, "_scope_checkpoint", lambda *_args: None)
    monkeypatch.setattr(executor, "runbook_tree_hash", lambda _books: "isolated-hash")
    monkeypatch.setattr(executor, "compile_activation", compile_packet)
    monkeypatch.setattr(executor, "cached_text_count", lambda *_args: NS(tokens=100, method="runtime"))
    monkeypatch.setattr(executor, "execute_capability", tool)
    async def async_tool(name, args, ctx):
        # Like registry.execute_async: synchronous adapters run in a worker.
        return await asyncio.to_thread(executor.execute_capability, name, args, ctx)
    monkeypatch.setattr(executor, "execute_capability_async", async_tool)
    monkeypatch.setattr(executor, "update_status", status)
    monkeypatch.setattr(executor, "mutate_note_metadata", mutate)
    monkeypatch.setattr(executor.model_runtime, "resolve_model", lambda *_args: model)
    monkeypatch.setattr(executor.model_runtime, "configured_spec", lambda *_args: model)
    monkeypatch.setattr(executor.model_runtime, "lease", lease)
    monkeypatch.setattr(executor.llm, "chat", reply)
    monkeypatch.setattr(executor.INDEX, "record_run", lambda **row: state.records.append(row))
    monkeypatch.setattr(executor.INDEX, "sync", lambda **_kwargs: None)
    monkeypatch.setattr(executor.action_trace, "emit", lambda *_args: None)
    monkeypatch.setattr(
        executor.knowledge_activity, "emit",
        lambda phase, refs, **fields: state.events.append(dict(phase=phase, refs=refs, **fields)),
    )

    async def run(**kwargs):
        return await executor.run_task(
            task, **{
                "emit_turn_event": False,
                "interactive": True,
                "runtime_params": {"request": "Move the requested application"},
                **kwargs,
            },
        )

    state.run = run
    state.reply = reply
    return state


def test_model_preflight_failure_closes_task_and_keeps_one_failed_receipt(execution, monkeypatch):
    def unavailable(*_args):
        raise RuntimeError("isolated model preflight failure")

    monkeypatch.setattr(executor.model_runtime, "resolve_model", unavailable)
    with pytest.raises(RuntimeError, match="isolated model preflight failure"):
        asyncio.run(execution.run())
    assert execution.statuses == ["running", "failed"]
    assert len(execution.records) == 1
    assert execution.records[0]["id"] == execution.live_meta["last_run"]
    assert execution.records[0]["status"] == "failed"
    assert [e["phase"] for e in execution.events] == ["query_started", "query_completed"]


def test_spine_failure_closes_task_as_blocked_with_one_terminal_event(execution, monkeypatch):
    monkeypatch.setattr(executor, "resolve_spine", lambda *_args: {"error": "missing Runbook"})
    result = asyncio.run(execution.run())
    assert result["status"] == "blocked"
    assert execution.statuses == ["running", "blocked"]
    assert len(execution.records) == 1
    assert execution.records[0]["status"] == "blocked"
    assert [e["phase"] for e in execution.events] == ["query_started", "query_completed"]


def test_late_failure_does_not_overwrite_a_newer_task_claim(execution, monkeypatch):
    async def replaced(*_args, **_kwargs):
        execution.live_meta.update({"last_run": "newer-run", "status": "running"})
        raise RuntimeError("isolated earlier activation failure")

    monkeypatch.setattr(executor, "compile_activation", replaced)
    with pytest.raises(RuntimeError, match="isolated earlier activation failure"):
        asyncio.run(execution.run())
    assert execution.statuses == ["running"]
    assert execution.live_meta["last_run"] == "newer-run"
    assert execution.live_meta["status"] == "running"
    assert execution.records[0]["id"] != "newer-run"
    assert execution.records[0]["status"] == "failed"



from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace as NS

import pytest

from obsidience.harness.execution import executor
from obsidience.harness.models import runtime
from obsidience.tests.test_execution_cancellation import execution  # noqa: F401


def unavailable():
    spec = runtime.MODELS[runtime.SPECIALIST_MODEL]
    device = next(iter(runtime.DEVICE_LABELS))
    return runtime.ModelResourceUnavailable(spec, [(device,)], {"speech": (device,)})


@pytest.mark.parametrize("ephemeral", [False, True])
def test_resource_race_preserves_exact_occurrence_without_failed_receipt(execution, monkeypatch, ephemeral):
    before = {
        "status": "completed", "last_run": "previous", "summary": "Previous completed result",
        "params": {"event": "task.create", "activation_key": "current"},
        "event_queue": [{"event": "task.create", "activation_key": "later"}],
    }
    execution.task.meta.update(before)
    execution.live_meta.update(before)

    @asynccontextmanager
    async def lease(*_args, **_kwargs):
        raise unavailable()
        yield

    monkeypatch.setattr(executor.model_runtime, "lease", lease)
    result = asyncio.run(execution.run(
        interactive=ephemeral,
        runtime_params={"request": "Exact current request"} if ephemeral else None,
    ))
    assert result["status"] == ("blocked" if ephemeral else "pending")
    assert result["resource_blocked"] is True
    assert result["resource"]["code"] == "model_resources_reserved"
    assert execution.records == []
    assert execution.calls == []
    assert execution.live_meta["status"] == ("completed" if ephemeral else "pending")
    for key in ("last_run", "summary", "params", "event_queue"):
        assert execution.live_meta[key] == before[key]


def test_resource_loss_after_tool_effect_never_requeues_for_replay(execution, monkeypatch):
    acquisitions = 0
    resource_tool = next(iter(executor.MODEL_RESOURCE_TOOLS))

    @asynccontextmanager
    async def lease(*_args, **_kwargs):
        nonlocal acquisitions
        acquisitions += 1
        if acquisitions > 1:
            raise unavailable()
        yield

    async def chat(*_args, **_kwargs):
        return NS(content=json.dumps({"tool": resource_tool, "args": {}}), prompt_tokens=100)

    monkeypatch.setattr(executor.model_runtime, "lease", lease)
    monkeypatch.setattr(executor.llm, "chat", chat)
    with pytest.raises(runtime.ModelResourceUnavailable):
        asyncio.run(execution.run(interactive=False, runtime_params=None))
    assert execution.statuses[-1] == "failed"
    assert len(execution.calls) == 1
    assert execution.records[0]["status"] == "failed"
    trace = json.loads(execution.records[0]["trace"])
    assert any(row.get("tool") == resource_tool for row in trace)


@pytest.mark.parametrize("earlier_child_completed", [False, True])
def test_container_resource_race_stops_chain_and_preserves_prior_children(
    execution, monkeypatch, earlier_child_completed,
):
    child = NS(ref="Tasks/blocked-child", title="Blocked child", kind="task", meta={"status": "pending"})
    prior = NS(ref="Tasks/prior-child", title="Prior child", kind="task", meta={"status": "pending"})
    parent = NS(ref="Tasks/parent", title="Parent", kind="task",
                meta={"status": "pending", "last_run": "prior-parent-run"})
    children = [prior, child] if earlier_child_completed else [child]
    base_spine = executor.resolve_spine(execution.task, executor.resolver())
    states = {task.ref: dict(task.meta) for task in (parent, prior, child)}

    def spine(task, _resolver):
        return {"subtasks": children} if task is parent else base_spine

    def status(task, value, fields):
        states[task.ref].update({"status": value, **fields})

    def mutate(task, callback):
        callback(states[task.ref])

    async def session(task, _model, _messages, _allowed, _ctx, *_args, **_kwargs):
        if task is child:
            raise unavailable()
        return [], "completed", "Earlier child completed."

    monkeypatch.setattr(executor, "resolve_spine", spine)
    monkeypatch.setattr(executor, "update_status", status)
    monkeypatch.setattr(executor, "mutate_note_metadata", mutate)
    monkeypatch.setattr(executor, "_execute_session", session)
    if earlier_child_completed:
        with pytest.raises(runtime.ModelResourceUnavailable):
            asyncio.run(executor.run_task(parent, emit_turn_event=False))
        assert states[parent.ref]["status"] == "failed"
        assert [(r["task_ref"], r["status"]) for r in execution.records] == [
            (prior.ref, "completed"), (parent.ref, "failed"),
        ]
        trace = json.loads(execution.records[-1]["trace"])
        assert any(row.get("task") == prior.ref and row["status"] == "completed" for row in trace)
        assert any(row.get("resource_blocked_after_effect") and row["must_not_replay"] for row in trace)
    else:
        result = asyncio.run(executor.run_task(parent, emit_turn_event=False))
        assert result["status"] == "pending" and result["resource_blocked"]
        assert states[parent.ref]["last_run"] == "prior-parent-run"
        assert execution.records == []
    assert states[child.ref]["status"] == "pending"
    assert "last_run" not in states[child.ref]

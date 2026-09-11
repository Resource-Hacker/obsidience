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


def test_task_taxonomy_cannot_execute_children(execution, monkeypatch):
    """An index is not an implicit workflow, regardless of child resources."""
    parent = NS(ref="Tasks/parent", title="Parent", kind="task", meta={})
    child = NS(ref="Tasks/child", title="Child", kind="task", meta={})
    monkeypatch.setattr(executor, "resolve_spine", lambda *_: {"subtasks": [child]})
    result = asyncio.run(executor.run_task(parent, emit_turn_event=False))
    assert result["status"] == "blocked"
    assert execution.calls == []
    assert all(record["task_ref"] == parent.ref for record in execution.records)

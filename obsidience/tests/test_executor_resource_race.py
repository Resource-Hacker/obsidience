from __future__ import annotations

import asyncio
from types import SimpleNamespace as NS


from obsidience.harness.execution import executor
from obsidience.harness.models import runtime
from obsidience.tests.test_execution_cancellation import execution  # noqa: F401


def unavailable():
    spec = runtime.MODELS[runtime.EXECUTIVE_MODEL]
    device = next(iter(runtime.DEVICE_LABELS))
    return runtime.ModelResourceUnavailable(spec, [(device,)], {"speech": (device,)})


def test_task_taxonomy_cannot_execute_children(execution, monkeypatch):
    """An index is not an implicit workflow, regardless of child resources."""
    parent = NS(ref="Tasks/parent", title="Parent", kind="task", meta={})
    child = NS(ref="Tasks/child", title="Child", kind="task", meta={})
    monkeypatch.setattr(executor, "resolve_spine", lambda *_: {"subtasks": [child]})
    result = asyncio.run(executor.run_task(parent, emit_turn_event=False))
    assert result["status"] == "blocked"
    assert execution.calls == []
    assert all(record["task_ref"] == parent.ref for record in execution.records)

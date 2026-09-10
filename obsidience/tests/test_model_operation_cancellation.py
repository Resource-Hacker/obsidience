"""Real operation/lease cancellation boundaries with every external effect fake."""

import asyncio
import copy
from unittest.mock import AsyncMock

import pytest

from obsidience.harness.models import runtime as models


@pytest.fixture
def operation_runtime(monkeypatch):
    runtime = models._HardwareModelRuntime()
    model_id = models.EXECUTIVE_MODEL
    spec = models.MODELS[model_id]
    state = {"models": {model_id: {
        "allowed_devices": list(spec.default_allowed_devices),
        "context_tokens": 8192, "max_output_tokens": 1024,
        "max_num_seqs": 1, "gpu_memory_utilization": 0.8,
    }}, "hardware": {}, "benchmarks": {}}
    writes, sources = [], []

    def write(settings):
        writes.append(copy.deepcopy(settings))
        state.clear()
        state.update(copy.deepcopy(settings))

    def source(*args):
        sources.append(copy.deepcopy(args))
        return "evidence/models/committed.json"

    monkeypatch.setattr(models, "_read_settings", lambda: copy.deepcopy(state))
    monkeypatch.setattr(models, "_write_settings", write)
    monkeypatch.setattr(models, "record_model_source", source)
    monkeypatch.setattr(models, "model_document", lambda _id: copy.deepcopy(state["models"][_id]))
    monkeypatch.setattr(models, "_healthy", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(models, "configured_spec", lambda _id: spec)
    monkeypatch.setattr(runtime, "_pick_devices", lambda *_args: ("gpu",))
    monkeypatch.setattr(runtime, "_stop", AsyncMock())
    monkeypatch.setattr(runtime, "_activate_task_model", AsyncMock())
    monkeypatch.setattr(runtime, "_reconcile_defaults", AsyncMock())
    monkeypatch.setattr(models, "_benchmark_text_model", AsyncMock(return_value={"sample_count": 3}))
    return runtime, model_id, state, writes, sources


def assert_released(runtime):
    assert not runtime.lock.locked()
    assert runtime.switching is False
    assert runtime.running_model is None


def test_cancel_while_waiting_for_configure_does_not_read_or_commit(operation_runtime, monkeypatch):
    runtime, model_id, _state, writes, sources = operation_runtime

    async def exercise():
        await runtime.lock.acquire()
        monkeypatch.setattr(models, "_read_settings", lambda: pytest.fail("cancelled admission read settings"))
        task = asyncio.create_task(runtime.update_model(model_id, {"context_tokens": 4096}))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        runtime.lock.release()

    asyncio.run(exercise())
    assert not writes and not sources
    runtime._stop.assert_not_awaited()


def test_configure_reads_latest_settings_after_lock_admission(operation_runtime):
    runtime, model_id, state, writes, sources = operation_runtime

    async def exercise():
        await runtime.lock.acquire()
        task = asyncio.create_task(runtime.update_model(model_id, {"context_tokens": 4096}))
        await asyncio.sleep(0)
        state["models"][model_id]["max_num_seqs"] = 4
        runtime.lock.release()
        result = await task
        assert result["max_num_seqs"] == 4
        assert result["configuration_applied"] is True
        assert result["runtime_reconciled"] is True
        assert runtime.reconciliation_pending is False

    asyncio.run(exercise())
    assert len(writes) == len(sources) == 1
    assert sources[0][2]["before"]["max_num_seqs"] == 4
    assert_released(runtime)


def test_cancel_during_stop_leaves_configuration_uncommitted(operation_runtime):
    runtime, model_id, state, writes, sources = operation_runtime

    async def exercise():
        entered = asyncio.Event()

        async def stop(_spec):
            entered.set()
            await asyncio.Event().wait()

        runtime._stop.side_effect = stop
        task = asyncio.create_task(runtime.update_model(model_id, {"context_tokens": 4096}))
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(exercise())
    assert not writes and not sources
    assert state["models"][model_id]["context_tokens"] == 8192
    assert runtime.reconciliation_pending is True
    runtime._reconcile_defaults.assert_not_awaited()
    assert_released(runtime)


@pytest.mark.parametrize("operation", ["configure", "benchmark"])
def test_cancel_after_commit_keeps_actual_result_and_releases_owner(operation_runtime, operation):
    runtime, model_id, state, writes, sources = operation_runtime

    async def exercise():
        entered = asyncio.Event()
        exited = asyncio.Event()

        async def reconcile():
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                exited.set()

        runtime._reconcile_defaults.side_effect = reconcile
        task = asyncio.create_task(
            runtime.update_model(model_id, {"context_tokens": 4096})
            if operation == "configure" else runtime.benchmark(model_id, ["gpu"])
        )
        await asyncio.wait_for(entered.wait(), 1)
        assert len(writes) == len(sources) == 1
        task.cancel()
        result = await asyncio.wait_for(task, 1)
        assert result["runtime_reconciled"] is False
        assert runtime.reconciliation_pending is True
        assert result["cancellation_requested"] is True
        assert "interrupted" in result["reconciliation_warning"]
        assert task.cancelling() == 1 and not task.cancelled()
        assert exited.is_set()
        if operation == "configure":
            assert result["configuration_applied"] is True
            assert result["context_tokens"] == state["models"][model_id]["context_tokens"] == 4096
        else:
            assert result["sample_count"] == state["benchmarks"][model_id]["sample_count"] == 3
        assert_released(runtime)

    asyncio.run(exercise())
    assert len(writes) == len(sources) == 1
    runtime._reconcile_defaults.assert_awaited_once()


def test_cancel_during_benchmark_does_not_commit_measurements(operation_runtime, monkeypatch):
    runtime, model_id, _state, writes, sources = operation_runtime

    async def exercise():
        entered = asyncio.Event()

        async def sample(_spec):
            entered.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(models, "_benchmark_text_model", sample)
        task = asyncio.create_task(runtime.benchmark(model_id, ["gpu"]))
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 0.2)

    asyncio.run(exercise())
    assert not writes and not sources
    runtime._reconcile_defaults.assert_not_awaited()
    assert runtime.reconciliation_pending is True
    assert_released(runtime)


def test_cancel_systemctl_kills_and_reaps_its_cli_process(monkeypatch):
    async def exercise():
        entered = asyncio.Event()
        killed = asyncio.Event()

        class Process:
            returncode = None
            drains = 0

            async def communicate(self):
                self.drains += 1
                entered.set()
                await killed.wait()
                return b"", b""

            def kill(self):
                self.returncode = -9
                killed.set()

        process = Process()
        monkeypatch.setattr(models.asyncio, "create_subprocess_exec", AsyncMock(return_value=process))
        task = asyncio.create_task(models._systemctl("stop", "fixture.service"))
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert process.returncode == -9 and process.drains == 2

    asyncio.run(exercise())

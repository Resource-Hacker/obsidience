"""Model lease lifetime tests with no real hardware or service operations."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from obsidience.harness.models import runtime as model_runtime


@pytest.fixture
def fake_runtime(monkeypatch):
    runtime = model_runtime._HardwareModelRuntime()
    spec = SimpleNamespace(id="test-model")
    monkeypatch.setattr(runtime, "_pick_devices", lambda *_args: ("test-device",))
    monkeypatch.setattr(runtime, "_activate_task_model", AsyncMock())
    monkeypatch.setattr(runtime, "_reconcile_defaults", AsyncMock())
    monkeypatch.setattr(model_runtime, "configured_spec", lambda _model_id: spec)
    return runtime, spec


async def assert_next_lease_available(runtime, spec):
    assert not runtime.lock.locked()
    assert runtime.switching is False
    assert runtime.running_model is None

    async def acquire():
        async with runtime.lease(spec) as selected:
            assert selected is spec
            assert runtime.lock.locked()
            assert runtime.running_model == spec.id
            assert runtime.switching is False

    await asyncio.wait_for(acquire(), timeout=1)
    assert not runtime.lock.locked()
    assert runtime.switching is False
    assert runtime.running_model is None
    assert runtime.reconciliation_pending is False


def test_normal_lease_reconciles_once_and_releases(fake_runtime):
    runtime, spec = fake_runtime

    asyncio.run(assert_next_lease_available(runtime, spec))

    runtime._activate_task_model.assert_awaited_once_with(spec, ("test-device",))
    runtime._reconcile_defaults.assert_awaited_once_with()


def test_cancel_during_reconciliation_releases_for_next_lease(fake_runtime):
    runtime, spec = fake_runtime

    async def exercise():
        entered = asyncio.Event()
        reconciling = asyncio.Event()

        async def reconcile():
            reconciling.set()
            await asyncio.Event().wait()

        async def use():
            async with runtime.lease(spec):
                entered.set()

        runtime._reconcile_defaults.side_effect = reconcile
        pending = asyncio.create_task(use())
        await asyncio.wait_for(entered.wait(), timeout=1)
        await asyncio.wait_for(reconciling.wait(), timeout=1)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        runtime._reconcile_defaults.assert_awaited_once_with()
        assert runtime.reconciliation_pending is True

        runtime._reconcile_defaults.side_effect = None
        # Pending defaults do not prevent admission of the next exact Task.
        await assert_next_lease_available(runtime, spec)
        assert runtime._reconcile_defaults.await_count == 2

    asyncio.run(exercise())


@pytest.mark.parametrize("canceled", [False, True])
def test_failed_or_canceled_activation_releases_for_next_lease(fake_runtime, canceled):
    runtime, spec = fake_runtime

    async def exercise():
        activating = asyncio.Event()

        async def activate(*_args):
            activating.set()
            if canceled:
                await asyncio.Event().wait()
            raise RuntimeError("test activation failure")

        async def use():
            async with runtime.lease(spec):
                pytest.fail("failed activation must not enter the lease body")

        runtime._activate_task_model.side_effect = activate
        pending = asyncio.create_task(use())
        await asyncio.wait_for(activating.wait(), timeout=1)
        if canceled:
            pending.cancel()
        with pytest.raises(asyncio.CancelledError if canceled else RuntimeError):
            await pending
        if canceled:
            runtime._reconcile_defaults.assert_not_awaited()
            assert runtime.reconciliation_pending is True
        else:
            runtime._reconcile_defaults.assert_awaited_once_with()

        runtime._activate_task_model.side_effect = None
        await assert_next_lease_available(runtime, spec)
        assert runtime._activate_task_model.await_count == 2
        assert runtime._reconcile_defaults.await_count == (1 if canceled else 2)

    asyncio.run(exercise())


def test_cancelled_body_skips_blocking_reconcile_and_next_lease_recovers(fake_runtime):
    runtime, spec = fake_runtime

    async def exercise():
        entered = asyncio.Event()

        async def blocking_reconcile():
            pytest.fail("cancelled cleanup started default-model loading")

        async def use():
            async with runtime.lease(spec):
                entered.set()
                await asyncio.Event().wait()

        runtime._reconcile_defaults.side_effect = blocking_reconcile
        task = asyncio.create_task(use())
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 0.2)
        assert not runtime.lock.locked()
        assert runtime.reconciliation_pending is True
        runtime._reconcile_defaults.assert_not_awaited()

        runtime._reconcile_defaults.side_effect = None
        async with runtime.lease(spec) as selected:
            assert selected is spec
            assert runtime.running_model == spec.id
            assert runtime.reconciliation_pending is True
        assert runtime.reconciliation_pending is False
        runtime._reconcile_defaults.assert_awaited_once()
        await assert_next_lease_available(runtime, spec)

    asyncio.run(exercise())


def test_executor_manual_exit_during_cancellation_does_not_load_defaults(fake_runtime):
    runtime, spec = fake_runtime

    async def exercise():
        entered = asyncio.Event()

        async def use():
            lease = runtime.lease(spec)
            await lease.__aenter__()
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                # The executor manually owns its lease across Tool boundaries.
                await lease.__aexit__(None, None, None)

        task = asyncio.create_task(use())
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 0.2)
        assert not runtime.lock.locked()
        assert runtime.reconciliation_pending is True
        runtime._reconcile_defaults.assert_not_awaited()
        await assert_next_lease_available(runtime, spec)

    asyncio.run(exercise())

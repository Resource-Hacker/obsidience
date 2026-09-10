"""Dispatch model operations on the owning loop; no HTTP, hardware or settings."""

import asyncio
import json
import threading
from unittest.mock import AsyncMock

import pytest

from obsidience.harness.capabilities import registry
from obsidience.harness.capabilities.model import benchmark, configure


def test_async_dispatch_keeps_native_operation_on_calling_task(monkeypatch):
    context = {}

    async def exercise():
        owner = asyncio.current_task()

        async def operation(args, received):
            assert asyncio.current_task() is owner
            assert received is context
            received["visited"] = True
            return args

        monkeypatch.setattr(registry, "resolve", lambda _name: operation)
        assert await registry.execute_async("model.configure", {"x": 1}, context) == {"x": 1}

    asyncio.run(exercise())
    assert context == {"visited": True}


def test_sync_dispatch_stays_in_worker_and_preserves_context(monkeypatch):
    context = {}
    owner_thread = threading.get_ident()

    def operation(args, received):
        assert threading.get_ident() != owner_thread
        assert received is context
        return "read"

    monkeypatch.setattr(registry, "resolve", lambda _name: operation)
    assert asyncio.run(registry.execute_async("source.read", {}, context)) == "read"


def test_sync_entrypoint_rejects_async_adapter_before_call(monkeypatch):
    operation = AsyncMock()
    monkeypatch.setattr(registry, "resolve", lambda _name: operation)
    with pytest.raises(TypeError, match="requires execute_async"):
        registry.execute("model.configure", {}, {})
    operation.assert_not_called()


@pytest.mark.parametrize("pre_cancelled", [False, True])
def test_cancellation_reaches_native_operation_and_cooperative_flag(monkeypatch, pre_cancelled):
    cancel = threading.Event()
    calls = []

    async def exercise():
        entered = asyncio.Event()

        async def operation(args, context):
            calls.append("entered")
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                calls.append("exited")

        monkeypatch.setattr(registry, "resolve", lambda _name: operation)
        if pre_cancelled:
            cancel.set()
        task = asyncio.create_task(registry.execute_async("model.configure", {}, {
            "_capability_cancel_event": cancel,
        }))
        if not pre_cancelled:
            await asyncio.wait_for(entered.wait(), 1)
            task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cancel.is_set()

    asyncio.run(exercise())
    assert calls == ([] if pre_cancelled else ["entered", "exited"])


@pytest.mark.parametrize("module,name,args,owner_name,expected_args", [
    (configure, "model.configure", {"model_id": " m ", "context_tokens": 4096,
     "ignored": "not forwarded"}, "update_model", ("m", {"context_tokens": 4096})),
    (benchmark, "model.benchmark", {"model_id": " m ", "devices": ["gpu"]},
     "benchmark", ("m", ["gpu"])),
])
def test_model_adapter_uses_existing_runtime_and_keeps_committed_cancellation(
    monkeypatch, module, name, args, owner_name, expected_args,
):
    operation = AsyncMock(return_value={
        "configuration_applied": True, "runtime_reconciled": False,
        "reconciliation_warning": "interrupted", "cancellation_requested": True,
        "context_tokens": 4096,
    })
    monkeypatch.setattr(module.model_runtime, owner_name, operation)
    context = {}
    result = json.loads(asyncio.run(registry.execute_async(name, args, context)))
    operation.assert_awaited_once_with(*expected_args)
    assert result["runtime_reconciled"] is False
    assert result["reconciliation_warning"] == "interrupted"
    assert "cancellation_requested" not in result
    assert context["_capability_cancelled_after_commit"] is True


@pytest.mark.parametrize("module,args,owner_name", [
    (configure, {"model_id": "m", "context_tokens": 4096}, "update_model"),
    (benchmark, {"model_id": "m", "devices": ["gpu"]}, "benchmark"),
])
def test_model_adapter_does_not_turn_precommit_cancellation_into_failure_text(
    monkeypatch, module, args, owner_name,
):
    monkeypatch.setattr(module.model_runtime, owner_name, AsyncMock(side_effect=asyncio.CancelledError))
    context = {}
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(module.execute(args, context))
    assert "_capability_cancelled_after_commit" not in context


def test_read_only_policy_is_reviewed_implementation_allowlist():
    assert registry.READ_ONLY_CAPABILITIES == {
        "source.read", "vault.read", "vault.search", "vault.validate", "harness.status",
    }
    assert not registry.READ_ONLY_CAPABILITIES.intersection(registry.MODEL_RESOURCE_TOOLS)
    assert "task.complete" not in registry.READ_ONLY_CAPABILITIES

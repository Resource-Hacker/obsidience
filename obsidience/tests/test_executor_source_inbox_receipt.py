"""Ingest provenance belongs to the admitted occurrence, even before the model runs."""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from copy import deepcopy

import pytest

from obsidience.harness.execution import executor
from obsidience.tests.test_execution_cancellation import execution  # noqa: F401


@pytest.mark.parametrize("outcome", ["completed", "compile_cancel", "lease_cancel", "compile_failure", "provider_failure"])
def test_ingest_retains_source_receipt_at_every_terminal_boundary(execution, monkeypatch, outcome):
    source = {
        "source_id": "isolated-source-id",
        "source_citation": "source:isolated-source-id",
        "source_path": "obsidience/evidence/inbox/isolated.md",
        "source_sha256": "a" * 64,
        "research_task": "Tasks/research/question",
        "research_run_id": "isolated-research-run",
    }
    params = {"event": "source.inbox", "activation_key": "source.inbox:isolated", **source,
              "unrelated_private_input": "Must not enter the source receipt."}
    execution.task.ref = "Tasks/ingest"
    execution.task.title = "Ingest"
    execution.task.meta.update({"params": params, "event_queue": [{"activation_key": "next"}]})
    before = deepcopy(execution.task.meta)
    monkeypatch.setattr(executor.INDEX, "bind_continuation_ingest", lambda *_args: None)

    def complete(name, args, _ctx):
        assert name == "task.complete"
        execution.calls.append((name, args))
        return {"accepted": True, "status": "completed", "summary": "Isolated completion."}

    monkeypatch.setattr(executor, "execute_capability", complete)

    async def exercise():
        reached = asyncio.Event()

        async def interrupted(*_args, **_kwargs):
            reached.set()
            await asyncio.Event().wait()

        async def failed(*_args, **_kwargs):
            raise RuntimeError("Isolated pre-effect failure")

        @asynccontextmanager
        async def lease(*_args, **_kwargs):
            await interrupted()
            yield

        if outcome == "compile_cancel":
            monkeypatch.setattr(executor, "compile_activation", interrupted)
        elif outcome == "lease_cancel":
            monkeypatch.setattr(executor.model_runtime, "lease", lease)
            monkeypatch.setattr(executor.llm, "chat", lambda *_args, **_kwargs: pytest.fail("provider started before lease"))
        elif outcome == "compile_failure":
            monkeypatch.setattr(executor, "compile_activation", failed)
        elif outcome == "provider_failure":
            monkeypatch.setattr(executor.llm, "chat", failed)

        turn = asyncio.create_task(execution.run(interactive=False, runtime_params=None))
        if outcome.endswith("cancel"):
            await asyncio.wait_for(reached.wait(), 2)
            turn.cancel()
            with pytest.raises(asyncio.CancelledError):
                await turn
        elif outcome == "compile_failure":
            with pytest.raises(RuntimeError, match="Isolated pre-effect failure"):
                await turn
        elif outcome == "provider_failure":
            assert (await turn)["status"] == "failed"
        else:
            assert (await turn)["status"] == "completed"

    asyncio.run(exercise())
    assert len(execution.records) == 1
    record = execution.records[0]
    assert record["status"] == ("completed" if outcome == "completed" else
                                "interrupted" if outcome.endswith("cancel") else "failed")
    rows = json.loads(record["trace"])
    assert [row["source_inbox"] for row in rows if "source_inbox" in row] == [source]
    assert execution.task.meta == before
    if outcome != "completed":
        assert execution.calls == []
    assert "unrelated_private_input" not in rows[0]["source_inbox"]

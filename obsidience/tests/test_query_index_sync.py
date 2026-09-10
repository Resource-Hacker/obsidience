"""An answer-only Query preserves durable state without a redundant Vault sync."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace as NS

import pytest

from obsidience.harness.execution import executor
from obsidience.harness.knowledge import vault
from obsidience.tests.test_execution_cancellation import execution


def _params(event="chat.request"):
    return {"event": event, "source": "text" if event == "chat.request" else "voice",
            "request": "Say hello.", "computer_outcome": "answer",
            "conversation_id": "isolated-conversation", "reply_to_turn_id": "isolated-owner-turn"}


def _scan_counter(execution, monkeypatch):
    scans = []
    # A snapshot parameter is supported by the production resolver. This fixture
    # deliberately supplies only the already admitted isolated Executive.
    agent = NS(ref="Agents/Executive/Executive", title="Executive", kind="agent", meta={})
    monkeypatch.setattr(executor, "resolver", lambda **_kwargs: NS(resolve=lambda _ref: agent))
    monkeypatch.setattr(executor.INDEX, "sync", lambda: scans.append(True))
    return scans


@pytest.mark.parametrize("event", ["chat.request", "voice.activation"])
def test_answer_only_query_skips_index_rebuild_but_records_success(execution, monkeypatch, event):
    scans = _scan_counter(execution, monkeypatch)
    async def measured_response(*args, **kwargs):
        reply = await execution.reply(*args, **kwargs)
        reply.provider_metrics = {"generation_ms": 2.0, "first_public_delta_ms": 1.0}
        return reply

    monkeypatch.setattr(executor.llm, "chat", measured_response)
    result = asyncio.run(execution.run(runtime_params=_params(event)))
    assert result["status"] == "completed"
    assert scans == []
    assert execution.records[-1]["status"] == "completed"
    assert execution.statuses[-1] == "completed"
    calls = executor.INDEX.tool_run_receipts(result["run_id"])["calls"]
    assert [(call["tool"], call["status"]) for call in calls] == [("task.complete", "returned")]


@pytest.mark.parametrize("change", [
    {"event": "task.continue"}, {"event": "turn.complete"},
    {"computer_outcome": "observe"}, {"computer_outcome": None},
    {"conversation_id": ""}, {"reply_to_turn_id": ""},
])
def test_uncovered_request_origin_retains_index_sync(execution, monkeypatch, change):
    scans = _scan_counter(execution, monkeypatch)
    asyncio.run(execution.run(runtime_params={**_params(), **change}))
    assert scans == [True]


@pytest.mark.parametrize("variant", ["other_task", "noninteractive", "failed", "invalid_then_complete", "tool_then_complete", "rejected_then_complete"])
def test_any_other_execution_retains_index_sync(execution, monkeypatch, variant):
    scans = _scan_counter(execution, monkeypatch)
    run_kwargs = {"runtime_params": _params()}
    if variant == "other_task":
        execution.task.ref = "Tasks/other"
    elif variant == "noninteractive":
        run_kwargs["interactive"] = False
    replies = []
    if variant == "failed":
        replies.append({"tool": "task.complete", "args": {"status": "failed", "summary": "Cannot answer."}})
    elif variant == "invalid_then_complete":
        replies.append("Invalid public response")
    elif variant == "tool_then_complete":
        replies.append({"tool": "window.place", "args": {}})
    elif variant == "rejected_then_complete":
        replies.append({"tool": "task.complete", "args": {"status": "invalid", "summary": "Rejected."}})
    replies.append({"tool": "task.complete", "args": {"status": "completed", "summary": "Hello."}})

    async def response(*_args, **_kwargs):
        value = replies.pop(0)
        return NS(content=json.dumps(value) if isinstance(value, dict) else value,
                  prompt_tokens=100, finish_reason="stop", completion_tokens=20)

    monkeypatch.setattr(executor.llm, "chat", response)
    asyncio.run(execution.run(**run_kwargs))
    assert scans == [True]


def test_answer_only_query_persists_runtime_and_leaves_article_bytes_unchanged(execution, monkeypatch, tmp_path):
    scans = _scan_counter(execution, monkeypatch)
    monkeypatch.setattr(vault.CONFIG, "vault_dir", tmp_path / "vault")
    vault.write_note("Tasks/query.md", {"kind": "task", "title": "Query"}, "Answer the current question.")
    execution.task.path = "Tasks/query.md"
    execution.task.body = "Answer the current question.\n"
    before = (vault.CONFIG.vault_dir / execution.task.path).read_bytes()
    ledger = executor.INDEX
    monkeypatch.setattr(executor, "update_status", vault.update_status)
    monkeypatch.setattr(executor, "mutate_note_metadata", vault.mutate_note_metadata)
    monkeypatch.setattr(ledger, "record_run", type(ledger).record_run.__get__(ledger))

    result = asyncio.run(execution.run(runtime_params=_params()))

    assert result["status"] == "completed" and scans == []
    assert ledger.run(result["run_id"])["status"] == "completed"
    assert ledger.task_runtime("Tasks/query")["status"] == "completed"
    assert vault.load_note("Tasks/query.md").meta["status"] == "completed"
    assert (vault.CONFIG.vault_dir / execution.task.path).read_bytes() == before

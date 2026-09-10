"""Task admission and retry requests never rewrite past execution outcomes."""

import asyncio
from importlib import import_module
from types import SimpleNamespace as NS

from fastapi import HTTPException
import pytest

api = import_module("obsidience.harness.interfaces.api.app")


@pytest.fixture
def task(monkeypatch):
    note = NS(ref="Tasks/link", kind="task", meta={
        "status": "failed", "last_run": "old-attempt", "blocked_reason": "Old provider error",
        "params": {"event": "task.create", "activation_key": "same-occurrence"},
        "event_queue": [{"activation_key": "later-occurrence"}],
    })
    run = {"id": "old-attempt", "task_ref": note.ref, "status": "interrupted",
           "finished": 10, "summary": "Interrupted after reading."}
    monkeypatch.setattr(api.INDEX, "run", lambda _id: dict(run))
    monkeypatch.setattr(api.scheduler, "retry_blocked_reason", lambda *_args: "")
    monkeypatch.setattr(api, "load_note", lambda _path: note)
    return note


def test_failed_head_is_attention_but_keeps_actual_last_attempt_status(task):
    result = api.task_execution_state(task, NS())
    assert result["state"] == "needs_attention" and result["retry_allowed"]
    assert result["last_run"]["status"] == "interrupted"
    assert result["reason"] == "Old provider error"
    assert task.meta["status"] == "failed"


def test_pending_realtime_wait_keeps_failed_history_without_marking_live_error(task, monkeypatch):
    task.meta["status"] = "pending"
    monkeypatch.setattr(api.scheduler, "_realtime_allows", lambda *_args: False)
    monkeypatch.setattr(api.realtime.RUNTIME, "scheduler_paused", lambda: True)
    monkeypatch.setattr(api.scheduler, "_resource_error", lambda *_args: pytest.fail("no GPU query while paused"))
    result = api.task_execution_state(task, NS())
    assert result["state"] == "waiting" and "Realtime" in result["reason"]
    assert result["label"] == "Paused: Realtime"
    assert result["last_run"]["status"] == "interrupted"
    assert not result["retry_allowed"]
    assert task.meta["event_queue"] == [{"activation_key": "later-occurrence"}]


def test_finished_manual_attempt_is_history_not_a_current_queue_failure(task):
    task.meta.pop("params")
    task.meta.pop("event_queue")
    result = api.task_execution_state(task, NS())
    assert result["state"] == "idle" and result["reason"] == ""
    assert result["last_run"]["status"] == "interrupted"


def test_retry_route_queues_exact_attempt_without_launch_or_runtime_overrides(task, monkeypatch):
    calls = []
    monkeypatch.setattr(api.scheduler, "launch", lambda *_a, **_k: pytest.fail("retry must respect scheduler admission"))
    monkeypatch.setattr(api.scheduler, "retry_failed_occurrence", lambda note, run: calls.append((note, run)) or {"status": "pending"})
    assert asyncio.run(api.run_now(task.ref, {"retry_run_id": "old-attempt"})) == {"status": "pending"}
    assert calls == [(task, "old-attempt")]
    with pytest.raises(HTTPException) as error:
        asyncio.run(api.run_now(task.ref, {}))
    assert error.value.status_code == 409
    for payload in ({"retry_run_id": ""}, {"retry_run_id": "old-attempt", "params": {"request": "different"}}):
        with pytest.raises(HTTPException) as error:
            asyncio.run(api.run_now(task.ref, payload))
        assert error.value.status_code == 400

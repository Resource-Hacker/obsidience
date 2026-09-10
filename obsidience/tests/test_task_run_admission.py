from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from obsidience.harness.interfaces.api import app


@pytest.fixture
def admitted_task(monkeypatch):
    note = SimpleNamespace(ref="Tasks/executive/operate", kind="task", meta={
        "status": "pending", "model": "obsidience-gemma", "reasoning_effort": "none",
    })
    calls = []
    monkeypatch.setattr(app, "load_note", lambda _ref: note)
    monkeypatch.setattr(app.scheduler, "launch", lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setattr(app.model_runtime, "resolve_model", lambda *_args: SimpleNamespace(id="obsidience-gemma"))
    return note, calls


@pytest.mark.parametrize("params", [
    {"computer_outcome": "input"}, {"computer_outcome": "action"},
    {"computer_outcome": "action", "computer_scope": "unknown"},
    {"computer_outcome": "observe", "computer_scope": "state"},
    {"computer_outcome": "answer", "computer_scope": "input"},
])
def test_invalid_computer_binding_is_http_400_before_scheduler_claim(admitted_task, params):
    note, calls = admitted_task
    with pytest.raises(HTTPException) as error:
        asyncio.run(app.run_now(note.ref, {"params": params}))
    assert error.value.status_code == 400
    assert calls == []


@pytest.mark.parametrize("outcome,scope", [("action", "input"), ("action", "state"), ("observe", None), ("answer", None)])
def test_valid_outcome_reaches_existing_scheduler_unchanged(admitted_task, outcome, scope):
    note, calls = admitted_task
    params = {"request": "Exact owner request", "computer_outcome": outcome}
    if scope is not None:
        params["computer_scope"] = scope
    result = asyncio.run(app.run_now(note.ref, {"params": params}))
    assert result["started"] == note.ref
    assert len(calls) == 1
    assert calls[0][1]["runtime_params"] == params


def test_saved_binding_is_validated_with_runtime_override_before_claim(admitted_task):
    note, calls = admitted_task
    note.meta["params"] = {"computer_outcome": "action"}
    with pytest.raises(HTTPException) as error:
        asyncio.run(app.run_now(note.ref))
    assert error.value.status_code == 400
    assert calls == []
    asyncio.run(app.run_now(note.ref, {"params": {"computer_scope": "state"}}))
    assert len(calls) == 1

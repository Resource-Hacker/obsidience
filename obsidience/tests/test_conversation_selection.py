"""Semantic admission plumbing, using inert structured model responses.

These tests attest context, authority and validation; live model probes must
separately establish that the selected model classifies natural language well.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
import json
from types import SimpleNamespace as NS

import pytest

from obsidience.harness.conversation import selection
from obsidience.harness.models.llm import ChatReply


def choice(outcome="answer", application=None, scope=None):
    return {"task_ref": selection.QUERY_REF if outcome == "answer" else selection.OPERATE_REF,
            "computer_outcome": outcome, "application": application, "computer_scope": scope}


@pytest.fixture
def admission(monkeypatch):
    query = NS(ref=selection.QUERY_REF, title="Actual Query title", kind="task",
               body="Actual accepted Query outcome.", meta={"model": "configured-query-model"})
    operate = NS(ref=selection.OPERATE_REF, title="Actual Computer Use title", kind="task",
                 body="Actual accepted computer outcome.", meta={"model": "different-operate-model"})
    agent = NS(ref=selection.EXECUTIVE_REF, kind="agent")
    scene = {"available": True, "fields": ["kind", "name", "title", "focused", "visible"],
             "surfaces": {"samsung": [["application", "teamfight_tactics", "TFT Normal lobby", True, True],
                                        ["application", "fixture.editor", "Document", False, True]],
                          "usb-c": [["pane", "reader", "Reader", False, True]]}}
    state = NS(notes={query.ref: query, operate.ref: operate, agent.ref: agent},
               assigned=[query, operate], scene=scene, calls=[], leases=[], releases=[],
               events=[], preferences=[], response=choice(), hook=None, error=None)
    model = NS(id="configured-query-model", supports_json_schema=True)
    monkeypatch.setattr(selection, "resolver", lambda **_kwargs: NS(resolve=state.notes.get))
    monkeypatch.setattr(selection, "assigned_tasks", lambda *_: state.assigned)
    monkeypatch.setattr(selection.SCENE, "activation_binding", lambda: deepcopy(state.scene))

    def resolve(preference, owner):
        state.preferences.append((preference, owner))
        return model

    @asynccontextmanager
    async def lease(spec):
        assert spec is model
        state.leases.append(spec)
        try:
            yield spec
        finally:
            state.releases.append(spec)

    async def chat(messages, **kwargs):
        state.calls.append((deepcopy(messages), deepcopy(kwargs)))
        if state.hook:
            await state.hook()
        if state.error:
            raise state.error
        return ChatReply(content=state.response if isinstance(state.response, str) else json.dumps(state.response),
                         finish_reason=getattr(state, "finish_reason", "stop"),
                         completion_tokens=35, prompt_tokens=800)

    monkeypatch.setattr(selection.model_runtime, "resolve_model", resolve)
    monkeypatch.setattr(selection.model_runtime, "lease", lease)
    monkeypatch.setattr(selection.llm, "chat", chat)
    monkeypatch.setattr(selection.trace, "emit", lambda *args: state.events.append(args))
    state.run = lambda text, **kwargs: asyncio.run(selection.select_task(text, "voice", **kwargs))
    return state


@pytest.mark.parametrize("utterance,outcome,scope", [
    ("Let's play normal TFT.", "action", "state"),
    ("Yes, start a normal game", "action", "state"),
    ("Can you start the match?", "action", "state"),
    ("Click normal game", "action", "input"),
    ("It's already up", "answer", None),
    ("Don't start the match", "answer", None),
])
def test_incident_requests_receive_context_before_the_structured_choice(admission, utterance, outcome, scope):
    admission.response = choice(outcome, "teamfight_tactics" if outcome == "action" else None, scope)
    context = "User: Click Normal in TFT.\nExecutive: The Normal tile was clicked."
    task, params, event = admission.run(utterance, conversation_context=context)
    assert task.ref == admission.response["task_ref"]
    assert params["request"] == utterance and params["computer_outcome"] == outcome
    assert event == "voice.activation" and params["source"] == "voice"
    assert params.get("computer_scope") == scope
    assert len(admission.calls) == len(admission.leases) == len(admission.releases) == 1
    messages, kwargs = admission.calls[0]
    payload = json.loads(messages[1]["content"])
    assert payload["objective"] == utterance and payload["recent_conversation"] == context
    assert payload["shell_scene"] == admission.scene
    assert payload["task_catalog"] == [
        {"task_ref": note.ref, "title": note.title, "outcome": note.body}
        for note in admission.assigned
    ]
    assert kwargs["reasoning_effort"] == "none" and kwargs["temperature"] == 0
    assert kwargs["max_tokens"] == 192 and "allowed_tools" not in kwargs
    assert kwargs["response_schema"]["properties"]["task_ref"]["enum"] == [selection.QUERY_REF, selection.OPERATE_REF]
    assert admission.preferences == [("configured-query-model", selection.EXECUTIVE_REF)]
    assert admission.events[0][:2] == ("model", "Task selection timing")
    assert utterance not in repr(admission.events)


def history(index=0):
    return {"scope": "historical_execution", "current_state": False, "run_id": f"past-{index}",
            "task_ref": selection.QUERY_REF, "status": "completed", "effect_dispatched": False,
            "tools": [{"tool": "task.complete"}]}


def test_historical_no_effect_evidence_cannot_leak_private_trace_material(admission):
    evidence = history() | {"obs": "private observation", "args": {"point": {"x": 1, "y": 2}}}
    evidence["tools"] = [{"tool": "computer.act", "target": {"kind": "application", "name": "teamfight_tactics", "window_id": "private-window"},
                          "verified_scope": "click", "delivery": "acknowledged", "semantic_postcondition_verified": False,
                          "args": {"point": {"x": 1, "y": 2}}, "_private_image_png": "private pixels"}]
    admission.run("It's already up", historical_evidence=[evidence])
    payload = json.loads(admission.calls[0][0][1]["content"])
    record = payload["historical_execution_evidence"][0]
    assert record["effect_dispatched"] is False and record["current_state"] is False
    assert record["tools"] == [{"tool": "computer.act", "target": {"kind": "application", "name": "teamfight_tactics"},
                                "verified_scope": "click", "delivery": "acknowledged", "semantic_postcondition_verified": False}]
    assert "private" not in json.dumps(payload) and '"point"' not in json.dumps(payload)
    many = [history(index) | {"tools": [{"tool": "task.complete"}] * 10} for index in range(6)]
    projected = selection.project_historical_evidence(many)
    assert [row["run_id"] for row in projected] == [f"past-{index}" for index in range(2, 6)]
    assert all(len(row["tools"]) == 8 for row in projected)


def test_context_bound_preserves_recent_whole_paragraphs_and_exact_request(admission):
    context = "old " * 4000 + "\n\nUser: Select Normal.\nExecutive: Clicked.\n\nUser: Start it."
    request = "  Please start it.  "
    _, params, _ = admission.run(request, conversation_context=context)
    payload = json.loads(admission.calls[0][0][1]["content"])
    assert params["request"] == payload["objective"] == request
    assert len(payload["recent_conversation"]) <= selection.MAX_CONTEXT_CHARS
    assert payload["recent_conversation"].endswith("User: Select Normal.\nExecutive: Clicked.\n\nUser: Start it.")
    assert "Earlier conversation omitted" in payload["recent_conversation"]


@pytest.mark.parametrize("response", [
    {}, [], {"tool": "computer.act", "args": {}},
    choice() | {"extra": "ignored authority"},
    choice() | {"task_ref": "Tasks/unknown"},
    choice() | {"computer_outcome": "action"},
    choice("action", "teamfight_tactics", "state") | {"task_ref": selection.QUERY_REF},
    choice("observation"), choice("action", "teamfight_tactics"),
    choice("action", None, "state"), choice("action", "invented-app", "state"),
    choice("launch", "fixture.editor"), choice("launch"),
    choice("answer", "teamfight_tactics"), choice("observe", "teamfight_tactics", "input"),
    '{"task_ref":"Tasks/query","task_ref":"Tasks/executive/operate","computer_outcome":"answer"}',
    '```json\n{"task_ref":"Tasks/query","computer_outcome":"answer"}\n```',
])
def test_invalid_or_incoherent_selection_never_falls_back_to_a_task(admission, response):
    admission.response = response
    with pytest.raises(selection.TaskSelectionError):
        admission.run("Start the match")
    assert len(admission.calls) == len(admission.releases) == 1
    assert all(event[0] == "model" for event in admission.events)


def test_exact_scene_app_ids_and_registered_launch_names_remain_valid(admission):
    admission.response = choice("action", "fixture.editor", "input")
    assert admission.run("Click Save")[1]["application"] == "fixture.editor"
    admission.response = choice("launch", "TFT")
    admission.scene = {"available": False, "reason": "unavailable"}
    assert admission.run("Open TFT")[1]["application"] == "teamfight_tactics"
    admission.response = choice("action", "teamfight_tactics", "state")
    with pytest.raises(selection.TaskSelectionError, match="absent"):
        admission.run("Start the match")


def test_unassigned_and_changed_tasks_cannot_be_admitted(admission):
    admission.assigned = admission.assigned[:1]
    admission.response = choice("action", "teamfight_tactics", "state")
    with pytest.raises(selection.TaskSelectionError, match="unavailable"):
        admission.run("Start the match")
    assert admission.calls[0][1]["response_schema"]["properties"]["task_ref"]["enum"] == [selection.QUERY_REF]
    admission.assigned = []
    with pytest.raises(selection.TaskSelectionError, match="Query Task is unavailable"):
        admission.run("Hello")
    assert len(admission.calls) == 1


def test_catalog_is_revalidated_after_model_selection(admission):
    async def removed():
        admission.assigned = []
    admission.hook = removed
    with pytest.raises(selection.TaskSelectionError, match="unavailable"):
        admission.run("Hello")
    assert len(admission.releases) == 1


@pytest.mark.parametrize("failure", ["exception", "truncated"])
def test_provider_failure_retains_no_raw_response_or_fallback(admission, failure):
    if failure == "exception":
        admission.error = RuntimeError("private provider payload")
    else:
        admission.finish_reason = "length"
    with pytest.raises(selection.TaskSelectionError) as error:
        admission.run("Start the match")
    assert "private provider payload" not in str(error.value)
    assert "private provider payload" not in repr(admission.events)
    assert len(admission.calls) == len(admission.releases) == 1


def test_cancelled_selection_releases_the_only_model_lease(admission):
    async def exercise():
        entered = asyncio.Event()
        async def block():
            entered.set()
            await asyncio.Event().wait()
        admission.hook = block
        pending = asyncio.create_task(selection.select_task("Start it", "text"))
        await entered.wait()
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
    asyncio.run(exercise())
    assert len(admission.calls) == len(admission.releases) == 1
    assert "cancelled" in repr(admission.events)


def test_oversized_request_is_rejected_before_model_admission(admission):
    with pytest.raises(selection.TaskSelectionError, match="bound"):
        admission.run("x" * (selection.MAX_REQUEST_CHARS + 1))
    assert not admission.calls and not admission.leases

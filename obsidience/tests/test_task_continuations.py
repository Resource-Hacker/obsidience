from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from obsidience.harness.capabilities.task import complete as task_complete
from obsidience.harness.capabilities.task import create as task_create
from obsidience.harness.config import CONFIG
from obsidience.harness.conversation.store import ConversationStore
from obsidience.harness.execution import executor, scheduler
from obsidience.harness.knowledge import index
from obsidience.harness.conversation.runtime import ConversationRuntime


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    # Continuation delivery uses the isolated ledger; its UI context projection
    # is covered separately and must not materialize this fixture in the live Vault.
    monkeypatch.setattr(ConversationRuntime, "publish_context", lambda _runtime: None)
    monkeypatch.setattr(CONFIG, "db_path", tmp_path / "continuations.sqlite3")
    result = index.Index()
    monkeypatch.setattr(index, "INDEX", result)
    yield result
    result.db.close()


def _record_run(ledger, run_id: str, trace: list[dict], *, status: str = "completed"):
    ledger.record_run(
        id=run_id,
        task_ref="Tasks/link",
        agent="Alexandria",
        started=1.0,
        finished=2.0,
        status=status,
        summary="Checked the exact candidate.",
        trace=json.dumps(trace),
    )


def _continuation(ledger, suffix: str = "one") -> dict:
    return ledger.create_continuation(
        caller_task_ref="Tasks/query",
        caller_run_id=f"caller-{suffix}",
        target_task_ref="Tasks/research/question",
        target_activation_key=f"activation-{suffix}",
        objective=f"Research objective {suffix}",
        conversation_id=f"conversation-{suffix}",
        reply_to_turn_id=f"turn-{suffix}",
        reply_source="text",
        await_publication=True,
    )


def test_run_trace_is_valid_bounded_json_and_retains_terminal_evidence() -> None:
    terminal = {
        "tool": "task.complete",
        "args": {
            "status": "completed",
            "outcome": "no_change",
            "evidence": ["Exact accepted evidence was unchanged."],
        },
        "accepted": True,
    }
    trace = [
        {"maintenance_candidate": {
            "target_task": "Tasks/link",
            "candidate_key": "a" * 20,
            "candidate_revision": "b" * 64,
            "candidate_refs": ["Articles/one"],
        }},
        *(
            {"tool": "vault.read", "args": {"ref": str(number)}, "obs": "x" * 4_000}
            for number in range(80)
        ),
        terminal,
    ]

    payload = executor.serialize_run_trace(trace)
    decoded = json.loads(payload)

    assert len(payload) <= executor.MAX_RUN_TRACE_CHARS
    assert decoded[0]["maintenance_candidate"]["candidate_key"] == "a" * 20
    assert decoded[-1] == terminal
    assert any("trace_truncated" in item for item in decoded)


def test_no_change_suppression_requires_controller_binding_and_terminal_evidence(ledger) -> None:
    activation = {
        "maintenance_candidate": {
            "target_task": "Tasks/link",
            "candidate_key": "a" * 20,
            "candidate_revision": "b" * 64,
            "candidate_refs": ["Articles/one", "Articles/two"],
        }
    }
    terminal = {
        "tool": "task.complete",
        "args": {
            "status": "completed",
            "summary": "No edit is justified.",
            "outcome": "no_change",
            "evidence": ["Both accepted Articles already agree."],
        },
        "accepted": True,
    }
    _record_run(ledger, "valid", [activation, terminal])
    _record_run(ledger, "missing-evidence", [
        activation,
        {**terminal, "args": {**terminal["args"], "evidence": []}},
    ])
    _record_run(ledger, "rejected-terminal", [
        activation,
        {**terminal, "accepted": False},
    ])
    _record_run(ledger, "failed-run", [activation, terminal], status="failed")

    assert ledger.maintenance_no_change_keys() == {
        ("Tasks/link", "a" * 20, "b" * 64),
    }


def test_continuation_resolves_only_from_approved_or_supported_no_change(ledger) -> None:
    first = _continuation(ledger, "approved")
    assert ledger.bind_continuation_handoff("caller-approved", "source-approved")
    assert ledger.bind_continuation_ingest("source-approved", "ingest-approved")
    ledger.record_review_decision(
        proposal_id="proposal-approved",
        run_id="ingest-approved",
        task_ref="Tasks/ingest",
        target="Articles/accepted.md",
        decision="approved",
    )
    outcome = ledger.record_review_decision(
        proposal_id="proposal-rejected",
        run_id="ingest-approved",
        task_ref="Tasks/ingest",
        target="Articles/rejected.md",
        decision="rejected",
    )
    assert outcome["approved_count"] == 1
    assert outcome["rejected_count"] == 1
    assert ledger.resolve_ingest_review("ingest-approved") == "ready"
    ready = ledger.continuation_for_caller("caller-approved")
    assert ready and ready["status"] == "ready"
    result = json.loads(ready["result"])
    assert result["disposition"] == "approved"
    assert result["review"]["approved_count"] == 1
    assert result["review"]["rejected_count"] == 1

    claimed = ledger.claim_continuation(first["id"])
    assert claimed and claimed["status"] == "claimed"
    assert ledger.claim_continuation(first["id"]) is None
    ledger.finish_continuation(first["id"], resumed_run_id="resume-one", completed=True)
    assert ledger.continuation_for_caller("caller-approved")["status"] == "resumed"

    second = _continuation(ledger, "no-change")
    assert ledger.resolve_research_no_change(
        "caller-no-change",
        "research-no-change",
        {"evidence": ["The accepted graph already answers it."]},
    )
    assert ledger.continuation_for_caller("caller-no-change")["status"] == "ready"

    third = _continuation(ledger, "rejected")
    ledger.bind_continuation_handoff("caller-rejected", "source-rejected")
    ledger.bind_continuation_ingest("source-rejected", "ingest-rejected")
    ledger.record_review_decision(
        proposal_id="proposal-only-rejected",
        run_id="ingest-rejected",
        task_ref="Tasks/ingest",
        target="Articles/not-accepted.md",
        decision="rejected",
    )
    assert ledger.resolve_ingest_review("ingest-rejected") == "rejected"
    assert ledger.continuation_for_caller("caller-rejected")["status"] == "rejected"
    assert second["id"] != third["id"]


def test_task_complete_fails_closed_and_distinguishes_auto_approved_change(ledger) -> None:
    task = SimpleNamespace(ref="Tasks/ingest", kind="task", meta={})
    base_context = {
        "task_note": task,
        "task": task.ref,
        "event": "source.inbox",
        "params": {"source_id": "source-one"},
    }
    invalid = task_complete.execute(
        {"status": "done", "summary": "Looks complete."},
        base_context,
    )
    assert invalid["accepted"] is False
    assert invalid["error"] == "status must be completed, failed, or review"

    unsupported = task_complete.execute(
        {"status": "completed", "summary": "No update."},
        base_context,
    )
    assert unsupported["accepted"] is False
    assert '"outcome":"no_change"' in unsupported["error"]

    supported = task_complete.execute(
        {
            "status": "completed",
            "summary": "No update.",
            "outcome": "no_change",
            "evidence": ["The exact Source repeats the accepted Article."],
        },
        base_context,
    )
    assert supported["accepted"] is True
    assert supported["outcome"] == "no_change"

    approved_context = {
        **base_context,
        "staged_proposals": [{
            "staged": "_staging/already-approved.md",
            "target": "Articles/published.md",
            "auto_approved": True,
        }],
    }
    approved = task_complete.execute(
        {"status": "completed", "summary": "Published."},
        approved_context,
    )
    assert approved["accepted"] is True
    assert approved["outcome"] == "changed"
    assert approved["evidence"] == [
        "Owner Auto-curate approved Articles/published.md"
    ]
    contradictory = task_complete.execute(
        {
            "status": "completed",
            "summary": "No update.",
            "outcome": "no_change",
            "evidence": ["Contradictory claim."],
        },
        approved_context,
    )
    assert contradictory["accepted"] is False
    assert "approved change" in contradictory["error"]

    reviewed_context = {
        **base_context,
        "run_id": "ingest-reviewed",
        "staged_proposals": [{
            "staged": "_staging/reviewed.md",
            "target": "Articles/reviewed.md",
            "action": "create",
        }],
    }
    ledger.record_review_decision(
        proposal_id="reviewed.md",
        run_id="ingest-reviewed",
        task_ref="Tasks/ingest",
        target="Articles/reviewed.md",
        decision="approved",
    )
    reviewed = task_complete.execute(
        {"status": "completed", "summary": "Published after owner review."},
        reviewed_context,
    )
    assert reviewed["accepted"] is True
    assert reviewed["outcome"] == "changed"
    assert reviewed["evidence"] == [
        "Owner review approved Articles/reviewed.md"
    ]


def test_task_create_waits_only_for_declared_research_targets(ledger, monkeypatch) -> None:
    monkeypatch.setattr(
        scheduler,
        "enqueue_event",
        lambda _task, _params: {
            "state": "started",
            "status": "pending",
            "position": 1,
            "reason": "",
        },
    )
    conversation_id = ledger.active_conversation_id()
    user_turn = ledger.append_conversation_turn(
        conversation_id=conversation_id,
        role="user",
        source="text",
        text="Find the current primary evidence.",
        run_id=None,
        reply_to=None,
        state="final",
    )
    context = {
        "task": "Tasks/query",
        "run_id": "caller-task-create",
        "interactive": True,
        "objective": "Find the current primary evidence.",
        "params": {
            "conversation_id": conversation_id,
            "reply_to_turn_id": user_turn["id"],
            "source": "voice",
        },
    }
    result = json.loads(task_create.execute({
        "task": "Tasks/research/question",
        "wait_for_result": True,
        "params": {"question": "Which primary source is current?"},
    }, context))
    assert result["waiting_for_result"] is True
    continuation = ledger.continuation_for_caller("caller-task-create")
    assert continuation
    assert continuation["target_task_ref"] == "Tasks/research/question"
    assert continuation["reply_to_turn_id"] == user_turn["id"]
    assert continuation["reply_source"] == "text"

    unbound = task_create.execute({
        "task": "Tasks/research/question",
        "wait_for_result": True,
    }, {
        **context,
        "run_id": "caller-unbound",
        "params": {},
    })
    assert "exact persisted user turn binding" in unbound

    assert "only Question or Learn" in task_create.execute({
        "task": "Tasks/link",
        "wait_for_result": True,
    }, {**context, "run_id": "caller-link"})
    assert "does not accept task.create" in task_create.execute({
        "task": "Tasks/research/model",
    }, {**context, "run_id": "caller-model"})


def test_source_added_skips_only_trusted_same_research_learn(monkeypatch) -> None:
    learn = scheduler.load_note("Tasks/research/learn.md")
    assert learn is not None
    monkeypatch.setattr(scheduler, "iter_notes", lambda: [learn])
    monkeypatch.setattr(
        scheduler.INDEX,
        "run",
        lambda run_id: (
            {"id": run_id, "task_ref": "Tasks/research/question"}
            if run_id == "trusted-run"
            else None
        ),
    )
    calls = []
    monkeypatch.setattr(
        scheduler,
        "enqueue_event",
        lambda task, params: calls.append((task.ref, params)) or {
            "state": "started",
            "status": "pending",
            "position": 1,
        },
    )
    ordinary = {"source_id": "source-one", "source_class": "external"}

    assert scheduler.enqueue_named_event(
        "source.added",
        ordinary,
        handled_by_task_ref="Tasks/research/question",
        handled_by_run_id="trusted-run",
    ) == []
    assert calls == []

    dispatched = scheduler.enqueue_named_event(
        "source.added",
        ordinary,
        handled_by_task_ref="Tasks/research/question",
        handled_by_run_id="forged-run",
    )
    assert [item["task"] for item in dispatched] == ["Tasks/research/learn"]
    assert len(calls) == 1


def test_deferred_observation_finalization_survives_a_new_index(ledger) -> None:
    store = ConversationStore(ledger)
    runtime = ConversationRuntime()
    runtime._conversation = store
    runtime.defer_observation_session("conversation-closed", "chat.new_conversation")

    second = index.Index()
    try:
        assert second.deferred_observation_finalizations() == [{
            "conversation_id": "conversation-closed",
            "session_boundary": "chat.new_conversation",
            "created_at": pytest.approx(
                second.deferred_observation_finalizations()[0]["created_at"]
            ),
            "updated_at": pytest.approx(
                second.deferred_observation_finalizations()[0]["updated_at"]
            ),
            "last_error": "",
        }]
        second.complete_observation_finalization("conversation-closed")
        assert second.deferred_observation_finalizations() == []
    finally:
        second.db.close()


def test_continuation_resume_appends_one_reply_to_the_original_turn(ledger, monkeypatch) -> None:
    store = ConversationStore(ledger)
    runtime = ConversationRuntime()
    runtime._conversation = store
    user_turn = asyncio.run(store.append(
        role="user",
        source="text",
        text="What is the current primary answer?",
    ))
    continuation = ledger.create_continuation(
        caller_task_ref="Tasks/query",
        caller_run_id="caller-resume",
        target_task_ref="Tasks/research/question",
        target_activation_key="activation-resume",
        objective=user_turn["text"],
        conversation_id=user_turn["conversation_id"],
        reply_to_turn_id=user_turn["id"],
        reply_source="text",
    )
    ledger.resolve_research_no_change(
        "caller-resume",
        "research-resume",
        {"evidence": ["The direct evidence was already represented."]},
    )
    claimed = ledger.claim_continuation(continuation["id"])
    assert claimed is not None
    seen = []

    async def prepare(_turn, **_kwargs):
        return ""

    async def run_task(_task, **kwargs):
        seen.append(kwargs)
        return {
            "status": "completed",
            "run_id": "resume-run",
            "summary": "The accepted answer remains current.",
        }

    monkeypatch.setattr(runtime, "prepare_immediate_observations", prepare)
    monkeypatch.setattr(executor, "run_task", run_task)

    first = asyncio.run(runtime.resume_continuation(claimed))
    second = asyncio.run(runtime.resume_continuation(claimed))

    assert first["status"] == second["status"] == "completed"
    reply = ledger.assistant_reply_for(user_turn["id"])
    assert reply and reply["text"] == "The accepted answer remains current."
    assert len(ledger.conversation_turns(store.conversation_id)) == 2
    assert len(seen) == 1
    assert seen[0]["runtime_params"]["event"] == "task.continue"
    assert seen[0]["runtime_params"]["continuation_result"]["disposition"] == "no_change"
    assert seen[0]["conversation_evidence"] == []


@pytest.mark.parametrize("fault", [None, "missing_binding", "wrong_conversation", "wrong_task", "wrong_objective", "invalid_scope"])
def test_computer_continuation_restores_exact_recorded_intent_without_reselection(ledger, monkeypatch, fault):
    from obsidience.harness.conversation import runtime as runtime_module

    store = ConversationStore(ledger)
    runtime = ConversationRuntime(store)
    user = asyncio.run(store.append(role="user", source="text", text="Start the match"))
    request = {"computer_outcome": "action", "computer_scope": "state",
               "application": "teamfight_tactics", "operation": "computer_use"}
    activation = {"interactive_turn": {"conversation_id": store.conversation_id,
                                       "reply_to_turn_id": user["id"]},
                  "computer_request": dict(request)}
    if fault == "missing_binding":
        activation.pop("computer_request")
    elif fault == "wrong_conversation":
        activation["interactive_turn"]["conversation_id"] = "conversation-other"
    elif fault == "invalid_scope":
        activation["computer_request"]["computer_scope"] = "invented"
    ledger.record_run(
        id="caller-computer", task_ref="Tasks/query" if fault == "wrong_task" else "Tasks/executive/operate",
        objective="Other request" if fault == "wrong_objective" else user["text"],
        agent="Executive", started=1, finished=2, status="waiting", summary="Waiting",
        trace=json.dumps([activation]),
    )
    continuation = ledger.create_continuation(
        caller_task_ref="Tasks/executive/operate", caller_run_id="caller-computer",
        target_task_ref="Tasks/research/question", target_activation_key="computer-question",
        objective=user["text"], conversation_id=store.conversation_id,
        reply_to_turn_id=user["id"], reply_source="text",
    )
    ledger.resolve_research_no_change("caller-computer", "research-computer", {"evidence": ["Research result"]})
    claimed = ledger.claim_continuation(continuation["id"])
    calls = []

    async def forbidden_selection(*_args, **_kwargs):
        raise AssertionError("A continuation must not classify the owner request again")

    async def prepare(_turn, **_kwargs):
        return "exact originating context"

    async def execute(task, **kwargs):
        calls.append((task, kwargs))
        return {"status": "failed", "summary": "fixture performs no computer action"}

    monkeypatch.setattr(runtime_module, "select_task", forbidden_selection)
    monkeypatch.setattr(runtime, "prepare_immediate_observations", prepare)
    monkeypatch.setattr(executor, "run_task", execute)
    if fault:
        with pytest.raises(RuntimeError, match="computer continuation"):
            asyncio.run(runtime.resume_continuation(claimed))
        assert calls == []
    else:
        result = asyncio.run(runtime.resume_continuation(claimed))
        assert result["status"] == "failed"
        assert len(calls) == 1
        task, fields = calls[0]
        assert task.ref == "Tasks/executive/operate"
        assert {key: fields["runtime_params"][key] for key in request} == request
        assert fields["conversation_context"] == "exact originating context"
        assert fields["conversation_evidence"] == []


def test_continuation_rejects_changed_original_user_binding_before_execution(ledger, monkeypatch):
    store = ConversationStore(ledger)
    runtime = ConversationRuntime(store)
    user = asyncio.run(store.append(role="user", source="text", text="A question"))
    continuation = ledger.create_continuation(
        caller_task_ref="Tasks/query", caller_run_id="caller-binding",
        target_task_ref="Tasks/research/question", target_activation_key="binding-question",
        objective=user["text"], conversation_id=store.conversation_id,
        reply_to_turn_id=user["id"], reply_source="text",
    )
    ledger.resolve_research_no_change("caller-binding", "research-binding", {"evidence": ["Result"]})
    claimed = ledger.claim_continuation(continuation["id"])
    with pytest.raises(RuntimeError, match="exact persisted user turn"):
        asyncio.run(runtime.resume_continuation({**claimed, "conversation_id": "conversation-other"}))
    with pytest.raises(RuntimeError, match="recorded caller binding"):
        asyncio.run(runtime.resume_continuation({**claimed, "objective": "Different objective"}))

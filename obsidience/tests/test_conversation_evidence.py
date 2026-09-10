from __future__ import annotations

import asyncio
import copy
import json
import time

import pytest

from obsidience.harness.conversation.evidence import historical_evidence, historical_public_replies
from obsidience.harness.conversation.store import ConversationStore


@pytest.fixture
def conversation(isolated_task_ledger):
    return ConversationStore(isolated_task_ledger)


def _pair(conversation, run_id, tools, *, status="completed", task="Tasks/query"):
    async def append():
        user = await conversation.append(role="user", source="realtime", text="Start a normal game")
        conversation.index.record_run(
            id=run_id, task_ref=task, agent="Executive", started=1, finished=2,
            status=status, summary="I've launched it and started the match.",
            trace=json.dumps([{"interactive_turn": {
                "conversation_id": conversation.conversation_id,
                "reply_to_turn_id": user["id"],
            }}, *tools]),
        )
        assistant = await conversation.append(
            role="assistant", source="realtime", text="I've started the match.",
            run_id=run_id, reply_to=user["id"],
        )
        return user, assistant

    return asyncio.run(append())


def _projection(conversation, **kwargs):
    return historical_evidence(
        conversation, conversation_id=conversation.conversation_id,
        before_sequence=100, **kwargs,
    )


def _click():
    return {
        "tool": "computer.act", "args": {"application": "TFT", "point": {"x": 500, "y": 400}},
        "completion_evidence": {
            "verified": True, "target": {"kind": "application", "name": "teamfight_tactics"},
            "effect": {"kind": "click", "label": "NORMAL"},
            "verified_scope": "click", "semantic_postcondition_verified": False,
        },
    }


@pytest.mark.parametrize("status", ["completed", "failed"])
def test_query_summary_cannot_fabricate_a_historical_effect(conversation, status):
    _pair(conversation, "query-1", [{
        "tool": "task.complete", "args": {
            "summary": "I've started it", "outcome": "action",
            "evidence": ["I clicked Play"],
        }, "accepted": True,
    }], status=status)

    record = _projection(conversation)[0]
    assert record["status"] == status
    assert record["effect_dispatched"] is False
    assert record["evidence_available"] is True
    assert record["tools"] == [{"tool": "task.complete"}]
    assert "summary" not in json.dumps(record)


def test_actual_normal_click_is_historical_scoped_evidence_not_current_game_state(conversation):
    _pair(conversation, "normal-click", [_click()], task="Tasks/executive/operate")
    record = _projection(conversation)[0]
    assert record["scope"] == "historical_execution"
    assert record["current_state"] is False
    assert record["effect_scope"] == "computer"
    assert record["effect_dispatched"] is True
    assert record["tools"] == [{
        "tool": "computer.act", "verified": True,
        "target": {"kind": "application", "name": "teamfight_tactics"},
        "verified_scope": "click", "delivery": "acknowledged",
        "semantic_postcondition_verified": False,
    }]


@pytest.mark.parametrize("field,value", [
    ("conversation_id", "conversation-other"), ("reply_to_turn_id", "turn-other"),
])
def test_cross_conversation_or_wrong_reply_run_binding_is_not_projected(conversation, field, value):
    _pair(conversation, "wrong-binding", [_click()])
    row = conversation.index.run("wrong-binding")
    trace = json.loads(row["trace"])
    trace[0]["interactive_turn"][field] = value
    conversation.index.record_run(**{**row, "trace": json.dumps(trace)})
    assert _projection(conversation) == []


def test_legacy_run_without_interactive_metadata_keeps_exact_reply_link(conversation):
    _pair(conversation, "legacy", [])
    row = conversation.index.run("legacy")
    conversation.index.record_run(**{**row, "trace": "[]"})
    assert _projection(conversation)[0]["effect_dispatched"] is False


@pytest.mark.parametrize("change", [
    "wrong_application", "stale", "interrupted", "unverified", "semantic_claim", "wrong_scope",
])
def test_incoherent_or_stale_witness_never_proves_dispatch(conversation, change):
    entry = _click()
    if change == "wrong_application":
        entry["args"]["application"] = "world_of_warcraft"
    elif change == "stale":
        entry["completion_evidence"]["stale"] = True
    elif change == "interrupted":
        entry["interrupted"] = True
    elif change == "unverified":
        entry["completion_evidence"]["verified"] = 1
    elif change == "semantic_claim":
        entry["completion_evidence"]["semantic_postcondition_verified"] = True
    else:
        entry["completion_evidence"]["verified_scope"] = "game_started"
    _pair(conversation, "incoherent", [entry])
    record = _projection(conversation)[0]
    assert record["effect_dispatched"] is None
    assert record["tools"] == [{"tool": "computer.act", "verified": False}]


def test_raw_observation_arguments_private_identity_and_model_summary_do_not_escape(conversation):
    entry = _click()
    entry["obs"] = "PRIVATE_OBSERVATION"
    entry["args"].update({"target": "PRIVATE_LABEL", "capture_token": "PRIVATE_CAPTURE"})
    entry["completion_evidence"]["target"].update({"pid": 987654, "address": "PRIVATE_WINDOW"})
    entry["completion_evidence"].update({"_private_image_png": "PRIVATE_PIXELS", "point": [500, 400]})
    _pair(conversation, "privacy", [entry])
    before = copy.deepcopy(conversation.index.run("privacy"))
    encoded = json.dumps(_projection(conversation))
    assert "PRIVATE" not in encoded
    assert all(key not in encoded for key in ("point", "capture", "pid", "args", "obs", "summary"))
    assert conversation.index.run("privacy") == before


@pytest.mark.parametrize("tool,scope", [
    ("application.launch", "application_ready"), ("window.activate", "focus"),
    ("window.place", "placement"), ("computer.observe", "observation"),
])
def test_prior_state_witness_does_not_invent_a_dispatched_click(conversation, tool, scope):
    target = {"kind": "application", "name": "teamfight_tactics"}
    args = {"application": "TFT"} if tool == "application.launch" else {"target": target}
    _pair(conversation, "state-only", [{
        "tool": tool, "args": args,
        "completion_evidence": {"verified": True, "target": target},
    }])
    record = _projection(conversation)[0]
    assert record["tools"][0]["verified_scope"] == scope
    assert record["effect_dispatched"] is (False if tool == "computer.observe" else None)
    assert "delivery" not in record["tools"][0]


@pytest.mark.parametrize("trace", ["null", "[1]", "not-json", '[{"tool": "INVALID PRIVATE DATA"}]'])
def test_missing_or_malformed_trace_is_unknown_not_no_effect(conversation, trace):
    _pair(conversation, "invalid-trace", [])
    row = conversation.index.run("invalid-trace")
    conversation.index.record_run(**{**row, "trace": trace})
    record = _projection(conversation)[0]
    assert record["evidence_available"] is False
    assert record["effect_dispatched"] is None
    assert record["tools"] == []


def test_projection_is_bounded_and_does_not_lose_an_earlier_effect(conversation):
    for i in range(6):
        _pair(conversation, f"run-{i}", [_click(), *[{"tool": "vault.read"}] * 10])
    records = _projection(conversation, limit=999)
    assert [record["run_id"] for record in records] == ["run-2", "run-3", "run-4", "run-5"]
    assert all(len(record["tools"]) == 8 for record in records)
    assert all(record["omitted_tool_count"] == 3 for record in records)
    assert all(record["effect_dispatched"] is True for record in records)
    earlier = historical_evidence(
        conversation, conversation_id=conversation.conversation_id, before_sequence=5,
    )
    assert [record["run_id"] for record in earlier] == ["run-0", "run-1"]


def test_existing_ledger_lock_covers_pair_selection_and_exact_run_read(conversation, monkeypatch):
    _pair(conversation, "locked", [])
    read = conversation.index.run

    def checked_read(run_id):
        assert conversation.index.lock._is_owned()
        return read(run_id)

    monkeypatch.setattr(conversation.index, "run", checked_read)
    assert _projection(conversation)[0]["run_id"] == "locked"


def _failed_public_reply(conversation, *, run_id="failed-reply", status="failed", user=None):
    if user is None:
        user = asyncio.run(conversation.append(role="user", source="realtime", text="What level is Squander?"))
    text = "Did you mean Squancher?"
    conversation.index.record_run(
        id=run_id, task_ref="Tasks/query", agent="Executive", started=user["created_at"],
        finished=time.time(), status=status, summary=text,
        trace=json.dumps([
            {"interactive_turn": {"conversation_id": conversation.conversation_id,
                                  "reply_to_turn_id": user["id"]}},
            {"tool": "task.complete", "accepted": True, "args": {"status": status, "summary": text}},
        ]),
    )
    return user


@pytest.mark.parametrize("status", ["failed", "review"])
def test_public_failure_clarification_is_recovered_as_exact_historical_dialogue(conversation, status):
    user = _failed_public_reply(conversation, status=status)
    current = asyncio.run(conversation.append(role="user", source="realtime", text="Yes, Squancher"))
    replies = historical_public_replies(
        conversation, conversation_id=conversation.conversation_id, before_sequence=current["sequence"],
    )
    assert replies == {user["id"]: {"run_id": "failed-reply", "status": status, "text": "Did you mean Squancher?"}}
    assert historical_public_replies(
        conversation, conversation_id=conversation.conversation_id, before_sequence=user["sequence"],
    ) == {}


@pytest.mark.parametrize("fault", ["unaccepted", "raw_error", "wrong_conversation", "wrong_user", "oversized", "summary_mismatch", "ambiguous_runs"])
def test_public_dialogue_never_uses_unaccepted_unbound_or_ambiguous_results(conversation, fault):
    user = _failed_public_reply(conversation)
    row = conversation.index.run("failed-reply")
    trace = json.loads(row["trace"])
    if fault == "unaccepted":
        trace[1]["accepted"] = False
    elif fault == "raw_error":
        trace = [trace[0], {"error": "PRIVATE RAW ERROR"}]
    elif fault == "wrong_conversation":
        trace[0]["interactive_turn"]["conversation_id"] = "conversation-other"
    elif fault == "wrong_user":
        trace[0]["interactive_turn"]["reply_to_turn_id"] = "turn-other"
    elif fault == "oversized":
        trace[1]["args"]["summary"] = "x" * 2001
        row["summary"] = "x" * 2001
    elif fault == "summary_mismatch":
        row["summary"] = "Different public response"
    else:
        _failed_public_reply(conversation, run_id="second-reply", user=user)
    conversation.index.record_run(**{**row, "trace": json.dumps(trace)})
    assert historical_public_replies(
        conversation, conversation_id=conversation.conversation_id, before_sequence=None,
    ) == {}


def test_existing_public_reply_wins_and_a_reused_run_id_is_rejected(conversation):
    user = _failed_public_reply(conversation)
    asyncio.run(conversation.append(
        role="assistant", source="realtime", text="Canonical reply", reply_to=user["id"], run_id="failed-reply",
    ))
    assert historical_public_replies(
        conversation, conversation_id=conversation.conversation_id, before_sequence=None,
    ) == {}

    other = _failed_public_reply(conversation, run_id="reused")
    # A run already attached to another reply is not a new public response.
    conversation.index.db.execute("UPDATE conversation_turns SET run_id='reused' WHERE role='assistant'")
    conversation.index.db.commit()
    assert other["id"] not in historical_public_replies(
        conversation, conversation_id=conversation.conversation_id, before_sequence=None,
    )


@pytest.mark.parametrize("finished,available", [(199.0, True), (200.0, True), (201.0, False), (None, False), (99.0, False)])
def test_public_reply_must_finish_by_exact_request_admission(conversation, finished, available):
    user = _failed_public_reply(conversation)
    current = asyncio.run(conversation.append(role="user", source="realtime", text="Yes, Squancher"))
    with conversation.index.lock:
        conversation.index.db.execute("UPDATE conversation_turns SET created_at=100 WHERE id=?", (user["id"],))
        conversation.index.db.execute("UPDATE conversation_turns SET created_at=200 WHERE id=?", (current["id"],))
        conversation.index.db.execute("UPDATE runs SET started=100,finished=? WHERE id='failed-reply'", (finished,))
        conversation.index.db.commit()
    replies = historical_public_replies(
        conversation, conversation_id=conversation.conversation_id, before_sequence=current["sequence"],
    )
    assert (user["id"] in replies) is available


def test_future_continuation_and_reply_do_not_rewrite_prior_context(conversation):
    user = _failed_public_reply(conversation)
    current = asyncio.run(conversation.append(role="user", source="realtime", text="Yes, Squancher"))
    _failed_public_reply(conversation, user=user, run_id="later-continuation")
    later = asyncio.run(conversation.append(
        role="assistant", source="realtime", text="Later response", reply_to=user["id"], run_id="failed-reply",
    ))
    with conversation.index.lock:
        conversation.index.db.executemany(
            "UPDATE conversation_turns SET created_at=? WHERE id=?",
            [(100, user["id"]), (200, current["id"]), (300, later["id"])],
        )
        conversation.index.db.execute("UPDATE runs SET started=101,finished=150 WHERE id='failed-reply'")
        conversation.index.db.execute("UPDATE runs SET started=160,finished=250 WHERE id='later-continuation'")
        conversation.index.db.commit()
    replies = historical_public_replies(
        conversation, conversation_id=conversation.conversation_id, before_sequence=current["sequence"],
    )
    assert replies[user["id"]]["text"] == "Did you mean Squancher?"
    assert historical_public_replies(
        conversation, conversation_id=conversation.conversation_id, before_sequence=None,
    ) == {}


def test_missing_request_boundary_cannot_recover_replies_from_the_future(conversation):
    user = _failed_public_reply(conversation)
    assert historical_public_replies(
        conversation, conversation_id=conversation.conversation_id, before_sequence=user["sequence"] + 1,
    ) == {}


def test_review_run_can_retain_its_accepted_completed_public_summary(conversation):
    user = _failed_public_reply(conversation, status="review")
    row = conversation.index.run("failed-reply")
    entries = json.loads(row["trace"])
    entries[1]["args"]["status"] = "completed"
    conversation.index.record_run(**{**row, "trace": json.dumps(entries)})
    result = historical_public_replies(
        conversation, conversation_id=conversation.conversation_id, before_sequence=None,
    )
    assert result[user["id"]] == {"run_id": "failed-reply", "status": "review", "text": "Did you mean Squancher?"}

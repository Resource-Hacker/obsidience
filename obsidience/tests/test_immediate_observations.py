from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from obsidience.harness import config
from obsidience.harness.conversation import observations as turn_memory
from obsidience.harness.conversation.store import ConversationStore
from obsidience.harness.execution import executor, scheduler
from obsidience.harness.knowledge import index as indexer
from obsidience.harness.knowledge import source
from obsidience.harness.knowledge import vault as knowledge_vault
from obsidience.harness.knowledge.vault import load_note, write_note
from obsidience.harness.conversation import runtime as conversation_runtime
from obsidience.harness.models.context import PayloadCount


@pytest.fixture(autouse=True)
def owner_enabled_observation_policy(monkeypatch):
    # These lifecycle tests isolate compaction from owner policy. Permission
    # inheritance and disabled writers are exercised in test_auto_curate_task.
    monkeypatch.setattr(turn_memory, "auto_curate_enabled", lambda _target: True)


def _summary(goal: str) -> str:
    return (
        f"Goal: {goal}\n\nConstraints and corrections: None recorded.\n\n"
        "Verified state: No external state attested.\n\nOutstanding: None recorded."
    )


def test_immediate_context_compacts_into_cumulative_temporary_article(
    monkeypatch, tmp_path,
) -> None:
    vault = tmp_path / "vault"
    monkeypatch.setattr(indexer.CONFIG, "db_path", tmp_path / "context.sqlite3")
    monkeypatch.setattr(turn_memory.CONFIG, "vault_dir", vault)
    test_index = indexer.Index()
    store = ConversationStore(test_index)
    sync_calls = 0

    def count_sync(*_args, **_kwargs) -> None:
        nonlocal sync_calls
        sync_calls += 1

    monkeypatch.setattr(test_index, "sync", count_sync)

    async def append_pair(user_text: str, reply_text: str) -> tuple[dict, dict]:
        user = await store.append(role="user", source="realtime", text=user_text)
        assistant = await store.append(
            role="assistant",
            source="realtime",
            text=reply_text,
            reply_to=user["id"],
        )
        return user, assistant

    _first_user, first_reply = asyncio.run(append_pair("First request", "First reply"))
    initial = turn_memory.project_immediate_observations(
        store,
        conversation_id=store.conversation_id,
    )
    assert "User: First request\nExecutive: First reply" in initial["body"]
    immediate = load_note(turn_memory.IMMEDIATE_OBSERVATIONS_PATH)
    assert immediate is not None
    assert immediate.meta["kind"] == "knowledge"
    assert immediate.meta["observation_scope"] == "immediate"
    assert immediate.meta["retrieval"] is False
    assert immediate.meta["immediate"] is True
    assert immediate.meta["conversation_id"] == store.conversation_id
    assert immediate.title == "Current conversation"
    assert immediate.path.endswith("Immediate Observations/current-conversation.md")

    created = turn_memory.append_temporary_observation(
        {
            "text": _summary("The owner made a first request and received a first reply."),
            "related_refs": [],
        },
        {
            "curation_mode": "compaction",
            "origin_task_ref": turn_memory.IMMEDIATE_COMPACT_TASK_REF,
            "target_path": str(turn_memory.EXECUTIVE_TEMPORARY_PATH),
            "turn_id": "compact-first",
            "conversation_id": store.conversation_id,
            "through_sequence": first_reply["sequence"],
        },
    )
    assert created["status"] == "appended"
    assert turn_memory.latest_context_compaction(store.conversation_id) is None
    turn_memory.commit_context_compaction(
        conversation_id=store.conversation_id,
        through_sequence=first_reply["sequence"],
        turn_id="compact-first",
    )

    compacted = turn_memory.project_immediate_observations(
        store,
        conversation_id=store.conversation_id,
    )
    assert "Cumulative Temporary Observation" in compacted["body"]
    assert "The owner made a first request" in compacted["body"]
    assert "User: First request" not in compacted["body"]
    assert compacted["compacted_through"] == first_reply["sequence"]

    asyncio.run(append_pair("Second request", "Second reply"))
    continued = turn_memory.project_immediate_observations(
        store,
        conversation_id=store.conversation_id,
    )
    assert "The owner made a first request" in continued["body"]
    assert "User: Second request\nExecutive: Second reply" in continued["body"]
    assert "User: First request" not in continued["body"]
    assert sync_calls == 1
    test_index.db.close()


def test_compaction_summary_uses_the_larger_bounded_temporary_contract(
    monkeypatch, tmp_path,
) -> None:
    monkeypatch.setattr(turn_memory.CONFIG, "vault_dir", tmp_path / "vault")
    summary = (
        "## Goal\nKeep the exact objective.\n\n"
        "## Constraints and corrections\nUse the corrected constraint.\n\n"
        "## Verified state\nOne result is verified.\n\n"
        "## Outstanding\nOne question remains."
    )
    result = turn_memory.append_temporary_observation(
        {"text": summary, "related_refs": []},
        {
            "curation_mode": "compaction",
            "origin_task_ref": turn_memory.IMMEDIATE_COMPACT_TASK_REF,
            "target_path": str(turn_memory.EXECUTIVE_TEMPORARY_PATH),
            "turn_id": "compact-large",
            "conversation_id": "conversation-test",
            "through_sequence": 2,
        },
    )
    note = load_note(result["ref"] + ".md")
    assert note is not None
    assert note.meta["kind"] == "knowledge"
    assert note.meta["observation_scope"] == "temporary"
    assert note.meta["retrieval"] is False
    assert note.meta["compaction"] is True
    assert note.meta["compaction_committed"] is False
    assert note.body.strip() == summary


@pytest.mark.parametrize("related_ref", [
    turn_memory.IMMEDIATE_OBSERVATIONS_REF,
    "Agents/Executive/Observations/Immediate%20Observations/current-conversation.md",
    "/Agents/Executive/Observations/Immediate%20Observations/current-conversation.md#Context",
    "[[Agents/Executive/Observations/Immediate%20Observations/current-conversation.md|Conversation]]",
])
def test_compaction_accepts_exact_article_reference_spellings(
    monkeypatch, tmp_path, related_ref,
) -> None:
    monkeypatch.setattr(turn_memory.CONFIG, "vault_dir", tmp_path / "vault")
    write_note(str(turn_memory.IMMEDIATE_OBSERVATIONS_PATH), {
        "kind": "knowledge", "title": "Current conversation", "immediate": True,
    }, "Completed conversation prefix.")
    args = {"text": _summary("A bounded summary."), "related_refs": [
        related_ref, turn_memory.IMMEDIATE_OBSERVATIONS_REF,
    ]}
    runtime = {
        "curation_mode": "compaction",
        "origin_task_ref": turn_memory.IMMEDIATE_COMPACT_TASK_REF,
        "target_path": str(turn_memory.EXECUTIVE_TEMPORARY_PATH),
        "turn_id": "compact-encoded-reference",
        "conversation_id": "conversation-reference-test",
        "through_sequence": 2,
    }
    result = turn_memory.append_temporary_observation(args, runtime)
    assert result["status"] == "appended"
    note = load_note(result["ref"] + ".md")
    assert note.meta["related_refs"] == [f"[[{turn_memory.IMMEDIATE_OBSERVATIONS_REF}]]"]
    assert note.meta["compaction_committed"] is False
    assert turn_memory.append_temporary_observation(args, runtime)["status"] == "existing"
    committed = turn_memory.commit_context_compaction(
        conversation_id=runtime["conversation_id"], through_sequence=2,
        turn_id=runtime["turn_id"],
    )
    assert committed.ref == result["ref"]
    assert turn_memory.latest_context_compaction(runtime["conversation_id"]).ref == committed.ref


@pytest.mark.parametrize("related_ref", [
    "Missing/Immediate%20Observations/current-conversation.md",
    "Agents/Executive/Observations/Immediate%2520Observations/current-conversation.md",
    "../Agents/Executive/Observations/Immediate%20Observations/current-conversation.md",
    "%2e%2e/Agents/Executive/Observations/Immediate%20Observations/current-conversation.md",
    "current-conversation",
    "Current conversation",
])
def test_compaction_rejects_nonexact_references_without_partial_write(
    monkeypatch, tmp_path, related_ref,
) -> None:
    monkeypatch.setattr(turn_memory.CONFIG, "vault_dir", tmp_path / "vault")
    write_note(str(turn_memory.IMMEDIATE_OBSERVATIONS_PATH), {
        "kind": "knowledge", "title": "Current conversation", "immediate": True,
    }, "Completed conversation prefix.")
    before = {p: p.read_bytes() for p in turn_memory.CONFIG.vault_dir.rglob("*.md")}
    with pytest.raises(ValueError, match="does not resolve exactly"):
        turn_memory.append_temporary_observation({
            "text": _summary("A bounded summary."), "related_refs": [related_ref],
        }, {
            "curation_mode": "compaction",
            "origin_task_ref": turn_memory.IMMEDIATE_COMPACT_TASK_REF,
            "target_path": str(turn_memory.EXECUTIVE_TEMPORARY_PATH),
            "turn_id": "compact-invalid-reference",
            "conversation_id": "conversation-reference-test", "through_sequence": 2,
        })
    assert {p: p.read_bytes() for p in turn_memory.CONFIG.vault_dir.rglob("*.md")} == before


def test_observation_context_is_graph_visible_but_not_retrievable(
    monkeypatch, tmp_path,
) -> None:
    vault = tmp_path / "vault"
    monkeypatch.setattr(indexer.CONFIG, "db_path", tmp_path / "context-index.sqlite3")
    monkeypatch.setattr(turn_memory.CONFIG, "vault_dir", vault)
    test_index = indexer.Index()
    store = ConversationStore(test_index)
    turn_memory.project_immediate_observations(
        store,
        conversation_id=store.conversation_id,
    )
    test_index.sync(embed=False)

    graph_nodes = {node["id"]: node for node in test_index.graph()["nodes"]}
    assert turn_memory.IMMEDIATE_OBSERVATIONS_REF in graph_nodes
    assert "observation_scope" not in graph_nodes[turn_memory.IMMEDIATE_OBSERVATIONS_REF]
    assert test_index.db.execute(
        "SELECT count(*) FROM notes_fts WHERE ref=?",
        (turn_memory.IMMEDIATE_OBSERVATIONS_REF,),
    ).fetchone()[0] == 0
    assert test_index.db.execute(
        "SELECT count(*) FROM embeddings WHERE ref=?",
        (turn_memory.IMMEDIATE_OBSERVATIONS_REF,),
    ).fetchone()[0] == 0
    test_index.db.close()


def test_compaction_requires_exact_task_and_discards_failed_output(
    monkeypatch, tmp_path,
) -> None:
    monkeypatch.setattr(turn_memory.CONFIG, "vault_dir", tmp_path / "vault")
    runtime = {
        "curation_mode": "compaction",
        "origin_task_ref": turn_memory.IMMEDIATE_COMPACT_TASK_REF,
        "target_path": str(turn_memory.EXECUTIVE_TEMPORARY_PATH),
        "turn_id": "compact-boundary",
        "conversation_id": "conversation-boundary",
        "through_sequence": 4,
    }
    with pytest.raises(ValueError, match="exact Compact Task"):
        turn_memory.append_temporary_observation(
            {"text": _summary("Pending summary"), "related_refs": []},
            runtime | {"origin_task_ref": "Tasks/query"},
        )
    with pytest.raises(ValueError, match="exact Compact Task"):
        turn_memory.append_temporary_observation(
            {"text": _summary("Pending summary"), "related_refs": []},
            runtime | {"target_path": "Agents/Darwin/Observations/Temporary Observations"},
        )
    with pytest.raises(ValueError, match="does not resolve exactly"):
        turn_memory.append_temporary_observation(
            {"text": _summary("Pending summary"), "related_refs": ["Missing/Article"]},
            runtime,
        )

    result = turn_memory.append_temporary_observation(
        {"text": _summary("Pending summary"), "related_refs": []}, runtime,
    )
    assert turn_memory.latest_context_compaction("conversation-boundary") is None
    assert turn_memory.discard_pending_context_compaction(
        conversation_id="conversation-boundary",
        through_sequence=4,
        turn_id="compact-boundary",
    ) is True
    assert load_note(result["ref"] + ".md") is None


def test_expired_compaction_cannot_ride_in_immediate_observations(
    monkeypatch, tmp_path,
) -> None:
    monkeypatch.setattr(turn_memory.CONFIG, "vault_dir", tmp_path / "vault")
    runtime = {
        "curation_mode": "compaction",
        "origin_task_ref": turn_memory.IMMEDIATE_COMPACT_TASK_REF,
        "target_path": str(turn_memory.EXECUTIVE_TEMPORARY_PATH),
        "turn_id": "compact-expired",
        "conversation_id": "conversation-expired",
        "through_sequence": 2,
    }
    result = turn_memory.append_temporary_observation(
        {"text": _summary("Expired summary"), "related_refs": []}, runtime,
    )
    committed = turn_memory.commit_context_compaction(
        conversation_id="conversation-expired",
        through_sequence=2,
        turn_id="compact-expired",
    )
    meta = dict(committed.meta)
    expired = datetime.now(timezone.utc) - timedelta(days=2)
    meta["observed_at"] = expired.isoformat()
    meta["expires_at"] = (expired + timedelta(days=1)).isoformat()
    write_note(committed.path, meta, committed.body)

    assert turn_memory.latest_context_compaction("conversation-expired") is None
    assert load_note(result["ref"] + ".md") is None


def test_active_compaction_anchor_survives_ttl(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(indexer.CONFIG, "db_path", tmp_path / "active.sqlite3")
    monkeypatch.setattr(turn_memory.CONFIG, "vault_dir", tmp_path / "vault")
    test_index = indexer.Index()
    store = ConversationStore(test_index)

    async def append_pair() -> dict:
        user = await store.append(role="user", source="text", text="Keep this context")
        return await store.append(
            role="assistant",
            source="text",
            text="This context remains active.",
            reply_to=user["id"],
        )

    reply = asyncio.run(append_pair())
    created = turn_memory.append_temporary_observation(
        {"text": _summary("Active context anchor"), "related_refs": []},
        {
            "curation_mode": "compaction",
            "origin_task_ref": turn_memory.IMMEDIATE_COMPACT_TASK_REF,
            "target_path": str(turn_memory.EXECUTIVE_TEMPORARY_PATH),
            "turn_id": "compact-active",
            "conversation_id": store.conversation_id,
            "active_conversation_id": store.conversation_id,
            "through_sequence": reply["sequence"],
        },
    )
    committed = turn_memory.commit_context_compaction(
        conversation_id=store.conversation_id,
        through_sequence=reply["sequence"],
        turn_id="compact-active",
    )
    expired = datetime.now(timezone.utc) - timedelta(days=2)
    write_note(
        committed.path,
        {
            **committed.meta,
            "observed_at": expired.isoformat(),
            "expires_at": (expired + timedelta(days=1)).isoformat(),
        },
        committed.body,
    )

    projected = turn_memory.project_immediate_observations(
        store,
        conversation_id=store.conversation_id,
        materialize=True,
    )

    assert "Active context anchor" in projected["body"]
    assert turn_memory.latest_context_compaction(store.conversation_id) is not None
    for number in range(turn_memory.TEMPORARY_MAX_ENTRIES):
        turn_memory.append_temporary_observation(
            {"text": f"Recent ordinary observation {number}", "related_refs": []},
            {
                "curation_mode": "temporary",
                "target_path": str(turn_memory.EXECUTIVE_TEMPORARY_PATH),
                "turn_id": f"ordinary-{number}",
            },
        )
    retained = turn_memory._temporary_notes(turn_memory.EXECUTIVE_TEMPORARY_PATH)
    assert len(retained) == turn_memory.TEMPORARY_MAX_ENTRIES
    assert load_note(created["ref"] + ".md") is not None
    test_index.db.close()


@pytest.mark.parametrize("force", [False, True])
def test_compaction_keeps_two_exact_pairs_until_session_closes(
    monkeypatch, tmp_path, force,
) -> None:
    monkeypatch.setattr(indexer.CONFIG, "db_path", tmp_path / "recent.sqlite3")
    monkeypatch.setattr(turn_memory.CONFIG, "vault_dir", tmp_path / "vault")
    test_index = indexer.Index()
    monkeypatch.setattr(test_index, "sync", lambda *_args, **_kwargs: None)
    store = ConversationStore(test_index)
    runtime = conversation_runtime.ConversationRuntime()
    runtime._conversation = store
    task = SimpleNamespace(
        ref=turn_memory.IMMEDIATE_COMPACT_TASK_REF,
        kind="task",
        meta={
            "assignee": "[[Agents/Executive/Executive]]",
            "context_threshold": 80,
            "model": "obsidience-gemma",
        },
    )
    fake_resolver = SimpleNamespace(resolve=lambda ref: task if ref == task.ref else None)
    calls: list[dict] = []

    async def append_pair(number: int) -> None:
        user = await store.append(
            role="user",
            source="text",
            text=f"Request {number}",
        )
        await store.append(
            role="assistant",
            source="text",
            text=f"Reply {number}",
            reply_to=user["id"],
        )

    async def compact(_task, **fields) -> dict:
        calls.append(fields)
        runtime_params = fields["runtime_params"]
        turn_memory.append_temporary_observation(
            {
                "text": (
                    "## Goal\nContinue the test.\n\n"
                    "## Constraints and corrections\nKeep exact recent pairs.\n\n"
                    "## Verified state\nThe supplied prefix was compacted.\n\n"
                    "## Outstanding\nContinue the conversation."
                ),
                "related_refs": [],
            },
            runtime_params | {"origin_task_ref": turn_memory.IMMEDIATE_COMPACT_TASK_REF},
        )
        return {"status": "completed"}

    for number in range(1, 5):
        asyncio.run(append_pair(number))
    monkeypatch.setattr(knowledge_vault, "resolver", lambda: fake_resolver)
    monkeypatch.setattr(executor, "run_task", compact)
    monkeypatch.setattr(indexer.INDEX, "sync", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(conversation_runtime, "cached_text_count", lambda text, _spec: PayloadCount(100_000 if text else 0))

    ongoing = asyncio.run(runtime.compact_conversation(force=force))
    assert ongoing["status"] == "completed"
    assert calls[0]["runtime_params"]["through_sequence"] == "4"
    assert "Request 1" in calls[0]["conversation_context"]
    assert "Request 2" in calls[0]["conversation_context"]
    assert "Request 3" not in calls[0]["conversation_context"]
    projected = turn_memory.project_immediate_observations(
        store,
        conversation_id=store.conversation_id,
        materialize=False,
    )
    assert "Request 3" in projected["body"]
    assert "Request 4" in projected["body"]

    closed = asyncio.run(runtime.compact_conversation(force=True, closed_session=True))
    assert closed["status"] == "completed"
    assert calls[1]["runtime_params"]["through_sequence"] == "8"
    assert calls[1]["runtime_params"]["event"] == "observations.immediate.boundary"
    assert "Request 3" in calls[1]["conversation_context"]
    assert "Request 4" in calls[1]["conversation_context"]
    final = turn_memory.project_immediate_observations(
        store,
        conversation_id=store.conversation_id,
        materialize=False,
    )
    assert "Exact completed dialogue" not in final["body"]
    test_index.db.close()


def test_closed_session_queues_one_exact_alexandria_promotion(
    monkeypatch, tmp_path,
) -> None:
    monkeypatch.setattr(turn_memory.CONFIG, "vault_dir", tmp_path / "vault")
    result = turn_memory.append_temporary_observation(
        {"text": _summary("The owner chose the compact observation lifecycle."), "related_refs": []},
        {
            "curation_mode": "compaction",
            "origin_task_ref": turn_memory.IMMEDIATE_COMPACT_TASK_REF,
            "target_path": str(turn_memory.EXECUTIVE_TEMPORARY_PATH),
            "turn_id": "compact-promote",
            "conversation_id": "conversation-promote",
            "through_sequence": 6,
        },
    )
    turn_memory.commit_context_compaction(
        conversation_id="conversation-promote",
        through_sequence=6,
        turn_id="compact-promote",
    )
    captured = {}

    def enqueue(event: str, params: dict) -> list[dict]:
        captured.update({"event": event, "params": dict(params)})
        return [{
            "task": turn_memory.TEMPORARY_PROMOTION_TASK_REF,
            "state": "started",
            "status": "pending",
            "position": 0,
            "queue_depth": 0,
        }]

    monkeypatch.setattr(scheduler, "enqueue_named_event", enqueue)
    queued = turn_memory.queue_temporary_promotion(
        "conversation-promote",
        session_boundary="chat.new_conversation",
    )

    assert captured["event"] == turn_memory.TEMPORARY_PROMOTION_EVENT
    assert captured["params"]["temporary_refs"] == [result["ref"]]
    assert captured["params"]["through_sequence"] == 6
    assert captured["params"]["wait_for_idle"] is True
    assert captured["params"]["queue_after_review"] is True
    assert captured["params"]["agent_ref"] == "Agents/Executive/Executive"
    assert queued["state"] == "queued"
    note = load_note(result["ref"] + ".md")
    assert note is not None
    assert note.meta["promotion_pending"] == queued["promotion_key"]


def test_pending_promotion_is_not_reissued_with_a_later_compaction(
    monkeypatch, tmp_path,
) -> None:
    monkeypatch.setattr(turn_memory.CONFIG, "vault_dir", tmp_path / "vault")
    conversation_id = "conversation-promotion-sequence"
    queued_params: list[dict] = []

    def enqueue(_event: str, params: dict) -> list[dict]:
        queued_params.append(dict(params))
        return [{"task": turn_memory.TEMPORARY_PROMOTION_TASK_REF, "state": "started"}]

    monkeypatch.setattr(scheduler, "enqueue_named_event", enqueue)
    refs = []
    for through_sequence in (2, 4):
        turn_id = f"compact-{through_sequence}"
        created = turn_memory.append_temporary_observation(
            {"text": _summary(f"Summary through {through_sequence}"), "related_refs": []},
            {
                "curation_mode": "compaction",
                "origin_task_ref": turn_memory.IMMEDIATE_COMPACT_TASK_REF,
                "target_path": str(turn_memory.EXECUTIVE_TEMPORARY_PATH),
                "turn_id": turn_id,
                "conversation_id": conversation_id,
                "through_sequence": through_sequence,
            },
        )
        refs.append(created["ref"])
        turn_memory.commit_context_compaction(
            conversation_id=conversation_id,
            through_sequence=through_sequence,
            turn_id=turn_id,
        )
        turn_memory.queue_temporary_promotion(
            conversation_id,
            session_boundary="realtime.stopped",
        )

    assert queued_params[0]["temporary_refs"] == [refs[0]]
    assert queued_params[1]["temporary_refs"] == [refs[1]]
    assert queued_params[0]["promotion_key"] != queued_params[1]["promotion_key"]


def test_promotion_archives_one_attested_source_bundle_idempotently(
    monkeypatch, tmp_path,
) -> None:
    conversation_id = "conversation-" + "e" * 32
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(indexer.CONFIG, "db_path", tmp_path / "source.sqlite3")
    monkeypatch.setattr(turn_memory.CONFIG, "vault_dir", tmp_path / "vault")
    test_index = indexer.Index()
    monkeypatch.setattr(indexer, "INDEX", test_index)

    created = turn_memory.append_temporary_observation(
        {"text": _summary("The owner selected Alexandria for durable promotion."), "related_refs": []},
        {
            "curation_mode": "compaction",
            "origin_task_ref": turn_memory.IMMEDIATE_COMPACT_TASK_REF,
            "target_path": str(turn_memory.EXECUTIVE_TEMPORARY_PATH),
            "turn_id": "compact-archive",
            "conversation_id": conversation_id,
            "through_sequence": 8,
        },
    )
    turn_memory.commit_context_compaction(
        conversation_id=conversation_id,
        through_sequence=8,
        turn_id="compact-archive",
    )
    captured = {}

    def enqueue(
        event: str,
        params: dict,
        *,
        expected_task: str | None = None,
        source_event: tuple[str, str] | None = None,
    ) -> list[dict]:
        if event == turn_memory.TEMPORARY_PROMOTION_EVENT:
            captured.update(params)
            return [{"task": turn_memory.TEMPORARY_PROMOTION_TASK_REF, "state": "started"}]
        assert event == "source.added"
        assert expected_task == "Tasks/research/learn"
        assert params["source_class"] == source.OBSERVATION_ARCHIVE_SOURCE_CLASS
        return []

    monkeypatch.setattr(scheduler, "enqueue_named_event", enqueue)
    turn_memory.queue_temporary_promotion(
        conversation_id,
        session_boundary="realtime.stopped",
    )
    before = (turn_memory.CONFIG.vault_dir / f"{created['ref']}.md").read_bytes()
    before_sha = "sha256:" + hashlib.sha256(before).hexdigest()
    runtime = {
        **captured,
        "origin_task_ref": turn_memory.TEMPORARY_PROMOTION_TASK_REF,
        "event": turn_memory.TEMPORARY_PROMOTION_EVENT,
    }

    archived = turn_memory.archive_temporary_observations({}, runtime)
    preserved = source.get_source(archived["source"]["citation"])
    assert archived["source"]["created"] is True
    assert archived["source"]["article_count"] == 1
    assert preserved["source_ref"].endswith(
        f"/{conversation_id}/{captured['promotion_key']}"
    )
    assert "Article count: 1" in preserved["content"]
    assert f"[[{created['ref']}]]" in preserved["content"]
    assert before_sha in preserved["content"]
    note = load_note(created["ref"] + ".md")
    assert note is not None
    assert note.meta["source_archive"] == archived["source"]["citation"]
    assert note.meta["source_article_sha256"] == before_sha
    assert "promotion_pending" not in note.meta

    retried = turn_memory.archive_temporary_observations({}, runtime)
    assert retried["source"]["created"] is False
    assert retried["source"]["citation"] == archived["source"]["citation"]
    assert retried["articles"][0]["article_sha256"] == before_sha
    with pytest.raises(ValueError, match="exact Promote Task"):
        turn_memory.archive_temporary_observations(
            {}, runtime | {"origin_task_ref": "Tasks/query"},
        )
    test_index.db.close()


def test_immediate_context_preserves_unanswered_request_before_its_correction(monkeypatch, tmp_path):
    monkeypatch.setattr(indexer.CONFIG, "db_path", tmp_path / "unanswered.sqlite3")
    monkeypatch.setattr(turn_memory.CONFIG, "vault_dir", tmp_path / "vault")
    index = indexer.Index()
    store = ConversationStore(index)

    async def dialogue():
        question = await store.append(role="user", source="realtime", text="What level is Squander?")
        with pytest.raises(ValueError, match="only final public"):
            await store.append(role="assistant", source="realtime", text="Unfinished private guess",
                               reply_to=question["id"], state="interrupted")
        correction = await store.append(role="user", source="realtime", text="Yes, I mean Squancher")
        return question, correction

    question, correction = asyncio.run(dialogue())
    projection = turn_memory.project_immediate_observations(
        store, conversation_id=store.conversation_id,
        before_sequence=correction["sequence"], materialize=False,
    )
    assert "User: What level is Squander?" in projection["body"]
    assert "request remains unresolved" in projection["body"]
    assert "Unfinished private guess" not in projection["body"]
    assert "Yes, I mean Squancher" not in projection["body"]
    assert projection["latest_sequence"] == question["sequence"]

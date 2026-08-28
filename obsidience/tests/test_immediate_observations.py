from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timedelta, timezone

import pytest

from obsidience.harness import config
from obsidience.harness.conversation import observations as turn_memory
from obsidience.harness.conversation.store import ConversationStore
from obsidience.harness.execution import scheduler
from obsidience.harness.knowledge import index as indexer
from obsidience.harness.knowledge import source
from obsidience.harness.knowledge.vault import load_note, write_note


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

    created = turn_memory.append_temporary_observation(
        {
            "text": "The owner made a first request and received a first reply.",
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
    summary = "x" * turn_memory.TEMPORARY_MAX_ENTRY_CHARS
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
    assert len(note.body.strip()) == turn_memory.TEMPORARY_MAX_ENTRY_CHARS


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

    graph_refs = {node["id"] for node in test_index.graph()["nodes"]}
    assert turn_memory.IMMEDIATE_OBSERVATIONS_REF in graph_refs
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
            {"text": "Pending summary", "related_refs": []},
            runtime | {"origin_task_ref": "Tasks/query"},
        )
    with pytest.raises(ValueError, match="exact Compact Task"):
        turn_memory.append_temporary_observation(
            {"text": "Pending summary", "related_refs": []},
            runtime | {"target_path": "Agents/Darwin/Observations/Temporary Observations"},
        )
    with pytest.raises(ValueError, match="does not resolve exactly"):
        turn_memory.append_temporary_observation(
            {"text": "Pending summary", "related_refs": ["Missing/Article"]},
            runtime,
        )

    result = turn_memory.append_temporary_observation(
        {"text": "Pending summary", "related_refs": []}, runtime,
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
        {"text": "Expired summary", "related_refs": []}, runtime,
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


def test_closed_session_queues_one_exact_alexandria_promotion(
    monkeypatch, tmp_path,
) -> None:
    monkeypatch.setattr(turn_memory.CONFIG, "vault_dir", tmp_path / "vault")
    result = turn_memory.append_temporary_observation(
        {"text": "The owner chose the compact observation lifecycle.", "related_refs": []},
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


def test_promotion_archives_one_attested_source_bundle_idempotently(
    monkeypatch, tmp_path,
) -> None:
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(indexer.CONFIG, "db_path", tmp_path / "source.sqlite3")
    monkeypatch.setattr(turn_memory.CONFIG, "vault_dir", tmp_path / "vault")
    test_index = indexer.Index()
    monkeypatch.setattr(indexer, "INDEX", test_index)

    created = turn_memory.append_temporary_observation(
        {"text": "The owner selected Alexandria for durable promotion.", "related_refs": []},
        {
            "curation_mode": "compaction",
            "origin_task_ref": turn_memory.IMMEDIATE_COMPACT_TASK_REF,
            "target_path": str(turn_memory.EXECUTIVE_TEMPORARY_PATH),
            "turn_id": "compact-archive",
            "conversation_id": "conversation-archive",
            "through_sequence": 8,
        },
    )
    turn_memory.commit_context_compaction(
        conversation_id="conversation-archive",
        through_sequence=8,
        turn_id="compact-archive",
    )
    captured = {}

    def enqueue(
        event: str,
        params: dict,
        *,
        expected_task: str | None = None,
    ) -> list[dict]:
        if event == turn_memory.TEMPORARY_PROMOTION_EVENT:
            captured.update(params)
            return [{"task": turn_memory.TEMPORARY_PROMOTION_TASK_REF, "state": "started"}]
        assert event == "source.added"
        assert expected_task == "Tasks/research/learn"
        return [{"task": "Tasks/research/learn", "state": "started"}]

    monkeypatch.setattr(scheduler, "enqueue_named_event", enqueue)
    turn_memory.queue_temporary_promotion(
        "conversation-archive",
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
        f"/conversation-archive/{captured['promotion_key']}"
    )
    assert f"Article count: 1" in preserved["content"]
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

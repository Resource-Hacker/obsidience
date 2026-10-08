from __future__ import annotations

import asyncio

from obsidience.harness.conversation.store import ConversationStore
from obsidience.harness.knowledge import index as indexer


def _index(monkeypatch, tmp_path):
    monkeypatch.setattr(indexer.CONFIG, "db_path", tmp_path / "conversation.sqlite3")
    return indexer.Index()


def test_hot_window_is_ordered_and_rehydrates_from_sqlite(monkeypatch, tmp_path) -> None:
    async def scenario() -> None:
        first_index = _index(monkeypatch, tmp_path)
        store = ConversationStore(first_index, hot_limit=2)
        conversation_id = store.conversation_id

        user = await store.append(role="user", source="realtime", text="Hello")
        assistant = await store.append(
            role="assistant",
            source="realtime",
            text="Hello there",
            run_id="run-1",
            reply_to=user["id"],
        )
        latest = await store.append(role="user", source="text", text="Remember me")

        assert [user["sequence"], assistant["sequence"], latest["sequence"]] == [1, 2, 3]
        assert [turn["sequence"] for turn in store.snapshot()["turns"]] == [2, 3]
        assert [turn["sequence"] for turn in store.history()] == [1, 2, 3]

        first_index.db.close()
        second_index = indexer.Index()
        restored = ConversationStore(second_index, hot_limit=2)
        assert restored.conversation_id == conversation_id
        assert [turn["sequence"] for turn in restored.snapshot()["turns"]] == [2, 3]
        second_index.db.close()

    asyncio.run(scenario())


def test_new_conversation_preserves_old_rows_and_ignores_late_reply(
    monkeypatch, tmp_path,
) -> None:
    async def scenario() -> None:
        test_index = _index(monkeypatch, tmp_path)
        store = ConversationStore(test_index)
        old_id = store.conversation_id
        old_user = await store.append(role="user", source="realtime", text="Old request")

        events = store.subscribe()
        assert (await events.get())["type"] == "history"
        snapshot = await store.new_conversation()
        assert (await events.get()) == snapshot
        assert snapshot["conversation_id"] != old_id

        late = await store.append(
            role="assistant",
            source="realtime",
            text="Late reply",
            conversation_id=old_id,
            reply_to=old_user["id"],
        )
        assert late["conversation_id"] == old_id
        assert events.empty()
        assert store.snapshot()["turns"] == []
        assert [turn["text"] for turn in store.history(old_id)] == [
            "Old request",
            "Late reply",
        ]

        current = await store.append(role="user", source="text", text="New request")
        event = await events.get()
        assert event == {
            "type": "turn",
            "conversation_id": snapshot["conversation_id"],
            "turn": current,
        }
        store.unsubscribe(events)
        test_index.db.close()

    asyncio.run(scenario())


def test_conversation_values_are_closed(monkeypatch, tmp_path) -> None:
    async def scenario() -> None:
        test_index = _index(monkeypatch, tmp_path)
        store = ConversationStore(test_index)
        for fields in (
            {"role": "tool", "source": "text", "text": "x"},
            {"role": "user", "source": "browser", "text": "x"},
            {"role": "user", "source": "text", "text": "x", "state": "draft"},
            {"role": "user", "source": "text", "text": "   "},
            {"role": "assistant", "source": "text", "text": "unpaired"},
        ):
            try:
                await store.append(**fields)
            except ValueError:
                pass
            else:
                raise AssertionError(f"accepted invalid conversation values: {fields}")
        assert store.history() == []
        test_index.db.close()

    asyncio.run(scenario())

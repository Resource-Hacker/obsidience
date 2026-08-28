"""One persisted Executive conversation with a bounded hot turn window."""

from __future__ import annotations

import asyncio
from collections import deque

from ..knowledge.index import INDEX, Index

_ROLES = {"user", "assistant"}
_SOURCES = {"text", "realtime"}
_FINAL_STATE = "final"


class ConversationStore:
    def __init__(self, index: Index = INDEX, *, hot_limit: int = 80):
        if hot_limit < 1:
            raise ValueError("hot_limit must be positive")
        self.index = index
        self.hot_limit = hot_limit
        self._conversation_id = index.active_conversation_id()
        self._turns: deque[dict] = deque(
            index.conversation_turns(self._conversation_id, limit=hot_limit),
            maxlen=hot_limit,
        )
        self._lock = asyncio.Lock()
        self._subscribers: set[asyncio.Queue[dict]] = set()

    @property
    def conversation_id(self) -> str:
        return self._conversation_id

    def snapshot(self) -> dict:
        return {
            "type": "history",
            "conversation_id": self._conversation_id,
            "turns": [dict(turn) for turn in self._turns],
        }

    def history(
        self,
        conversation_id: str | None = None,
        *,
        limit: int | None = None,
    ) -> list[dict]:
        return self.index.conversation_turns(
            conversation_id or self._conversation_id,
            limit=limit,
        )

    async def append(
        self,
        *,
        role: str,
        source: str,
        text: str,
        run_id: str | None = None,
        reply_to: str | None = None,
        state: str = "final",
        conversation_id: str | None = None,
    ) -> dict:
        if role not in _ROLES:
            raise ValueError(f"invalid conversation role: {role}")
        if source not in _SOURCES:
            raise ValueError(f"invalid conversation source: {source}")
        if state != _FINAL_STATE:
            raise ValueError("only final public conversation turns may be persisted")
        if not text or not text.strip():
            raise ValueError("conversation text must not be empty")
        if role == "user" and reply_to is not None:
            raise ValueError("a user turn cannot reply to another turn")
        if role == "assistant" and reply_to is None:
            raise ValueError("an assistant turn must reply to one exact user turn")

        async with self._lock:
            target_id = conversation_id or self._conversation_id
            turn = self.index.append_conversation_turn(
                conversation_id=target_id,
                role=role,
                source=source,
                text=text,
                run_id=run_id,
                reply_to=reply_to,
                state=state,
            )
            if target_id == self._conversation_id:
                self._turns.append(turn)
                self._publish({
                    "type": "turn",
                    "conversation_id": target_id,
                    "turn": dict(turn),
                })
            return dict(turn)

    async def new_conversation(self) -> dict:
        async with self._lock:
            self._conversation_id = self.index.new_conversation()
            self._turns.clear()
            snapshot = self.snapshot()
            self._publish(snapshot)
            return snapshot

    def prompt_context(
        self,
        *,
        conversation_id: str | None = None,
        before_sequence: int | None = None,
        after_sequence: int = 0,
        max_chars: int,
    ) -> str:
        """Pack newest complete public pairs, then return them chronologically."""
        if max_chars <= 0:
            return ""
        pairs = self.complete_pairs(
            conversation_id=conversation_id,
            before_sequence=before_sequence,
            after_sequence=after_sequence,
        )
        rendered = [
            f"User: {user['text']}\nExecutive: {assistant['text']}"
            for user, assistant in pairs
        ]
        selected: list[str] = []
        used = 0
        for pair in reversed(rendered):
            size = len(pair) + (2 if selected else 0)
            if used + size > max_chars:
                break
            selected.append(pair)
            used += size
        return "\n\n".join(reversed(selected))

    def complete_pairs(
        self,
        *,
        conversation_id: str | None = None,
        before_sequence: int | None = None,
        after_sequence: int = 0,
    ) -> list[tuple[dict, dict]]:
        """Return exact final user/reply pairs from SQLite in user order."""
        target_id = conversation_id or self._conversation_id
        turns = self.index.conversation_turns(target_id)
        if before_sequence is not None:
            turns = [turn for turn in turns if turn["sequence"] < before_sequence]
        turns = [turn for turn in turns if turn["sequence"] > after_sequence]
        users = {
            turn["id"]: turn
            for turn in turns
            if turn["role"] == "user" and turn["state"] == "final"
        }
        pairs = [
            (users[turn["reply_to"]], turn)
            for turn in turns
            if turn["role"] == "assistant"
            and turn["state"] == "final"
            and turn["reply_to"] in users
        ]
        pairs.sort(key=lambda pair: pair[0]["sequence"])
        return pairs

    def publish(self, event: dict) -> None:
        """Broadcast bounded runtime state alongside canonical turn events."""
        self._publish(event)

    def subscribe(self) -> asyncio.Queue[dict]:
        queue: asyncio.Queue[dict] = asyncio.Queue()
        self._subscribers.add(queue)
        queue.put_nowait(self.snapshot())
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict]) -> None:
        self._subscribers.discard(queue)

    def _publish(self, event: dict) -> None:
        for queue in tuple(self._subscribers):
            queue.put_nowait(event)


CONVERSATION = ConversationStore()

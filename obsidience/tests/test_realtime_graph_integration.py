from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest

from obsidience.harness.interfaces.api.app import _live_task_selection
from obsidience.harness.conversation import observations as turn_memory
from obsidience.harness.execution import activity as knowledge_activity
from obsidience.harness.execution import executor, scheduler
from obsidience.harness.execution.executor import compile_activation
from obsidience.harness.knowledge import index as indexer
from obsidience.harness.knowledge.tasks import TASK_TAXONOMY_BY_PATH
from obsidience.harness.knowledge.vault import resolver
from obsidience.harness.models import llm
from obsidience.harness.models import runtime as model_runtime
from obsidience.harness.realtime.runtime import (
    MAX_CONTEXT_THRESHOLD,
    REALTIME_CONFIRMATION,
    REALTIME_RESPONSE_CONTRACT,
    RUNTIME,
    RealtimeSessionManager,
)


class MemoryConversation:
    """Tiny exact-pair store for Realtime wiring tests; never touches the live ledger."""

    def __init__(self) -> None:
        self.turns: list[dict] = []
        self.rotations = 0
        self.conversation_id = "conversation-test"
        self.events: list[dict] = []

    async def new_conversation(self) -> dict:
        self.rotations += 1
        self.turns.clear()
        self.conversation_id = f"conversation-{self.rotations}"
        return {
            "type": "history",
            "conversation_id": self.conversation_id,
            "turns": [],
        }

    async def append(self, **fields) -> dict:
        turn = {
            "id": f"turn-{len(self.turns) + 1}",
            "conversation_id": fields.get("conversation_id", self.conversation_id),
            "sequence": len(self.turns) + 1,
            "role": fields["role"],
            "source": fields["source"],
            "text": fields["text"],
            "run_id": fields.get("run_id"),
            "reply_to": fields.get("reply_to"),
            "state": "final",
            "created_at": 0.0,
        }
        self.turns.append(turn)
        return turn

    def prompt_context(self, **fields) -> str:
        pairs = self.complete_pairs(
            before_sequence=fields.get("before_sequence"),
            after_sequence=fields.get("after_sequence", 0),
        )
        rendered = [
            f"User: {user['text']}\nExecutive: {assistant['text']}"
            for user, assistant in pairs
        ]
        return "\n\n".join(rendered)[-fields["max_chars"]:]

    def complete_pairs(self, **fields) -> list[tuple[dict, dict]]:
        before = fields.get("before_sequence")
        after = fields.get("after_sequence", 0)
        users = {
            turn["id"]: turn
            for turn in self.turns
            if turn["role"] == "user"
            and turn["sequence"] > after
            and (before is None or turn["sequence"] < before)
        }
        return [
            (users[turn["reply_to"]], turn)
            for turn in self.turns
            if turn["role"] == "assistant"
            and turn["sequence"] > after
            and (before is None or turn["sequence"] < before)
            and turn["reply_to"] in users
        ]

    def publish(self, event: dict) -> None:
        self.events.append(event)


@pytest.fixture(autouse=True)
def immediate_observation_projection(monkeypatch):
    original = turn_memory.project_immediate_observations

    def project(
        conversation,
        *,
        conversation_id: str,
        before_sequence=None,
        materialize=True,
    ):
        if not isinstance(conversation, MemoryConversation):
            return original(
                conversation,
                conversation_id=conversation_id,
                before_sequence=before_sequence,
                materialize=materialize,
            )
        pairs = conversation.complete_pairs(before_sequence=before_sequence)
        dialogue = "\n\n".join(
            f"User: {user['text']}\nExecutive: {assistant['text']}"
            for user, assistant in pairs
        ) or "No completed conversation pair exists yet."
        latest = max((assistant["sequence"] for _user, assistant in pairs), default=0)
        return {
            "ref": turn_memory.IMMEDIATE_OBSERVATIONS_REF,
            "body": dialogue,
            "compacted_through": 0,
            "latest_sequence": latest,
            "temporary_ref": None,
        }

    monkeypatch.setattr(turn_memory, "project_immediate_observations", project)


def test_live_packet_uses_one_objective_and_canonical_ontology_order(monkeypatch) -> None:
    task = resolver().resolve("Tasks/query")
    assert task is not None
    objective = "OBJECTIVE-SENTINEL-74f8"
    retrieval_queries: list[str] = []

    def capture_retrieval(query: str, *_args) -> tuple[str, list[str]]:
        retrieval_queries.append(query)
        return "### [[Knowledge/test]] — Test Knowledge\nObjective-free context.", [
            "Knowledge/test"
        ]

    monkeypatch.setattr(
        executor.retrieval,
        "fast_context_with_refs",
        capture_retrieval,
    )
    activation = asyncio.run(
        compile_activation(
            task,
            runtime_params={
                "request": objective,
                "source": "voice",
                "event": "voice.activation",
            },
            emit_activity=False,
            include_realtime=True,
            conversation_context="No completed conversation pair exists yet.",
        )
    )
    full_packet = activation["packet"]
    realtime_packet = activation["realtime_packet"]
    assert realtime_packet is not None
    headings = [
        "## Agent Identity",
        "## Task",
        "## Objective",
        "## Tools",
        "## Skills",
        "## Runbook",
        "## Bindings",
        "## Relevant Knowledge",
        "## Immediate Observations",
    ]

    def semantic_headings(packet: str) -> list[str]:
        return [line for line in packet.splitlines() if line.startswith("## ")]

    assert semantic_headings(full_packet) == headings
    assert semantic_headings(realtime_packet) == headings
    assert activation["objective"] == objective
    assert activation["bindings"] == {}
    assert retrieval_queries == [objective]
    for packet in (full_packet, realtime_packet):
        assert packet.count("## Objective") == 1
        assert packet.count(objective) == 1
        assert "Owner request:" not in packet
        assert "## Bound Parameters" not in packet
    assert activation["refs"][:2] == ["Agents/Executive/Executive", "Tasks/query"]
    assert "Runbooks/answer-the-user" in activation["refs"]


def test_scheduled_leaf_uses_one_task_runbook_objective_everywhere(monkeypatch) -> None:
    task = resolver().resolve("Tasks/curate")
    assert task is not None
    spine = executor.resolve_spine(task, resolver())
    expected = " ".join(
        [task.title, *(runbook.title for runbook in spine["runbooks"])]
    )
    retrieval_queries: list[str] = []
    events: list[dict] = []
    packets: list[str] = []
    runs: list[dict] = []

    def capture_retrieval(query: str, *_args) -> tuple[str, list[str]]:
        retrieval_queries.append(query)
        return "", []

    def capture_activity(phase: str, refs: list[str], **fields: object) -> dict:
        event = {"phase": phase, "refs": refs, **fields}
        events.append(event)
        return event

    async def complete_without_a_model(
        _task, _model, messages, _allowed, _ctx, _agent_name, _effort,
    ):
        packets.append(messages[1]["content"])
        return [], "completed", "ok"

    monkeypatch.setattr(
        executor.retrieval,
        "fast_context_with_refs",
        capture_retrieval,
    )
    monkeypatch.setattr(knowledge_activity, "emit", capture_activity)
    monkeypatch.setattr(executor, "_execute_session", complete_without_a_model)
    monkeypatch.setattr(executor.INDEX, "record_run", lambda **fields: runs.append(fields))
    monkeypatch.setattr(executor.INDEX, "sync", lambda: None)

    result = asyncio.run(
        executor.run_task(task, keep_task_open=True, emit_turn_event=False)
    )

    assert result["objective"] == expected
    assert retrieval_queries == [expected]
    transaction = [
        event for event in events
        if event["phase"] in {"query_started", "path", "query_completed"}
    ]
    assert [event["phase"] for event in transaction] == [
        "query_started", "path", "query_completed",
    ]
    assert [event["query"] for event in transaction] == [expected] * 3
    assert len(packets) == 1
    assert packets[0].count("## Objective") == 1
    assert packets[0].count(expected) == 1
    assert len(runs) == 1
    assert runs[0]["objective"] == expected


def test_live_voice_and_chat_share_one_task_selection() -> None:
    voice_task, voice_params, voice_event = _live_task_selection(
        "What is Obsidience?", "voice"
    )
    text_task, text_params, text_event = _live_task_selection(
        "What is Obsidience?", "text"
    )
    assert voice_task is not None and text_task is not None
    assert voice_task.ref == text_task.ref == "Tasks/query"
    assert voice_params["request"] == text_params["request"]
    assert voice_event == "voice.activation"
    assert text_event == "chat.request"


def test_realtime_voice_selects_one_persistent_executive_task() -> None:
    task, params, event = _live_task_selection(
        "Check the harness status", "voice", realtime_active=True,
    )
    assert task is not None
    assert task.ref == "Tasks/executive/realtime"
    assert params["request"] == "Check the harness status"
    assert event == "voice.activation"


def test_explicit_control_prompt_selects_computer_use_without_a_play_task() -> None:
    task, params, event = _live_task_selection("Press Play in TFT.", "voice")
    assert task is not None
    assert task.ref == "Tasks/executive/operate"
    assert task.title == "Computer Use"
    assert params["operation"] == "computer_use"
    assert params["application"] == "teamfight_tactics"
    assert params["request"] == "Press Play in TFT."
    assert event == "voice.activation"


def test_discussing_a_control_does_not_select_computer_use() -> None:
    task, params, _event = _live_task_selection(
        "How does the Play button in TFT work?", "text",
    )
    assert task is not None and task.ref == "Tasks/query"
    assert "operation" not in params


def test_realtime_session_uses_the_canonical_task_activity_path(monkeypatch) -> None:
    events: list[dict] = []

    def capture(phase: str, refs: list[str], **fields: object) -> dict:
        event = {"phase": phase, "refs": refs, **fields}
        events.append(event)
        return event

    monkeypatch.setattr(knowledge_activity, "emit", capture)
    runtime = RealtimeSessionManager()
    asyncio.run(runtime._activate_task_activity())

    assert [event["phase"] for event in events] == ["query_started", "path"]
    assert events[0]["refs"] == ["Tasks/executive/realtime"]
    assert "Agents/Executive/Executive" in events[1]["refs"]
    assert "Tasks/executive/realtime" in events[1]["refs"]
    assert "Runbooks/realtime" in events[1]["refs"]
    assert events[0]["query"] == events[1]["query"]
    assert runtime._task_activity is not None


def test_realtime_startup_path_completes_when_runtime_is_ready(monkeypatch) -> None:
    phases: list[str] = []
    monkeypatch.setattr(
        knowledge_activity,
        "emit",
        lambda phase, _refs, **_fields: phases.append(phase) or {},
    )
    runtime = RealtimeSessionManager()
    runtime._task_activity = {
        "refs": ["Agents/Executive/Executive", "Tasks/executive/realtime"],
        "query": "Realtime",
        "graph_id": "main",
        "retrieval_ms": 2.0,
    }

    runtime._complete_task_activity()
    runtime._complete_task_activity()

    assert phases == ["query_completed"]
    assert runtime._task_activity is None


def test_realtime_command_requests_the_local_ready_confirmation() -> None:
    runtime = RealtimeSessionManager()
    runtime._selected_model = model_runtime.resolve_model(
        model_runtime.EXECUTIVE_MODEL, "Agents/Executive/Executive",
    )
    runtime._selected_devices = (model_runtime.RTX_4080_DEVICE,)
    command = runtime._command()
    index = command.index("--startup-confirmation")
    assert command[index + 1] == REALTIME_CONFIRMATION
    assert command[1:3] == ("-m", "obsidience.harness.realtime.speech.worker")
    assert "--asr-model" in command
    assert "--pocket-root" in command
    assert "--host" not in command
    assert "--port" not in command
    assert "--microphone" not in command
    assert "--speaker" not in command
    assert "--backchannels" not in command
    assert "--model" not in command
    assert "--tools" not in command


def test_realtime_reports_only_its_live_echo_cancellation_route() -> None:
    runtime = RealtimeSessionManager()
    assert runtime.snapshot()["live_transcript"] is None
    assert runtime.snapshot()["user_speaking"] is False
    assert runtime.snapshot()["acoustic_echo_cancellation"] is False
    runtime._aec_active = True
    assert runtime.snapshot()["acoustic_echo_cancellation"] is True


def test_context_threshold_uses_raw_tokens_and_caps_at_ninety(monkeypatch) -> None:
    runtime = RealtimeSessionManager()
    used = 799

    def status(**_kwargs):
        return {
            "used_tokens": used,
            "capacity_tokens": 1_000,
            "percent": 80.0,
            "compact_at": 80,
            "latest_sequence": 0,
            "compacted_through": 0,
        }

    monkeypatch.setattr(runtime, "context_status", status)
    assert MAX_CONTEXT_THRESHOLD == 90
    assert asyncio.run(runtime.compact_conversation(force=False))["status"] == "not_needed"
    used = 800
    assert (
        asyncio.run(runtime.compact_conversation(force=False))["status"]
        == "nothing_to_compact"
    )


def test_prepare_context_binds_the_user_conversation_task_and_request(monkeypatch) -> None:
    runtime = RealtimeSessionManager()
    runtime._conversation = MemoryConversation()
    captured: dict = {}

    async def compact(**fields):
        captured.update(fields)
        return {"status": "not_needed"}

    monkeypatch.setattr(runtime, "compact_conversation", compact)
    user_turn = {
        "conversation_id": "conversation-exact",
        "sequence": 7,
        "text": "A current request",
    }
    asyncio.run(runtime.prepare_immediate_observations(
        user_turn,
        context_task_ref="Tasks/query",
    ))

    assert captured == {
        "force": False,
        "before_sequence": 7,
        "conversation_id": "conversation-exact",
        "context_task_ref": "Tasks/query",
        "pending_text": "A current request",
    }


def test_compact_commits_the_captured_conversation_after_rotation(monkeypatch) -> None:
    runtime = RealtimeSessionManager()
    memory = MemoryConversation()
    runtime._conversation = memory
    runtime._thinking_overhead_tokens = 777
    projected: list[tuple[str, bool]] = []
    committed: list[dict] = []

    def project(_conversation, *, conversation_id, before_sequence=None, materialize=True):
        projected.append((conversation_id, materialize))
        return {
            "ref": turn_memory.IMMEDIATE_OBSERVATIONS_REF,
            "body": "User: old\nExecutive: reply",
            "compacted_through": 0,
            "latest_sequence": 2,
            "temporary_ref": None,
        }

    async def complete(_task, **fields):
        assert fields["keep_task_open"] is True
        assert fields["runtime_params"]["conversation_id"] == "conversation-test"
        await memory.new_conversation()
        return {
            "status": "completed",
            "prompt_tokens_estimate": 9_999,
            "conversation_tokens_estimate": 10,
        }

    def commit(**fields):
        committed.append(fields)
        return SimpleNamespace(ref="Agents/Executive/Observations/Temporary Observations/ok")

    monkeypatch.setattr(turn_memory, "project_immediate_observations", project)
    monkeypatch.setattr(turn_memory, "commit_context_compaction", commit)
    monkeypatch.setattr(
        turn_memory,
        "discard_pending_context_compaction",
        lambda **_fields: pytest.fail("successful Compact must not discard"),
    )
    monkeypatch.setattr(executor, "run_task", complete)
    monkeypatch.setattr(indexer.INDEX, "sync", lambda: None)

    result = asyncio.run(runtime.compact_conversation(
        force=True,
        conversation_id="conversation-test",
        context_task_ref="Tasks/query",
    ))

    assert result["temporary_ref"].endswith("/ok")
    assert committed == [{
        "conversation_id": "conversation-test",
        "through_sequence": 2,
        "turn_id": "compact-test-2",
    }]
    assert runtime._thinking_overhead_tokens == 777
    assert ("conversation-test", False) in projected
    assert projected[-1] == ("conversation-1", True)


@pytest.mark.parametrize("mode", ["failed", "canceled"])
def test_compact_discards_unaccepted_output(monkeypatch, mode: str) -> None:
    runtime = RealtimeSessionManager()
    runtime._conversation = MemoryConversation()
    discarded: list[dict] = []

    def project(_conversation, *, conversation_id, before_sequence=None, materialize=True):
        return {
            "ref": turn_memory.IMMEDIATE_OBSERVATIONS_REF,
            "body": "User: old\nExecutive: reply",
            "compacted_through": 0,
            "latest_sequence": 2,
            "temporary_ref": None,
        }

    async def reject(_task, **_fields):
        if mode == "canceled":
            raise asyncio.CancelledError
        return {"status": "failed", "summary": "rejected"}

    def discard(**fields):
        discarded.append(fields)
        return True

    monkeypatch.setattr(turn_memory, "project_immediate_observations", project)
    monkeypatch.setattr(turn_memory, "discard_pending_context_compaction", discard)
    monkeypatch.setattr(
        turn_memory,
        "commit_context_compaction",
        lambda **_fields: pytest.fail("unaccepted Compact must not commit"),
    )
    monkeypatch.setattr(executor, "run_task", reject)
    monkeypatch.setattr(indexer.INDEX, "sync", lambda: None)

    if mode == "canceled":
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(runtime.compact_conversation(force=True))
    else:
        result = asyncio.run(runtime.compact_conversation(force=True))
        assert result["status"] == "failed"
    assert discarded == [{
        "conversation_id": "conversation-test",
        "through_sequence": 2,
        "turn_id": "compact-test-2",
    }]


def test_realtime_exposes_the_exact_transcript_given_to_the_task(monkeypatch) -> None:
    class FakeStdout:
        def __init__(self) -> None:
            self._lines = iter((
                b'{"type":"transcript_partial","text":"Can   you hear"}\n',
                b'{"type":"speech_detected"}\n',
                b'{"type":"speech_ended"}\n',
                b'{"type":"transcript_final","text":"Can  you hear me?"}\n',
            ))
            self._blocked = asyncio.Event()

        async def readline(self) -> bytes:
            try:
                return next(self._lines)
            except StopIteration:
                await self._blocked.wait()
                return b""

    class FakeProcess:
        def __init__(self) -> None:
            self.stdout = FakeStdout()
            self.returncode = None
            self.pid = 123

    runtime = RealtimeSessionManager()
    runtime._live_transcript = {"text": "old utterance", "final": True}
    published: list[tuple[dict | None, bool]] = []
    accepted: list[str] = []
    finished = asyncio.Event()

    async def capture_publish(_kind: str, **_payload: object) -> None:
        snapshot = runtime.snapshot()
        published.append((snapshot["live_transcript"], snapshot["user_speaking"]))

    async def capture_transcript(text: str) -> None:
        accepted.append(text)
        finished.set()

    monkeypatch.setattr(runtime, "_publish", capture_publish)
    monkeypatch.setattr(runtime, "_accept_transcript", capture_transcript)

    async def exercise() -> None:
        monitor = asyncio.create_task(runtime._monitor_process(FakeProcess(), 0))
        await asyncio.wait_for(finished.wait(), timeout=1)
        await asyncio.sleep(0)
        monitor.cancel()
        with pytest.raises(asyncio.CancelledError):
            await monitor

    asyncio.run(exercise())

    assert published == [
        ({"text": "Can you hear", "final": False}, False),
        ({"text": "Can you hear", "final": False}, True),
        ({"text": "Can you hear", "final": False}, False),
        ({"text": "Can you hear me?", "final": True}, False),
    ]
    assert accepted == ["Can you hear me?"]


def test_every_realtime_utterance_emits_one_canonical_thinking_packet(monkeypatch) -> None:
    events: list[dict] = []
    packets: list[tuple[list[dict], list[str]]] = []
    retrieval_queries: list[str] = []
    runs: list[dict] = []

    def capture(phase: str, refs: list[str], **fields: object) -> dict:
        event = {"phase": phase, "refs": refs, **fields}
        events.append(event)
        return event

    async def complete_without_a_model(
        _task, _model, messages, allowed, _ctx, _agent_name, _effort,
    ):
        packets.append((messages, allowed))
        return [], "completed", "ok"

    async def ignore_worker(_payload: dict) -> None:
        return None

    async def ignore_publish(_kind: str, **_payload: object) -> None:
        return None

    def capture_retrieval(query: str, *_args) -> tuple[str, list[str]]:
        retrieval_queries.append(query)
        return "", []

    monkeypatch.setattr(knowledge_activity, "emit", capture)
    monkeypatch.setattr(
        executor.retrieval,
        "fast_context_with_refs",
        capture_retrieval,
    )
    monkeypatch.setattr(executor, "_execute_session", complete_without_a_model)
    monkeypatch.setattr(executor.INDEX, "record_run", lambda **fields: runs.append(fields))
    monkeypatch.setattr(executor.INDEX, "sync", lambda: None)

    runtime = RealtimeSessionManager()
    runtime._phase = "command"
    runtime._conversation = MemoryConversation()
    monkeypatch.setattr(runtime, "_send_worker", ignore_worker)
    monkeypatch.setattr(runtime, "_publish", ignore_publish)
    utterances = ["First spoken request", "Second spoken request"]

    async def exercise() -> None:
        for utterance in utterances:
            await runtime._accept_transcript(utterance)
            turn = runtime._turn_task
            assert turn is not None
            await turn

    asyncio.run(exercise())

    for utterance in utterances:
        transaction = [event for event in events if event.get("query") == utterance]
        assert [event["phase"] for event in transaction] == [
            "query_started", "path", "query_completed",
        ]
        path = transaction[1]
        assert path["graph_id"] == "main"
        assert path["retrieval_ms"] > 0
        assert "Agents/Executive/Executive" in path["refs"]
        assert "Tasks/executive/realtime" in path["refs"]
        assert "Runbooks/realtime" in path["refs"]
        assert turn_memory.IMMEDIATE_OBSERVATIONS_REF in path["refs"]
        assert "Skills/appending-temporary-observations" not in path["refs"]
        assert "Tools/observations.temporary.append" not in path["refs"]

    assert len(packets) == 2
    for utterance, (messages, allowed) in zip(utterances, packets, strict=True):
        packet = messages[1]["content"]
        assert packet.startswith("# Thinking Packet")
        assert packet.count("## Objective") == 1
        objective_section = packet.split("## Objective\n", 1)[1].split("\n\n## ", 1)[0]
        immediate_section = packet.split("## Immediate Observations\n", 1)[1]
        assert objective_section == utterance
        assert utterance not in immediate_section
        assert "Owner request:" not in packet
        assert REALTIME_RESPONSE_CONTRACT in messages[0]["content"]
        assert llm.REALTIME_PROTOCOL in messages[0]["content"]
        assert allowed == []
    assert retrieval_queries == utterances
    assert [run["objective"] for run in runs] == utterances
    assert "## Immediate Observations" in packets[0][0][1]["content"]
    assert "User: First spoken request\nExecutive: ok" in packets[1][0][1]["content"]


def test_realtime_turn_ends_with_a_public_reply_not_task_complete(monkeypatch) -> None:
    task = resolver().resolve("Tasks/executive/realtime")
    assert task is not None
    model = model_runtime.resolve_model(
        task.meta.get("model"), "Agents/Executive/Executive",
    )

    class Lease:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    async def reply(*_args, **_kwargs):
        return llm.ChatReply(
            content='{"reply":"Yes, I can hear you."}',
            finish_reason="stop",
            completion_tokens=8,
        )

    monkeypatch.setattr(llm, "chat", reply)
    monkeypatch.setattr(model_runtime, "configured_spec", lambda _model_id: model)
    monkeypatch.setattr(model_runtime, "lease", lambda _model: Lease())

    trace, status, summary = asyncio.run(executor._execute_session(
        task,
        model,
        [{"role": "system", "content": llm.REALTIME_PROTOCOL}],
        [],
        {"realtime": True},
        "JARVIS",
        "none",
    ))

    assert status == "completed"
    assert summary == "Yes, I can hear you."
    assert trace == [{
        "reply_chars": 20,
        "reply_sha256": executor.hashlib.sha256(summary.encode()).hexdigest(),
    }]


def test_realtime_rejects_completion_then_uses_a_tool_and_replies(monkeypatch) -> None:
    mixed = '{"tool":"clock.read","args":{},"reply":"skip the Tool"}'
    assert llm.parse_action(mixed, allow_reply=True) is None
    assert llm.action_parse_error(mixed, allow_reply=True) == (
        "Realtime response contains both reply and tool fields"
    )

    task = resolver().resolve("Tasks/executive/realtime")
    assert task is not None
    model = model_runtime.resolve_model(
        task.meta.get("model"), "Agents/Executive/Executive",
    )

    class Lease:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    replies = iter((
        '{"tool":"task.complete","args":{"status":"completed","summary":"internal"}}',
        '{"tool":"clock.read","args":{}}',
        '{"reply":"It is 8:30 AM."}',
    ))
    calls: list[tuple[str, dict]] = []

    async def reply(*_args, **_kwargs):
        return llm.ChatReply(
            content=next(replies), finish_reason="stop", completion_tokens=8,
        )

    def execute_capability(name: str, args: dict, _ctx: dict):
        if name == "task.complete":
            return {
                "accepted": False,
                "status": "",
                "summary": "",
                "error": "task.complete is owned by the Realtime button",
            }
        calls.append((name, args))
        return "08:30"

    monkeypatch.setattr(llm, "chat", reply)
    monkeypatch.setattr(model_runtime, "configured_spec", lambda _model_id: model)
    monkeypatch.setattr(model_runtime, "lease", lambda _model: Lease())
    monkeypatch.setattr(executor, "execute_capability", execute_capability)

    trace, status, summary = asyncio.run(executor._execute_session(
        task,
        model,
        [{"role": "system", "content": llm.REALTIME_PROTOCOL}],
        ["clock.read"],
        {"realtime": True},
        "JARVIS",
        "none",
    ))

    assert status == "completed"
    assert summary == "It is 8:30 AM."
    assert calls == [("clock.read", {})]
    assert trace[0]["completion_rejected"] is True
    assert trace[1]["tool"] == "clock.read"
    assert trace[2]["reply_chars"] == len(summary)


def test_realtime_speaks_only_the_explicit_reply_field(monkeypatch) -> None:
    runtime = RealtimeSessionManager()
    runtime._phase = "command"
    spoken: list[dict] = []

    async def complete(*_args, **_kwargs):
        return {
            "run_id": "complete",
            "status": "completed",
            "summary": "internal ledger summary",
            "reply": "Public answer.",
        }

    async def capture_speech(payload: dict) -> None:
        spoken.append(payload)

    async def ignore_publish(_kind: str, **_payload: object) -> None:
        return None

    monkeypatch.setattr(executor, "run_task", complete)
    monkeypatch.setattr(runtime, "_send_worker", capture_speech)
    monkeypatch.setattr(runtime, "_publish", ignore_publish)

    asyncio.run(runtime._run_voice_turn("hello", runtime._generation))

    assert spoken == [{
        "type": "speak",
        "generation": runtime._generation,
        "text": "Public answer.",
    }]


def test_realtime_persists_only_the_exact_completed_public_pair(monkeypatch) -> None:
    runtime = RealtimeSessionManager()
    runtime._phase = "command"
    memory = MemoryConversation()
    runtime._conversation = memory
    user = asyncio.run(memory.append(role="user", source="realtime", text="hello"))

    async def complete(*_args, **_kwargs):
        return {
            "run_id": "complete",
            "status": "completed",
            "summary": "Public answer.",
            "reply": "Public answer.",
        }

    async def ignore(_payload: dict) -> None:
        return None

    async def ignore_publish(_kind: str, **_payload: object) -> None:
        return None

    monkeypatch.setattr(executor, "run_task", complete)
    monkeypatch.setattr(runtime, "_send_worker", ignore)
    monkeypatch.setattr(runtime, "_publish", ignore_publish)

    asyncio.run(runtime._run_voice_turn("hello", runtime._generation, user))

    assert [(turn["role"], turn["text"]) for turn in memory.turns] == [
        ("user", "hello"),
        ("assistant", "Public answer."),
    ]
    assert memory.turns[1]["reply_to"] == user["id"]


def test_realtime_failure_is_not_sent_to_speech(monkeypatch) -> None:
    runtime = RealtimeSessionManager()
    runtime._phase = "command"
    spoken: list[dict] = []
    published: list[tuple[str, dict]] = []

    async def fail(*_args, **_kwargs):
        return {"run_id": "failed", "status": "failed", "summary": "private failure detail"}

    async def capture_speech(payload: dict) -> None:
        spoken.append(payload)

    async def capture_publish(kind: str, **payload: object) -> None:
        published.append((kind, payload))

    monkeypatch.setattr(executor, "run_task", fail)
    monkeypatch.setattr(runtime, "_send_worker", capture_speech)
    monkeypatch.setattr(runtime, "_publish", capture_publish)

    memory = MemoryConversation()
    runtime._conversation = memory
    user = asyncio.run(memory.append(role="user", source="realtime", text="hello"))

    asyncio.run(runtime._run_voice_turn("hello", runtime._generation, user))

    assert spoken == []
    assert [turn["role"] for turn in memory.turns] == ["user"]
    assert runtime._last_error == "Realtime turn failed: private failure detail"
    assert published == [("runtime", {"line": runtime._last_error})]


def test_realtime_keeps_an_exited_worker_owned_until_cleanup() -> None:
    class ExitedProcess:
        returncode = 0
        pid = 123

    runtime = RealtimeSessionManager()
    runtime._process = ExitedProcess()

    snapshot = asyncio.run(runtime.start())

    assert snapshot["pid"] is None
    assert runtime._process is not None


def test_realtime_failed_preflight_does_not_rotate_the_executive_conversation(
    monkeypatch, tmp_path,
) -> None:
    python = tmp_path / "python"
    model = tmp_path / "model.nemo"
    python.touch()
    model.touch()
    runtime = RealtimeSessionManager()
    memory = MemoryConversation()
    runtime._conversation = memory

    monkeypatch.setattr("obsidience.harness.realtime.runtime.REALTIME_PYTHON", python)
    monkeypatch.setattr("obsidience.harness.realtime.runtime.NEMOTRON_MODEL", model)
    monkeypatch.setattr(
        "obsidience.harness.realtime.runtime.media_runtime.settings",
        lambda: (_ for _ in ()).throw(RuntimeError("stop after rotation")),
    )
    monkeypatch.setattr(
        "obsidience.harness.realtime.runtime.media_runtime.set_realtime_camera_active",
        lambda *_args: None,
    )

    with pytest.raises(RuntimeError, match="stop after rotation"):
        asyncio.run(runtime.start())

    assert memory.rotations == 0


def test_realtime_task_uses_its_ordinary_model_field() -> None:
    task = resolver().resolve("Tasks/executive/realtime")
    assert task is not None
    selected = model_runtime.resolve_model(
        task.meta.get("model"),
        "Agents/Executive/Executive",
    )
    assert selected.id == model_runtime.EXECUTIVE_MODEL
    assert selected.task_capable


def test_worker_interruption_is_not_echoed_back_to_pipecat(monkeypatch) -> None:
    runtime = RealtimeSessionManager()
    sent: list[dict] = []

    async def capture(payload: dict) -> None:
        sent.append(payload)

    monkeypatch.setattr(runtime, "_send_worker", capture)
    asyncio.run(runtime._cancel_turn(stop_playback=False))

    assert runtime._generation == 1
    assert sent == []


def test_transcript_starts_a_turn_without_echoing_cancel_to_pipecat(monkeypatch) -> None:
    runtime = RealtimeSessionManager()
    runtime._phase = "command"
    memory = MemoryConversation()
    runtime._conversation = memory
    sent: list[dict] = []

    async def capture(payload: dict) -> None:
        sent.append(payload)

    started = asyncio.Event()

    async def wait_for_cancel(_text: str, _generation: int, *_args, **_kwargs) -> None:
        assert [(turn["role"], turn["text"]) for turn in memory.turns] == [
            ("user", "Can you hear me?"),
        ]
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(runtime, "_send_worker", capture)
    monkeypatch.setattr(runtime, "_run_voice_turn", wait_for_cancel)

    async def exercise() -> None:
        await runtime._accept_transcript("Can you hear me?")
        assert runtime._turn_task is not None
        await asyncio.wait_for(started.wait(), timeout=1)
        runtime._turn_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await runtime._turn_task

    asyncio.run(exercise())

    assert runtime._generation == 1
    assert sent == []


def test_realtime_pause_admits_only_exact_executive_specialist_delegation(monkeypatch) -> None:
    specialist = resolver().resolve("Tasks/research/model")
    executive = resolver().resolve("Tasks/query")
    assert specialist is not None and executive is not None
    monkeypatch.setattr(RUNTIME, "scheduler_paused", lambda: True)

    autonomous = replace(specialist, meta={**specialist.meta, "params": {"event": "model.added"}})
    delegated = replace(
        specialist,
        meta={
            **specialist.meta,
            "params": {
                "event": "task.create",
                "realtime_delegate": True,
                "created_by_task_ref": "Tasks/executive/realtime",
            },
        },
    )
    forged = replace(
        specialist,
        meta={
            **specialist.meta,
            "params": {
                "realtime_delegate": True,
                "created_by_task_ref": "Tasks/query",
            },
        },
    )
    assert not scheduler._realtime_allows(autonomous)
    assert scheduler._realtime_allows(delegated)
    assert not scheduler._realtime_allows(forged)
    assert scheduler._realtime_allows(executive)


def test_observation_taxonomy_has_only_real_transition_tasks() -> None:
    assert TASK_TAXONOMY_BY_PATH["observations"].kind == "knowledge"
    assert TASK_TAXONOMY_BY_PATH["observations/immediate"].kind == "knowledge"
    assert TASK_TAXONOMY_BY_PATH["observations/temporary"].kind == "knowledge"
    assert TASK_TAXONOMY_BY_PATH["observations/durable"].kind == "knowledge"
    assert TASK_TAXONOMY_BY_PATH["observations/immediate/compact"].kind == "task"
    assert TASK_TAXONOMY_BY_PATH["observations/durable/promote"].kind == "task"
    assert "observations/temporary/expire" not in TASK_TAXONOMY_BY_PATH
    assert "observations/durable/distill" not in TASK_TAXONOMY_BY_PATH
    assert "observations/durable/stage" not in TASK_TAXONOMY_BY_PATH


def test_promotion_events_queue_fifo_while_an_earlier_result_is_in_review(
    monkeypatch,
) -> None:
    task = resolver().resolve("Tasks/observations/durable/promote")
    assert task is not None
    state = {**task.meta, "status": "review", "event_queue": []}

    def mutate(_task, operation):
        operation(state)
        return state

    monkeypatch.setattr(scheduler, "mutate_note_metadata", mutate)
    first = scheduler.enqueue_event(task, {
        "activation_key": "a" * 20,
        "queue_after_review": True,
    })
    duplicate = scheduler.enqueue_event(task, {
        "activation_key": "a" * 20,
        "queue_after_review": True,
    })
    second = scheduler.enqueue_event(task, {
        "activation_key": "b" * 20,
        "queue_after_review": True,
    })

    assert first["state"] == "queued" and first["position"] == 1
    assert duplicate["position"] == 1
    assert second["position"] == 2
    assert [row["activation_key"] for row in state["event_queue"]] == [
        "a" * 20,
        "b" * 20,
    ]


def test_promotion_waits_for_tasks_outside_the_scheduler_semaphore(monkeypatch) -> None:
    promotion = resolver().resolve("Tasks/observations/durable/promote")
    query = resolver().resolve("Tasks/query")
    assert promotion is not None and query is not None
    promotion = replace(promotion, meta={
        **promotion.meta,
        "status": "pending",
        "params": {"wait_for_idle": True},
    })
    running_query = replace(query, meta={**query.meta, "status": "running"})
    monkeypatch.setattr(scheduler, "_running", set())
    monkeypatch.setattr(scheduler, "_realtime_allows", lambda _note: True)
    monkeypatch.setattr(scheduler, "iter_notes", lambda: [promotion, running_query])
    assert promotion not in scheduler.due_tasks()

    finished_query = replace(query, meta={**query.meta, "status": "completed"})
    monkeypatch.setattr(scheduler, "iter_notes", lambda: [promotion, finished_query])
    assert promotion in scheduler.due_tasks()


def test_conversation_finalization_compacts_and_promotes_exactly_once(monkeypatch) -> None:
    runtime = RealtimeSessionManager()
    compacted = []
    promoted = []

    async def compact(**kwargs):
        compacted.append(kwargs)
        return {"status": "nothing_to_compact"}

    def promote(conversation_id: str, *, session_boundary: str):
        promoted.append((conversation_id, session_boundary))
        return {"state": "not_needed", "queued": 0}

    monkeypatch.setattr(runtime, "compact_conversation", compact)
    monkeypatch.setattr(turn_memory, "queue_temporary_promotion", promote)

    async def exercise() -> tuple[dict, dict]:
        first = await runtime.finalize_observation_session(
            "conversation-final",
            session_boundary="chat.new_conversation",
        )
        second = await runtime.finalize_observation_session(
            "conversation-final",
            session_boundary="chat.new_conversation",
        )
        return first, second

    first, second = asyncio.run(exercise())
    assert first["status"] == "finalized"
    assert second["status"] == "already_finalized"
    assert compacted == [{"force": True, "conversation_id": "conversation-final"}]
    assert promoted == [("conversation-final", "chat.new_conversation")]

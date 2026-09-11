from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from obsidience.harness.conversation import observations as turn_memory
from obsidience.harness.conversation import runtime as conversation_runtime
from obsidience.harness.execution import activity as knowledge_activity
from obsidience.harness.execution import executor, scheduler
from obsidience.harness.execution.executor import compile_activation
from obsidience.harness.conversation.runtime import (
    ConversationRuntime,
    MAX_CONTEXT_THRESHOLD, MIN_CONTEXT_THRESHOLD, SPEECH_RESPONSE_CONTRACT,
)
from obsidience.harness.knowledge import index as indexer
from obsidience.harness.knowledge.tasks import TASK_TAXONOMY_BY_PATH
from obsidience.harness.knowledge.vault import resolver
from obsidience.harness.models import llm
from obsidience.harness.models.context import PayloadCount
from obsidience.harness.models import runtime as model_runtime
from obsidience.harness.realtime.runtime import (
    REALTIME_CONFIRMATION,
    RUNTIME,
    RealtimeSessionManager,
)


class MemoryConversation:
    """Tiny exact-pair store for Realtime wiring tests; never touches the live ledger."""

    def __init__(self) -> None:
        self.index = indexer.INDEX
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
def fixed_async_task_admission(monkeypatch):
    """Lifecycle tests do not invoke the semantic selector's live provider."""
    async def select(text, source="voice", **_context):
        event = "voice.activation" if source == "voice" else "chat.request"
        return resolver().resolve("Tasks/query"), {
            "request": text, "source": source, "event": event, "computer_outcome": "answer",
        }, event

    monkeypatch.setattr(conversation_runtime, "select_task", select)


@pytest.fixture(autouse=True)
def immediate_observation_projection(monkeypatch):
    monkeypatch.setattr(executor, "update_status", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(indexer.INDEX, "complete_observation_finalization", lambda *_args: None)
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

    def capture_retrieval(query: str, *_args, **_kwargs) -> tuple[str, list[str]]:
        retrieval_queries.append(query)
        return "### [[Knowledge/test]] — Test Knowledge\nObjective-free context.", [
            "Knowledge/test"
        ]

    monkeypatch.setattr(
        executor.retrieval,
        "fast_context_with_refs",
        capture_retrieval,
    )
    scene_binding = {
        "available": True,
        "fields": ["kind", "name", "title", "focused", "visible"],
        "surfaces": {
            "samsung": [["app", "microsoft-edge", "Edge", False, True]],
            "usb-c": [["pane", "reader", "Reader", True, True]],
            "dp-4": [],
        },
    }
    monkeypatch.setattr(
        executor.shell_scene.SCENE,
        "activation_binding",
        lambda: scene_binding,
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
            conversation_context="No completed conversation pair exists yet.",
        )
    )
    full_packet = activation["packet"]
    assert "realtime_packet" not in activation
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
    assert activation["objective"] == objective
    assert activation["bindings"] == {"shell_scene": scene_binding}
    assert retrieval_queries == [objective]
    for packet in (full_packet,):
        binding_json = packet.split("## Bindings\n", 1)[1].split(
            "\n\n## Relevant Knowledge", 1
        )[0]
        assert json.loads(binding_json) == {"shell_scene": scene_binding}
        assert packet.count("## Objective") == 1
        assert packet.count(objective) == 1
        assert "Owner request:" not in packet
        assert "## Bound Parameters" not in packet
    assert activation["refs"][:2] == ["Agents/Executive/Executive", "Tasks/query"]
    assert "Runbooks/answer-the-user" in activation["refs"]


def test_computer_task_keeps_its_authored_tools():
    selected = resolver().resolve("Tasks/executive/operate")
    assert selected is not None and selected.kind == "task"
    spine = executor.resolve_spine(selected, resolver())
    assert {"computer.observe", "computer.act", "window.activate", "window.place"} <= set(spine["tools"])
    assert not hasattr(executor, "_select_realtime_skills")

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

    def capture_retrieval(query: str, *_args, **_kwargs) -> tuple[str, list[str]]:
        retrieval_queries.append(query)
        return "", []

    def capture_activity(phase: str, refs: list[str], **fields: object) -> dict:
        event = {"phase": phase, "refs": refs, **fields}
        events.append(event)
        return event

    async def complete_without_a_model(
        _task, _model, messages, _allowed, _ctx, _agent_name, _effort,
        interruption_event=None,
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
    monkeypatch.setattr(executor.INDEX, "sync", lambda **_kwargs: None)

    result = asyncio.run(
        executor.run_task(task, emit_turn_event=False)
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




def test_realtime_is_not_an_executable_task():
    task = resolver().resolve("Tasks/query")
    assert task is not None and task.kind == "task"
    assert resolver().resolve("Tasks/executive/realtime") is None







def test_idle_realtime_has_no_task_or_synthetic_thinking_packet(monkeypatch):
    phases = []
    monkeypatch.setattr(knowledge_activity, "emit", lambda phase, *args, **kwargs: phases.append(phase))
    runtime = RealtimeSessionManager(ConversationRuntime(MemoryConversation()))
    runtime._phase = "command"
    state = runtime.snapshot()
    assert state["ready"] and not state["scheduler_paused"]
    # Idle listening is not global admission policy; real reservations and
    # foreground demand remain independently checked by the scheduler.
    assert not {"task_ref", "task_run_id", "task_status", "model"} & state.keys()
    assert not hasattr(runtime, "_begin_task")
    assert not hasattr(runtime, "_activate_task_activity")
    assert phases == []

def test_speech_supervisor_does_not_own_conversation_or_task_execution():
    runtime = RealtimeSessionManager(ConversationRuntime(MemoryConversation()))
    assert not hasattr(runtime, "compact_conversation")
    assert not hasattr(runtime, "submit_text")
    assert not hasattr(runtime, "_execute_session")
    assert runtime.conversation is not None

def test_realtime_command_requests_the_local_ready_confirmation() -> None:
    runtime = RealtimeSessionManager(ConversationRuntime(MemoryConversation()))
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
    runtime = RealtimeSessionManager(ConversationRuntime(MemoryConversation()))
    assert runtime.snapshot()["live_transcript"] is None
    assert runtime.snapshot()["user_speaking"] is False
    assert runtime.snapshot()["acoustic_echo_cancellation"] is False
    runtime._aec_active = True
    assert runtime.snapshot()["acoustic_echo_cancellation"] is True


def test_context_threshold_uses_raw_tokens_and_caps_at_ninety(monkeypatch) -> None:
    runtime = ConversationRuntime(MemoryConversation())
    used = 799

    def status(**_kwargs):
        return {
            "used_tokens": used,
            "count_method": "runtime",
            "capacity_tokens": 1_000,
            "percent": 80.0,
            "compact_at": 80,
            "latest_sequence": 0,
            "compacted_through": 0,
        }

    monkeypatch.setattr(runtime, "context_status", status)
    assert MIN_CONTEXT_THRESHOLD == 60
    assert MAX_CONTEXT_THRESHOLD == 90
    assert asyncio.run(runtime.compact_conversation(force=False))["status"] == "not_needed"
    used = 800
    assert (
        asyncio.run(runtime.compact_conversation(force=False))["status"]
        == "nothing_to_compact"
    )


def test_context_meter_uses_selected_model_token_counts(monkeypatch) -> None:
    runtime = ConversationRuntime(MemoryConversation())
    runtime._conversation = MemoryConversation()
    runtime._thinking_overhead_tokens = 50
    spec = SimpleNamespace(context_tokens=1_000, max_output_tokens=100)
    turn_spec = SimpleNamespace(context_tokens=2_000, max_output_tokens=200)
    counted: list[str] = []
    counted_specs: list[object] = []

    def count(text: str, selected_spec) -> PayloadCount:
        counted.append(text)
        counted_specs.append(selected_spec)
        return PayloadCount(7 if text == "pending objective" else 11)

    monkeypatch.setattr(runtime, "_context_model", lambda _task_ref=None: spec)
    monkeypatch.setattr(runtime, "_context_threshold", lambda: 80)
    monkeypatch.setattr("obsidience.harness.conversation.runtime.cached_text_count", count)
    monkeypatch.setattr(
        model_runtime,
        "configured_spec",
        lambda model_id: turn_spec if model_id == "model-used-for-the-turn" else None,
    )

    status = runtime.context_status(pending_text="pending objective")
    assert status["used_tokens"] == 68
    assert status["count_method"] == "runtime"
    assert status["capacity_tokens"] == 644
    assert counted[-1] == "pending objective"

    runtime.record_prompt_usage(
        {
            "model": "model-used-for-the-turn",
            "prompt_tokens_estimate": 100,
            "conversation_tokens_estimate": 30,
        },
        request_text="pending objective",
    )
    assert runtime._thinking_overhead_tokens == 63
    assert counted_specs[-1] is turn_spec


def test_fitting_cached_bound_never_waits_for_tokenization(monkeypatch) -> None:
    runtime = ConversationRuntime(MemoryConversation())
    runtime._thinking_overhead_tokens = 0
    monkeypatch.setattr(runtime, "_context_model", lambda _ref=None: SimpleNamespace(
        context_tokens=1_256, max_output_tokens=0))
    monkeypatch.setattr(runtime, "_context_threshold", lambda: 80)
    monkeypatch.setattr(conversation_runtime, "cached_text_count", lambda text, _spec: (
        PayloadCount(799, "utf8_upper_bound") if text else PayloadCount(0)))

    async def unexpected(*_args):
        pytest.fail("a fitting upper bound must not wait for the tokenizer")

    monkeypatch.setattr(conversation_runtime, "measure_text", unexpected)
    result = asyncio.run(runtime.compact_conversation(force=False))
    assert result["status"] == "not_needed"
    assert result["context"]["count_method"] == "utf8_upper_bound"
    assert result["context"]["used_tokens"] == 799


@pytest.mark.parametrize("method, measured, expected", [
    ("runtime", 100, "not_needed"),
    ("utf8_upper_bound", 900, "measurement_unavailable"),
    ("runtime", 800, "nothing_to_compact"),
])
def test_only_confirmed_context_pressure_can_reach_compaction(monkeypatch, method, measured, expected):
    runtime = ConversationRuntime(MemoryConversation())
    runtime._thinking_overhead_tokens = 0
    selected = SimpleNamespace(context_tokens=1_256, max_output_tokens=0)
    monkeypatch.setattr(runtime, "_context_model", lambda _ref=None: selected)
    monkeypatch.setattr(runtime, "_context_threshold", lambda: 80)
    monkeypatch.setattr(conversation_runtime, "cached_text_count", lambda text, _spec: (
        PayloadCount(900, "utf8_upper_bound") if text else PayloadCount(0)))
    calls = []

    async def measure(text, spec):
        calls.append((text, spec))
        return PayloadCount(measured, method) if text else PayloadCount(0)

    monkeypatch.setattr(conversation_runtime, "measure_text", measure)
    result = asyncio.run(runtime.compact_conversation(force=False))
    assert result["status"] == expected
    assert result["context"]["used_tokens"] == measured
    assert result["context"]["count_method"] == method
    assert calls == [("No completed conversation pair exists yet.", selected), ("", selected)]


def test_prepare_context_binds_the_user_conversation_task_and_request(monkeypatch) -> None:
    runtime = ConversationRuntime(MemoryConversation())
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


def test_typed_realtime_input_preserves_the_complete_objective(monkeypatch) -> None:
    runtime = ConversationRuntime(MemoryConversation())
    memory = MemoryConversation()
    runtime._conversation = memory
    captured: list[str] = []

    async def run_turn(text: str, *_args, **_kwargs) -> dict:
        captured.append(text)
        return {"status": "completed"}

    monkeypatch.setattr(runtime, "_run_turn", run_turn)
    objective = "  Preserve   formatting\n" + ("exact-objective " * 400)
    asyncio.run(runtime.submit(objective))

    expected = objective.strip()
    assert len(expected) > 4_000
    assert captured == [expected]
    assert memory.turns[0]["text"] == expected


def test_compact_commits_the_captured_conversation_after_rotation(monkeypatch) -> None:
    runtime = ConversationRuntime(MemoryConversation())
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
        assert "keep_task_open" not in fields
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
    monkeypatch.setattr(indexer.INDEX, "sync", lambda **_kwargs: None)

    async def seed_pair() -> None:
        user = await memory.append(role="user", source="text", text="old")
        await memory.append(
            role="assistant",
            source="text",
            text="reply",
            reply_to=user["id"],
        )

    asyncio.run(seed_pair())

    result = asyncio.run(runtime.compact_conversation(
        force=True,
        conversation_id="conversation-test",
        context_task_ref="Tasks/query",
        closed_session=True,
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
    runtime = ConversationRuntime(MemoryConversation())
    memory = MemoryConversation()
    runtime._conversation = memory
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
    monkeypatch.setattr(indexer.INDEX, "sync", lambda **_kwargs: None)

    async def seed_pair() -> None:
        user = await memory.append(role="user", source="text", text="old")
        await memory.append(
            role="assistant",
            source="text",
            text="reply",
            reply_to=user["id"],
        )

    asyncio.run(seed_pair())

    if mode == "canceled":
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(runtime.compact_conversation(force=True, closed_session=True))
    else:
        result = asyncio.run(runtime.compact_conversation(force=True, closed_session=True))
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

    runtime = RealtimeSessionManager(ConversationRuntime(MemoryConversation()))
    runtime._live_transcript = {"text": "old utterance", "final": True}
    published: list[tuple[dict | None, bool]] = []
    accepted: list[str] = []
    finished = asyncio.Event()

    async def capture_publish(_kind: str, **_payload: object) -> None:
        snapshot = runtime.snapshot()
        published.append((snapshot["live_transcript"], snapshot["user_speaking"]))

    async def capture_transcript(text: str, **_kwargs) -> None:
        accepted.append(text)
        finished.set()

    monkeypatch.setattr(runtime, "_publish", capture_publish)
    monkeypatch.setattr(runtime.conversation, "submit", capture_transcript)

    async def exercise() -> None:
        runtime._process = FakeProcess()
        runtime._phase = "command"
        monitor = asyncio.create_task(runtime._monitor_process(runtime._process, 0))
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
        interruption_event=None,
    ):
        packets.append((messages, allowed))
        return [], "completed", "ok"

    async def ignore_worker(_payload: dict) -> None:
        return None

    async def ignore_publish(_kind: str, **_payload: object) -> None:
        return None

    def capture_retrieval(query: str, *_args, **_kwargs) -> tuple[str, list[str]]:
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
    monkeypatch.setattr(executor.INDEX, "sync", lambda **_kwargs: None)

    runtime = RealtimeSessionManager(ConversationRuntime(MemoryConversation()))
    runtime._phase = "command"
    runtime.conversation._conversation = MemoryConversation()
    runtime.conversation.speech = runtime
    monkeypatch.setattr(runtime, "_send_worker", ignore_worker)
    monkeypatch.setattr(runtime, "_publish", ignore_publish)
    utterances = ["First spoken request", "Second spoken request"]

    async def exercise() -> None:
        for utterance in utterances:
            await runtime.conversation.submit(utterance, source="realtime", wait=False)
            turn = runtime.conversation._turn_task
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
        assert "Tasks/query" in path["refs"]
        assert "Runbooks/answer-the-user" in path["refs"]
        assert turn_memory.IMMEDIATE_OBSERVATIONS_REF in path["refs"]
        assert "Skills/observations.temporary.append" in path["refs"]
        assert "Tools/observations.temporary.append" in path["refs"]

    assert len(packets) == 2
    for utterance, (messages, allowed) in zip(utterances, packets, strict=True):
        assert messages[1]["content"].startswith("## Immediate Observations")
        packet = messages[2]["content"]
        assert packet.startswith("## Objective")
        assert "# Thinking Packet" in messages[0]["content"]
        assert "## Tools" in messages[0]["content"]
        assert "## Runbook" in messages[0]["content"]
        assert "## Objective\n" not in messages[0]["content"]
        assert packet.count("## Objective") == 1
        objective_section = packet.split("## Objective\n", 1)[1].split("\n\n## ", 1)[0]
        immediate_section = messages[1]["content"].split("## Immediate Observations\n", 1)[1]
        assert objective_section == utterance
        assert utterance not in immediate_section
        assert "Owner request:" not in packet
        assert SPEECH_RESPONSE_CONTRACT in messages[0]["content"]
        assert llm.PROTOCOL in messages[0]["content"]
        assert "task.complete" in allowed
        assert "vault.read" in allowed
    assert retrieval_queries == utterances
    assert [run["objective"] for run in runs] == utterances
    assert "## Immediate Observations" in packets[0][0][1]["content"]
    assert "User: First spoken request\nExecutive: ok" in packets[1][0][1]["content"]


def test_interactive_task_completes_through_normal_tool(monkeypatch):
    task = resolver().resolve("Tasks/query")
    model = model_runtime.resolve_model(task.meta.get("model"), "Agents/Executive/Executive")
    class Lease:
        async def __aenter__(self): return self
        async def __aexit__(self, *_args): return None
    async def reply(*_args, **_kwargs):
        return llm.ChatReply(content='{"tool":"task.complete","args":{"status":"completed","summary":"Yes, I can hear you."}}', finish_reason="stop", completion_tokens=8)
    monkeypatch.setattr(llm, "chat", reply)
    monkeypatch.setattr(model_runtime, "lease", lambda _: Lease())
    monkeypatch.setattr(model_runtime, "configured_spec", lambda _: model)
    trace, status, summary = asyncio.run(executor._execute_session(
        task, model, [{"role":"system","content":llm.PROTOCOL}],
        ["task.complete"], {"interactive":True, "task":task.ref}, "Executive", "none",
    ))
    assert status == "completed" and summary == "Yes, I can hear you."
    assert trace[-1]["tool"] == "task.complete"

def test_visual_observation_reaches_only_the_ephemeral_model_message(monkeypatch) -> None:
    task = resolver().resolve("Tasks/executive/operate")
    assert task is not None
    model = model_runtime.resolve_model(
        task.meta.get("model"), "Agents/Executive/Executive",
    )
    assert "vision" in model.capabilities

    class Lease:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    replies = iter((
        '{"tool":"computer.observe","args":{"target":{"kind":"pane",'
        '"name":"reader"},"query":"What is visible?"}}',
        '{"tool":"task.complete","args":{"summary":"The Reader is showing Source.","status":"completed"}}',
    ))
    requests: list[list[dict]] = []

    async def reply(messages, **_kwargs):
        requests.append(json.loads(json.dumps(messages)))
        return llm.ChatReply(
            content=next(replies), finish_reason="stop", completion_tokens=8,
        )

    def execute_capability(name: str, _args: dict, _ctx: dict):
        if name == "task.complete":
            return {"accepted": True, "status": "completed", "summary": _args["summary"]}
        assert name == "computer.observe"
        return {
            "observation": {
                "status": "observed",
                "target": {"kind": "pane", "name": "reader"},
            },
            "_private_image_png": b"pixels",
        }

    monkeypatch.setattr(llm, "chat", reply)
    monkeypatch.setattr(model_runtime, "configured_spec", lambda _model_id: model)
    monkeypatch.setattr(model_runtime, "lease", lambda _model: Lease())
    monkeypatch.setattr(executor, "execute_capability", execute_capability)

    trace, status, summary = asyncio.run(executor._execute_session(
        task,
        model,
        [{"role": "system", "content": llm.PROTOCOL}],
        ["computer.observe", "task.complete"],
        {"interactive": True, "task": task.ref},
        "Executive",
        "none",
    ))

    assert status == "completed"
    assert summary == "The Reader is showing Source."
    visual_message = requests[1][-1]
    assert visual_message["role"] == "user"
    assert visual_message["content"][0]["type"] == "text"
    assert visual_message["content"][1] == {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64,cGl4ZWxz"},
    }
    persisted = json.dumps(trace)
    assert "_private_image_png" not in persisted
    assert "pixels" not in persisted


def test_visual_observation_fails_before_capture_for_a_text_only_model(monkeypatch) -> None:
    task = resolver().resolve("Tasks/executive/operate")
    assert task is not None
    selected = model_runtime.resolve_model(
        task.meta.get("model"), "Agents/Executive/Executive",
    )
    model = replace(selected, capabilities=("text", "reasoning", "tools"))

    class Lease:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    replies = iter((
        '{"tool":"computer.observe","args":{"target":{"kind":"focused"},'
        '"query":"What is visible?"}}',
        '{"tool":"task.complete","args":{"summary":"Visual evidence is unavailable to this model.","status":"completed"}}',
    ))
    requests: list[list[dict]] = []

    async def reply(messages, **_kwargs):
        requests.append(json.loads(json.dumps(messages)))
        return llm.ChatReply(
            content=next(replies), finish_reason="stop", completion_tokens=8,
        )

    def should_not_capture(name, args, _ctx):
        if name == "task.complete":
            return {"accepted": True, "status": "completed", "summary": args["summary"]}
        raise AssertionError("computer.observe must not capture for a text-only model")

    monkeypatch.setattr(llm, "chat", reply)
    monkeypatch.setattr(model_runtime, "configured_spec", lambda _model_id: model)
    monkeypatch.setattr(model_runtime, "lease", lambda _model: Lease())
    monkeypatch.setattr(executor, "execute_capability", should_not_capture)

    trace, status, _summary = asyncio.run(executor._execute_session(
        task,
        model,
        [{"role": "system", "content": llm.PROTOCOL}],
        ["computer.observe", "task.complete"],
        {"interactive": True, "task": task.ref},
        "Executive",
        "none",
    ))

    assert status == "completed"
    assert "model_has_no_vision" in requests[1][-1]["content"]
    assert "model_has_no_vision" in trace[0]["obs"]


def test_reply_only_protocol_is_not_accepted():
    assert llm.parse_action('{"reply":"skip verification"}') is None
    assert not hasattr(llm, "REALTIME_PROTOCOL")


@pytest.mark.parametrize("text", ["Hello there", "Move TFT to the Samsung"])
def test_text_and_speech_use_the_same_task_and_model_even_while_connected(monkeypatch, text):
    calls = []

    async def run(task, **kwargs):
        calls.append((task.ref, task.meta.get("model"), task.meta.get("reasoning_effort"), kwargs))
        return {"status": "completed", "run_id": "test", "summary": "Done."}

    async def ignore(_payload):
        pass

    monkeypatch.setattr(executor, "run_task", run)

    async def check():
        for source in ("text", "realtime"):
            runtime = ConversationRuntime(MemoryConversation())
            speech = RealtimeSessionManager(runtime)
            speech._phase = "command"
            runtime.speech = speech
            monkeypatch.setattr(speech, "_send_worker", ignore)
            await runtime.submit(text, source=source)
            assert [turn["text"] for turn in runtime._conversation.turns] == [text, "Done."]

    asyncio.run(check())
    assert calls[0][:3] == calls[1][:3]
    assert calls[0][1] == "obsidience-gemma"
    for _, _, _, kwargs in calls:
        assert kwargs["interactive"] is True
        assert kwargs["conversation_context"]
        assert "realtime_projection" not in kwargs
    assert "response_contract" not in calls[0][3]["runtime_params"]
    assert calls[1][3]["runtime_params"]["response_contract"] == SPEECH_RESPONSE_CONTRACT

@pytest.mark.parametrize("status", ["failed", "review", "waiting"])
def test_noncompleted_results_never_persist_a_successful_pair(monkeypatch, status):
    runtime = ConversationRuntime(MemoryConversation())
    speech = RealtimeSessionManager(runtime)
    speech._phase = "command"
    runtime.speech = speech
    spoken = []
    async def result(*args, **kwargs):
        return {"status": status, "summary": "not a verified public answer"}
    async def send(payload): spoken.append(payload)
    monkeypatch.setattr(executor, "run_task", result)
    monkeypatch.setattr(speech, "_send_worker", send)
    asyncio.run(runtime.submit("hello", source="realtime"))
    notices = [p for p in spoken if p["type"] == "speak"]
    assert len(notices) == (0 if status == "waiting" else 1)
    assert all("not a verified public answer" not in p["text"] for p in notices)
    assert [row["role"] for row in runtime._conversation.turns] == ["user"]

def test_realtime_persists_only_the_exact_completed_public_pair(monkeypatch) -> None:
    runtime = RealtimeSessionManager(ConversationRuntime(MemoryConversation()))
    runtime._phase = "command"
    memory = MemoryConversation()
    runtime.conversation._conversation = memory
    runtime.conversation.speech = runtime
    user = asyncio.run(memory.append(role="user", source="realtime", text="hello"))

    async def complete(*_args, **_kwargs):
        return {
            "run_id": "complete",
            "status": "completed",
            "summary": "Public answer.",
        }

    async def ignore(_payload: dict) -> None:
        return None

    async def ignore_publish(_kind: str, **_payload: object) -> None:
        return None

    monkeypatch.setattr(executor, "run_task", complete)
    monkeypatch.setattr(runtime, "_send_worker", ignore)
    monkeypatch.setattr(runtime, "_publish", ignore_publish)

    asyncio.run(runtime.conversation._run_turn("hello", runtime.conversation._generation, user, source="realtime"))

    assert [(turn["role"], turn["text"]) for turn in memory.turns] == [
        ("user", "hello"),
        ("assistant", "Public answer."),
    ]
    assert memory.turns[1]["reply_to"] == user["id"]


def test_realtime_internal_failure_gets_only_a_generic_spoken_notice(monkeypatch) -> None:
    runtime = RealtimeSessionManager(ConversationRuntime(MemoryConversation()))
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
    runtime.conversation._conversation = memory
    runtime.conversation.speech = runtime
    user = asyncio.run(memory.append(role="user", source="realtime", text="hello"))

    asyncio.run(runtime.conversation._run_turn("hello", runtime.conversation._generation, user, source="realtime"))

    assert len(spoken) == 1 and spoken[0]["type"] == "speak"
    assert "private failure detail" not in spoken[0]["text"]
    assert [turn["role"] for turn in memory.turns] == ["user"]
    assert runtime._last_error is None
    assert published == [("task_result", {"status": "failed", "text": spoken[0]["text"], "run_id": "failed"})]


def test_resource_blocked_turn_explains_admission_without_success_or_replay(monkeypatch) -> None:
    runtime = ConversationRuntime(MemoryConversation())
    speech = RealtimeSessionManager(runtime)
    speech._phase = "command"
    runtime.speech = speech
    spoken = []

    async def blocked(*args, **kwargs):
        return {"status": "blocked", "resource_blocked": True,
                "summary": "private resource details", "resource": {"private": "value"}}

    async def send(payload):
        spoken.append(payload)

    monkeypatch.setattr(executor, "run_task", blocked)
    monkeypatch.setattr(speech, "_send_worker", send)
    result = asyncio.run(runtime.submit("hello", source="realtime"))
    notices = [payload["text"] for payload in spoken if payload["type"] == "speak"]
    assert result["status"] == "blocked"
    assert notices == ["The selected model's hardware is currently reserved. "
                       "Please retry this request when it is available."]
    assert [row["role"] for row in runtime._conversation.turns] == ["user"]
    assert speech._last_error is None


def test_realtime_keeps_an_exited_worker_owned_until_cleanup() -> None:
    class ExitedProcess:
        returncode = 0
        pid = 123

    runtime = RealtimeSessionManager(ConversationRuntime(MemoryConversation()))
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
    runtime = RealtimeSessionManager(ConversationRuntime(MemoryConversation()))
    memory = MemoryConversation()
    runtime.conversation._conversation = memory

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


@pytest.mark.parametrize("task_ref,effort", [("Tasks/query","none"), ("Tasks/executive/operate","none")])
def test_interactive_tasks_keep_their_authored_model_and_effort(task_ref, effort):
    task = resolver().resolve(task_ref)
    assert task.meta["model"] == model_runtime.EXECUTIVE_MODEL
    assert task.meta["reasoning_effort"] == effort

def test_worker_interruption_is_not_echoed_back_to_pipecat(monkeypatch) -> None:
    runtime = RealtimeSessionManager(ConversationRuntime(MemoryConversation()))
    sent: list[dict] = []

    async def capture(payload: dict) -> None:
        sent.append(payload)

    monkeypatch.setattr(runtime, "_send_worker", capture)
    asyncio.run(runtime.conversation.cancel(stop_playback=False))

    assert runtime.conversation._generation == 1
    assert sent == []


def test_transcript_invalidates_pending_speech_without_echoing_interruption(monkeypatch) -> None:
    runtime = RealtimeSessionManager(ConversationRuntime(MemoryConversation()))
    runtime._phase = "command"
    memory = MemoryConversation()
    runtime.conversation._conversation = memory
    runtime.conversation.speech = runtime
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
    monkeypatch.setattr(runtime.conversation, "_run_turn", wait_for_cancel)

    async def exercise() -> None:
        await runtime.conversation.submit("Can you hear me?", source="realtime", wait=False)
        assert runtime.conversation._turn_task is not None
        await asyncio.wait_for(started.wait(), timeout=1)
        runtime.conversation._turn_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await runtime.conversation._turn_task

    asyncio.run(exercise())

    assert runtime.conversation._generation == 1
    assert sent == [{"type": "cancel", "generation": 1, "stop_playback": False}]


def test_realtime_pause_does_not_trust_forged_flags(monkeypatch):
    specialist = resolver().resolve("Tasks/research/model")
    executive = resolver().resolve("Tasks/query")
    monkeypatch.setattr(RUNTIME, "scheduler_paused", lambda: True)
    forged = replace(specialist, meta={**specialist.meta, "params":{
        "event":"task.create", "interactive":True, "realtime_delegate":True,
        "created_by_task_ref":"Tasks/query", "created_by_run_id":"missing",
    }})
    assert not scheduler._realtime_allows(forged)
    assert scheduler._realtime_allows(executive)

def test_observation_taxonomy_has_only_real_transition_tasks() -> None:
    assert TASK_TAXONOMY_BY_PATH["observations"].kind == "knowledge"
    assert TASK_TAXONOMY_BY_PATH["observations"].children == (
        "observations/compact", "observations/promote",
    )
    assert {path for path in TASK_TAXONOMY_BY_PATH if path.startswith("observations/")} == {
        "observations/compact", "observations/promote",
    }
    assert TASK_TAXONOMY_BY_PATH["observations/compact"].kind == "task"
    assert TASK_TAXONOMY_BY_PATH["observations/promote"].kind == "task"


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
    monkeypatch.setattr(scheduler, "_realtime_allows", lambda _note, _res=None: True)
    monkeypatch.setattr(scheduler, "iter_notes", lambda: [promotion, running_query])
    assert promotion not in scheduler.due_tasks()

    finished_query = replace(query, meta={**query.meta, "status": "completed"})
    monkeypatch.setattr(scheduler, "iter_notes", lambda: [promotion, finished_query])
    assert promotion in scheduler.due_tasks()


def test_conversation_finalization_is_idempotent_through_sequence(monkeypatch) -> None:
    runtime = ConversationRuntime(MemoryConversation())
    compacted = []
    promoted = []
    latest_sequence = 4
    promoted_through = 0

    async def compact(**kwargs):
        compacted.append(kwargs)
        return {"status": "nothing_to_compact"}

    def promote(conversation_id: str, *, session_boundary: str):
        nonlocal promoted_through
        promoted.append((conversation_id, session_boundary))
        promoted_through = latest_sequence
        return {"state": "not_needed", "queued": 0}

    def project(_conversation, **_fields):
        return {"latest_sequence": latest_sequence}

    monkeypatch.setattr(runtime, "compact_conversation", compact)
    monkeypatch.setattr(turn_memory, "queue_temporary_promotion", promote)
    monkeypatch.setattr(turn_memory, "project_immediate_observations", project)
    monkeypatch.setattr(
        turn_memory,
        "promoted_context_sequence",
        lambda *_args, **_kwargs: promoted_through,
    )

    async def exercise() -> tuple[dict, dict, dict]:
        nonlocal latest_sequence
        first = await runtime.finalize_observation_session(
            "conversation-final",
            session_boundary="chat.new_conversation",
        )
        second = await runtime.finalize_observation_session(
            "conversation-final",
            session_boundary="chat.new_conversation",
        )
        latest_sequence = 6
        third = await runtime.finalize_observation_session(
            "conversation-final",
            session_boundary="realtime.stopped",
        )
        return first, second, third

    first, second, third = asyncio.run(exercise())
    assert first["status"] == "finalized"
    assert second["status"] == "already_finalized"
    assert third["status"] == "finalized"
    assert compacted == [
        {
            "force": True,
            "conversation_id": "conversation-final",
            "closed_session": True,
        },
        {
            "force": True,
            "conversation_id": "conversation-final",
            "closed_session": True,
        },
    ]
    assert promoted == [
        ("conversation-final", "chat.new_conversation"),
        ("conversation-final", "realtime.stopped"),
    ]












def test_deliberate_failed_completion_is_a_transient_notice_and_connection_stays_ready(monkeypatch):
    runtime = ConversationRuntime(MemoryConversation())
    speech = RealtimeSessionManager(runtime)
    speech._phase = 'command'
    runtime.speech = speech
    spoken = []
    async def result(*args, **kwargs):
        return {'status': 'failed', 'summary': 'diagnostic details',
                'public_summary': 'Which application do you mean?', 'run_id': 'clarification'}
    async def send(payload):
        spoken.append(payload)
    monkeypatch.setattr(executor, 'run_task', result)
    monkeypatch.setattr(speech, '_send_worker', send)
    value = asyncio.run(runtime.submit('Bring it to the foreground', source='realtime'))
    assert value['status'] == 'failed'
    assert speech.snapshot()['ready'] and speech._last_error is None
    assert [p['text'] for p in spoken if p['type'] == 'speak'] == ['Which application do you mean?']
    assert [row['role'] for row in runtime._conversation.turns] == ['user']
    assert any(e.get('status') == 'failed' and e['text'] == 'Which application do you mean?'
               for e in runtime._conversation.events)


def test_stale_task_notice_is_not_spoken_or_published(monkeypatch):
    runtime = ConversationRuntime(MemoryConversation())
    speech = RealtimeSessionManager(runtime)
    speech._phase = 'command'
    runtime.speech = speech
    spoken = []
    async def send(payload):
        spoken.append(payload)
    monkeypatch.setattr(speech, '_send_worker', send)
    asyncio.run(runtime._report_task_outcome(
        {'status': 'failed', 'public_summary': 'Old failure'}, source='realtime', generation=-1))
    assert spoken == []
    assert runtime._conversation.events == []


def test_canceled_preexecution_has_bounded_causal_trace(monkeypatch):
    from obsidience.harness.execution import trace
    runtime = ConversationRuntime(MemoryConversation())
    entries = []
    monkeypatch.setattr(trace, 'emit', lambda *args: entries.append(args))
    async def exercise():
        ready = asyncio.Event()
        async def prepare(*args, **kwargs):
            ready.set()
            await asyncio.Event().wait()
        monkeypatch.setattr(runtime, 'prepare_immediate_observations', prepare)
        await runtime.submit('Can you focus Edge?', wait=False)
        await ready.wait()
        await runtime.cancel(reason='speech.interruption', stop_playback=False)
    asyncio.run(exercise())
    canceled = [e for e in entries if e[0] == 'interruption']
    assert len(canceled) == 1
    assert 'reason: speech.interruption' in canceled[0][2]
    assert any('turn-1' in item for item in canceled[0][2])
    assert all('Can you focus Edge?' not in item for item in canceled[0][2])


def test_unexpected_task_error_has_one_generic_public_notice(monkeypatch):
    runtime = ConversationRuntime(MemoryConversation())
    speech = RealtimeSessionManager(runtime)
    speech._phase = 'command'
    runtime.speech = speech
    spoken, diagnostics = [], []
    async def fail(*args, **kwargs):
        raise RuntimeError('private diagnostic fixture')
    async def send(payload):
        spoken.append(payload)
    monkeypatch.setattr(executor, 'run_task', fail)
    monkeypatch.setattr(speech, '_send_worker', send)
    monkeypatch.setattr('obsidience.harness.conversation.runtime.trace.emit',
                        lambda *args: diagnostics.append(args))
    result = asyncio.run(runtime.submit('Can you focus Edge?', source='realtime'))
    assert result['status'] == 'failed'
    errors = [e for e in runtime._conversation.events if e.get('type') == 'error']
    assert len(errors) == 1
    assert 'private diagnostic fixture' not in json.dumps(errors + spoken)
    assert 'private diagnostic fixture' in str(diagnostics)
    assert [p['text'] for p in spoken if p['type'] == 'speak'] == [errors[0]['text']]
    assert speech.snapshot()['ready'] and speech._last_error is None
    assert [r['role'] for r in runtime._conversation.turns] == ['user']


def test_speech_pipe_failure_preserves_verified_task_and_chat_reply(monkeypatch):
    runtime = ConversationRuntime(MemoryConversation())
    speech = RealtimeSessionManager(runtime)
    speech._phase = 'command'
    runtime.speech = speech
    attempted = []
    async def completed(*args, **kwargs):
        return {'status': 'completed', 'summary': 'Edge is focused.', 'run_id': 'verified-focus'}
    async def send(payload):
        if payload['type'] == 'speak':
            attempted.append(payload)
            raise BrokenPipeError('speech process ended')
    monkeypatch.setattr(executor, 'run_task', completed)
    monkeypatch.setattr(speech, '_send_worker', send)
    result = asyncio.run(runtime.submit('Can you focus Edge?', source='realtime'))
    assert result['status'] == 'completed'
    assert len(attempted) == 1
    assert [r['role'] for r in runtime._conversation.turns] == ['user', 'assistant']
    assert runtime._conversation.turns[-1]['run_id'] == 'verified-focus'
    assert 'BrokenPipeError' in speech._last_error
    assert not any(e.get('type') == 'error' for e in runtime._conversation.events)


def test_notice_rechecks_generation_after_event_publication(monkeypatch):
    runtime = ConversationRuntime(MemoryConversation())
    speech = RealtimeSessionManager(runtime)
    speech._phase = 'command'
    runtime.speech = speech
    spoken = []
    async def publish(*args, **kwargs):
        runtime._generation += 1
    async def send(payload):
        spoken.append(payload)
    monkeypatch.setattr(speech, '_publish', publish)
    monkeypatch.setattr(speech, '_send_worker', send)
    asyncio.run(runtime._report_task_outcome(
        {'status': 'failed', 'public_summary': 'Old failed turn'},
        source='realtime', generation=0))
    assert spoken == []


def test_acoustic_cancel_invalidates_worker_before_task_cleanup(monkeypatch):
    runtime = ConversationRuntime(MemoryConversation())
    speech = RealtimeSessionManager(runtime)
    runtime.speech = speech
    async def exercise():
        running, invalidated, release_cleanup = asyncio.Event(), asyncio.Event(), asyncio.Event()
        messages = []
        async def task():
            try:
                running.set()
                await asyncio.Event().wait()
            finally:
                await release_cleanup.wait()
        async def send(payload):
            messages.append(payload)
            invalidated.set()
        monkeypatch.setattr(speech, '_send_worker', send)
        runtime._turn_task = asyncio.create_task(task())
        await running.wait()
        cancellation = asyncio.create_task(runtime.cancel(stop_playback=False, reason='speech.interruption'))
        await asyncio.wait_for(invalidated.wait(), 1)
        assert not cancellation.done()
        assert messages == [{'type': 'cancel', 'generation': 1, 'stop_playback': False}]
        release_cleanup.set()
        await cancellation
    asyncio.run(exercise())


def test_coordinator_prepares_context_before_selection_and_shares_exact_execution_evidence(monkeypatch):
    memory = MemoryConversation()
    runtime = ConversationRuntime(memory)
    calls = []
    selected_inputs = {}
    exact_context = "User: Click normal game\nExecutive: I clicked NORMAL."

    async def prepare(user_turn, **_kwargs):
        calls.append("context")
        assert user_turn["sequence"] == 3
        return exact_context

    async def select(text, source, *, conversation_context, historical_evidence):
        calls.append("selection")
        assert conversation_context == exact_context
        assert historical_evidence[0]["run_id"] == "prior-click"
        assert historical_evidence[0]["effect_dispatched"] is True
        assert historical_evidence[0]["current_state"] is False
        selected_inputs.update(context=conversation_context, evidence=historical_evidence)
        return resolver().resolve("Tasks/executive/operate"), {
            "request": text, "source": source, "event": "chat.request",
            "computer_outcome": "action", "computer_scope": "state",
            "application": "teamfight_tactics", "operation": "computer_use",
        }, "chat.request"

    async def execute(task, **fields):
        calls.append("execution")
        assert task.ref == "Tasks/executive/operate"
        assert fields["conversation_context"] == selected_inputs["context"]
        assert fields["conversation_evidence"] is selected_inputs["evidence"]
        assert fields["runtime_params"]["request"] == "Can you start the match?"
        # This wiring test does not execute an application effect.
        return {"status": "failed", "summary": "fixture stopped before execution"}

    monkeypatch.setattr(runtime, "prepare_immediate_observations", prepare)
    monkeypatch.setattr(conversation_runtime, "select_task", select)
    monkeypatch.setattr(executor, "run_task", execute)

    async def exercise():
        user = await memory.append(role="user", source="realtime", text="Click normal game")
        memory.index.record_run(
            id="prior-click", task_ref="Tasks/executive/operate", agent="Executive",
            started=1, finished=2, status="completed", summary="I clicked NORMAL.",
            trace=json.dumps([
                {"interactive_turn": {"conversation_id": memory.conversation_id,
                                      "reply_to_turn_id": user["id"]}},
                {"tool": "computer.act", "args": {"application": "teamfight_tactics"},
                 "completion_evidence": {
                     "verified": True, "target": {"kind": "application", "name": "teamfight_tactics"},
                     "effect": {"kind": "click", "label": "NORMAL"},
                     "verified_scope": "click", "semantic_postcondition_verified": False,
                 }},
            ]),
        )
        await memory.append(role="assistant", source="realtime", text="I clicked NORMAL.",
                            reply_to=user["id"], run_id="prior-click")
        result = await runtime.submit("Can you start the match?", source="text")
        assert result["status"] == "failed"

    asyncio.run(exercise())
    assert calls == ["context", "selection", "execution"]


def test_cancel_during_semantic_selection_never_claims_or_executes_a_task(monkeypatch):
    memory = MemoryConversation()
    runtime = ConversationRuntime(memory)
    calls = []

    async def exercise():
        selecting = asyncio.Event()
        canceled = asyncio.Event()

        async def select(*_args, **_kwargs):
            selecting.set()
            try:
                await asyncio.Event().wait()
            finally:
                canceled.set()

        async def execute(*_args, **_kwargs):
            calls.append("unexpected Task execution")
            raise AssertionError("selection has not returned")

        monkeypatch.setattr(conversation_runtime, "select_task", select)
        monkeypatch.setattr(executor, "run_task", execute)
        await runtime.submit("Start the match", source="text", wait=False)
        await asyncio.wait_for(selecting.wait(), 1)
        await runtime.cancel(reason="test.selection_cancel")
        assert canceled.is_set()
        assert runtime._turn_task is None

    asyncio.run(exercise())
    assert calls == []
    assert [turn["role"] for turn in memory.turns] == ["user"]
    assert memory.events[-1]["type"] == "end"


@pytest.mark.parametrize("failure", ["invalid_response", "missing_task"])
def test_invalid_semantic_selection_has_no_task_run_or_successful_pair(monkeypatch, failure):
    from obsidience.harness.conversation.selection import TaskSelectionError

    memory = MemoryConversation()
    runtime = ConversationRuntime(memory)
    calls = []

    async def select(*_args, **_kwargs):
        if failure == "invalid_response":
            raise TaskSelectionError("invalid selection response")
        return None, {}, "chat.request"

    async def execute(*_args, **_kwargs):
        calls.append("unexpected Task execution")
        raise AssertionError("invalid selection must not execute")

    monkeypatch.setattr(conversation_runtime, "select_task", select)
    monkeypatch.setattr(executor, "run_task", execute)
    result = asyncio.run(runtime.submit("Start the match", source="text"))
    assert result["status"] == "failed"
    assert calls == []
    assert [turn["role"] for turn in memory.turns] == ["user"]
    notices = [event for event in memory.events if event["type"] == "error"]
    assert len(notices) == 1
    assert notices[0]["text"] == "I couldn't complete that request. The Action Trace has the error details."

@pytest.mark.parametrize('source', ['text', 'realtime'])
@pytest.mark.parametrize('corrected', [True, False])
def test_misrouted_turn_rechecks_once_without_new_user_turn(monkeypatch, source, corrected):
    runtime = ConversationRuntime(MemoryConversation())
    speech = RealtimeSessionManager(runtime)
    speech._phase = 'command'
    runtime.speech = speech
    selections, attempts, spoken = [], [], []
    async def select(text, transport, **kwargs):
        selections.append((text, transport, kwargs))
        effect = len(selections) == 2 and corrected
        ref = 'Tasks/executive/operate' if effect else 'Tasks/query'
        params = {'request':text, 'source':transport,
                  'computer_outcome':'launch' if effect else 'answer'}
        if effect: params['application'] = 'teamfight_tactics'
        return resolver().resolve(ref), params, 'voice.activation' if transport == 'voice' else 'chat.request'
    async def run(task, **kwargs):
        attempts.append((task.ref, kwargs))
        if len(attempts) == 1:
            return {'status':'failed','run_id':'misrouted', 'routing_reclassification':True}
        return {'status':'completed','run_id':'corrected','summary':'The requested application is ready.'}
    async def send(payload): spoken.append(payload)
    monkeypatch.setattr(conversation_runtime, 'select_task', select)
    monkeypatch.setattr(executor, 'run_task', run)
    monkeypatch.setattr(speech, '_send_worker', send)
    result = asyncio.run(runtime.submit('Can you start TFT?', source=source))
    assert len(selections) == 2
    assert selections[0][:2] == selections[1][:2]
    assert selections[1][2]['reclassification'] is True
    assert len(attempts) == (2 if corrected else 1)
    assert result['status'] == ('completed' if corrected else 'failed')
    turns = runtime._conversation.turns
    assert len([row for row in turns if row['role'] == 'user']) == 1
    if corrected:
        assert attempts[0][1]['runtime_params']['reply_to_turn_id'] == attempts[1][1]['runtime_params']['reply_to_turn_id']
        assert attempts[1][1]['runtime_params']['routing_rechecked'] is True
        assert runtime._last_task_ref == 'Tasks/executive/operate'
        assert turns[-1]['run_id'] == 'corrected' and turns[-1]['reply_to'] == turns[0]['id']
    else:
        assert [row['role'] for row in turns] == ['user']
    assert speech._phase != 'off'
    assert len([item for item in spoken if item['type'] == 'speak']) == (1 if source == 'realtime' else 0)

@pytest.mark.parametrize("interruption", ["generation", "clarification"])
def test_admission_recheck_cannot_outlive_cancellation_or_ignore_clarification(monkeypatch, interruption):
    runtime = ConversationRuntime(MemoryConversation())
    selections, attempts = [], []
    async def select(text, transport, **kwargs):
        selections.append(kwargs)
        correcting = kwargs.get("reclassification") is True
        if correcting and interruption == "generation":
            runtime._generation += 1
        ref = "Tasks/executive/operate" if correcting else "Tasks/query"
        return resolver().resolve(ref), {"request":text,"computer_outcome":"launch" if correcting else "answer"}, "chat.request"
    async def run(task, **kwargs):
        attempts.append(task.ref)
        if interruption == "clarification":
            kwargs["steering"].applied.append("a-persisted-clarification")
        return {"status":"failed","run_id":"first","routing_reclassification":True}
    monkeypatch.setattr(conversation_runtime, "select_task", select)
    monkeypatch.setattr(executor, "run_task", run)
    result = asyncio.run(runtime.submit("Can you start TFT?"))
    assert attempts == ["Tasks/query"]
    assert len(selections) == (2 if interruption == "generation" else 1)
    assert result["status"] == ("interrupted" if interruption == "generation" else "failed")
    assert [turn["role"] for turn in runtime._conversation.turns] == ["user"]

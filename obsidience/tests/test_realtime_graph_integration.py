from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from obsidience.harness.conversation import runtime as conversation_runtime
from obsidience.harness.execution import activity as knowledge_activity
from obsidience.harness.execution import executor, scheduler
from obsidience.harness.execution.executor import compile_activation
from obsidience.harness.conversation.runtime import (
    ConversationRuntime,
    SPEECH_RESPONSE_CONTRACT,
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
def inert_native_executive_session(monkeypatch):
    """Conversation turns refresh the ADK conversation log; keep it inert."""
    from obsidience.harness.execution.adk import sessions

    async def refresh(_conversation_id):
        return None

    async def measure(*_args, **_kwargs):
        return None

    monkeypatch.setattr(sessions, "refresh", refresh)
    monkeypatch.setattr(sessions, "measure_context", measure)
    monkeypatch.setattr(executor, "update_status", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(indexer.INDEX, "complete_observation_finalization", lambda *_args: None)


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
        "## Required Context",
        "## Bindings",
        "## Relevant Knowledge",
        "## Native conversation context",
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
        interruption_event=None, **_session_options,  # e.g. initial_lease
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
    command = runtime._command()  # Wake-by-name (default) starts silently.
    assert command[command.index("--startup-confirmation") + 1] == ""
    runtime._mode = "realtime"
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


def test_realtime_reports_only_its_live_echo_cancellation_route(monkeypatch) -> None:
    from obsidience.harness.realtime import media as realtime_media
    runtime = RealtimeSessionManager(ConversationRuntime(MemoryConversation()))
    assert runtime.snapshot()["live_transcript"] is None
    assert runtime.snapshot()["user_speaking"] is False
    assert runtime.snapshot()["acoustic_echo_cancellation"] is False
    runtime._aec_active = True
    # Only a live owning AEC process (a backend other than "none") counts.
    assert runtime.snapshot()["acoustic_echo_cancellation"] is False
    monkeypatch.setattr(realtime_media, "realtime_aec_backend", lambda: "webrtc")
    assert runtime.snapshot()["acoustic_echo_cancellation"] is True


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
        runtime._mode = "realtime"  # Wake mode (the default) drops speech until wake.
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
    # The Executive Operate Task is retired; any Task exercises the session.
    task = SimpleNamespace(ref="Tasks/fixture/visual", title="Visual", kind="task", meta={})
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
    # The executor dispatches through the async registry entry; never reach real Tools.
    monkeypatch.setattr(executor, "execute_capability_async",
                        lambda name, args, ctx: asyncio.to_thread(execute_capability, name, args, ctx))

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
    # The Executive Operate Task is retired; any Task exercises the session.
    task = SimpleNamespace(ref="Tasks/fixture/visual", title="Visual", kind="task", meta={})
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
    # The executor dispatches through the async registry entry; never reach real Tools.
    monkeypatch.setattr(executor, "execute_capability_async",
                        lambda name, args, ctx: asyncio.to_thread(should_not_capture, name, args, ctx))

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
    # Conversation turns now execute the Executive via run_conversation.
    monkeypatch.setattr(executor, "run_conversation", run)

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
    # Conversation turns now execute the Executive via run_conversation.
    monkeypatch.setattr(executor, "run_conversation", result)
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
    # Conversation turns now execute the Executive via run_conversation.
    monkeypatch.setattr(executor, "run_conversation", complete)
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
    # Conversation turns now execute the Executive via run_conversation.
    monkeypatch.setattr(executor, "run_conversation", fail)
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
    # Conversation turns now execute the Executive via run_conversation.
    monkeypatch.setattr(executor, "run_conversation", blocked)
    monkeypatch.setattr(speech, "_send_worker", send)
    result = asyncio.run(runtime.submit("hello", source="realtime"))
    notices = [payload["text"] for payload in spoken if payload["type"] == "speak"]
    assert result["status"] == "blocked"
    assert notices == ["The selected model's hardware is currently reserved. "
                       "Please retry this request when it is available."]
    assert [row["role"] for row in runtime._conversation.turns] == ["user"]
    assert speech._last_error is None


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
    # Conversation turns now execute the Executive via run_conversation.
    monkeypatch.setattr(executor, "run_conversation", result)
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
        monkeypatch.setattr(runtime, 'prepare_conversation_context', prepare)
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
    # Conversation turns now execute the Executive via run_conversation.
    monkeypatch.setattr(executor, "run_conversation", fail)
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
    # Conversation turns now execute the Executive via run_conversation.
    monkeypatch.setattr(executor, "run_conversation", completed)
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



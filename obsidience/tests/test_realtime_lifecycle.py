"""Speech supervision keeps one exact process owner through cleanup."""

from __future__ import annotations

import asyncio
import json
import signal
from pathlib import Path
from types import SimpleNamespace

import pytest

from obsidience.harness.realtime import runtime as speech


class Conversation:
    def __init__(self):
        self.speech = None
        self._conversation = SimpleNamespace(conversation_id="conversation-test")
        self.cancelled = []
        self.submitted = []
        self.finalized = []
        self.rotation_error = None

    def _ledger(self):
        return SimpleNamespace(deferred_observation_finalizations=lambda: [])

    async def cancel(self, **kwargs):
        self.cancelled.append(kwargs)

    async def new_conversation(self, **kwargs):
        if self.rotation_error is not None:
            raise self.rotation_error

    async def submit(self, text, **kwargs):
        self.submitted.append((text, kwargs))

    async def finalize_pending(self, conversation_id, **kwargs):
        self.finalized.append((conversation_id, kwargs))


class Process:
    def __init__(self, pid):
        self.pid = pid
        self.returncode = None
        self.stdout = asyncio.StreamReader()
        self.exited = asyncio.Event()
        self.commands = []
        self.waited = 0
        self.stdin = SimpleNamespace(write=self.commands.append, drain=self.drain)

    async def drain(self):
        pass

    async def wait(self):
        self.waited += 1
        await self.exited.wait()
        return self.returncode

    def emit(self, **event):
        self.stdout.feed_data((json.dumps(event) + "\n").encode())

    def exit(self, returncode=0):
        if self.returncode is None:
            self.returncode = returncode
            self.stdout.feed_eof()
            self.exited.set()


@pytest.fixture
def environment(monkeypatch, tmp_path):
    state = SimpleNamespace(
        processes=[], signals=[], reservations=[], releases=[], cameras=[],
        exit_on_signal=True, block_camera=False,
        cleanup_entered=asyncio.Event(), cleanup_release=asyncio.Event(),
    )
    media = {"microphone": "mic", "speaker": "speaker", "tts_voice": "voice"}
    monkeypatch.setattr(speech, "REALTIME_PYTHON", Path(__file__))
    monkeypatch.setattr(speech, "NEMOTRON_MODEL", Path(__file__))
    monkeypatch.setattr(speech, "RUNTIME_ROOT", tmp_path / "runtime")
    monkeypatch.setattr(speech.media_runtime, "settings", lambda: media)
    monkeypatch.setattr(speech.media_runtime, "prepare_microphone", lambda source: source)
    monkeypatch.setattr(speech.media_runtime, "start_realtime_aec", lambda *_: ("aec", "sink"))
    monkeypatch.setattr(speech.media_runtime, "stop_realtime_aec", lambda: None)
    monkeypatch.setattr(speech.media_runtime, "interface_catalog", lambda: [
        {"id": key, "options": [{"id": value, "available": True}]}
        for key, value in media.items()
    ])

    def camera(*args):
        state.cameras.append(args)

    async def to_thread(function, *args, **kwargs):
        if function is camera and state.block_camera:
            state.block_camera = False
            state.cleanup_entered.set()
            await state.cleanup_release.wait()
        return function(*args, **kwargs)

    async def reserve(owner, devices):
        state.reservations.append((owner, devices))

    async def release(owner):
        state.releases.append(owner)

    async def spawn(*args, **kwargs):
        process = Process(10000 + len(state.processes))
        state.processes.append(process)
        return process

    def killpg(pid, sig):
        state.signals.append((pid, sig))
        if state.exit_on_signal:
            next(process for process in state.processes if process.pid == pid).exit(-sig)

    monkeypatch.setattr(speech.media_runtime, "set_realtime_camera_active", camera)
    monkeypatch.setattr(speech.asyncio, "to_thread", to_thread)
    monkeypatch.setattr(speech.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(speech.model_runtime, "reserve_devices", reserve)
    monkeypatch.setattr(speech.model_runtime, "release_devices", release)
    monkeypatch.setattr(speech.os, "killpg", killpg)
    return state


@pytest.mark.parametrize("owner", ["stop", "monitor"])
def test_restart_waits_for_previous_hardware_camera_and_speech_cleanup(environment, owner):
    async def scenario():
        conversation = Conversation()
        runtime = speech.RealtimeSessionManager(conversation)
        await runtime.start()
        previous = environment.processes[-1]
        environment.block_camera = True
        if owner == "stop":
            cleanup = asyncio.create_task(runtime.stop())
        else:
            cleanup = runtime._monitor
            previous.exit(1)
        await asyncio.wait_for(environment.cleanup_entered.wait(), 1)
        replacement = asyncio.create_task(runtime.start())
        await asyncio.sleep(0)
        assert not replacement.done()
        assert runtime._process is previous
        environment.cleanup_release.set()
        await asyncio.wait_for(cleanup, 1)
        await asyncio.wait_for(replacement, 1)
        assert runtime._process is environment.processes[-1]
        assert runtime._process is not previous
        assert conversation.speech is runtime
        assert runtime._hardware_leased
        assert environment.releases == [speech.RUNTIME_LEASE_OWNER]
        assert environment.cameras == [("mic", False)]
        await runtime.shutdown()

    asyncio.run(scenario())


def test_stopping_worker_discards_buffered_ready_transcript_and_interruption(environment):
    async def scenario():
        conversation = Conversation()
        runtime = speech.RealtimeSessionManager(conversation)
        await runtime.start()
        process = environment.processes[-1]
        environment.exit_on_signal = False
        stopping = asyncio.create_task(runtime.stop())
        await asyncio.sleep(0)
        assert runtime._phase == "stopping"
        for event in (
            {"type": "runtime_ready"},
            {"type": "transport_ready"},
            {"type": "speech_detected"},
            {"type": "input_capture", "active": True},
            {"type": "input_level", "level": 1.0},
            {"type": "transcript_final", "text": "open an application"},
            {"type": "interruption"},
        ):
            process.emit(**event)
        await asyncio.sleep(0)
        assert runtime._phase == "stopping"
        assert runtime._transport_ready is False
        assert runtime._user_speaking is False
        assert runtime._input_level == 0
        assert runtime.snapshot()["capture_active"] is False
        assert conversation.submitted == []
        assert conversation.cancelled == [{}]
        process.exit()
        await asyncio.wait_for(stopping, 1)
        await asyncio.wait_for(runtime._monitor, 1)
        assert environment.releases == [speech.RUNTIME_LEASE_OWNER]
        assert environment.cameras == [("mic", False)]
        assert len(conversation.finalized) == 1
        assert runtime._phase == "off" and conversation.speech is None

    asyncio.run(scenario())


def test_provisional_capture_and_partial_stream_do_not_admit_work(environment):
    async def scenario():
        conversation = Conversation()
        runtime = speech.RealtimeSessionManager(conversation)
        await runtime.start()
        process = environment.processes[-1]
        queue = runtime.subscribe()

        async def receive(event, predicate):
            process.emit(**event)
            while True:
                published = await asyncio.wait_for(queue.get(), 1)
                if predicate(published):
                    return published

        await receive({"type": "runtime_ready"}, lambda event: event.get("reason") == "runtime_ready")
        runtime._live_transcript = {"text": "previous final", "final": True}
        capture = await receive(
            {"type": "input_capture", "active": True},
            lambda event: event.get("reason") == "capture_active",
        )
        assert capture["state"]["capture_active"] is True
        assert capture["state"]["user_speaking"] is False
        assert capture["state"]["live_transcript"] is None
        for text in ("Can", "Can you hear", "Can you hear me?"):
            partial = await receive(
                {"type": "transcript_partial", "text": text},
                lambda event: event.get("line", "").startswith("[partial]"),
            )
            assert partial["state"]["live_transcript"] == {"text": text, "final": False}
            assert conversation.submitted == []
            assert conversation.cancelled == []
        await receive(
            {"type": "transcript_final", "text": "Can you hear me?"},
            lambda event: event.get("line", "").startswith("[heard]"),
        )
        assert conversation.submitted == [("Can you hear me?", {"source": "realtime", "wait": False})]
        assert conversation.cancelled == []
        assert not any("input_capture" in line for line in runtime.snapshot()["recent_log"])
        await runtime.stop()
        assert runtime.snapshot()["capture_active"] is False
        runtime.unsubscribe(queue)

    asyncio.run(scenario())


def test_stale_monitor_cannot_change_or_release_a_new_process(environment):
    async def scenario():
        conversation = Conversation()
        runtime = speech.RealtimeSessionManager(conversation)
        await runtime.start()
        previous = environment.processes[-1]
        monitor = runtime._monitor
        replacement = Process(20000)
        runtime._process = replacement
        runtime._operation += 1
        runtime._phase = "proactive"
        previous.emit(type="runtime_ready")
        await asyncio.wait_for(monitor, 1)
        assert runtime._phase == "proactive"
        assert runtime._process is replacement
        assert conversation.speech is runtime
        assert runtime._hardware_leased
        assert environment.releases == []
        assert environment.cameras == []
        previous.exit()
        replacement.exit()
        await runtime.shutdown()

    asyncio.run(scenario())


def test_duplicate_ready_does_not_reset_proactive_and_startup_transcript_is_ignored(environment):
    async def scenario():
        conversation = Conversation()
        runtime = speech.RealtimeSessionManager(conversation)
        await runtime.start()
        process = environment.processes[-1]
        process.emit(type="transcript_final", text="premature request")
        await asyncio.sleep(0)
        assert conversation.submitted == []
        runtime._phase = "proactive"
        process.emit(type="runtime_ready")
        process.emit(type="transcript_final", text="accepted request")
        await asyncio.sleep(0)
        assert runtime._phase == "proactive"
        assert conversation.submitted == [(
            "accepted request", {"source": "realtime", "wait": False},
        )]
        await runtime.shutdown()

    asyncio.run(scenario())


def test_speech_restart_preserves_selected_conversation(environment):
    async def scenario():
        conversation = Conversation()
        conversation.rotation_error = AssertionError("speech must not rotate conversation")
        runtime = speech.RealtimeSessionManager(conversation)
        await runtime.start()
        original = runtime._process
        assert conversation._conversation.conversation_id == "conversation-test"
        await runtime.stop()
        assert all(not identity for identity, _ in conversation.finalized)
        await runtime.start()
        assert runtime._process is not original
        assert conversation._conversation.conversation_id == "conversation-test"
        assert conversation.speech is runtime
        await runtime.shutdown()

    asyncio.run(scenario())


def test_restart_restores_requested_speech_before_background_admission(environment, tmp_path):
    async def scenario():
        path = tmp_path / "requested.json"
        conversation = Conversation()
        original = speech.RealtimeSessionManager(conversation, requested_state_path=path)
        await original.start()
        assert json.loads(path.read_text()) == {"enabled": True}
        await original.shutdown()
        assert path.exists()
        replacement = speech.RealtimeSessionManager(conversation, requested_state_path=path)
        await replacement.restore()
        assert replacement.scheduler_paused()
        assert replacement._phase == "starting"
        assert len(environment.processes) == 2
        assert conversation._conversation.conversation_id == "conversation-test"
        await replacement.stop()
        assert not path.exists()
        await replacement.shutdown()
        fresh = speech.RealtimeSessionManager(conversation, requested_state_path=path)
        await fresh.restore()
        assert fresh._phase == "off" and len(environment.processes) == 2

    asyncio.run(scenario())


@pytest.mark.parametrize("contents", ['broken', '[]', '{"enabled": 1}', '{"enabled": false}',
                                      '{"enabled": true, "extra": true}'])
def test_restart_ignores_invalid_or_disabled_speech_intent(environment, tmp_path, contents):
    path = tmp_path / "requested.json"
    path.write_text(contents)
    runtime = speech.RealtimeSessionManager(Conversation(), requested_state_path=path)
    asyncio.run(runtime.restore())
    assert runtime._phase == "off" and environment.processes == []


def test_restart_failure_stays_visible_without_retry_loop(environment, tmp_path, monkeypatch):
    path = tmp_path / "requested.json"
    path.write_text('{"enabled": true}')
    runtime = speech.RealtimeSessionManager(Conversation(), requested_state_path=path)
    monkeypatch.setattr(speech, "NEMOTRON_MODEL", tmp_path / "missing-model")
    result = asyncio.run(runtime.restore())
    assert result["phase"] == "error"
    assert "Nemotron" in result["last_error"]
    assert environment.processes == []


def test_harness_restores_speech_before_first_scheduler_tick(monkeypatch):
    from importlib import import_module
    from obsidience.harness.knowledge import intake
    api = import_module("obsidience.harness.interfaces.api.app")
    order = []

    async def nothing():
        return []

    async def restore():
        await asyncio.sleep(0)
        order.append("speech_reserved")

    async def scheduler_loop():
        assert order == ["speech_reserved"]
        order.append("scheduler_open")
        await asyncio.Future()

    monkeypatch.setattr(api.scheduler, "reconcile_interrupted_runs", lambda: None)
    monkeypatch.setattr(api.source, "list_sources", lambda: [])
    monkeypatch.setattr(api.system_knowledge, "refresh_system_knowledge", lambda **_: {"status": "ready", "changed": 0})
    monkeypatch.setattr(api.INDEX, "sync", lambda: None)
    monkeypatch.setattr(api.retrieval, "prewarm_fast_context", lambda: None)
    monkeypatch.setattr(api.model_runtime, "initialize", nothing)
    monkeypatch.setattr(api.model_runtime, "shutdown", nothing)
    monkeypatch.setattr(api.shell_scene.SCENE, "start", lambda: None)
    monkeypatch.setattr(api.shell_scene.SCENE, "stop", nothing)
    monkeypatch.setattr(intake, "SourceIntake", lambda: SimpleNamespace(start=lambda: None, stop=lambda: None))
    monkeypatch.setattr(api.realtime.RUNTIME, "restore", restore)
    monkeypatch.setattr(api.realtime.RUNTIME, "shutdown", nothing)
    monkeypatch.setattr(api.conversation_runtime.RUNTIME, "cancel", nothing)
    monkeypatch.setattr(api.scheduler, "loop", scheduler_loop)
    monkeypatch.setattr(api.scheduler, "shutdown", nothing)

    async def scenario():
        async with api.lifespan(api.app):
            await asyncio.sleep(0)
            assert order == ["speech_reserved", "scheduler_open"]

    asyncio.run(scenario())


def test_explicit_stop_tears_down_worker_even_if_restart_intent_cannot_be_cleared(environment, tmp_path, monkeypatch):
    async def scenario():
        path = tmp_path / "requested.json"
        runtime = speech.RealtimeSessionManager(Conversation(), requested_state_path=path)
        await runtime.start()
        process = runtime._process
        original_unlink = Path.unlink

        def fail_unlink(candidate, *args, **kwargs):
            if candidate == path:
                raise PermissionError("injected intent persistence failure")
            return original_unlink(candidate, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", fail_unlink)
        with pytest.raises(RuntimeError, match="stopped.*restart intent"):
            await runtime.stop()
        assert process.returncode is not None
        assert runtime._phase == "off" and not runtime._hardware_leased
        assert runtime.conversation.speech is None
        assert path.exists()
        await runtime.shutdown()

    asyncio.run(scenario())

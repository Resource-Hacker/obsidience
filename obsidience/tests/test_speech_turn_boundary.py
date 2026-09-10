from __future__ import annotations

import asyncio
import json
import io
import os
import queue
from types import SimpleNamespace

import pytest

pytest.importorskip("nemo")

from obsidience.harness.realtime.speech import worker
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    EndFrame,
    InputAudioRawFrame,
    InterimTranscriptionFrame,
    StartInterruptionFrame,
    TranscriptionFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
    TTSStartedFrame,
    TTSSpeakFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


def test_capture_levels_publish_before_asr_queue_and_stay_bounded(monkeypatch) -> None:
    events, forwarded = [], []
    clock = iter([100.0, 100.02, 100.11])
    monkeypatch.setattr(worker, "time", SimpleNamespace(monotonic=lambda: next(clock)))
    monkeypatch.setattr(worker, "calculate_audio_volume", lambda *_args: 0.23456)
    monkeypatch.setattr(worker, "emit", lambda kind, **payload: events.append((kind, payload)))

    async def enqueue(_transport, frame):
        # The first level must already be observable even if downstream ASR
        # has not consumed a single queued frame.
        assert events[0] == ("input_level", {"level": 0.2346})
        forwarded.append(frame)

    monkeypatch.setattr(worker.LocalAudioInputTransport, "push_audio_frame", enqueue)

    async def scenario():
        transport = worker.NeMoLocalAudioInputTransport(
            SimpleNamespace(), worker.LocalAudioTransportParams(audio_in_enabled=True),
        )
        frame = InputAudioRawFrame(audio=b"\0" * 640, sample_rate=16000, num_channels=1)
        for _ in range(3):
            await transport.push_audio_frame(frame)
        transport._paused = True
        await transport.push_audio_frame(frame)
        assert forwarded == [frame] * 4

    asyncio.run(scenario())
    assert events == [("input_level", {"level": 0.2346})] * 2


def test_provisional_capture_is_distinct_from_semantic_interruption(monkeypatch) -> None:
    events = []
    monkeypatch.setattr(worker, "emit", lambda kind, **payload: events.append((kind, payload)))

    async def scenario():
        transport = worker.NeMoLocalAudioInputTransport(
            SimpleNamespace(), worker.LocalAudioTransportParams(audio_in_enabled=True),
        )

        async def no_semantic_frame(*_args, **_kwargs):
            raise AssertionError("Provisional capture must not create an interruption frame")

        transport.push_frame = no_semantic_frame
        await transport._handle_user_interruption(worker.VADState.SPEAKING)
        await transport._handle_user_interruption(worker.VADState.SPEAKING)
        await transport._handle_user_interruption(worker.VADState.QUIET, emulated=True)
        assert transport._capture_active is True
        await transport._handle_user_interruption(worker.VADState.QUIET)

    asyncio.run(scenario())
    assert events == [("input_capture", {"active": True}), ("input_capture", {"active": False})]


class ResetProbe(FrameProcessor):
    def __init__(self) -> None:
        super().__init__()
        self.upstream_stops = 0

    async def process_frame(self, frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if direction is FrameDirection.UPSTREAM and isinstance(
            frame, VADUserStoppedSpeakingFrame,
        ):
            self.upstream_stops += 1
        await self.push_frame(frame, direction)


def test_playback_cancel_does_not_echo_as_a_user_interruption(monkeypatch) -> None:
    events: list[str] = []
    monkeypatch.setattr(worker, "emit", lambda kind, **_payload: events.append(kind))
    monkeypatch.setattr(worker.sys, "stdin", io.StringIO('{"type":"cancel"}\n{"type":"stop"}\n'))

    async def run() -> None:
        bridge = worker.ObsidienceTaskBridge()
        task = PipelineTask(
            Pipeline([bridge]),
            params=PipelineParams(allow_interruptions=True),
            idle_timeout_secs=None,
            enable_turn_tracking=False,
        )

        @task.event_handler("on_pipeline_started")
        async def drive(_task, _frame) -> None:
            # The natural NeMo interruption still reaches the coordinator;
            # its own playback-cancel command travels downstream without echo.
            await task.queue_frame(StartInterruptionFrame())
            await worker.command_loop(task, None)

        await PipelineRunner(handle_sigint=False).run(task)

    asyncio.run(run())
    assert events == ["interruption"]


async def run_turn_boundary(
    monkeypatch,
    *,
    gate_final: bool = False,
    initial_vad: bool = False,
) -> list[str]:
    events: list[str] = []
    monkeypatch.setattr(worker, "TRANSCRIPT_IDLE_SECS", 0.02)
    monkeypatch.setattr(worker, "emit", lambda kind, **_payload: events.append(kind))

    reset = ResetProbe()
    turn = worker.ObsidienceNeMoTurnTakingService(use_vad=True)
    bridge = worker.ObsidienceTaskBridge()
    final_enqueued = asyncio.Event()
    release_final = asyncio.Event()
    original_push = turn.push_frame

    async def gated_push(frame, direction=FrameDirection.DOWNSTREAM):
        await original_push(frame, direction)
        if gate_final and isinstance(frame, TranscriptionFrame):
            final_enqueued.set()
            await release_final.wait()

    if gate_final:
        turn.push_frame = gated_push

    task = PipelineTask(
        Pipeline([reset, turn, bridge]),
        params=PipelineParams(
            allow_interruptions=True,
            enable_metrics=False,
            enable_usage_metrics=False,
        ),
        idle_timeout_secs=None,
        enable_turn_tracking=False,
    )
    driver: asyncio.Task[None] | None = None

    async def drive() -> None:
        if initial_vad:
            await task.queue_frame(VADUserStartedSpeakingFrame())
        await task.queue_frame(InterimTranscriptionFrame(
            text="Can you hear me?", user_id="", timestamp="test",
        ))
        if gate_final:
            await asyncio.wait_for(final_enqueued.wait(), 1)
            await task.queue_frame(VADUserStartedSpeakingFrame())
            await asyncio.sleep(0)
            release_final.set()
        deadline = asyncio.get_running_loop().time() + 1
        while (
            events.count("transcript_final") != 1
            or events.count("speech_ended") != 1
            or reset.upstream_stops != 1
        ):
            assert asyncio.get_running_loop().time() < deadline, (
                events,
                reset.upstream_stops,
            )
            await asyncio.sleep(0.001)
        await task.queue_frame(EndFrame())

    @task.event_handler("on_pipeline_started")
    async def on_pipeline_started(_task, _frame) -> None:
        nonlocal driver
        driver = asyncio.create_task(drive())

    await PipelineRunner(handle_sigint=False).run(task)
    if driver is not None:
        await driver

    assert events.count("transcript_final") == 1
    assert events.count("speech_ended") == 1
    assert reset.upstream_stops == 1
    assert turn._user_speaking_buffer == ""
    if gate_final:
        starts = [index for index, kind in enumerate(events) if kind == "speech_detected"]
        # The new VAD onset is provisional; it cannot open a second semantic
        # turn or cancel the preceding finalized transcript without words.
        assert len(starts) == 1, events
        assert starts[0] < events.index("speech_ended"), events
    elif initial_vad:
        assert events[0] == "transcript_partial"
        assert events.index("transcript_partial") < events.index("speech_detected")
        assert events.count("interruption") == 1
        assert events.count("transcript_partial") == 1
        assert events.index("speech_ended") < events.index("transcript_final")
    else:
        assert turn._have_sent_user_started_speaking is False
        assert events == [
            "transcript_partial",
            "speech_detected",
            "interruption",
            "speech_ended",
            "transcript_final",
        ]
    return events


def test_transcript_endpoint_serializes_the_user_stop_edge(monkeypatch) -> None:
    asyncio.run(run_turn_boundary(monkeypatch))
    asyncio.run(run_turn_boundary(monkeypatch, gate_final=True))


def test_transcript_endpoint_closes_a_stale_vad_speaking_state(monkeypatch) -> None:
    asyncio.run(run_turn_boundary(monkeypatch, initial_vad=True))


@pytest.mark.parametrize("bot_speaking", [False, True])
def test_unconfirmed_vad_does_not_interrupt_thinking_or_playback(monkeypatch, bot_speaking) -> None:
    events: list[str] = []
    monkeypatch.setattr(worker, "emit", lambda kind, **_payload: events.append(kind))

    async def run() -> None:
        turn = worker.ObsidienceNeMoTurnTakingService(use_vad=True)
        bridge = worker.ObsidienceTaskBridge()
        task = PipelineTask(
            Pipeline([turn, bridge]),
            params=PipelineParams(
                allow_interruptions=True,
                enable_metrics=False,
                enable_usage_metrics=False,
            ),
            idle_timeout_secs=None,
            enable_turn_tracking=False,
        )

        @task.event_handler("on_pipeline_started")
        async def drive(_task, _frame) -> None:
            if bot_speaking:
                await task.queue_frame(BotStartedSpeakingFrame())
            await task.queue_frame(VADUserStartedSpeakingFrame())
            await task.queue_frame(VADUserStoppedSpeakingFrame())
            await task.queue_frame(EndFrame())

        await PipelineRunner(handle_sigint=False).run(task)
        assert turn._vad_user_speaking is False
        assert turn._have_sent_user_started_speaking is False

    asyncio.run(run())
    assert events == []


@pytest.mark.parametrize("bot_speaking", [False, True])
def test_recognized_partial_interrupts_active_work_before_final_transcript(monkeypatch, bot_speaking) -> None:
    async def exercise() -> None:
        events = []
        interrupted, ended = asyncio.Event(), asyncio.Event()
        active_work = asyncio.create_task(asyncio.Event().wait())

        def emit(kind, **_payload):
            events.append(kind)
            if kind == "interruption":
                active_work.cancel()
                interrupted.set()
            elif kind == "speech_ended":
                ended.set()

        monkeypatch.setattr(worker, "emit", emit)
        turn = worker.ObsidienceNeMoTurnTakingService(use_vad=True)
        bridge = worker.ObsidienceTaskBridge()
        task = PipelineTask(
            Pipeline([turn, bridge]), params=PipelineParams(allow_interruptions=True),
            idle_timeout_secs=None, enable_turn_tracking=False,
        )
        driver = None

        async def drive():
            if bot_speaking:
                await task.queue_frame(BotStartedSpeakingFrame())
            await task.queue_frame(VADUserStartedSpeakingFrame())
            await task.queue_frame(VADUserStoppedSpeakingFrame())
            await task.queue_frame(InterimTranscriptionFrame(
                text="Can you focus Edge?", user_id="", timestamp="test",
            ))
            await asyncio.wait_for(interrupted.wait(), 1)
            assert active_work.cancelling()
            assert "transcript_partial" in events
            assert "transcript_final" not in events
            await task.queue_frame(VADUserStoppedSpeakingFrame())
            await asyncio.wait_for(ended.wait(), 1)
            await task.queue_frame(EndFrame())

        @task.event_handler("on_pipeline_started")
        async def start(_task, _frame):
            nonlocal driver
            driver = asyncio.create_task(drive())

        try:
            await PipelineRunner(handle_sigint=False).run(task)
            await driver
            assert events.count("interruption") == 1
            assert events.count("transcript_final") == 1
            assert events.count("speech_ended") == 1
            assert events.index("transcript_partial") < events.index("interruption")
            assert turn._have_sent_user_started_speaking is False
            assert turn._vad_user_speaking is False
        finally:
            active_work.cancel()
            try:
                await active_work
            except asyncio.CancelledError:
                pass

    asyncio.run(exercise())


def test_playback_uses_aec_then_returns_the_same_input_to_raw(monkeypatch) -> None:
    calls: list[tuple[str, ...]] = []

    def run(command, **_kwargs):
        calls.append(command)
        if command[-2:] == ("list", "source-outputs"):
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps([{
                    "index": 42,
                    "properties": {"application.process.id": str(os.getpid())},
                }]).encode(),
            )
        return SimpleNamespace(returncode=0, stdout=b"")

    monkeypatch.setattr(worker.subprocess, "run", run)
    route = worker.PlaybackInputRoute(raw_source="raw", aec_source="clean")

    async def exercise() -> None:
        await route.prepare_playback()
        await route.process_frame(TTSStartedFrame(), FrameDirection.DOWNSTREAM)
        await route.process_frame(BotStoppedSpeakingFrame(), FrameDirection.UPSTREAM)

    asyncio.run(exercise())
    assert calls == [
        ("/usr/bin/pactl", "-f", "json", "list", "source-outputs"),
        ("/usr/bin/pactl", "move-source-output", "42", "clean"),
        ("/usr/bin/pactl", "move-source-output", "42", "raw"),
    ]


def test_acoustic_invalidation_during_playback_preparation_suppresses_old_reply() -> None:
    async def exercise() -> None:
        prepared, release = asyncio.Event(), asyncio.Event()
        restored, frames = [], []

        async def prepare():
            prepared.set()
            await release.wait()

        async def restore():
            restored.append(True)

        async def enqueue(frame):
            frames.append(frame)

        route = SimpleNamespace(prepare_playback=prepare, restore_capture=restore)
        task = SimpleNamespace(queue_frame=enqueue)
        playback = worker.PlaybackCommands()
        playback.speak(task, route, {"generation": 5, "text": "Old answer"})
        await prepared.wait()
        playback.invalidate()
        release.set()
        await playback._preparing
        assert frames == [] and restored == [True]
        playback.speak(task, route, {"generation": 5, "text": "Stale pipe command"})
        assert playback._queued is None
        playback.speak(task, route, {"generation": 7, "text": "Current answer"})
        await playback._preparing
        assert [frame.text for frame in frames] == ["Current answer"]
        assert playback.accepts(frames[0])
        await playback.close()
        assert not playback.accepts(frames[0])

    asyncio.run(exercise())


def test_command_reader_consumes_generation_cancel_while_preparation_waits(monkeypatch) -> None:
    lines = queue.Queue()
    monkeypatch.setattr(worker.sys, "stdin", SimpleNamespace(readline=lines.get))

    async def exercise() -> None:
        prepared, release, invalidated = asyncio.Event(), asyncio.Event(), asyncio.Event()
        frames, restored = [], []

        async def prepare():
            prepared.set()
            await release.wait()

        async def restore():
            restored.append(True)

        async def enqueue(frame):
            frames.append(frame)

        playback = worker.PlaybackCommands()
        original = playback.invalidate

        def invalidate(generation=None):
            result = original(generation)
            if generation == 2:
                invalidated.set()
            return result

        playback.invalidate = invalidate
        runner = asyncio.create_task(worker.command_loop(
            SimpleNamespace(queue_frame=enqueue),
            SimpleNamespace(prepare_playback=prepare, restore_capture=restore),
            playback,
        ))
        try:
            lines.put(json.dumps({"type": "speak", "generation": 1, "text": "Old failure notice"}))
            await asyncio.wait_for(prepared.wait(), 1)
            lines.put(json.dumps({"type": "cancel", "generation": 2, "stop_playback": False}))
            await asyncio.wait_for(invalidated.wait(), 1)
            release.set()
            await asyncio.wait_for(playback._preparing, 1)
            assert frames == []
            assert restored == [True]
        finally:
            release.set()
            lines.put('{"type":"stop"}')
            await asyncio.wait_for(runner, 1)

    asyncio.run(exercise())


def test_existing_bridge_drops_stale_speech_frame_after_acoustic_interruption(monkeypatch) -> None:
    heard = []
    monkeypatch.setattr(worker, "emit", lambda *_args, **_kwargs: None)

    class SpeechProbe(FrameProcessor):
        async def process_frame(self, frame, direction):
            await super().process_frame(frame, direction)
            if isinstance(frame, TTSSpeakFrame):
                heard.append(frame.text)
            await self.push_frame(frame, direction)

    async def exercise() -> None:
        playback = worker.PlaybackCommands()
        playback.generation, playback.epoch = 5, 1
        bridge = worker.ObsidienceTaskBridge(playback)
        task = PipelineTask(
            Pipeline([bridge, SpeechProbe()]),
            params=PipelineParams(allow_interruptions=True),
            idle_timeout_secs=None, enable_turn_tracking=False,
        )

        @task.event_handler("on_pipeline_started")
        async def drive(_task, _frame):
            stale = TTSSpeakFrame("Old answer")
            stale.metadata["obsidience_playback"] = (5, 1)
            await task.queue_frame(StartInterruptionFrame())
            await task.queue_frame(stale)
            await task.queue_frame(EndFrame())

        await PipelineRunner(handle_sigint=False).run(task)

    asyncio.run(exercise())
    assert heard == []


def test_pending_reply_is_replaced_without_concurrent_route_mutations() -> None:
    async def exercise() -> None:
        entered, release = asyncio.Event(), asyncio.Event()
        frames, calls = [], []

        async def prepare():
            calls.append("prepare")
            entered.set()
            await release.wait()

        async def restore():
            calls.append("restore")

        async def enqueue(frame):
            frames.append(frame)

        playback = worker.PlaybackCommands()
        task = SimpleNamespace(queue_frame=enqueue)
        route = SimpleNamespace(prepare_playback=prepare, restore_capture=restore)
        playback.speak(task, route, {"generation": 4, "text": "Superseded"})
        await entered.wait()
        pending = playback._preparing
        playback.speak(task, route, {"generation": 5, "text": "Current"})
        assert playback._preparing is pending
        assert playback.invalidate(3) is False
        release.set()
        await pending
        assert calls == ["prepare", "restore", "prepare"]
        assert [frame.text for frame in frames] == ["Current"]
        await playback.close()

    asyncio.run(exercise())


@pytest.mark.parametrize("interrupted", [False, True])
def test_startup_waits_for_initial_generation_without_overriding_user_activity(interrupted) -> None:
    async def exercise() -> None:
        frames = []

        async def prepare():
            pass

        async def restore():
            pass

        async def enqueue(frame):
            frames.append(frame)

        playback = worker.PlaybackCommands()
        startup = asyncio.create_task(playback.startup(
            SimpleNamespace(queue_frame=enqueue),
            SimpleNamespace(prepare_playback=prepare, restore_capture=restore),
            "Realtime active.",
        ))
        if interrupted:
            playback.invalidate()
        playback.invalidate(10)  # First controller cancel is the startup baseline.
        await startup
        if playback._preparing is not None:
            await playback._preparing
        assert [frame.text for frame in frames] == ([] if interrupted else ["Realtime active."])
        assert all(playback.accepts(frame) for frame in frames)
        await playback.close()

    asyncio.run(exercise())


def test_startup_preparation_is_invalidated_by_acoustic_interruption() -> None:
    async def exercise() -> None:
        entered, release = asyncio.Event(), asyncio.Event()
        frames, restored = [], []

        async def prepare():
            entered.set()
            await release.wait()

        async def restore():
            restored.append(True)

        async def enqueue(frame):
            frames.append(frame)

        playback = worker.PlaybackCommands()
        playback.invalidate(1)
        await playback.startup(
            SimpleNamespace(queue_frame=enqueue),
            SimpleNamespace(prepare_playback=prepare, restore_capture=restore),
            "Realtime active.",
        )
        await entered.wait()
        playback.invalidate()
        release.set()
        await playback._preparing
        assert frames == [] and restored == [True]
        await playback.close()

    asyncio.run(exercise())

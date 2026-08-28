from __future__ import annotations

import asyncio
import json
import os
from types import SimpleNamespace

import pytest

pytest.importorskip("nemo")

from obsidience.harness.realtime.speech import worker
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    EndFrame,
    InterimTranscriptionFrame,
    TranscriptionFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
    TTSStartedFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


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
        assert len(starts) == 2, events
        assert events.index("speech_ended") < starts[1], events
    elif initial_vad:
        assert events[0] == "speech_detected"
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


def test_vad_residual_does_not_interrupt_assistant_playback(monkeypatch) -> None:
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
            await task.queue_frame(BotStartedSpeakingFrame())
            await task.queue_frame(VADUserStartedSpeakingFrame())
            await task.queue_frame(VADUserStoppedSpeakingFrame())
            await task.queue_frame(EndFrame())

        await PipelineRunner(handle_sigint=False).run(task)

    asyncio.run(run())
    assert events == []


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

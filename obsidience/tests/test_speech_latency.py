"""Speech timestamps follow real turn/output boundaries without recording audio."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

pytest.importorskip('nemo')
from obsidience.harness.realtime.speech import worker
from pipecat.frames.frames import TTSStartedFrame, TTSAudioRawFrame
from pipecat.processors.frame_processor import FrameDirection


def test_input_timing_is_bounded_and_does_not_cross_finished_or_empty_turns(monkeypatch):
    ticks = iter([110, 120, 210, 220, 310, 320])
    monkeypatch.setattr(worker, 'time', SimpleNamespace(monotonic_ns=lambda: next(ticks)))
    timing = worker.SpeechInputTiming()
    timing.onset(100)
    timing.partial()
    for _ in range(100):
        timing.partial()
    first = timing.finish()
    assert first == {'speech_sequence': 1, 'stages': [
        {'stage': 'speech_onset', 'monotonic_ns': 100},
        {'stage': 'first_partial', 'monotonic_ns': 110},
        {'stage': 'speech_final', 'monotonic_ns': 120},
    ]}
    timing.onset(200)
    timing.discard()  # A noise-only VAD turn is not the next spoken request.
    timing.partial()  # Missed VAD: do not invent a capture-onset measurement.
    second = timing.finish()
    assert second == {'speech_sequence': 3, 'stages': [
        {'stage': 'first_partial', 'monotonic_ns': 210},
        {'stage': 'speech_final', 'monotonic_ns': 220},
    ]}
    assert len(first['stages']) == 3  # Finishing another turn cannot mutate history.


def command(generation=1, turn='turn-1', run='run-1', sequence=1):
    return dict(type='speak', generation=generation, turn_id=turn, run_id=run,
                speech_sequence=sequence, text='Public answer')


def test_playback_timings_discard_cancelled_preparation_and_preserve_exact_new_binding(monkeypatch):
    events = []
    monkeypatch.setattr(worker, 'emit', lambda kind, **payload: events.append((kind, payload)))

    async def scenario():
        preparing, release = asyncio.Event(), asyncio.Event()
        frames = []
        class Route:
            async def prepare_playback(self):
                preparing.set()
                await release.wait()
            async def restore_capture(self):
                pass
        class Task:
            async def queue_frame(self, frame):
                frames.append(frame)
        playback = worker.PlaybackCommands()
        playback.speak(Task(), Route(), command())
        await preparing.wait()
        old = playback._timing_context(command())
        playback.invalidate(2)
        release.set()
        await playback._preparing
        playback.record_timing('first_pcm', old)
        assert not frames
        assert [payload['stage'] for _, payload in events] == ['speech_received']
        playback.speak(Task(), Route(), command(3, 'turn-3', 'run-3', 3))
        await playback._preparing
        bound = frames[0].metadata['obsidience_timing']
        playback.record_timing('first_pcm', bound)
        assert all(payload['turn_id'] == 'turn-3' for _, payload in events[1:])
        assert [payload['stage'] for _, payload in events[1:]] == ['speech_received', 'aec_ready', 'first_pcm']
        assert all(set(payload) <= {'stage','monotonic_ns','duration_ms','generation','turn_id','run_id','speech_sequence'}
                   for _, payload in events)
        assert 'Public answer' not in repr(events)
    asyncio.run(scenario())


def test_first_output_write_uses_ordered_start_marker_and_rejects_inflight_cancel(monkeypatch):
    events = []
    monkeypatch.setattr(worker, 'emit', lambda kind, **payload: events.append(payload))
    async def forward(*_args, **_kwargs):
        pass
    monkeypatch.setattr(worker.LocalAudioOutputTransport, 'push_frame', forward)

    async def scenario():
        playback = worker.PlaybackCommands()
        playback.generation, playback.epoch = 1, 1
        old = playback._timing_context(command())
        output = worker.SpeechTimingAudioOutput(None, worker.LocalAudioTransportParams(audio_out_enabled=True), playback)
        frame = TTSAudioRawFrame(b'\0' * 1920, 24000, 1)
        entered, release = asyncio.Event(), asyncio.Event()
        async def write(_self, _frame):
            entered.set()
            await release.wait()
            return True
        monkeypatch.setattr(worker.LocalAudioOutputTransport, 'write_audio_frame', write)
        try:
            marker = TTSStartedFrame()
            marker.metadata['obsidience_timing'] = old
            await output.push_frame(marker, FrameDirection.DOWNSTREAM)
            pending = asyncio.create_task(output.write_audio_frame(frame))
            await entered.wait()
            playback.invalidate(2)
            release.set()
            assert await pending is True
            assert events == []  # A successful old write is never called new-turn speech.
            playback.generation, playback.epoch = 3, 3
            new = playback._timing_context(command(3, 'turn-3', 'run-3', 3))
            marker = TTSStartedFrame()
            marker.metadata['obsidience_timing'] = new
            await output.push_frame(marker, FrameDirection.DOWNSTREAM)
            await output.write_audio_frame(frame)
            await output.write_audio_frame(frame)
            assert len(events) == 1
            assert events[0]['stage'] == 'first_output_write'
            assert events[0]['turn_id'] == 'turn-3'
        finally:
            output._executor.shutdown()
    asyncio.run(scenario())


def test_unbound_or_malformed_playback_has_no_task_telemetry(monkeypatch):
    events = []
    monkeypatch.setattr(worker, 'emit', lambda *_args, **_kwargs: events.append(True))
    playback = worker.PlaybackCommands()
    playback.generation = 1
    for payload in [dict(generation=1), command(sequence=True), command(turn='private words'), command(run='x'*97)]:
        timing = playback._timing_context(payload)
        assert timing is None
        playback.record_timing('first_pcm', timing)
    assert events == []


def test_endpoint_waits_for_continued_speech_then_closes_once_at_shared_budget(monkeypatch):
    from pipecat.frames.frames import InterimTranscriptionFrame, VADUserStartedSpeakingFrame, VADUserStoppedSpeakingFrame, EndFrame
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.task import PipelineTask, PipelineParams
    from pipecat.pipeline.runner import PipelineRunner
    partial, final = asyncio.Event(), asyncio.Event()
    events = []
    def capture(kind, **payload):
        if kind == 'transcript_partial': partial.set()
        if kind == 'transcript_final':
            events.append(payload)
            final.set()
    monkeypatch.setattr(worker, 'emit', capture)

    async def scenario():
        timing = worker.SpeechInputTiming()
        turn = worker.ObsidienceNeMoTurnTakingService(timing=timing, use_vad=True)
        bridge = worker.ObsidienceTaskBridge()
        task = PipelineTask(Pipeline([turn,bridge]),
                            params=PipelineParams(allow_interruptions=True),
                            idle_timeout_secs=None, enable_turn_tracking=False)
        @task.event_handler('on_pipeline_started')
        async def drive(_task, _frame):
            onset = VADUserStartedSpeakingFrame()
            onset.metadata['obsidience_onset_ns'] = worker.time.monotonic_ns()
            await task.queue_frame(onset)
            await task.queue_frame(InterimTranscriptionFrame('Hello there', '', ''))
            await asyncio.wait_for(partial.wait(), 1)
            await asyncio.sleep(0.35)
            assert not final.is_set()
            partial.clear()
            await task.queue_frame(InterimTranscriptionFrame(' and pause', '', ''))
            await asyncio.wait_for(partial.wait(), 1)
            await asyncio.sleep(0.45)
            assert not final.is_set()  # The original deadline must have been reset.
            await asyncio.wait_for(final.wait(), 0.5)
            await task.queue_frame(VADUserStoppedSpeakingFrame())  # Late duplicate stop.
            await task.queue_frame(EndFrame())
        await PipelineRunner(handle_sigint=False).run(task)
    asyncio.run(scenario())
    assert len(events) == 1
    stages = events[0]['speech_timing']['stages']
    assert [row['stage'] for row in stages] == ['speech_onset','first_partial','speech_final']
    assert stages[0]['monotonic_ns'] < stages[1]['monotonic_ns'] < stages[2]['monotonic_ns']
    assert events[0]['text'] == 'Hello there and pause'


def test_native_output_queue_preserves_marker_binding_across_audio_chunking(monkeypatch):
    from pipecat.frames.frames import EndFrame
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.task import PipelineTask, PipelineParams
    from pipecat.pipeline.runner import PipelineRunner
    from pipecat.transports.base_output import BaseOutputTransport
    events, writes = [], []
    monkeypatch.setattr(worker, 'emit', lambda kind, **payload: events.append(payload))
    async def start_without_device(output, frame):
        await BaseOutputTransport.start(output, frame)
        await output.set_transport_ready(frame)
    async def write_without_device(output, frame):
        writes.append(len(frame.audio))
        return True
    monkeypatch.setattr(worker.LocalAudioOutputTransport, 'start', start_without_device)
    monkeypatch.setattr(worker.LocalAudioOutputTransport, 'write_audio_frame', write_without_device)

    async def scenario():
        playback = worker.PlaybackCommands()
        playback.generation, playback.epoch = 1, 1
        old = playback._timing_context(command())
        playback.generation, playback.epoch = 2, 2
        current = playback._timing_context(command(2, 'turn-2', 'run-2', 2))
        output = worker.SpeechTimingAudioOutput(None, worker.LocalAudioTransportParams(
            audio_out_enabled=True,audio_out_sample_rate=24000,audio_out_10ms_chunks=4,
            audio_out_end_silence_secs=0),playback)
        task = PipelineTask(Pipeline([output]), params=PipelineParams(audio_out_sample_rate=24000),
                            idle_timeout_secs=None,enable_turn_tracking=False)
        @task.event_handler('on_pipeline_started')
        async def drive(_task, _frame):
            for timing in [old,current]:
                marker = TTSStartedFrame()
                marker.metadata['obsidience_timing'] = timing
                await task.queue_frame(marker)
                # Native MediaSender splits an80ms chunk into two40ms writes.
                await task.queue_frame(TTSAudioRawFrame(b'\0'*3840,24000,1))
            await task.queue_frame(EndFrame())
        try:
            await PipelineRunner(handle_sigint=False).run(task)
        finally:
            output._executor.shutdown()
    asyncio.run(scenario())
    assert writes == [1920]*4
    assert len(events) == 1
    assert events[0]['stage'] == 'first_output_write'
    assert events[0]['turn_id'] == 'turn-2'

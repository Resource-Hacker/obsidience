"""Speech cancellation has bounded causal evidence without copying words."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from obsidience.harness.realtime import runtime as speech


def test_speech_trace_distinguishes_empty_onset_recognized_text_and_new_final(monkeypatch):
    entries = []
    monkeypatch.setattr(
        speech.trace, "emit",
        lambda channel, line, detail: entries.append((channel, line, json.loads(detail[0]))),
    )

    async def scenario():
        calls = []
        finished = asyncio.Event()
        conversation = SimpleNamespace(
            _conversation=SimpleNamespace(conversation_id="conversation-test"),
            _generation=7,
        )

        async def cancel(**kwargs):
            calls.append(("cancel", kwargs))
            conversation._generation += 1

        async def submit(text, **kwargs):
            calls.append(("submit", text, kwargs))
            conversation._generation += 1

        conversation.cancel = cancel
        conversation.submit = submit
        runtime = speech.RealtimeSessionManager(conversation)
        runtime._phase = "command"
        # A previous final must not make a new empty VAD onset look recognized.
        runtime._live_transcript = {"text": "previous private words", "final": True}
        stream = asyncio.StreamReader()
        process = SimpleNamespace(stdout=stream, pid=1234, returncode=None)
        runtime._process = process

        async def publish(kind, **payload):
            if payload.get("line") == "[listening: speech ended]":
                finished.set()

        runtime._publish = publish
        monitor = asyncio.create_task(runtime._monitor_process(process, runtime._operation))
        events = [
            {"type": "speech_detected"},
            {"type": "interruption"},
            {"type": "transcript_partial", "text": "new private words"},
            {"type": "interruption"},
            {"type": "transcript_final", "text": "new private words"},
            {"type": "speech_ended"},
        ]
        for event in events:
            stream.feed_data((json.dumps(event) + "\n").encode())
        try:
            await asyncio.wait_for(finished.wait(), 1)
        finally:
            monitor.cancel()
            try:
                await monitor
            except asyncio.CancelledError:
                pass
        assert calls == [
            ("cancel", {"reason": "speech.interruption", "stop_playback": False}),
            ("cancel", {"reason": "speech.interruption", "stop_playback": False}),
            ("submit", "new private words", {"source": "realtime", "wait": False}),
        ]

    asyncio.run(scenario())
    assert [entry[2]["event"] for entry in entries] == [
        "speech.detected", "speech.interruption", "speech.interruption",
        "speech.transcript_final", "speech.ended",
    ]
    assert [entry[2]["generation"] for entry in entries] == [7, 7, 8, 9, 10]
    assert [entry[2]["latest_transcript_state"] for entry in entries] == [
        "none", "none", "partial", "final", "final",
    ]
    assert [entry[2]["user_speaking"] for entry in entries] == [True] * 4 + [False]
    assert {entry[2]["speech_sequence"] for entry in entries} == {1}
    assert {entry[2]["conversation_id"] for entry in entries} == {"conversation-test"}
    assert "private words" not in json.dumps(entries)


def test_speech_trace_preserves_transcript_before_nemo_start_and_ignores_stale_worker(monkeypatch):
    entries = []
    monkeypatch.setattr(
        speech.trace, "emit",
        lambda channel, line, detail: entries.append(json.loads(detail[0])),
    )

    async def scenario():
        interrupted = asyncio.Event()
        conversation = SimpleNamespace(
            _conversation=SimpleNamespace(conversation_id="conversation-test"),
            _generation=3,
        )

        async def cancel(**kwargs):
            interrupted.set()

        conversation.cancel = cancel
        runtime = speech.RealtimeSessionManager(conversation)
        runtime._phase = "command"
        stream = asyncio.StreamReader()
        process = SimpleNamespace(stdout=stream, pid=1234, returncode=None)
        runtime._process = process
        monitor = asyncio.create_task(runtime._monitor_process(process, runtime._operation))
        # NeMo's transcript fallback can publish recognized text before its
        # UserStartedSpeaking / interruption pair.
        for event in [
            {"type": "transcript_partial", "text": "recognized private words"},
            {"type": "speech_detected"},
            {"type": "interruption"},
        ]:
            stream.feed_data((json.dumps(event) + "\n").encode())
        await asyncio.wait_for(interrupted.wait(), 1)
        runtime._operation += 1
        stream.feed_data(b'{"type":"speech_detected"}\n')
        await asyncio.wait_for(monitor, 1)

    asyncio.run(scenario())
    assert len(entries) == 2
    assert all(entry["latest_transcript_state"] == "partial" for entry in entries)
    assert all(entry["speech_sequence"] == 1 for entry in entries)
    assert "recognized private words" not in json.dumps(entries)

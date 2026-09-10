"""The speech supervisor admits only exact bounded timing evidence."""
import asyncio
import json
from types import SimpleNamespace

import pytest
from obsidience.harness.realtime import runtime as speech


def timing():
    return {'speech_sequence': 2, 'stages': [
        {'stage': 'speech_onset', 'monotonic_ns': 100},
        {'stage': 'first_partial', 'monotonic_ns': 200},
        {'stage': 'speech_final', 'monotonic_ns': 300},
    ]}


@pytest.mark.parametrize('change', ['bool_sequence','duplicate','out_of_order','missing_final','future','extra_stages'])
def test_input_timing_rejects_ambiguous_or_malformed_boundaries(change):
    value = timing()
    if change == 'bool_sequence': value['speech_sequence'] = True
    if change == 'duplicate': value['stages'][1]['stage'] = 'speech_onset'
    if change == 'out_of_order': value['stages'][1]['monotonic_ns'] = 50
    if change == 'missing_final': value['stages'].pop()
    if change == 'future': value['stages'][-1]['monotonic_ns'] = 2**63
    if change == 'extra_stages': value['stages'].append(value['stages'][-1])
    assert speech._input_speech_timing(value) is None


def test_input_timing_removes_nonmetric_content():
    value = timing() | {'text': 'private content'}
    value['stages'][0]['audio'] = 'private content'
    assert speech._input_speech_timing(value) == timing()


def test_playback_timing_requires_exact_sent_command_and_current_generation(monkeypatch):
    events = []
    monkeypatch.setattr(speech.trace, 'latency', lambda stage, **kw: events.append((stage, kw)), raising=False)
    conversation = SimpleNamespace(_generation=4)
    manager = speech.RealtimeSessionManager(conversation)
    manager._playback_timing_binding = (4,2,'turn-2','run-2')
    base = dict(stage='first_pcm', generation=4, speech_sequence=2,
                turn_id='turn-2', run_id='run-2', monotonic_ns=100, duration_ms=20)
    for changes in [{'generation':3},{'turn_id':'old'}, {'run_id':'other'}, {'speech_sequence':3},
                    {'stage':'private reasoning'}, {'monotonic_ns':True}, {'duration_ms':float('nan')}]:
        manager._record_playback_timing(base | changes)
    assert not events
    manager._record_playback_timing(base | {'text':'private words'})
    manager._record_playback_timing(base)  # Duplicate pipe event cannot invent another measurement.
    assert len(events) == 1
    assert 'private words' not in repr(events)


def test_long_final_record_is_parsed_before_display_truncation(monkeypatch):
    async def scenario():
        submitted = []
        completed = asyncio.Event()
        async def submit(text, **kwargs):
            submitted.append((text,kwargs)); completed.set()
        conversation = SimpleNamespace(
            _generation=1, _conversation=SimpleNamespace(conversation_id='c1'), submit=submit,
        )
        manager = speech.RealtimeSessionManager(conversation)
        manager._phase = 'command'
        stream = asyncio.StreamReader()
        process = SimpleNamespace(stdout=stream,pid=123,returncode=None)
        manager._process = process
        monkeypatch.setattr(manager, '_trace_speech_boundary', lambda *_args: None)
        async def publish(*_args, **_kwargs): pass
        monkeypatch.setattr(manager, '_publish', publish)
        task = asyncio.create_task(manager._monitor_process(process,manager._operation))
        payload = {'type':'transcript_final', 'text':'x'*400,'speech_timing':timing()}
        assert len(json.dumps(payload)) > speech.MAX_EVENT_TEXT
        stream.feed_data((json.dumps(payload)+'\n').encode())
        try:
            await asyncio.wait_for(completed.wait(),1)
            assert submitted == [('x'*400,dict(source='realtime',wait=False,speech_timing=timing()))]
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError): await task
    asyncio.run(scenario())

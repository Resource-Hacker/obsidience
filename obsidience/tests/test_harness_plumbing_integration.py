"""Crash and cancellation boundaries in the actual executor and public trace."""
import asyncio
import json
from collections import deque
from types import SimpleNamespace as NS

import pytest

from obsidience.harness.execution import executor, trace
from obsidience.tests.test_execution_cancellation import execution  # noqa: F401


def test_receipts_commit_before_dispatch_and_before_next_decision(execution, monkeypatch):
    requests = []
    real_tool = executor.execute_capability

    def tool(name, args, ctx):
        receipt = executor.INDEX.tool_run_receipts(ctx['run_id'])['calls'][-1]
        assert receipt['status'] == 'started'
        assert receipt['tool'] == name
        return real_tool(name, args, ctx)

    async def model(messages, **_kwargs):
        requests.append(json.loads(json.dumps(messages)))
        if len(requests) == 1:
            return NS(content='{"tool":"window.place","args":{}}', prompt_tokens=100)
        row = executor.INDEX.db.execute("SELECT run_id FROM tool_receipt_runs").fetchone()
        assert executor.INDEX.tool_run_receipts(row[0])['calls'][0]['status'] == 'returned'
        assert not execution.records  # The run's final record does not exist yet.
        return await execution.reply()

    monkeypatch.setattr(executor, 'execute_capability', tool)
    monkeypatch.setattr(executor.llm, 'chat', model)
    result = asyncio.run(execution.run())
    assert result['status'] == 'completed'
    assert requests[1][:len(requests[0])] == requests[0]
    assert [r['status'] for r in executor.INDEX.tool_run_receipts(result['run_id'])['calls']] == ['returned', 'returned']


def test_failed_intent_commit_never_dispatches_a_tool(execution, monkeypatch):
    def fail(**_kwargs):
        raise RuntimeError('isolated ledger fault')

    monkeypatch.setattr(executor.INDEX, 'begin_tool_call', fail)
    with pytest.raises(RuntimeError, match='isolated ledger fault'):
        asyncio.run(execution.run())
    assert execution.records[-1]['status'] == 'failed'
    assert execution.calls == []


def test_committed_async_result_survives_cancellation(execution, monkeypatch):
    async def exercise():
        reached = asyncio.Event()

        async def model(*_args, **_kwargs):
            return NS(content='{"tool":"model.configure","args":{}}', prompt_tokens=100)

        async def operation(_name, _args, ctx):
            reached.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                ctx['_capability_cancelled_after_commit'] = True
                return {'configuration_applied': True, 'runtime_reconciled': False}

        monkeypatch.setattr(executor.llm, 'chat', model)
        monkeypatch.setattr(executor, 'execute_capability_async', operation)
        task = asyncio.create_task(execution.run())
        await reached.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        record = execution.records[-1]
        receipt = executor.INDEX.tool_run_receipts(record['id'])['calls'][0]
        assert receipt['status'] == 'returned'
        evidence = json.loads(record['trace'])
        assert any('"configuration_applied": true' in row.get('obs', '') for row in evidence)
        assert record['status'] == 'interrupted'

    asyncio.run(exercise())


@pytest.fixture
def durable_trace(monkeypatch, isolated_task_ledger):
    monkeypatch.setattr(trace, '_HISTORY', deque())
    monkeypatch.setattr(trace, '_HISTORY_CHARS', 0)
    monkeypatch.setattr(trace, '_SUBSCRIBERS', set())
    monkeypatch.setattr(trace, '_LEDGER', None)
    monkeypatch.setattr(trace, '_LOOP', None)
    monkeypatch.setattr(trace, '_JOURNAL_AVAILABLE', True)
    yield isolated_task_ledger
    trace.stop()


def test_trace_rehydrates_and_replays_missing_entries(durable_trace):
    async def exercise():
        trace.start(durable_trace)
        trace.emit('run', 'Started')
        cursor = trace.replay()['cursor']
        await asyncio.to_thread(trace.emit, 'result', 'Worker returned', [], {'run_id': 'exact-run'})
        await asyncio.sleep(0)
        frame = trace.replay(cursor)
        assert frame['type'] == 'replay'
        assert [e['line'] for e in frame['entries']] == ['Worker returned']
        assert frame['entries'][0]['run_id'] == 'exact-run'
        before = trace.history()
        trace.stop()
        trace.start(durable_trace)
        assert trace.history() == before
        assert trace.replay(frame['cursor'])['entries'] == []

    asyncio.run(exercise())


def test_trace_slow_consumer_gap_is_explicit_and_secrets_never_persist(durable_trace):
    async def exercise():
        trace.start(durable_trace)
        queue = trace.subscribe()
        for i in range(510):
            trace.emit('tool', f'Call {i}', [], {'payload': {'kind': 'tool', 'phase': 'result', 'result': {'password': 'DO-NOT-PERSIST'}}})
        first = await queue.get()
        assert first['seq'] > 1
        frame = trace.replay(1)
        assert frame['type'] == 'snapshot' and frame['gap'] is True
        assert len(frame['entries']) == 500
        assert 'DO-NOT-PERSIST' not in json.dumps(durable_trace.trace_history())
        assert trace.replay(frame['cursor'] + 1)['gap'] is True
        trace.unsubscribe(queue)

    asyncio.run(exercise())


def test_popup_replay_merges_by_identity_and_orders_by_durable_sequence():
    from obsidience.tests.test_action_trace_popup import projection_check
    projection_check(r'''
const first={id:'first',seq:1,at:200,channel:'tool',line:'First'};
const second={id:'second',seq:2,at:100,channel:'result',line:'Second'};
let rows=trace.applyTraceFrame([],JSON.stringify({type:'snapshot',entries:[first]}),0);
rows=trace.applyTraceFrame(rows,JSON.stringify({type:'replay',entries:[first,second],cursor:2}),0);
assert.deepEqual(rows.map(row=>row.id),['first','second']);
assert.deepEqual(rows.map(row=>row.sequence),[1,2]);
rows=trace.applyTraceFrame(rows,JSON.stringify({type:'snapshot',gap:true,entries:[second],cursor:2}),0);
assert.deepEqual(rows.map(row=>row.id),['second']);
''')

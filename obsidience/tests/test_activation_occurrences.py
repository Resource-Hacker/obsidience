"""Occurrences retain independent objectives and exact attempt identities."""
import hashlib
import json
import pytest
from obsidience.harness.knowledge import index, vault
from obsidience.harness.execution import scheduler


@pytest.fixture(autouse=True)
def occurrence_vault(tmp_path, monkeypatch):
    monkeypatch.setattr(vault.CONFIG, "vault_dir", tmp_path / "vault")

def test_two_activations_of_one_definition_keep_separate_state(isolated_task_ledger):
    ledger=isolated_task_ledger
    first,token=ledger.begin_activation('Tasks/query',{'request':'First request','reply_to_turn_id':'turn-a'},'run-a')
    ledger.mutate_task_runtime('Tasks/query',lambda state:state.update(status='failed',summary='No effect'))
    ledger.reset_activation(token)
    second,token=ledger.begin_activation('Tasks/query',{'request':'Second request','reply_to_turn_id':'turn-b'},'run-b')
    ledger.mutate_task_runtime('Tasks/query',lambda state:state.update(status='completed',summary='Answered'))
    ledger.record_run(id='run-b',task_ref='Tasks/query',objective='Second request',agent='Executive',started=1.,finished=2.,status='completed',summary='Answered',trace='[]')
    ledger.reset_activation(token)
    assert first!=second
    assert ledger.activation(first)['status']=='failed'
    assert ledger.activation(first)['params']['request']=='First request'
    assert ledger.activation(second)['status']=='completed'
    assert ledger.run('run-b')['activation_id']==second
    assert ledger.task_runtime('Tasks/query')['activation_id']==second


def test_exact_turn_cannot_be_replayed_or_change_objective(isolated_task_ledger):
    ledger=isolated_task_ledger
    identifier,token=ledger.begin_activation('Tasks/query',{'request':'First','reply_to_turn_id':'turn-a'},'run-a')
    ledger.mutate_task_runtime('Tasks/query',lambda state:state.update(status='completed'))
    ledger.reset_activation(token)
    with pytest.raises(ValueError,match='completed'):
        ledger.begin_activation('Tasks/query',{'request':'Changed','reply_to_turn_id':'turn-a'},'run-b')


def test_legacy_fifo_migration_is_idempotent_and_preserves_failed_head(isolated_task_ledger):
    ledger=isolated_task_ledger
    old={'status':'failed','last_run':'old-run','params':{'event':'test','activation_key':'old','request':'Old'},
         'event_queue':[{'event':'test','activation_key':'new','request':'New'}]}
    with ledger.db:
        ledger.db.execute('INSERT INTO task_runtime VALUES(?,?,?)',('Tasks/example',json.dumps(old),1.))
    ledger._migrate()
    head=ledger.task_runtime('Tasks/example')
    assert head['status']=='failed' and head['params']==old['params']
    assert head['event_queue']==old['event_queue']
    identifiers=[row['id'] for row in ledger.activations('Tasks/example')]
    ledger._migrate()
    assert [row['id'] for row in ledger.activations('Tasks/example')]==identifiers
    assert len(identifiers)==2


def test_late_attempt_completion_cannot_overwrite_newer_head(isolated_task_ledger):
    ledger=isolated_task_ledger
    first,first_token=ledger.begin_activation('Tasks/query',{'request':'A','reply_to_turn_id':'a'},'a')
    second,second_token=ledger.begin_activation('Tasks/query',{'request':'B','reply_to_turn_id':'b'},'b')
    ledger.reset_activation(second_token)
    ledger.mutate_task_runtime('Tasks/query',lambda state:state.update(status='failed',summary='A ended'))
    ledger.reset_activation(first_token)
    assert ledger.activation(first)['status']=='failed'
    assert ledger.task_runtime('Tasks/query')['activation_id']==second
    assert ledger.activation(second)['status']=='running'


def test_read_only_failed_occurrence_does_not_block_independent_next(isolated_task_ledger,monkeypatch):
    ledger=isolated_task_ledger
    vault.write_note('Tasks/example.md',{'kind':'task','title':'Example','triggers':['task.create']},'Read facts.')
    ledger.seed_task_runtime('Tasks/example',{'status':'failed','last_run':'old',
        'params':{'event':'task.create','activation_key':'old','request':'Old'},
        'event_queue':[{'event':'task.create','activation_key':'new','request':'New'}]})
    ledger.begin_tool_run(run_id='old',task_ref='Tasks/example',params={},started=1.)
    old=ledger.task_runtime('Tasks/example')['activation_id']
    assert scheduler._promote_independent_event(vault.load_note('Tasks/example.md'))
    new=ledger.task_runtime('Tasks/example')
    assert new['status']=='pending' and new['params']['request']=='New'
    assert ledger.activation(old)['status']=='failed'
    assert new['activation_id']!=old


def test_missing_effect_receipts_do_not_allow_automatic_progress(isolated_task_ledger):
    ledger=isolated_task_ledger
    vault.write_note('Tasks/example.md',{'kind':'task','title':'Example'},'Work.')
    ledger.seed_task_runtime('Tasks/example',{'status':'failed','last_run':'unknown',
        'params':{'event':'task.create','activation_key':'old'},
        'event_queue':[{'event':'task.create','activation_key':'new'}]})
    assert not scheduler._promote_independent_event(vault.load_note('Tasks/example.md'))


def test_research_can_return_evidence_before_publication(isolated_task_ledger):
    ledger=isolated_task_ledger
    row=ledger.create_continuation(caller_task_ref='Tasks/query',caller_run_id='caller',
        target_task_ref='Tasks/research/question',target_activation_key='question',objective='Question')
    content='A sourced finding.'
    source={'id':'source-one','citation':'source://source-one','immutable':True,'content':content,
            'content_sha256':'sha256:'+hashlib.sha256(content.encode()).hexdigest()}
    ledger.bind_continuation_handoff('caller',source['id'])
    ledger.record_run(id='research',task_ref='Tasks/research/question',agent='Darwin',started=1.,finished=2.,
        status='completed',summary='Finding returned',trace='[]')
    assert ledger.resolve_research_finding('caller','research',source)
    ready=ledger.continuation_for_caller('caller')
    assert ready['status']=='ready' and not json.loads(ready['result'])['accepted_knowledge']
    ledger.bind_continuation_ingest(source['id'],'ingest')
    assert ledger.continuation_for_caller('caller')['status']=='ready'
    assert not ledger.resolve_research_finding('caller','research',source)


def test_queued_receipt_identifies_its_own_occurrence(isolated_task_ledger, monkeypatch):
    vault.write_note('Tasks/example.md', {'kind':'task','title':'Example','triggers':['task.create']}, 'Work.')
    monkeypatch.setattr(scheduler, '_resource_error', lambda *args, **_snapshot: None)
    first = scheduler.enqueue_event(vault.load_note('Tasks/example.md'), {'event':'task.create','activation_key':'first'})
    second = scheduler.enqueue_event(vault.load_note('Tasks/example.md'), {'event':'task.create','activation_key':'second'})
    assert first['activation_id'] and second['activation_id'] and first['activation_id'] != second['activation_id']
    assert isolated_task_ledger.activation(second['activation_id'])['params']['activation_key'] == 'second'


def test_completed_work_wakes_the_existing_scheduler_without_waiting_for_its_tick(monkeypatch):
    import asyncio
    from obsidience.harness.knowledge import source
    from obsidience.harness.execution import refinement
    monkeypatch.setattr(source, 'dispatch_pending_source_events', lambda: None)
    monkeypatch.setattr(scheduler.INDEX, 'sync', lambda: None)
    monkeypatch.setattr(scheduler, 'reconcile_check_health', lambda: None)
    monkeypatch.setattr(refinement, 'reconcile_candidates', lambda: None)
    monkeypatch.setattr(scheduler, '_claim_ready_continuation', lambda: None)
    monkeypatch.setattr(scheduler.CONFIG, 'tick_seconds', 60)
    async def exercise():
        first, second = asyncio.Event(), asyncio.Event()
        calls = []
        def tick():
            calls.append(True)
            (first if len(calls) == 1 else second).set()
        monkeypatch.setattr(scheduler, '_launch_due_tasks', tick)
        worker = asyncio.create_task(scheduler.loop())
        try:
            await asyncio.wait_for(first.wait(), 2)
            await asyncio.to_thread(scheduler.wake_scheduler)
            await asyncio.wait_for(second.wait(), 2)
        finally:
            worker.cancel()
            with pytest.raises(asyncio.CancelledError): await worker
        assert scheduler._wake_event is None and scheduler._wake_loop is None
        assert len(calls) == 2
    asyncio.run(exercise())

from __future__ import annotations

import pytest

from obsidience.harness.execution import scheduler
from obsidience.harness.knowledge import vault
from obsidience.harness.realtime.runtime import RUNTIME
from obsidience.tests.test_scheduler_interactive_provenance import delegate, ledger


def test_idle_tick_does_not_build_an_unused_role_resolver(ledger, monkeypatch):
    monkeypatch.setattr(scheduler, "_foreground_admissions", 0)
    monkeypatch.setattr(RUNTIME, "scheduler_paused", lambda: False)
    monkeypatch.setattr(scheduler, "Resolver", lambda _notes: pytest.fail("idle role scan is unnecessary"))
    assert scheduler.due_tasks() == []


def test_tick_builds_one_role_resolver_and_reads_changes_on_next_tick(ledger, monkeypatch):
    task = vault.load_note("Tasks/research/question.md")
    vault.update_status(task, "pending", {})
    original = scheduler.Resolver
    scan = scheduler.iter_notes
    snapshots = []
    scans = []

    def snapshot(notes):
        res = original(notes)
        snapshots.append(res)
        return res

    def read_notes():
        notes = scan()
        scans.append(notes)
        return notes

    monkeypatch.setattr(scheduler, "Resolver", snapshot)
    monkeypatch.setattr(scheduler, "iter_notes", read_notes)
    monkeypatch.setattr(scheduler, "_resources_allow", lambda _note, **_snapshot: True)
    assert scheduler.due_tasks() == []
    assert len(snapshots) == 1  # all five Task admissions share this snapshot
    assert len(scans) == 1  # Task and role admission share the same fresh read
    agent = vault.load_note("Agents/Darwin/Darwin.md")
    vault.mutate_note_metadata(agent, lambda meta: meta.update(role="executive"))
    assert [note.ref for note in scheduler.due_tasks()] == [task.ref]
    assert len(snapshots) == 2
    assert len(scans) == 2
    assert snapshots[0].resolve(agent.ref).meta["role"] == "researcher"
    assert snapshots[1].resolve(agent.ref).meta["role"] == "executive"


@pytest.mark.parametrize("gate", ["realtime", "foreground"])
def test_tick_uses_supplied_snapshot_and_rechecks_resources(ledger, monkeypatch, gate):
    monkeypatch.setattr(scheduler, "_foreground_admissions", int(gate == "foreground"))
    monkeypatch.setattr(RUNTIME, "scheduler_paused", lambda: gate == "realtime")
    task, _receipt = delegate(ledger)
    notes = vault.iter_notes()
    monkeypatch.setattr(scheduler, "iter_notes", lambda: pytest.fail("snapshot must not be rescanned"))
    monkeypatch.setattr(vault, "resolver", lambda: pytest.fail("roles must use supplied snapshot"))
    resource_checks = []
    available = False

    def resources(note, *, accepted_resolver=None):
        resource_checks.append(note.ref)
        return available

    monkeypatch.setattr(scheduler, "_resources_allow", resources)
    assert scheduler.due_tasks(notes) == []
    available = True
    assert [note.ref for note in scheduler.due_tasks(notes)] == [task.ref]
    assert resource_checks == [task.ref, task.ref]
    assert task.ref not in scheduler._running


@pytest.mark.parametrize("gate", ["realtime", "foreground"])
def test_tick_reuse_preserves_attested_delegation_and_pending_fifo(ledger, monkeypatch, gate):
    monkeypatch.setattr(scheduler, "_foreground_admissions", int(gate == "foreground"))
    monkeypatch.setattr(RUNTIME, "scheduler_paused", lambda: gate == "realtime")
    task, _receipt = delegate(ledger)
    current = dict(task.meta["params"])
    later = {"event": "task.create", "activation_key": "exact-later", "request": "Later question"}
    scheduler.enqueue_event(task, later)
    assert [note.ref for note in scheduler.due_tasks()] == [task.ref]
    waiting = vault.load_note(task.path)
    assert waiting.meta["params"] == current
    assert waiting.meta["event_queue"] == [later]
    assert task.ref not in scheduler._running and task.ref not in scheduler._last_fired

    # A subsequent tick must revalidate the real receipt; the former snapshot
    # is not authority to reuse a different or forged activation.
    vault.update_status(waiting, "pending", {"params": {
        **current, "created_by_run_id": "missing-caller",
    }})
    assert scheduler.due_tasks() == []
    after = vault.load_note(task.path)
    assert after.meta["event_queue"] == [later]
    assert after.meta["params"]["created_by_run_id"] == "missing-caller"


def test_resource_admission_reuses_tick_snapshot_without_rescanning(monkeypatch):
    agent=vault.Note('Agents/A/A.md','A',{'kind':'agent'},'')
    notes=[agent,*[vault.Note(f'Tasks/pending-{i}.md','Pending',
        {'kind':'task','status':'pending','assignee':'Agents/A/A','model':'auto'},'') for i in range(4)]]
    monkeypatch.setattr(scheduler,'_running',set())
    monkeypatch.setattr(scheduler,'_foreground_admissions',0)
    monkeypatch.setattr(RUNTIME,'scheduler_paused',lambda:False)
    monkeypatch.setattr(vault,'resolver',lambda **_kw:pytest.fail('Per-Task Vault rescan'))
    checked=[]
    monkeypatch.setattr(scheduler.model_runtime,'resolve_model',lambda preference,owner:(preference,owner))
    monkeypatch.setattr(scheduler.model_runtime,'check_resources',lambda spec:checked.append(spec))
    builds=[]
    def build(snapshot):
        builds.append(snapshot)
        return vault.Resolver(snapshot)
    monkeypatch.setattr(scheduler,'Resolver',build)
    assert scheduler.due_tasks(notes)==notes[1:]
    assert builds==[notes]
    assert checked==[('auto',agent.ref)]*4
    assert scheduler.due_tasks(notes)==notes[1:]
    assert len(builds)==2 and len(checked)==8
    assert not scheduler._running

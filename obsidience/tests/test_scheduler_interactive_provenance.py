from __future__ import annotations

import json
from dataclasses import replace

import pytest

from obsidience.harness import config
from obsidience.harness.capabilities.task import create as task_create
from obsidience.harness.execution import scheduler
from obsidience.harness.knowledge import index, source, vault
from obsidience.harness.realtime.runtime import RUNTIME


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config.CONFIG, "db_path", tmp_path / "index.sqlite3")
    monkeypatch.setattr(config.CONFIG, "vault_dir", tmp_path / "vault")
    result = index.Index()
    monkeypatch.setattr(index, "INDEX", result)
    monkeypatch.setattr(scheduler, "INDEX", result)
    monkeypatch.setattr(RUNTIME, "scheduler_paused", lambda: True)
    monkeypatch.setattr(scheduler, "_running", set())
    monkeypatch.setattr(scheduler, "_last_fired", {})
    for agent, role in (("Executive", "executive"), ("Darwin", "researcher"), ("Alexandria", "curator")):
        vault.write_note(f"Agents/{agent}/{agent}.md", {
            "kind": "agent", "title": agent, "role": role,
        }, "Agent fixture.")
    for task, agent, triggers in (
        ("query", "Executive", ["chat.request"]),
        ("research/question", "Darwin", ["task.create"]),
        ("research/learn", "Darwin", ["task.create", "source.added"]),
        ("link", "Alexandria", ["task.create"]),
        ("ingest", "Alexandria", ["source.inbox"]),
    ):
        vault.write_note(f"Tasks/{task}.md", {
            "kind": "task", "title": task, "status": "completed", "triggers": triggers,
            "assignee": f"[[Agents/{agent}/{agent}]]",
        }, "Task fixture.")
    yield result
    result.db.close()


def record(ledger, task_ref, run_id, receipt):
    ledger.record_run(
        id=run_id, task_ref=task_ref, agent="test", started=1.0, finished=2.0,
        status="completed", summary="Fixture execution.", trace=json.dumps([receipt]),
    )


def delegate(ledger, target="Tasks/research/question", *, channel="text", interactive=True):
    conversation_id = ledger.active_conversation_id()
    turn = ledger.append_conversation_turn(
        conversation_id=conversation_id, role="user", source=channel,
        text="Investigate this exact request.", run_id=None, reply_to=None, state="final",
    )
    binding = {"conversation_id": conversation_id, "reply_to_turn_id": turn["id"]}
    context = {
        "task": "Tasks/query", "run_id": "caller", "interactive": interactive,
        "params": binding,
    }
    outcome = json.loads(task_create.execute({"task": target}, context))
    assert outcome["state"] in {"started", "queued"}
    receipt = {"created_tasks": context["_created_tasks"]}
    if interactive:
        receipt["interactive_turn"] = binding
    record(ledger, "Tasks/query", "caller", receipt)
    return vault.load_note(target + ".md"), receipt


@pytest.mark.parametrize("channel", ["text", "realtime"])
@pytest.mark.parametrize("target", ["Tasks/research/question", "Tasks/link"])
def test_pause_admits_real_user_delegation_without_research_only_restriction(ledger, channel, target):
    task, _ = delegate(ledger, target, channel=channel)
    assert scheduler._realtime_allows(task)
    assert "realtime_delegate" not in task.meta["params"]
    assert scheduler._realtime_allows(vault.load_note("Tasks/query.md"))


def test_pause_rejects_forged_markers_and_mismatched_execution_receipts(ledger):
    task, receipt = delegate(ledger)
    for forged in (
        {"created_by_task_ref": "Tasks/link"},
        {"created_by_run_id": "other-run"},
        {"activation_key": "other-activation"},
        {"event": "source.added"},
    ):
        changed = replace(task, meta={**task.meta, "params": {**task.meta["params"], **forged}})
        assert not scheduler._realtime_allows(changed)
    different_target = replace(task, path="Tasks/link.md")
    assert not scheduler._realtime_allows(different_target)
    receipt["interactive_turn"]["reply_to_turn_id"] = "missing-turn"
    record(ledger, "Tasks/query", "caller", receipt)
    assert not scheduler._realtime_allows(task)
    forged = replace(task, meta={**task.meta, "params": {
        "event": "task.create", "interactive": True, "realtime_delegate": True,
        "created_by_task_ref": "Tasks/query", "created_by_run_id": "missing",
        "activation_key": "forged",
    }})
    assert not scheduler._realtime_allows(forged)


def test_noninteractive_creator_cannot_borrow_a_user_turn(ledger):
    task, _ = delegate(ledger, interactive=False)
    assert not scheduler._realtime_allows(task)


def test_missing_procedure_generation_requires_the_same_attested_waiting_task(ledger):
    target, _receipt = delegate(ledger)
    vault.write_note("Tasks/generate/runbook.md", {
        "kind": "task", "title": "Runbook", "triggers": ["task.assigned"],
        "assignee": "Agents/Darwin/Darwin", "status": "pending",
        "params": {"event": "task.assigned", "target_task": target.ref,
                   "target_agent": "Agents/Darwin/Darwin"},
    }, "Generate the missing procedure.")
    generator = vault.load_note("Tasks/generate/runbook.md")
    assert scheduler._realtime_allows(generator)
    for forged in ({"target_task": "Tasks/research/learn"}, {"target_agent": "Agents/Alexandria/Alexandria"}):
        changed = replace(generator, meta={**generator.meta, "params": {**generator.meta["params"], **forged}})
        assert not scheduler._realtime_allows(changed)
    vault.update_status(target, "pending", {"params": {
        "event": "task.create", "activation_key": "forged", "interactive": True,
    }})
    assert not scheduler._realtime_allows(generator)


def test_task_create_discards_caller_supplied_provenance(ledger):
    result = json.loads(task_create.execute({
        "task": "Tasks/link", "params": {
            "created_by_task_ref": "forged", "created_by_run_id": "forged",
            "realtime_delegate": True, "interactive": True,
            "interactive_turn": {"reply_to_turn_id": "forged"},
        },
    }, {"task": "Tasks/query", "run_id": "real-run", "interactive": True}))
    assert result["state"] == "started"
    params = vault.load_note("Tasks/link.md").meta["params"]
    assert params["created_by_task_ref"] == "Tasks/query"
    assert params["created_by_run_id"] == "real-run"
    assert not ({"realtime_delegate", "interactive", "interactive_turn"} & params.keys())


def test_inbox_follows_only_attested_user_research_while_source_learn_stays_paused(ledger):
    research, _ = delegate(ledger)
    record(ledger, research.ref, "research-run", {"task_activation": research.meta["params"]})
    raw = source.ingest_source(
        source_type="document", source_ref="https://example.com/primary",
        media_type="text/plain", captured_at=None, content="Exact primary evidence.",
    )
    handoff = source.handoff_source(
        title="Bounded finding", content=f"A supported finding. {raw['citation']}",
        research_task=research.ref, research_run_id="research-run",
    )
    ingest = vault.load_note("Tasks/ingest.md")
    assert scheduler._realtime_allows(ingest)
    assert not scheduler._realtime_allows(vault.load_note("Tasks/research/learn.md"))
    for forged in (
        {"research_run_id": "unrelated-run"},
        {"research_task": "Tasks/research/learn"},
        {"source_id": raw["id"]},
        {"source_sha256": "forged"},
        {"activation_key": "source.inbox:forged"},
    ):
        changed = replace(ingest, meta={**ingest.meta, "params": {**ingest.meta["params"], **forged}})
        assert not scheduler._realtime_allows(changed)
    ledger.db.execute("UPDATE source_evidence SET material_sha256='invalid' WHERE id=?", (handoff["id"],))
    ledger.db.commit()
    assert not scheduler._realtime_allows(ingest)


def test_paused_autonomous_occurrence_waits_behind_user_work_without_loss(ledger):
    task = vault.load_note("Tasks/link.md")
    first = {"event": "task.create", "activation_key": "background-one", "request": "first"}
    second = {"event": "task.create", "activation_key": "background-two", "request": "second"}
    scheduler.enqueue_event(task, first)
    scheduler.enqueue_event(task, second)
    _, _receipt = delegate(ledger, task.ref)

    due = scheduler.due_tasks()
    assert [note.ref for note in due] == [task.ref]
    assert due[0].meta["params"]["created_by_run_id"] == "caller"
    assert due[0].meta["event_queue"] == [first, second]
    assert vault.load_note(task.path).meta["event_queue"] == [first, second]


@pytest.mark.parametrize("status", ["running", "review", "failed", "blocked"])
def test_user_work_never_skips_an_active_or_unresolved_occurrence(ledger, status):
    task = vault.load_note("Tasks/link.md")
    first = {"event": "task.create", "activation_key": "background-one"}
    scheduler.enqueue_event(task, first)
    delegate(ledger, task.ref)
    vault.update_status(task, status)
    before = (config.CONFIG.vault_dir / task.path).read_bytes()
    assert scheduler.due_tasks() == []
    assert (config.CONFIG.vault_dir / task.path).read_bytes() == before


def test_peer_activation_runs_before_cron_without_admitting_later_autonomous_firing(ledger):
    task, _ = delegate(ledger, "Tasks/link")
    vault.mutate_note_metadata(task, lambda meta: meta.update(schedule="0 0 1 1 *"))
    due = scheduler.due_tasks()
    assert [note.ref for note in due] == [task.ref]

    vault.update_status(task, "completed")
    scheduler._last_fired[task.ref] = 1.0
    assert scheduler.due_tasks() == []

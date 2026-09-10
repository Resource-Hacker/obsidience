"""Repair completion and Check delivery depend on same-run controller evidence."""

from __future__ import annotations

import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace as NS

import pytest

from obsidience.harness.capabilities.harness import repair as repair_capability
from obsidience.harness.capabilities.harness import status as health
from obsidience.harness.capabilities.task import complete
from obsidience.harness.execution import executor, scheduler
from obsidience.harness.knowledge import review, source, vault
from obsidience.tests.test_execution_cancellation import execution  # noqa: F401
from obsidience.tests.test_harness_repair import cover
from obsidience.tests.test_scheduler_retry import occurrence  # noqa: F401


def repair_context():
    task = NS(ref="Tasks/repair", kind="task", meta={})
    return {"task": task.ref, "task_note": task, "run_id": "repair-run", "params": {}}


def finish(context, **args):
    return complete.execute({"status": "completed", "summary": "The bounded pass finished.", **args}, context)


@pytest.fixture
def health_inputs(monkeypatch, isolated_task_ledger):
    inputs = NS(tasks=[], issues=[])
    monkeypatch.setattr(vault, "iter_notes", lambda **_kwargs: inputs.tasks)
    monkeypatch.setattr(review, "list_proposals", lambda: [])
    monkeypatch.setattr(isolated_task_ledger, "graph", lambda: {"nodes": [], "links": []})
    monkeypatch.setattr(source, "list_source_files", lambda: {
        "files": [], "issues": inputs.issues, "coverage": {
            "scope": None, "limit": 2000, "returned": 0, "complete": True,
            "next_cursor": None, "consistency": "live",
        },
    })
    return inputs


@pytest.mark.parametrize("snapshot", [None, {}, "healthy", {"status": "failed"}])
def test_repair_rejects_completion_without_an_actual_health_snapshot(snapshot):
    context = repair_context()
    context["_harness_snapshot"] = snapshot
    result = finish(context, evidence=["I checked the harness and repaired everything."])
    assert result["accepted"] is False
    assert "current harness.status snapshot" in result["error"]


def test_model_evidence_and_arguments_cannot_supply_controller_snapshot():
    context = repair_context()
    context["trace"] = [{"tool": "harness.status", "obs": '{"status":"healthy"}'}]
    result = finish(context, evidence=["harness.status returned healthy"],
                    _harness_snapshot={"status": "healthy", "repair_plan": []},
                    harness_health={"version": 1, "status": "healthy"})
    assert result["accepted"] is False
    assert "_harness_snapshot" not in context


@pytest.mark.parametrize("degraded", [False, True])
def test_real_status_read_allows_finished_pass_without_claiming_system_recovered(health_inputs, degraded):
    if degraded:
        health_inputs.issues = [{"path": "fixture", "status": "blocked", "detail": "Needs owner disposition"}]
    context = repair_context()
    public = json.loads(health.execute({}, context))
    assert context["_harness_snapshot"] == public
    assert public["status"] == ("degraded" if degraded else "healthy")
    assert public["repair_plan"] == []
    result = finish(context)
    assert result["accepted"] is True
    assert result["status"] == "completed"
    assert context["_harness_snapshot"]["status"] == public["status"]


def test_repair_must_apply_eligible_operation_then_refresh_before_completion(occurrence, health_inputs):
    note, ledger = occurrence
    cover(ledger, note)
    health_inputs.tasks = [note]
    context = repair_context()
    health.execute({}, context)
    assert context["_harness_snapshot"]["repair_plan"][0]["operation"] == "retry"
    assert "eligible recovery operation" in finish(context)["error"]
    saved = {**context, "_harness_snapshot": deepcopy(context["_harness_snapshot"])}
    args = {"task": note.ref, "run_id": note.meta["last_run"]}
    result = json.loads(repair_capability.execute(args, context))
    assert result["status"] == "requeued"
    assert "_harness_snapshot" not in context
    assert "current harness.status snapshot" in finish(context)["error"]

    before = ledger.task_runtime(note.ref)
    duplicate = json.loads(repair_capability.execute(args, saved))
    assert duplicate["status"] == "already_processed"
    assert "_harness_snapshot" not in saved
    assert ledger.task_runtime(note.ref) == before
    assert len([run for run in ledger.runs() if run["status"] == "requeued"]) == 1

    health_inputs.tasks = [vault.load_note(note.path)]
    health.execute({}, context)
    assert context["_harness_snapshot"]["repair_plan"] == []
    assert finish(context)["accepted"] is True
    assert vault.load_note(note.path).meta["status"] == "pending"
    assert ledger.run(note.meta["last_run"])["status"] == "interrupted"


def test_eligible_attempt_that_loses_revalidation_consumes_snapshot(occurrence, health_inputs, monkeypatch):
    note, ledger = occurrence
    cover(ledger, note)
    health_inputs.tasks = [note]
    context = repair_context()
    health.execute({}, context)

    def late_block(*_args, **_kwargs):
        raise ValueError("The occurrence changed during the attempt.")

    monkeypatch.setattr(scheduler, "retry_failed_occurrence", late_block)
    result = json.loads(repair_capability.execute({"task": note.ref, "run_id": note.meta["last_run"]}, context))
    assert result["status"] == "blocked" and "changed" in result["reason"]
    assert "_harness_snapshot" not in context
    assert finish(context)["accepted"] is False
    assert finish(context, status="failed", summary=result["reason"])["accepted"] is True
    assert vault.load_note(note.path).meta["status"] == "failed"
    assert len(ledger.runs()) == 1


def test_pass_limit_defers_eligible_work_only_after_eight_attempts_and_fresh_status(
    occurrence, health_inputs, monkeypatch,
):
    note, ledger = occurrence
    cover(ledger, note)
    health_inputs.tasks = [note]
    context = repair_context()
    args = {"task": note.ref, "run_id": note.meta["last_run"]}
    context["trace"] = [
        {"tool": "harness.repair", "args": args, "obs": '{"status":"blocked"}', "sig": str(number)}
        for number in range(7)
    ] + [
        {"tool": "harness.status", "args": {}, "obs": '{"status":"degraded"}'},
        {"tool": "harness.repair", "args": args, "not_dispatched": True, "obs": "Prerequisite rejected"},
        {"provider_metrics": {"output_tokens": 10}},
    ]
    health.execute({}, context)
    result = finish(context, evidence=["The model claims eight recovery attempts have finished."])
    assert result["accepted"] is False
    assert "eligible recovery operation" in result["error"]

    def late_block(*_args, **_kwargs):
        raise ValueError("The eighth attempt lost its current precondition.")

    monkeypatch.setattr(scheduler, "retry_failed_occurrence", late_block)
    observation = repair_capability.execute(args, context)
    assert "eighth attempt" in json.loads(observation)["reason"]
    # The executor appends the actual Tool result after dispatch returns.
    context["trace"].append({"tool": "harness.repair", "args": args, "obs": observation, "sig": "eighth"})
    assert "_harness_snapshot" not in context
    result = finish(context)
    assert result["accepted"] is False
    assert "current harness.status snapshot" in result["error"]

    health.execute({}, context)
    snapshot = context["_harness_snapshot"]
    assert snapshot["status"] == "degraded"
    assert snapshot["repair_plan"][0]["operation"] == "retry"
    result = finish(context, summary="Eight recovery attempts finished; eligible work remains deferred.")
    assert result["accepted"] is True and result["status"] == "completed"
    assert "deferred" in result["summary"]
    assert context["_harness_snapshot"] == snapshot
    assert vault.load_note(note.path).meta["status"] == "failed"
    assert len(ledger.runs()) == 1


def test_unsupported_plan_row_does_not_require_reinspection(occurrence, health_inputs):
    note, _ledger = occurrence  # No durable dispatch coverage: this row cannot be retried.
    health_inputs.tasks = [note]
    context = repair_context()
    health.execute({}, context)
    snapshot = deepcopy(context["_harness_snapshot"])
    assert snapshot["repair_plan"][0]["operation"] == "blocked"
    result = json.loads(repair_capability.execute({"task": note.ref, "run_id": note.meta["last_run"]}, context))
    assert result["status"] == "blocked"
    assert context["_harness_snapshot"] == snapshot
    assert finish(context)["accepted"] is True


@pytest.mark.parametrize("ref", ["Tasks/query", "Tasks/check", "Tasks/repair-companion"])
def test_repair_completion_guard_does_not_gate_other_tasks(ref):
    context = repair_context()
    context["task"] = context["task_note"].ref = ref
    assert finish(context)["accepted"] is True


@pytest.mark.parametrize("ref,observed,expected", [
    ("Tasks/check", "healthy", {"version": 1, "status": "healthy"}),
    ("Tasks/check", "degraded", {"version": 1, "status": "degraded"}),
    ("Tasks/check", None, None),
    ("Tasks/query", "degraded", None),
    ("Tasks/repair", "degraded", None),
])
def test_executor_persists_only_check_controller_health_through_bounded_trace(
    execution, health_inputs, monkeypatch, ref, observed, expected,
):
    execution.task.ref = ref
    execution.task.title = ref.rsplit("/", 1)[-1]
    if observed == "degraded":
        health_inputs.issues = [{"path": "fixture", "status": "blocked", "detail": "Unresolved source"}]
    original = executor.execute_capability
    execution.tools.append("harness.status")

    def capability(name, args, context):
        if name == "harness.status":
            public = health.execute(args, context)
            # Exercise ordinary durable trace clipping, without model or live I/O.
            context["trace"].extend({"tool": "fixture.read", "obs": "x" * 1900} for _ in range(60))
            return public
        return original(name, args, context)

    replies = iter(([{"tool": "harness.status", "args": {}}] if observed else []) + [{
        "tool": "task.complete", "args": {
            "status": "completed", "summary": "The harness is degraded according to this model claim.",
            "harness_health": {"version": 1, "status": "degraded"},
        },
    }])

    async def reply(*_args, **_kwargs):
        return NS(content=json.dumps(next(replies)), prompt_tokens=100)

    monkeypatch.setattr(executor, "execute_capability", capability)
    monkeypatch.setattr(executor.llm, "chat", reply)
    assert asyncio.run(execution.run())["status"] == "completed"
    assert len(execution.records) == 1
    record = execution.records[0]
    assert record["status"] == "completed"
    assert len(record["trace"]) <= executor.MAX_RUN_TRACE_CHARS
    rows = json.loads(record["trace"])
    assert rows[0].get("harness_health") == expected
    assert "_harness_snapshot" not in rows[0]
    if observed:
        assert any(row.get("trace_truncated") for row in rows)
    if expected:
        assert set(rows[0]["harness_health"]) == {"version", "status"}

"""Autonomous Repair cannot turn legacy traces into replay authority."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from obsidience.harness.capabilities.harness import repair as capability
from obsidience.harness.config import CONFIG
from obsidience.harness.execution import repair, scheduler
from obsidience.harness.knowledge import index, vault
from obsidience.tests.test_scheduler_retry import occurrence  # noqa: F401


def cover(ledger, note, *, tool="vault.read", read_only=True, status="returned"):
    run_id = note.meta["last_run"]
    ledger.begin_tool_run(run_id=run_id, task_ref=note.ref, params=note.meta["params"], started=1.)
    ledger.begin_tool_call(run_id=run_id, call_id=run_id + ":tool:1", step=1, tool=tool,
                          signature="sha256:" + "a" * 64, started=1.1, read_only=read_only,
                          tool_ref="Tools/" + tool, tool_sha256="b" * 64)
    if status != "started":
        ledger.finish_tool_call(run_id=run_id, call_id=run_id + ":tool:1", status=status,
                                finished=1.2, duration_ms=100., result_sha256="c" * 64,
                                result_chars=100)


def inspect(note):
    return {"task": repair.REPAIR_TASK, "run_id": "repair-run",
            "_harness_snapshot": {"status": "degraded", "repair_plan": repair.repair_plan([note])}}


def apply(note, context):
    return json.loads(capability.execute({"task": note.ref, "run_id": note.meta["last_run"]}, context))


def test_covered_retry_preserves_original_evidence_article_and_fifo(occurrence, monkeypatch):
    note, ledger = occurrence
    cover(ledger, note)
    before = ledger.run(note.meta["last_run"])
    calls = ledger.tool_run_receipts(note.meta["last_run"])
    authored = (CONFIG.vault_dir / note.path).read_bytes()
    monkeypatch.setattr(scheduler, "launch", lambda *_a, **_k: pytest.fail("Must use normal admission"))
    context = inspect(note)
    original_inspection = dict(context)
    assert context["_harness_snapshot"]["repair_plan"][0]["operation"] == "retry"
    result = apply(note, context)
    assert result["status"] == "requeued"
    assert "_harness_snapshot" not in context
    current = vault.load_note(note.path)
    assert current.meta["status"] == "pending" and "blocked_reason" not in current.meta
    for field in ("params", "event_queue", "last_run", "summary"):
        assert current.meta[field] == note.meta[field]
    assert ledger.run(note.meta["last_run"]) == before
    assert ledger.tool_run_receipts(note.meta["last_run"]) == calls
    assert (CONFIG.vault_dir / note.path).read_bytes() == authored
    marker = ledger.run(result["repair_receipt_id"])
    assert marker["status"] == "requeued" and marker["agent"] == "scheduler"
    evidence = json.loads(marker["trace"])[0]["controller_disposition"]
    assert evidence["previous_run_id"] == before["id"]
    assert evidence["effect"] == "task_requeued" and evidence["tools_replayed"] is False
    assert evidence["params_sha256"] == ledger.tool_params_sha256(note.meta["params"])
    assert apply(note, context)["status"] == "blocked"
    assert apply(note, original_inspection)["status"] == "already_processed"
    assert "_harness_snapshot" not in original_inspection
    assert len(ledger.runs()) == 2


def test_uncovered_legacy_read_remains_blocked_despite_owner_retry_compatibility(occurrence):
    note, ledger = occurrence
    assert scheduler.retry_blocked_reason(note) == ""  # Existing owner-only fallback.
    before = ledger.task_runtime(note.ref)
    context = inspect(note)
    row = context["_harness_snapshot"]["repair_plan"][0]
    assert row["operation"] == "blocked" and "predates" in row["reason"]
    assert apply(note, context)["status"] == "blocked"
    # A stale or forged eligible projection still cannot bypass the owner guard.
    row["operation"] = "retry"
    assert "predates" in apply(note, context)["reason"]
    assert "_harness_snapshot" not in context
    with pytest.raises(ValueError, match="predates"):
        scheduler.retry_failed_occurrence(note, note.meta["last_run"], require_receipts=True)
    assert ledger.task_runtime(note.ref) == before and len(ledger.runs()) == 1


@pytest.mark.parametrize("status", ["started", "returned", "error", "interrupted"])
def test_possible_or_committed_mutation_is_never_requeued(occurrence, status):
    note, ledger = occurrence
    cover(ledger, note, tool="vault.propose", read_only=False, status=status)
    context = inspect(note)
    assert context["_harness_snapshot"]["repair_plan"][0]["operation"] == "blocked"
    assert "effects" in apply(note, context)["reason"]
    assert vault.load_note(note.path).meta["status"] == "failed"
    assert len(ledger.runs()) == 1


def test_proven_undispatched_intent_can_pass_the_existing_retry_policy(occurrence):
    note, ledger = occurrence
    cover(ledger, note, tool="vault.propose", read_only=False, status="undispatched")
    assert apply(note, inspect(note))["status"] == "requeued"


@pytest.mark.parametrize("obstacle", ["review", "continuation", "changed_receipt_params"])
def test_late_evidence_is_rechecked_inside_retry_transaction(occurrence, monkeypatch, obstacle):
    note, ledger = occurrence
    cover(ledger, note)
    context = inspect(note)
    original = scheduler.mutate_note_metadata

    def race(candidate, callback):
        def checked(meta):
            assert ledger.db.in_transaction
            if obstacle == "review":
                ledger.db.execute("INSERT INTO review_decisions VALUES(?,?,?,?,?,?)",
                                  ("proposal", note.meta["last_run"], note.ref, "Knowledge/one", "approved", 2.))
            elif obstacle == "continuation":
                ledger.db.execute(
                    "INSERT INTO task_continuations(id,caller_task_ref,caller_run_id,target_task_ref,"
                    "target_activation_key,objective,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    ("child", note.ref, note.meta["last_run"], "Tasks/child", "child-key", "Child", "pending", 1., 1.))
            else:
                ledger.db.execute("UPDATE tool_receipt_runs SET params_sha256=? WHERE run_id=?",
                                  ("d" * 64, note.meta["last_run"]))
            callback(meta)
        return original(candidate, checked)

    monkeypatch.setattr(scheduler, "mutate_note_metadata", race)
    assert apply(note, context)["status"] == "blocked"
    assert "_harness_snapshot" not in context
    assert vault.load_note(note.path).meta["status"] == "failed"
    assert repair.retry_receipt(note) is None


@pytest.mark.parametrize("field,value", [("last_run", "later-run"),
                                         ("params", {"event": "task.create", "activation_key": "changed"}),
                                         ("event_queue", [])])
def test_runtime_race_preserves_intervening_change_and_does_not_mark_retry(occurrence, monkeypatch, field, value):
    note, ledger = occurrence
    cover(ledger, note)
    context = inspect(note)
    original = scheduler.mutate_note_metadata

    def race(candidate, callback):
        vault.mutate_note_metadata(candidate, lambda meta: meta.update({field: value}))
        return original(candidate, callback)

    monkeypatch.setattr(scheduler, "mutate_note_metadata", race)
    result = apply(note, context)
    assert result["status"] == "blocked" and "changed" in result["reason"]
    assert "_harness_snapshot" not in context
    assert vault.load_note(note.path).meta[field] == value
    assert repair.retry_receipt(note) is None and len(ledger.runs()) == 1


def test_retry_marker_and_pending_transition_roll_back_together(occurrence, monkeypatch):
    note, ledger = occurrence
    cover(ledger, note)
    context = inspect(note)
    before = ledger.task_runtime(note.ref)
    original = ledger.record_run

    def fail_after_receipt(**values):
        original(**values)
        if values.get("status") == "requeued":
            assert ledger.db.in_transaction
            raise RuntimeError("Deterministic failure after marker insertion")

    monkeypatch.setattr(ledger, "record_run", fail_after_receipt)
    assert apply(note, context)["status"] == "blocked"
    assert "_harness_snapshot" not in context
    assert ledger.task_runtime(note.ref) == before
    assert repair.retry_receipt(note) is None and len(ledger.runs()) == 1
    monkeypatch.setattr(ledger, "record_run", original)
    assert apply(note, context)["status"] == "blocked"
    current = vault.load_note(note.path)
    assert apply(current, inspect(current))["status"] == "requeued"


def next_failure(note, ledger, *, new_occurrence=False):
    params = dict(note.meta["params"])
    if new_occurrence:
        params["activation_key"] = params["candidate_key"] = "different-original-event"
    run = ledger.run(note.meta["last_run"])
    trace = json.loads(run["trace"])
    trace[0]["task_activation"]["activation_key"] = params["activation_key"]
    ledger.record_run(**{**run, "id": "next-failed-run", "trace": json.dumps(trace)})
    vault.mutate_note_metadata(vault.load_note(note.path), lambda meta: meta.update(
        status="failed", last_run="next-failed-run", params=params))
    current = vault.load_note(note.path)
    cover(ledger, current)
    return current


def test_new_failed_run_for_same_original_occurrence_cannot_form_retry_loop(occurrence):
    note, ledger = occurrence
    cover(ledger, note)
    context = inspect(note)
    original_inspection = dict(context)
    assert apply(note, context)["status"] == "requeued"
    current = next_failure(note, ledger)
    row = repair.repair_plan([current])[0]
    assert row["occurrence_key"] == repair.occurrence_key(note)
    assert row["operation"] == "blocked" and row["reason"] == repair.ALREADY_RETRIED
    assert apply(current, inspect(current))["status"] == "blocked"
    assert apply(note, context)["status"] == "blocked"
    assert apply(note, original_inspection)["status"] == "already_processed"
    with pytest.raises(repair.AlreadyProcessed):
        scheduler.retry_failed_occurrence(current, current.meta["last_run"], require_receipts=True)
    assert vault.load_note(note.path).meta["status"] == "failed"
    assert len([run for run in ledger.runs() if run["status"] == "requeued"]) == 1


def test_new_original_event_has_independent_single_retry(occurrence):
    note, ledger = occurrence
    cover(ledger, note)
    context = inspect(note)
    original_inspection = dict(context)
    assert apply(note, context)["status"] == "requeued"
    current = next_failure(note, ledger, new_occurrence=True)
    assert repair.occurrence_key(current) != repair.occurrence_key(note)
    assert apply(note, original_inspection)["status"] == "blocked"  # Previous plan cannot touch the new head.
    assert apply(current, inspect(current))["status"] == "requeued"
    assert len([run for run in ledger.runs() if run["status"] == "requeued"]) == 2


def test_parameter_drift_under_same_event_cannot_reset_single_retry_limit(occurrence):
    note, ledger = occurrence
    cover(ledger, note)
    assert apply(note, inspect(note))["status"] == "requeued"
    current = vault.load_note(note.path)
    params = {**current.meta["params"], "candidate_refs": ["Knowledge/changed"]}
    vault.mutate_note_metadata(current, lambda meta: meta.update(status="failed", params=params))
    current = vault.load_note(note.path)
    assert repair.occurrence_key(current) == repair.occurrence_key(note)
    assert repair.repair_plan([current])[0]["operation"] == "blocked"
    with pytest.raises(ValueError, match="cannot be attested"):
        scheduler.retry_failed_occurrence(current, current.meta["last_run"], require_receipts=True)
    assert len([run for run in ledger.runs() if run["status"] == "requeued"]) == 1


def test_reopened_ledger_preserves_once_per_occurrence_limit(occurrence, monkeypatch):
    note, ledger = occurrence
    cover(ledger, note)
    assert apply(note, inspect(note))["status"] == "requeued"
    current = next_failure(note, ledger)
    monkeypatch.setattr(CONFIG, "db_path", ledger.db_path)
    reopened = index.Index()
    try:
        with monkeypatch.context() as patch:
            for module in (index, repair, scheduler):
                patch.setattr(module, "INDEX", reopened)
            row = repair.repair_plan([current])[0]
            assert row["operation"] == "blocked" and row["reason"] == repair.ALREADY_RETRIED
            assert apply(current, inspect(current))["status"] == "blocked"
            assert len([run for run in reopened.runs() if run["status"] == "requeued"]) == 1
    finally:
        reopened.db.close()


def test_zero_tools_requires_explicit_durable_coverage(occurrence):
    note, ledger = occurrence
    original = ledger.run(note.meta["last_run"])
    entries = [entry for entry in json.loads(original["trace"]) if "tool" not in entry]
    ledger.record_run(**{**original, "trace": json.dumps(entries)})
    assert repair.repair_plan([note])[0]["operation"] == "blocked"
    ledger.begin_tool_run(run_id=note.meta["last_run"], task_ref=note.ref,
                          params=note.meta["params"], started=1.)
    assert apply(note, inspect(note))["status"] == "requeued"


@pytest.mark.parametrize("trace", ["broken", "[]", '[{"controller_disposition": 1}]'])
def test_unverifiable_existing_marker_never_allows_another_retry(occurrence, trace):
    note, ledger = occurrence
    cover(ledger, note)
    context = inspect(note)
    ledger.record_run(id="repair-" + repair.occurrence_key(note), task_ref=note.ref,
                      agent="scheduler", started=1., finished=2., status="requeued",
                      summary="Unverifiable fixture", trace=trace)
    assert repair.repair_plan([note])[0]["operation"] == "blocked"
    assert apply(note, context)["status"] == "blocked"
    assert ledger.task_runtime(note.ref)["status"] == "failed"


@pytest.mark.parametrize("change", ["missing", "duplicate", "other_run", "other_key", "wrong_task", "extra_arg"])
def test_only_exact_same_run_health_plan_can_authorize_repair(occurrence, change):
    note, ledger = occurrence
    cover(ledger, note)
    context = inspect(note)
    plan = context["_harness_snapshot"]["repair_plan"]
    args = {"task": note.ref, "run_id": note.meta["last_run"]}
    if change == "missing": context.pop("_harness_snapshot")
    if change == "duplicate": plan.append(dict(plan[0]))
    if change == "other_run": plan[0]["run_id"] = "other-run"
    if change == "other_key": plan[0]["occurrence_key"] = "other-occurrence"
    if change == "wrong_task": context["task"] = "Tasks/check"
    if change == "extra_arg": args["command"] = "ignored shell request"
    assert json.loads(capability.execute(args, context))["status"] == "blocked"
    assert ledger.task_runtime(note.ref)["status"] == "failed" and len(ledger.runs()) == 1


def test_plan_bounds_config_blockers_and_excludes_repair_itself(occurrence):
    note, _ = occurrence
    config = replace(note, path="Tasks/config.md", meta={"status": "blocked", "kind": "task",
                     "blocked_reason": "Missing Runbook"})
    own = replace(note, path="Tasks/repair.md")
    plan = repair.repair_plan([own, config, note])
    assert {row["task"] for row in plan} == {note.ref, config.ref}
    assert all(row["operation"] == "blocked" for row in plan)
    assert "configuration" in next(row["reason"] for row in plan if row["task"] == config.ref)
    many = [replace(config, path=f"Tasks/blocked-{number:02d}.md") for number in range(30)]
    plan = repair.repair_plan(many)
    assert len(plan) == repair.PLAN_LIMIT
    assert [row["task"] for row in plan] == sorted(row["task"] for row in plan)


def test_more_than_twelve_earlier_blocked_rows_cannot_hide_eligible_work(occurrence):
    note, ledger = occurrence
    cover(ledger, note)
    blocked = [replace(note, path=f"Tasks/a-blocked-{number:02d}.md",
                       meta={"kind": "task", "status": "blocked", "blocked_reason": "Missing Runbook"})
               for number in range(13)]
    plan = repair.repair_plan([*blocked, note])
    assert len(plan) == repair.PLAN_LIMIT
    assert plan[0]["task"] == note.ref and plan[0]["operation"] == "retry"
    assert all(row["operation"] == "blocked" for row in plan[1:])
    assert [row["task"] for row in plan[1:]] == sorted(row["task"] for row in plan[1:])


def test_pass_attempt_count_uses_only_actual_controller_repair_rows():
    assert repair.repair_attempt_count({}) == 0
    assert repair.repair_attempt_count({"trace": "unavailable"}) == 0
    rows = [{"tool": "harness.repair", "obs": json.dumps({"status": status})}
            for status in ("requeued", "blocked", "already_processed")]
    rows.append({"tool": "harness.repair", "interrupted": True})
    rows.extend([None, "harness.repair", {"provider_metrics": {}},
                 {"tool": "harness.status"}, {"tool": "harness.repair-other"},
                 {"args": {"tool": "harness.repair"}},
                 {"tool": "harness.repair", "not_dispatched": True}])
    assert repair.repair_attempt_count({"trace": rows}) == 4


def test_more_than_eight_eligible_items_fit_a_bounded_pass_without_mutating_the_rest(occurrence):
    original, ledger = occurrence
    initial_run = ledger.run(original.meta["last_run"])
    tasks = []
    for number in range(10):
        task_ref, run_id = f"Tasks/eligible-{number:02d}", f"eligible-failure-{number}"
        vault.write_note(task_ref + ".md", {**original.meta, "last_run": run_id}, original.body)
        task = vault.load_note(task_ref + ".md")
        entries = json.loads(initial_run["trace"])
        entries[0]["activation_packet"] = [task_ref]
        ledger.record_run(**{**initial_run, "id": run_id, "task_ref": task_ref, "trace": json.dumps(entries)})
        cover(ledger, task)
        tasks.append(task)
    context = {"task": repair.REPAIR_TASK, "run_id": "bounded-repair-pass", "trace": []}

    def status():
        plan = repair.repair_plan([vault.load_note(task.path) for task in tasks])
        context["_harness_snapshot"] = {"status": "degraded", "repair_plan": plan}
        return plan

    plan = status()
    assert len(plan) == 10 and all(row["operation"] == "retry" for row in plan)
    for _ in range(repair.PASS_ATTEMPT_LIMIT):
        row = plan[0]
        args = {"task": row["task"], "run_id": row["run_id"]}
        returned = capability.execute(args, context)
        assert json.loads(returned)["status"] == "requeued"
        assert "_harness_snapshot" not in context
        # Match the executor's append-after-return ordering. No second counter
        # or persistence path is needed to bound this same Task pass.
        context["trace"].append({"tool": "harness.repair", "args": args, "obs": returned})
        plan = status()
    assert repair.repair_attempt_count(context) == 8
    assert len(plan) == 2 and all(row["operation"] == "retry" for row in plan)
    assert 1 + 2 * repair.PASS_ATTEMPT_LIMIT + 1 == 18  # Initial read, operations/reads, completion.
    assert 18 <= CONFIG.max_steps
    before = {task.ref: ledger.task_runtime(task.ref) for task in tasks}
    row = plan[0]
    rejected = json.loads(capability.execute({"task": row["task"], "run_id": row["run_id"]}, context))
    assert rejected["status"] == "blocked" and "limit" in rejected["reason"]
    assert "_harness_snapshot" not in context  # Final acceptance still needs a fresh read.
    assert {task.ref: ledger.task_runtime(task.ref) for task in tasks} == before
    assert len([run for run in ledger.runs() if run["status"] == "requeued"]) == 8
    assert len(status()) == 2  # Remaining eligible work stays visible for later Check passes.

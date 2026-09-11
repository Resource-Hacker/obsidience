"""Invalidated maintenance commitments settle without repeating Tool effects."""
import asyncio
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from types import SimpleNamespace

import pytest

from obsidience.harness.capabilities.task import create
from obsidience.harness.capabilities.vault import maintenance
from obsidience.harness.config import CONFIG
from obsidience.harness.execution import assignments, executor, scheduler
from obsidience.harness.knowledge import vault
from obsidience.harness.realtime.runtime import RUNTIME
from obsidience.harness.models.context import PayloadCount

BODY = "Shared routing evidence establishes how applications access accepted articles and preserve useful cited facts while changes pass through owner review. Existing relationships document dependencies, execution constraints, operating context, recovery procedures, source provenance, validation requirements and known limitations for future work."


@pytest.fixture
def scene(tmp_path, monkeypatch, isolated_task_ledger):
    monkeypatch.setattr(CONFIG, "vault_dir", tmp_path / "vault")
    monkeypatch.setattr(scheduler, "_running", set())
    monkeypatch.setattr(scheduler, "_interactive_occurrence", lambda *_: False)
    monkeypatch.setattr(scheduler, "_resources_allow", lambda *_: True)
    monkeypatch.setattr(scheduler, "_resource_error", lambda *_: None)
    monkeypatch.setattr(scheduler, "_realtime_allows", lambda *_: True)
    monkeypatch.setattr(RUNTIME, "scheduler_paused", lambda: False)
    monkeypatch.setattr(maintenance, "_completed_candidates", lambda: set())
    monkeypatch.setattr(assignments, "ensure_task_runbook", lambda *_: {"status": "ready"})
    for owner in ("A", "B"):
        vault.write_note(f"Agents/{owner}/{owner}.md", {"kind": "agent", "title": owner}, f"Accountable executor {owner}.")
        vault.write_note(f"Agents/{owner}/Records/Records.md", {"kind": "knowledge", "title": "Records"}, BODY)
    for name in ("one", "two"):
        vault.write_note(f"Knowledge/{name}.md", {"kind": "knowledge", "title": "Routing evidence"}, BODY)
    vault.write_note("Tasks/merge.md", {"kind": "task", "title": "Merge", "status": "completed", "triggers": ["task.create"]}, "Confirm duplicate identity before proposing changes.")
    return isolated_task_ledger


def revision(refs):
    res = vault.resolver()
    return maintenance.candidate_revision([res.resolve(ref) for ref in refs])


def activation(refs, *, old_revision=None, key="a" * 20):
    return {"event": "task.create", "target_task": "Tasks/merge", "created_by_task_ref": "Tasks/curate",
            "created_by_run_id": "creator-" + key, "activation_key": key,
            "candidate_key": key, "candidate_revision": old_revision or revision(refs),
            "candidate_refs": refs, "candidate_kind": "possible_duplicate",
            "candidate_signals": {"same_normalized_subject": True, "shared_terms": 48,
                                  "body_containment": 0.8, "body_jaccard": 0.7}}


def creator(ledger, params, *, legacy=False, migrated=False, bounded=False, submitted=None):
    raw = submitted if submitted is not None else {
        key: value for key, value in params.items() if key.startswith("candidate_")}
    raw = deepcopy(raw)
    if migrated:
        raw["candidate_refs"] = [ref.rsplit("/", 1)[0] + "/index" for ref in raw["candidate_refs"]]
    target = params["target_task"]
    args = {"task": target, "params": raw}
    sig = "task.create:" + (json.dumps(args, sort_keys=True) if legacy else
                            "sha256:" + hashlib.sha256(json.dumps(args, sort_keys=True).encode()).hexdigest())
    entry = {"tool": "task.create", "args": args, "sig": sig,
             "obs": json.dumps({"task": target, "created_by": "Tasks/curate", "state": "queued"})}
    if bounded:
        entry = executor._bounded_trace_value(entry)
    ledger.record_run(id=params["created_by_run_id"], task_ref="Tasks/curate", agent="Alexandria", started=1., finished=2.,
                     status="completed", summary="Activated maintenance.", trace=json.dumps([{"activation_packet": ["Tasks/curate"]}, entry]))


def head(ledger, params, *, queue=(), status="failed", effects=()):
    target = params["target_task"]
    trace = [{"activation_packet": [target], "task_activation": {key: params[key] for key in
             ("event", "activation_key", "created_by_task_ref", "created_by_run_id")}}, *effects]
    ledger.record_run(id="previous", task_ref=target, agent="Alexandria", started=3., finished=4., status="failed",
                     summary="Candidate precondition failed.", trace=json.dumps(trace))
    note = vault.load_note(target + ".md")
    vault.mutate_note_metadata(note, lambda meta: meta.update(status=status, params=deepcopy(params), event_queue=deepcopy(list(queue)),
                              last_run="previous", summary="Candidate precondition failed.", blocked_reason="Invalid input."))
    return vault.load_note(note.path)


def test_agent_folder_similarity_excluded_but_real_leaf_duplicates_remain(scene):
    rows = maintenance._maintenance_candidates()["candidates"]
    merges = [row for row in rows if row["recommended_task"] == "Merge"]
    assert merges and any(set(row["refs"]) == {"Knowledge/one", "Knowledge/two"} for row in merges)
    assert all(not any(ref.startswith("Agents/") for ref in row["refs"]) for row in merges)
    # The same path/title has no Agent protection without an actual Agent owner.
    owner = vault.load_note("Agents/A/A.md")
    vault.write_note(owner.path, {"kind": "knowledge", "title": "A"}, "Ordinary subject, not an Agent.")
    res = vault.resolver()
    assert not maintenance.agent_structural_hub(res.resolve("Agents/A/Records/Records"), res)


def test_canonical_agent_and_ordinary_shadow_charter_remain_merge_candidates(scene):
    vault.write_note("Agents/A/A.md", {"kind": "agent", "title": "Routing evidence"}, BODY)
    vault.write_note("Agents/A/shadow.md", {"kind": "knowledge", "title": "Routing evidence"}, BODY)
    rows = maintenance._maintenance_candidates()["candidates"]
    assert any(row["recommended_task"] == "Merge" and set(row["refs"]) == {
        "Agents/A/A", "Agents/A/shadow",
    } for row in rows)


@pytest.mark.parametrize("legacy,migrated,bounded", [(False, False, True), (True, False, False), (True, True, False), (True, False, True)])
def test_exact_creator_binding_and_empty_attempt_settle_hub( scene, legacy, migrated, bounded):
    refs = ["Agents/A/Records/Records", "Agents/B/Records/Records"]
    params = activation(refs)
    creator(scene, params, legacy=legacy, migrated=migrated, bounded=bounded)
    note = head(scene, params)
    previous = scene.run("previous")
    authored = (CONFIG.vault_dir / note.path).read_bytes()
    result = scheduler.settle_maintenance_occurrence(note)
    assert result and result["status"] == "completed"
    receipt = scene.run(result["settlement_run_id"])
    evidence = json.loads(receipt["trace"])[0]["controller_disposition"]
    assert evidence["reason"] == "agent_structural_hub"
    assert evidence["creator_run_id"] == params["created_by_run_id"]
    assert evidence["tools_executed"] is False
    assert scene.run("previous") == previous
    assert (CONFIG.vault_dir / note.path).read_bytes() == authored
    assert scheduler.settle_maintenance_occurrence(note) is None


def test_stale_leaf_head_settles_and_preserves_next_valid_fifo_before_model(scene, monkeypatch):
    params = activation(["Knowledge/one", "Knowledge/two"])
    creator(scene, params)
    vault.write_note("Knowledge/one.md", {"kind": "knowledge", "title": "Routing evidence"}, BODY + " Accepted correction.")
    waiting = activation(params["candidate_refs"], key="b" * 20)
    creator(scene, waiting)
    note = head(scene, params, queue=[waiting, {"event": "manual-unrelated", "request": "Preserve me"}])
    assert "invalidated" in scheduler.retry_blocked_reason(note)
    monkeypatch.setattr(scheduler, "run_task", lambda *_a, **_k: pytest.fail("Settlement cannot run a model or Tool"))
    assert scheduler.due_tasks() == []
    current = vault.load_note(note.path)
    assert current.meta["status"] == "pending" and current.meta["params"] == waiting
    assert current.meta["event_queue"] == [{"event": "manual-unrelated", "request": "Preserve me"}]
    assert scheduler.settle_maintenance_occurrence(current) is None
    assert [item.ref for item in scheduler.due_tasks()] == ["Tasks/merge"]


@pytest.mark.parametrize("entry", [{"tool": "vault.propose", "args": {}, "obs": "published"},
    {"tool": "vault.read", "args": {}, "obs": "read"}, {"trace_truncated": 2},
    {"task": "Tasks/child", "status": "completed"}, {"unknown": True}])
@pytest.mark.parametrize("status", ["failed", "pending"])
def test_effectful_or_unknown_prior_same_occurrence_never_settles(scene, entry, status):
    params = activation(["Agents/A/Records/Records", "Agents/B/Records/Records"])
    creator(scene, params)
    note = head(scene, params, effects=[entry], status=status)
    before = scene.task_runtime(note.ref)
    assert scheduler.settle_maintenance_occurrence(note) is None
    assert scene.task_runtime(note.ref) == before and len(scene.runs()) == 2


@pytest.mark.parametrize("fault", ["missing_creator", "wrong_args", "wrong_result", "wrong_signature", "extra_input", "duplicate_receipt", "unmapped_rename"])
def test_unknown_or_forged_creator_provenance_remains_unresolved(scene, fault):
    params = activation(["Agents/A/Records/Records", "Agents/B/Records/Records"])
    creator(scene, params)
    run = scene.run(params["created_by_run_id"])
    trace = json.loads(run["trace"])
    if fault == "missing_creator": params["created_by_run_id"] = "absent"
    elif fault == "extra_input": params["request"] = "Additional work"
    elif fault == "wrong_args": trace[1]["args"]["params"]["candidate_signals"]["shared_terms"] = 49
    elif fault == "wrong_result": trace[1]["obs"] = json.dumps({"state": "rejected", "task": "Tasks/merge"})
    elif fault == "wrong_signature": trace[1]["sig"] = "task.create:sha256:" + "0" * 64
    elif fault == "duplicate_receipt": trace.append(deepcopy(trace[1]))
    elif fault == "unmapped_rename": params["candidate_refs"][0] = "Agents/A/Unknown/Unknown"
    run["trace"] = json.dumps(trace)
    scene.record_run(**{key: value for key, value in run.items() if key != "receipt_path"})
    note = head(scene, params)
    assert scheduler.settle_maintenance_occurrence(note) is None


def test_unrelated_continuation_with_empty_source_does_not_block(scene):
    params = activation(["Agents/A/Records/Records", "Agents/B/Records/Records"])
    creator(scene, params)
    note = head(scene, params)
    scene.create_continuation(caller_task_ref="Tasks/query", caller_run_id="unrelated", target_task_ref="Tasks/research/question",
                             target_activation_key="unrelated", objective="Unrelated inquiry")
    assert scheduler.settle_maintenance_occurrence(note)


def test_receipt_and_fifo_transaction_roll_back_together(scene):
    params = activation(["Agents/A/Records/Records", "Agents/B/Records/Records"])
    creator(scene, params)
    note = head(scene, params)
    before = scene.task_runtime(note.ref)
    scene.db.execute("CREATE TRIGGER fail_settlement BEFORE UPDATE ON task_runtime BEGIN SELECT RAISE(ABORT,'failed state write'); END")
    with pytest.raises(Exception, match="failed state write"):
        scheduler.settle_maintenance_occurrence(note)
    assert scene.task_runtime(note.ref) == before and len(scene.runs()) == 2


def test_same_revision_dedupes_but_new_revision_reopens_settled_refs(scene):
    refs = ["Knowledge/one", "Knowledge/two"]
    params = activation(refs)
    creator(scene, params)
    note = head(scene, params)
    vault.write_note("Knowledge/one.md", {"kind": "knowledge", "title": "Routing evidence", "description": "Accepted refinement"}, BODY)
    assert scheduler.settle_maintenance_occurrence(note)
    row = {"candidate_key": params["candidate_key"], "candidate_revision": revision(refs), "refs": refs,
           "recommended_task": "Merge", "kind": "possible_duplicate", "signals": params["candidate_signals"]}
    raw = {**{key: params[key] for key in params if key.startswith("candidate_")}, "candidate_revision": row["candidate_revision"]}
    context = {"task": "Tasks/curate", "run_id": "new-curate", "_maintenance_snapshot": {"candidates": [row]}}
    first = json.loads(create.execute({"task": note.ref, "params": raw}, context))
    assert first["state"] == "started"
    current = vault.load_note(note.path)
    assert current.meta["status"] == "pending"
    assert current.meta["params"]["activation_key"] != params["activation_key"]
    second = json.loads(create.execute({"task": note.ref, "params": raw}, context))
    assert second["state"] == "started" and second["queue_position"] == 0
    assert not vault.load_note(note.path).meta.get("event_queue")
    assert maintenance._candidate_identity(params) != maintenance._candidate_identity(raw)


def test_executor_rechecks_structural_scope_before_session(scene):
    params = activation(["Agents/A/Records/Records", "Agents/B/Records/Records"])
    with pytest.raises(RuntimeError, match="agent_structural_hub"):
        executor._maintenance_candidate_evidence(vault.load_note("Tasks/merge.md"), params, vault.resolver())


def coverage_activation():
    vault.write_note("Knowledge/Knowledge.md", {"kind": "knowledge", "title": "Knowledge"},
                     "Condensation of this subject; native hierarchy supplies child navigation.")
    vault.write_note("Tasks/improve.md", {"kind": "task", "title": "Improve", "status": "completed",
                     "triggers": ["task.create"]}, "Repair actual knowledge defects.")
    params = activation(["Knowledge/Knowledge", "Knowledge/one", "Knowledge/two"])
    return {**params, "target_task": "Tasks/improve", "candidate_kind": "index_coverage",
            "candidate_signals": {"index_ref": "Knowledge/Knowledge",
                                  "missing_child_refs": ["Knowledge/one", "Knowledge/two"]}}


@pytest.mark.parametrize("legacy,bounded", [(False, False), (False, True), (True, False), (True, True)])
def test_old_coverage_receipt_settles_unchanged_inputs_and_preserves_fifo(scene, monkeypatch, legacy, bounded):
    params = coverage_activation()
    creator(scene, params, legacy=legacy, bounded=bounded)
    waiting = {"event": "task.create", "activation_key": "next-real-defect", "request": "Preserve this work"}
    tail = {"event": "manual", "request": "Keep the remaining queue"}
    note = head(scene, params, queue=[waiting, tail])
    previous, original_creator = scene.run("previous"), scene.run(params["created_by_run_id"])
    authored = {path: path.read_bytes() for path in CONFIG.vault_dir.rglob("*.md")}
    monkeypatch.setattr(scheduler, "run_task", lambda *_a, **_k: pytest.fail("Settlement must not execute work"))
    with pytest.raises(RuntimeError, match="native_hierarchy_coverage"):
        executor._maintenance_candidate_evidence(note, params, vault.resolver())

    result = scheduler.settle_maintenance_occurrence(note)

    assert result and result["status"] == "pending"
    receipt = json.loads(scene.run(result["settlement_run_id"])["trace"])[0]["controller_disposition"]
    assert receipt["reason"] == "native_hierarchy_coverage"
    assert receipt["expected_revision"] == receipt["current_revision"] == params["candidate_revision"]
    assert receipt["tools_executed"] is False and receipt["effect_applied"] is False
    current = vault.load_note(note.path)
    assert current.meta["params"] == waiting and current.meta["event_queue"] == [tail]
    assert scene.run("previous") == previous and scene.run(params["created_by_run_id"]) == original_creator
    assert authored == {path: path.read_bytes() for path in authored}
    assert scheduler.settle_maintenance_occurrence(current) is None


@pytest.mark.parametrize("fault", ["changed_list", "truncated_list", "wrong_signature", "nested_list",
                                  "too_many_refs", "oversized_list", "effect", "review"])
def test_old_coverage_cannot_settle_unverifiable_or_effectful_evidence(scene, fault):
    params = coverage_activation()
    if fault == "nested_list":
        params["candidate_signals"]["missing_child_refs"] = [["Knowledge/one"]]
    elif fault == "too_many_refs":
        params["candidate_signals"]["missing_child_refs"] = ["Knowledge/one"] * 9
    elif fault == "oversized_list":
        params["candidate_signals"]["missing_child_refs"] = ["Knowledge/" + "x" * 501]
    creator(scene, params, bounded=True)
    run = scene.run(params["created_by_run_id"])
    trace = json.loads(run["trace"])
    if fault == "changed_list":
        trace[1]["args"]["params"]["candidate_signals"]["missing_child_refs"] = "['Knowledge/two', 'Knowledge/one']"
    elif fault == "truncated_list":
        trace[1]["args"]["params"]["candidate_signals"]["missing_child_refs"] = "['Knowledge/one', 'Knowledge/tw"
    elif fault == "wrong_signature":
        trace[1]["sig"] = "task.create:sha256:" + "0" * 64
    run["trace"] = json.dumps(trace)
    scene.record_run(**{key: value for key, value in run.items() if key != "receipt_path"})
    effects = [{"tool": "vault.propose", "args": {}, "obs": "Uncertain effect"}] if fault == "effect" else []
    note = head(scene, params, effects=effects)
    if fault == "review":
        CONFIG.staging_dir.mkdir(parents=True, exist_ok=True)
        (CONFIG.staging_dir / "pending.md").write_text("---\ntask: Tasks/improve\nrun_id: previous\n---\nPending owner Review.\n")
    before = scene.task_runtime(note.ref)
    assert scheduler.settle_maintenance_occurrence(note) is None
    assert scene.task_runtime(note.ref) == before and len(scene.runs()) == 2


@pytest.mark.parametrize("legacy,bounded", [(False, False), (False, True), (True, False), (True, True)])
@pytest.mark.parametrize("submitted_score,canonical_score", [(1, 1.0), (1.0, 1)])
def test_original_numeric_signature_settles_equal_canonical_signals(
    scene, legacy, bounded, submitted_score, canonical_score,
):
    params = activation(["Knowledge/one", "Knowledge/two"])
    params["candidate_signals"].update(title_coverage=canonical_score, same_parent=False)
    raw = deepcopy({key: value for key, value in params.items() if key.startswith("candidate_")})
    raw["candidate_signals"]["title_coverage"] = submitted_score
    creator(scene, params, legacy=legacy, bounded=bounded, submitted=raw)
    note = head(scene, params)
    previous, original_creator = scene.run("previous"), scene.run(params["created_by_run_id"])
    vault.write_note("Knowledge/one.md", {"kind": "knowledge", "title": "Routing evidence"}, BODY + " Accepted correction.")

    result = scheduler.settle_maintenance_occurrence(note)

    assert result and result["status"] == "completed"
    receipt = json.loads(scene.run(result["settlement_run_id"])["trace"])[0]["controller_disposition"]
    args = {"task": note.ref, "params": raw}
    assert receipt["creator_args_sha256"] == hashlib.sha256(json.dumps(args, sort_keys=True).encode()).hexdigest()
    assert receipt["reason"] == "revision_changed" and receipt["tools_executed"] is False
    assert scene.run("previous") == previous
    assert scene.run(params["created_by_run_id"]) == original_creator


@pytest.mark.parametrize("legacy,bounded", [(False, False), (False, True), (True, False), (True, True)])
@pytest.mark.parametrize("submitted_score,canonical_score", [(True, 1), (1, True), (False, 0.0), (1.1, 1.0),
    ("1", 1.0), (float("nan"), float("nan")), (float("inf"), float("inf")),
    ([1], [1]), ({"value": 1}, {"value": 1})])
def test_signature_does_not_authorize_changed_or_nonfinite_signal_values(
    scene, legacy, bounded, submitted_score, canonical_score,
):
    params = activation(["Agents/A/Records/Records", "Agents/B/Records/Records"])
    params["candidate_signals"]["title_coverage"] = canonical_score
    raw = deepcopy({key: value for key, value in params.items() if key.startswith("candidate_")})
    raw["candidate_signals"]["title_coverage"] = submitted_score
    creator(scene, params, legacy=legacy, bounded=bounded, submitted=raw)
    note = head(scene, params)
    before = scene.task_runtime(note.ref)
    assert scheduler.settle_maintenance_occurrence(note) is None
    assert scene.task_runtime(note.ref) == before and len(scene.runs()) == 2


@pytest.mark.parametrize("fault", ["truncated_scalar", "missing_signal", "wrong_signature", "modified_projection",
    "oversized_integer", "nonfinite_scalar"])
def test_numeric_recovery_requires_complete_args_and_exact_signature(scene, fault):
    params = activation(["Agents/A/Records/Records", "Agents/B/Records/Records"])
    params["candidate_signals"]["title_coverage"] = 1.0
    raw = deepcopy({key: value for key, value in params.items() if key.startswith("candidate_")})
    raw["candidate_signals"]["title_coverage"] = 1
    creator(scene, params, bounded=True, submitted=raw)
    run = scene.run(params["created_by_run_id"])
    trace = json.loads(run["trace"])
    signals = trace[1]["args"]["params"]["candidate_signals"]
    if fault == "truncated_scalar": signals["title_coverage"] = "1 … [truncated sha256=unverifiable]"
    elif fault == "missing_signal": signals.pop("title_coverage")
    elif fault == "wrong_signature": trace[1]["sig"] = "task.create:sha256:" + "0" * 64
    elif fault == "modified_projection": signals["title_coverage"] = "1.0"
    elif fault == "oversized_integer": signals["title_coverage"] = "1" * 5000
    elif fault == "nonfinite_scalar": signals["title_coverage"] = "1e999"
    run["trace"] = json.dumps(trace)
    scene.record_run(**{key: value for key, value in run.items() if key != "receipt_path"})
    note = head(scene, params)
    before = scene.task_runtime(note.ref)
    assert scheduler.settle_maintenance_occurrence(note) is None
    assert scene.task_runtime(note.ref) == before and len(scene.runs()) == 2


def test_real_activation_admission_race_settles_without_replaying_and_preserves_fifo(scene, monkeypatch):
    vault.write_note("Agents/Executive/Executive.md", {"kind":"agent","title":"Executive",
        "knowledge":["[[Knowledge/one]]","[[Knowledge/two]]"]}, "Fixture principal.")
    params = activation(["Knowledge/one", "Knowledge/two"])
    params["candidate_signals"].update(title_coverage=1.0, same_parent=False)
    raw = deepcopy({key: value for key, value in params.items() if key.startswith("candidate_")})
    raw["candidate_signals"]["title_coverage"] = 1
    snapshot = {"candidate_key": params["candidate_key"], "candidate_revision": params["candidate_revision"],
                "refs": params["candidate_refs"], "kind": params["candidate_kind"],
                "signals": params["candidate_signals"], "recommended_task": "Merge"}
    context = {"task": "Tasks/curate", "run_id": params["created_by_run_id"],
               "_maintenance_snapshot": {"candidates": [snapshot]}}
    created = json.loads(create.execute({"task": "Tasks/merge", "params": raw}, context))
    assert created["state"] == "started"
    note = vault.load_note("Tasks/merge.md")
    params = note.meta["params"]
    assert type(params["candidate_signals"]["title_coverage"]) is float
    creator(scene, params, bounded=True, submitted=raw)
    admitted = scheduler.due_tasks()
    assert [item.ref for item in admitted] == [note.ref]

    # Accepted input changes after Scheduler admission and before Executor checks.
    vault.write_note("Knowledge/one.md", {"kind": "knowledge", "title": "Routing evidence"}, BODY + " Accepted correction.")
    waiting = activation(params["candidate_refs"], key="b" * 20)
    creator(scene, waiting)
    tail = {"event": "unrelated", "request": "Preserve the next commitment"}
    vault.mutate_note_metadata(note, lambda meta: meta.update(event_queue=[waiting, tail]))
    authored = (CONFIG.vault_dir / note.path).read_bytes()
    book = SimpleNamespace(ref="Runbooks/merge", title="Merge procedure")
    model = SimpleNamespace(id="isolated", label="Isolated", context_tokens=10000, max_output_tokens=1000)
    monkeypatch.setattr(executor, "resolve_spine", lambda *_: dict(runbook=book, runbooks=[book], skills=[], tools=[]))
    monkeypatch.setattr(executor, "runbook_tree_hash", lambda *_: "isolated")
    monkeypatch.setattr(executor.model_runtime, "resolve_model", lambda *_: model)
    monkeypatch.setattr(executor, "cached_text_count", lambda *_: PayloadCount(100))
    monkeypatch.setattr(executor.knowledge_activity, "emit", lambda *_a, **_kw: None)
    monkeypatch.setattr(executor.action_trace, "emit", lambda *_a, **_kw: None)
    monkeypatch.setattr(executor, "_execute_session", lambda *_a, **_kw: pytest.fail("No provider or Tool may run"))

    async def compile_packet(*_args, **_kwargs):
        return {"spine": executor.resolve_spine(note, executor.resolver()), "packet": "Isolated packet", "refs": [note.ref, book.ref], "retrieval_ms": 1.0,
                "objective": "Inspect the bound candidate", "provider_system": "Isolated", "provider_user": "Inspect"}

    monkeypatch.setattr(executor, "compile_activation", compile_packet)
    with pytest.raises(RuntimeError, match="revision_changed"):
        asyncio.run(executor.run_task(admitted[0], emit_turn_event=False))
    failed = vault.load_note(note.path)
    previous = scene.run(failed.meta["last_run"])
    assert previous["status"] == "failed"
    assert len(json.loads(previous["trace"])) == 1
    assert "invalidated" in scheduler.retry_blocked_reason(failed)

    assert scheduler.due_tasks() == []
    current = vault.load_note(note.path)
    receipt = json.loads(scene.run(current.meta["last_run"])["trace"])[0]["controller_disposition"]
    assert receipt["previous_run_id"] == previous["id"] and receipt["tools_executed"] is False
    assert current.meta["status"] == "pending" and current.meta["params"] == waiting
    assert current.meta["event_queue"] == [tail]
    assert scene.run(previous["id"]) == previous
    assert (CONFIG.vault_dir / note.path).read_bytes() == authored
    assert [item.ref for item in scheduler.due_tasks()] == [note.ref]

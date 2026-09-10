"""Frozen refinement artifacts reach Review only through exact independent Audit evidence."""

from __future__ import annotations

import asyncio
from collections import deque
from contextlib import asynccontextmanager
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from obsidience.harness import config
from obsidience.harness.capabilities.harness import evaluate
from obsidience.harness.capabilities.vault.propose import stage_proposal
from obsidience.harness.config import CONFIG
from obsidience.harness.execution import executor, refinement, scheduler
from obsidience.harness.knowledge import curation, review, vault
from obsidience.tests.test_harness_evaluation import case


TARGET = "Runbooks/example.md"


def body(marker):
    return f"""## Prerequisites
The exact fixture task is active. {marker}
## Ordered Actions
Follow [[Skills/vault.read]] to read the exact Article, then report the supported finding.
## Bounded Branches
Keep missing evidence explicit.
## Stop Conditions
Stop after the bounded result.
## Completion Criteria
The requested finding is supported.
## Verification
Match the observed Article.
## Recovery
Report an unavailable observation without another effect.
"""


@pytest.fixture
def workflow(tmp_path, monkeypatch, isolated_task_ledger):
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(CONFIG, "vault_dir", tmp_path / "obsidience" / "vault")
    monkeypatch.setattr(CONFIG, "git_commit", False)
    monkeypatch.setattr(isolated_task_ledger, "sync", lambda *_a, **_k: None)
    monkeypatch.setattr(review, "git_commit", lambda *_a, **_k: None)
    monkeypatch.setattr(curation, "try_auto_approve", lambda result, *_a: result)
    state = NS(ledger=isolated_task_ledger, queued=[], requests=[], leases=0, releases=0,
               contract={"spec": {"id": "fixture-model"}, "reasoning_effort": "none"},
               revision="a" * 64, provider_error=None)
    monkeypatch.setattr(refinement, "_model_contract", lambda *_a: deepcopy(state.contract))
    monkeypatch.setattr(refinement, "_code_revision", lambda: state.revision)
    for name in ("task.complete", "vault.read"):
        vault.write_note("Tools/" + name + ".md", {"kind": "tool", "title": name,
            "binding": "capability:" + name,
            "source": "obsidience/harness/capabilities/" + name.replace(".", "/") + ".py"}, "Exact fixture Tool.")
        vault.write_note("Skills/" + name + ".md", {"kind": "skill", "title": name,
            "tool": "[[Tools/" + name + "]]"}, "Use the paired Tool within this Task.")
    for name in ("Executive", "Darwin", "Heimdall"):
        vault.write_note(f"Agents/{name}/{name}.md", {"kind": "agent", "title": name}, "Perform assigned work.")
    vault.write_note("Tasks/example.md", {"kind": "task", "title": "Example",
        "assignee": "[[Agents/Executive/Executive]]", "runbook": "[[Runbooks/example]]",
        "model": "fixture-model", "reasoning_effort": "none"}, "Report the exact requested finding.")
    vault.write_note(TARGET, {"kind": "runbook", "title": "Example procedure",
        "task": "[[Tasks/example]]", "for_agent": "[[Agents/Executive/Executive]]",
        "skills": ["[[Skills/vault.read]]"], "owner_maintained": True}, body("BASELINE_RULE"))
    for task_ref, name, trigger in ((refinement.GENERATOR, "Darwin", "task.create"),
                                     (refinement.AUDITOR, "Heimdall", "runbook.proposed")):
        vault.write_note(task_ref + ".md", {"kind": "task", "title": task_ref.rsplit("/", 1)[-1],
            "assignee": f"[[Agents/{name}/{name}]]", "triggers": [trigger]}, "Perform the bound workflow.")
    isolated_task_ledger.record_run(id="origin", task_ref="Tasks/example", agent="Executive", started=1., finished=2.,
        status="failed", summary="The necessary read was skipped", trace="[]", runbook_ref="Runbooks/example",
        runbook_sha256=hashlib.sha256((CONFIG.vault_dir / TARGET).read_bytes()).hexdigest())
    training, protected = case(), case("protected", "holdout")
    training["objective"] = "TRAIN: inspect the exact Article."
    protected["objective"] = "HOLDOUT: inspect the exact Article."
    state.specification = {"schema_version": 1, "task": "Tasks/example", "runbook": "Runbooks/example",
        "origin_run_id": "origin", "problem": "The baseline skipped a required Article read.",
        "suite": {"schemaVersion": 1, "cases": [training, protected], "repetitions": 1}}
    state.prepared = refinement.prepare_case(state.specification)
    state.context = {"task": refinement.GENERATOR, "agent": "Darwin", "run_id": "author-run",
                     "params": {"refinement_case": state.prepared["case_id"]}, "event": "task.create"}

    def enqueue(event, params, **kwargs):
        state.queued.append((event, deepcopy(params), kwargs))
        return [{"state": "queued", "task": refinement.AUDITOR}]

    monkeypatch.setattr(scheduler, "enqueue_named_event", enqueue)
    model = NS(id="fixture-model", label="Fixture", context_tokens=10000, max_output_tokens=1000,
               capabilities=("text", "tools"))
    monkeypatch.setattr(executor.model_runtime, "resolve_model", lambda *_a: model)
    monkeypatch.setattr(executor.model_runtime, "configured_spec", lambda *_a: model)

    @asynccontextmanager
    async def lease(_spec):
        state.leases += 1
        try:
            yield model
        finally:
            state.releases += 1

    async def chat(messages, **_kwargs):
        state.requests.append(deepcopy(messages))
        if state.provider_error:
            raise state.provider_error
        system = messages[0]["content"]
        training_case = any("TRAIN:" in message["content"] for message in messages)
        read_already = any(message["role"] == "assistant" and '"vault.read"' in message["content"] for message in messages)
        if read_already or (training_case and "CANDIDATE_RULE" not in system):
            action = {"tool": "task.complete", "args": {"status": "completed", "outcome": "no_change",
                       "summary": "The verified fixture needs no change."}}
        else:
            action = {"tool": "vault.read", "args": {"ref": "Knowledge/one"}}
        return executor.llm.ChatReply(content=json.dumps(action), prompt_tokens=42, completion_tokens=8, finish_reason="stop")

    def no_dispatch(*_a, **_k):
        pytest.fail("a frozen trial dispatched a live Capability")

    monkeypatch.setattr(executor.model_runtime, "lease", lease)
    monkeypatch.setattr(executor.llm, "chat", chat)
    monkeypatch.setattr(executor, "execute_capability", no_dispatch)
    monkeypatch.setattr(executor, "execute_capability_async", no_dispatch)
    state.trace_emit = executor.action_trace.emit
    monkeypatch.setattr(executor.action_trace, "emit", lambda *_a, **_k: None)
    monkeypatch.setattr(executor.action_trace, "latency", lambda *_a, **_k: None)
    return state


def stage(state, **changes):
    args = {"target": TARGET, "action": "update", "title": "Example procedure",
            "body": body("CANDIDATE_RULE"), "metadata": {}, "reason": "Repair the missing read."}
    args.update(changes)
    result = stage_proposal(args, state.context)
    state.proposal = Path(result["staged"]).name
    state.note = vault.load_note(result["staged"])
    state.audit_context = {"task": refinement.AUDITOR, "agent": "Heimdall", "run_id": "audit-run",
                           "params": deepcopy(state.queued[-1][1])}
    return result


def evaluate_candidate(state):
    state.returned = asyncio.run(evaluate.execute({"proposal": state.proposal}, state.audit_context))
    state.result = json.loads(state.returned)
    assert "error" not in state.result
    state.report = refinement._load("reports/" + state.audit_context["params"]["proposal_sha256"],
                                    state.result["evaluation_report"])
    return state.result


def attest(state, *, run_id="audit-run", run_status="completed", call_status="returned", result=None, task_ref=None):
    task_ref = task_ref or refinement.AUDITOR
    ledger = state.ledger
    ledger.begin_tool_run(run_id=run_id, task_ref=task_ref, params=state.audit_context["params"], started=10.)
    ledger.begin_tool_call(run_id=run_id, call_id=run_id + ":1", step=1, tool="harness.evaluate",
        signature="harness.evaluate:sha256:" + "b" * 64, started=11., read_only=False,
        tool_ref="Tools/harness.evaluate", tool_sha256="c" * 64)
    encoded = json.dumps(state.returned if result is None else result, sort_keys=True).encode()
    ledger.finish_tool_call(run_id=run_id, call_id=run_id + ":1", status=call_status, finished=12.,
        duration_ms=1000., result_sha256=hashlib.sha256(encoded).hexdigest(), result_chars=len(encoded))
    ledger.record_run(id=run_id, task_ref=task_ref, agent="Heimdall", started=10., finished=13.,
        status=run_status, summary="The frozen evaluation finished.", trace="[]")


def test_prepare_freezes_real_dependency_bytes_and_exposes_only_training_to_author(workflow):
    state = workflow
    document = refinement._current(state.prepared["case_id"])
    assert document["origin"]["id"] == "origin"
    assert document["articles"]["Runbooks/example"] == (CONFIG.vault_dir / TARGET).read_text()
    public = refinement.activation_context(state.prepared["case_id"])
    assert [item["split"] for item in public["training_cases"]] == ["train"]
    assert "HOLDOUT" not in json.dumps(public)
    before = (CONFIG.vault_dir / TARGET).read_bytes()
    stage(state)
    assert state.note.meta["refinement"]["base_sha256"] == document["base_sha256"]
    assert state.note.meta["authored_fields"] == []
    assert state.queued[0][0] == "runbook.proposed"
    assert state.queued[0][2] == {"expected_task": refinement.AUDITOR}
    assert state.queued[0][1]["proposal_sha256"] == hashlib.sha256((CONFIG.vault_dir / state.note.path).read_bytes()).hexdigest()
    assert (CONFIG.vault_dir / TARGET).read_bytes() == before
    refinement.candidate_staged(str(CONFIG.vault_dir / state.note.path), state.context)
    assert len(state.queued) == 1


@pytest.mark.parametrize("changes", [{"title": "Renamed"}, {"metadata": {"skills": ["[[Skills/task.complete]]"]}},
                                    {"action": "create"}, {"body": body("BASELINE_RULE")}])
def test_candidate_cannot_change_authority_or_be_a_noop(workflow, changes):
    with pytest.raises(ValueError):
        stage(workflow, **changes)
    assert workflow.queued == []
    assert not list(CONFIG.staging_dir.glob("*.md"))


@pytest.mark.parametrize("change", ["model", "evaluator", "article", "extra_runbook"])
def test_changed_frozen_contract_requires_new_case(workflow, change):
    state = workflow
    if change == "model":
        state.contract["reasoning_effort"] = "high"
    elif change == "evaluator":
        state.revision = "d" * 64
    elif change == "article":
        note = vault.load_note(TARGET)
        vault.write_note(TARGET, note.meta, body("UNRELATED_EDIT"))
    else:
        note = vault.load_note(TARGET)
        vault.write_note("Runbooks/extra.md", {**note.meta, "title": "Extra applicable procedure"}, body("EXTRA"))
    with pytest.raises(ValueError):
        refinement._current(state.prepared["case_id"])


@pytest.mark.parametrize("change", ["article", "extra_runbook"])
def test_supplied_current_snapshot_preserves_frozen_bytes_and_dependency_checks(workflow, change):
    state = workflow
    stage(state)
    note = vault.load_note(TARGET)
    if change == "article":
        vault.write_note(TARGET, note.meta, body("CHANGED_FROZEN_BODY"))
    else:
        vault.write_note("Runbooks/extra.md", {**note.meta, "title": "Another applicable procedure"}, body("EXTRA"))
    current = vault.resolver(include_system=False)
    with pytest.raises(ValueError, match="changed"):
        refinement._current(state.prepared["case_id"], accepted_resolver=current)
    with pytest.raises(ValueError, match="changed"):
        refinement._validate_proposal(state.note, accepted_resolver=current)


@pytest.mark.parametrize("supplied", [False, True])
@pytest.mark.parametrize("operation", ["current", "proposal"])
def test_revalidation_constructs_at_most_one_live_resolver(workflow, monkeypatch, supplied, operation):
    state = workflow
    stage(state)
    snapshot = vault.resolver(include_system=False)
    original_resolver, original_current = refinement.resolver, refinement._current
    built, checked = [], []

    def counted_resolver(*args, **kwargs):
        built.append(True)
        return original_resolver(*args, **kwargs)

    def counted_current(case_id, **kwargs):
        checked.append(kwargs.get("accepted_resolver"))
        return original_current(case_id, **kwargs)

    monkeypatch.setattr(refinement, "resolver", counted_resolver)
    monkeypatch.setattr(refinement, "_current", counted_current)
    kwargs = {"accepted_resolver": snapshot} if supplied else {}
    if operation == "current":
        refinement._current(state.prepared["case_id"], **kwargs)
    else:
        refinement._validate_proposal(state.note, **kwargs)
    assert len(built) == (0 if supplied else 1)
    assert len(checked) == 1
    if supplied:
        assert checked[0] is snapshot


def test_review_listing_reuses_one_locked_snapshot_for_all_refinement_rows(workflow, monkeypatch):
    state = workflow
    stage(state)
    for number in range(2):
        vault.write_note(f"_staging/copy-{number}.md", state.note.meta, state.note.body)
    original_list_resolver, original_current = review.Resolver, refinement._current
    built, checked = [], []

    def listing_resolver(notes):
        result = original_list_resolver(notes)
        built.append(result)
        return result

    def current(case_id, *, accepted_resolver=None):
        assert vault._NOTE_WRITE_LOCK._is_owned()
        assert accepted_resolver is not None
        checked.append(accepted_resolver)
        return original_current(case_id, accepted_resolver=accepted_resolver)

    def unexpected_live_resolver(*_args, **_kwargs):
        pytest.fail("Review listing rebuilt its accepted Vault snapshot")

    monkeypatch.setattr(review, "Resolver", listing_resolver)
    monkeypatch.setattr(refinement, "resolver", unexpected_live_resolver)
    monkeypatch.setattr(refinement, "_current", current)
    assert len(review.list_proposals()) == 3
    assert len(built) == 1 and len(checked) == 3
    assert all(item is built[0] for item in checked)


def test_approval_rechecks_fresh_dependencies_after_listing_was_approvable(workflow):
    state = workflow
    stage(state)
    evaluate_candidate(state)
    attest(state)
    row = next(item for item in review.list_proposals() if item["file"] == state.proposal)
    assert row["approvable"] is True
    note = vault.load_note(TARGET)
    vault.write_note("Runbooks/extra.md", {**note.meta, "title": "New applicable procedure"}, body("EXTRA"))
    with pytest.raises(ValueError, match="dependency selection changed"):
        review.approve(state.proposal)
    assert "BASELINE_RULE" in vault.load_note(TARGET).body


def test_paired_trials_emit_sanitized_distinct_correlations_inside_outer_audit(workflow, monkeypatch):
    state = workflow
    stage(state)
    trace = executor.action_trace
    monkeypatch.setattr(trace, "emit", state.trace_emit)
    monkeypatch.setattr(trace, "_HISTORY", deque())
    monkeypatch.setattr(trace, "_HISTORY_CHARS", 0)
    monkeypatch.setattr(trace, "_LEDGER", state.ledger)
    monkeypatch.setattr(trace, "_LOOP", None)
    monkeypatch.setattr(trace, "_SUBSCRIBERS", set())
    token = trace.bind("audit-run", refinement.AUDITOR, refinement.HEIMDALL)
    try:
        assert evaluate_candidate(state)["verdict"] == "passed"
        trace.emit("status", "Outer Audit resumed")
    finally:
        trace.reset(token)
    events = trace.history()
    simulated = [event for event in events if "trial" in event]
    assert simulated
    identities = {(event["trial"]["case_id"], event["trial"]["split"], event["trial"]["variant"],
                   event["trial"]["repetition"]) for event in simulated}
    assert identities == {(case_id, split, variant, 1) for case_id, split in
                          (("training", "train"), ("protected", "holdout"))
                          for variant in ("baseline", "candidate")}
    assert len({event["trial"]["id"] for event in simulated}) == 4
    for event in simulated:
        assert event["run_id"] == "audit-run" and event["task_ref"] == refinement.AUDITOR
        assert event["line"].startswith("Simulation · " + event["trial"]["variant"].title())
        if "payload" in event:
            assert event["payload"]["simulated"] is True
        if event.get("payload", {}).get("kind") in {"tool", "model"} and event.get("step", 0) > 0:
            assert event["call_id"].startswith(event["trial"]["id"] + ":")
    assert events[-1]["line"] == "Outer Audit resumed" and "trial" not in events[-1]
    assert state.ledger.trace_history() == events
    assert not state.ledger.db.execute("SELECT 1 FROM tool_receipt_runs").fetchone()


def test_actual_paired_report_needs_completed_exact_audit_receipt_before_review(workflow):
    state = workflow
    before = deepcopy(vault.load_note(TARGET).meta)
    stage(state)
    assert evaluate_candidate(state)["verdict"] == "passed"
    rows = state.report["observations"]
    assert [row["passed"] for row in rows["baseline"]] == [False, True]
    assert [row["passed"] for row in rows["candidate"]] == [True, True]
    assert all(row["error"] is None for variant in rows.values() for row in variant)
    assert state.leases == state.releases == 4
    assert not state.ledger.db.execute("SELECT 1 FROM tool_receipt_runs").fetchone()
    assert refinement.review_blocker(state.note)
    with pytest.raises(ValueError):
        review.approve(state.proposal)
    attest(state)
    assert refinement.review_blocker(state.note) is None
    assert review.approve(state.proposal)["approved"] == TARGET
    accepted = vault.load_note(TARGET)
    assert "CANDIDATE_RULE" in accepted.body
    assert {key: accepted.meta[key] for key in before} == before
    assert set(accepted.meta) - before.keys() == {"approved_at", "provenance"}


@pytest.mark.parametrize("fault", ["failed_run", "failed_call", "wrong_candidate", "wrong_run", "wrong_task"])
def test_review_rejects_nonmatching_or_failed_audit_evidence(workflow, fault):
    state = workflow
    stage(state)
    evaluate_candidate(state)
    options = {}
    if fault == "failed_run":
        options["run_status"] = "failed"
    elif fault == "failed_call":
        options["call_status"] = "error"
    elif fault == "wrong_candidate":
        options["result"] = json.dumps({**state.result, "proposal": "another.md"}, sort_keys=True)
    elif fault == "wrong_run":
        options["run_id"] = "unrelated-audit"
    else:
        options["task_ref"] = "Tasks/check"
    attest(state, **options)
    assert refinement.review_blocker(state.note)
    with pytest.raises(ValueError):
        review.approve(state.proposal)
    assert "BASELINE_RULE" in vault.load_note(TARGET).body


def test_provider_errors_remain_in_complete_pairs_and_block_review(workflow):
    state = workflow
    stage(state)
    state.provider_error = RuntimeError("Fixture provider unavailable")
    result = evaluate_candidate(state)
    assert result["verdict"] == "incomplete"
    rows = state.report["observations"]
    assert len(rows["baseline"]) == len(rows["candidate"]) == 2
    assert all(row["error"] and row["passed"] is False for variant in rows.values() for row in variant)
    attest(state)
    assert refinement.review_blocker(state.note)


def test_comparison_cannot_drop_same_case_from_both_recorded_sides(workflow):
    state = workflow
    specification = deepcopy(state.specification)
    specification["suite"]["cases"].extend([case("another-training"), case("another-protected", "holdout")])
    state.prepared = refinement.prepare_case(specification)
    state.context["params"]["refinement_case"] = state.prepared["case_id"]
    stage(state)
    evaluate_candidate(state)
    # A valid-looking smaller suite must not replace this frozen suite's coverage.
    report = deepcopy(state.report)
    for variant in report["observations"].values():
        del variant[2:]
    from obsidience.harness.execution.evaluation import compare_observations
    report["comparison"] = compare_observations(report["observations"]["baseline"], report["observations"]["candidate"])
    assert report["comparison"]["verdict"] == "passed"
    report_id = refinement._store("reports/" + report["proposal_sha256"], report)
    state.result = refinement._result(report_id, report)
    state.returned = json.dumps(state.result, sort_keys=True)
    attest(state)
    assert refinement.review_blocker(state.note)
    with pytest.raises(ValueError):
        review.approve(state.proposal)


@pytest.mark.parametrize("fault", ["same_author", "wrong_proposal", "wrong_hash"])
def test_audit_must_bind_current_candidate_and_independent_execution(workflow, fault):
    state = workflow
    stage(state)
    if fault == "same_author":
        state.audit_context["run_id"] = state.context["run_id"]
    elif fault == "wrong_proposal":
        state.audit_context["params"]["proposal"] = "other.md"
    else:
        state.audit_context["params"]["proposal_sha256"] = "f" * 64
    result = json.loads(asyncio.run(evaluate.execute({"proposal": state.proposal}, state.audit_context)))
    assert result["error"]
    assert "_harness_evaluation" not in state.audit_context
    assert state.requests == []


def test_candidate_edit_after_passing_audit_invalidates_review_receipt(workflow):
    state = workflow
    stage(state)
    evaluate_candidate(state)
    attest(state)
    assert refinement.review_blocker(state.note) is None
    vault.write_note(state.note.path, state.note.meta, body("CANDIDATE_RULE changed after audit"))
    current = vault.load_note(state.note.path)
    assert refinement.review_blocker(current)
    with pytest.raises(ValueError):
        review.approve(state.proposal)
    assert "BASELINE_RULE" in vault.load_note(TARGET).body

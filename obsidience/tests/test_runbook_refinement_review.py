"""Refinement uses ordinary staging and Review with controller-owned evidence."""

from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from obsidience.harness.capabilities.task.complete import _completion_error, _generated_runbook_completion_error
from obsidience.harness.capabilities.vault.propose import stage_proposal, validate_generated_runbook
from obsidience.harness.config import CONFIG
from obsidience.harness.knowledge import curation, review, vault


TARGET = "Runbooks/example.md"
GENERATOR = "Tasks/generate/runbook"


@pytest.fixture
def refinement_review(tmp_path, monkeypatch, isolated_task_ledger):
    from obsidience.harness.execution import refinement

    monkeypatch.setattr(CONFIG, "vault_dir", tmp_path / "vault")
    monkeypatch.setattr(CONFIG, "git_commit", False)
    monkeypatch.setattr(isolated_task_ledger, "sync", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(review, "git_commit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(curation, "try_auto_approve", lambda result, *_args: result)
    vault.write_note(TARGET, {
        "kind": "runbook", "title": "Example procedure", "owner_maintained": True,
        "task": "[[Tasks/example]]", "for_agent": "[[Agents/Executive/Executive]]",
        "skills": ["[[Skills/vault.read]]"],
    }, "Read accepted evidence and report its supported result.\n")
    vault.write_note("Tasks/example.md", {
        "kind": "task", "title": "Example", "runbook": "[[Runbooks/example]]",
        "model": "unchanged-model", "reasoning_effort": "none",
    }, "Answer one bounded question.")
    vault.write_note("Agents/Executive/Executive.md", {
        "kind": "agent", "title": "Executive", "tasks": ["[[Tasks/example]]"],
    }, "Execute assigned work.")
    vault.write_note(GENERATOR + ".md", {
        "kind": "task", "title": "Generate Runbook", "triggers": ["task.create"],
        "status": "review", "params": {"refinement_case": "case-one"},
    }, "Propose one bounded procedure refinement.")
    state = SimpleNamespace(
        validation_error=None, context_error=None, blocker="Independent evaluation is pending.",
        validations=[], handoffs=[], checks=[], evaluated_sha256=None,
        envelope={"case_ref": "case-one", "runbook_ref": TARGET.removesuffix(".md"),
                  "base_sha256": hashlib.sha256((CONFIG.vault_dir / TARGET).read_bytes()).hexdigest()},
    )

    def proposal_context(context):
        if "refinement_case" not in context.get("params", {}):
            return None
        if state.context_error:
            if isinstance(state.context_error, Exception):
                raise state.context_error
            raise ValueError(state.context_error)
        return deepcopy(state.envelope)

    def validate_candidate(*args):
        state.validations.append(deepcopy(args))
        if state.validation_error:
            raise ValueError(state.validation_error)

    def candidate_staged(staged, context):
        path = Path(staged)
        if not path.is_absolute():
            path = CONFIG.vault_dir / path
        note = vault.load_note(path)
        assert note.meta["refinement"] == state.envelope
        state.handoffs.append((path, context["run_id"], hashlib.sha256(path.read_bytes()).hexdigest()))

    def review_blocker(note, *, accepted_resolver=None):
        if "refinement" not in note.meta:
            return None
        assert vault._NOTE_WRITE_LOCK._is_owned()
        path = CONFIG.vault_dir / note.path
        state.checks.append((path, deepcopy(note.meta), note.body))
        if state.evaluated_sha256 is not None and hashlib.sha256(path.read_bytes()).hexdigest() != state.evaluated_sha256:
            return "The candidate changed after independent evaluation."
        return state.blocker

    monkeypatch.setattr(refinement, "proposal_context", proposal_context)
    monkeypatch.setattr(refinement, "validate_candidate", validate_candidate)
    monkeypatch.setattr(refinement, "candidate_staged", candidate_staged)
    monkeypatch.setattr(refinement, "review_blocker", review_blocker)
    state.context = {"task": GENERATOR, "agent": "Darwin", "run_id": "darwin-run",
                     "event": "task.create", "params": {"refinement_case": "case-one"}}
    return state


def proposal():
    return {"target": TARGET, "action": "update", "title": "Example procedure",
            "body": "Read the complete accepted evidence. Report supported results and unresolved gaps.",
            "reason": "Correct the evidenced incomplete-read procedure.", "metadata": {}}


def test_staging_and_identical_retry_validate_and_handoff_complete_candidate(refinement_review):
    state = refinement_review
    accepted_before = (CONFIG.vault_dir / TARGET).read_bytes()
    first = stage_proposal(proposal(), state.context)
    second = stage_proposal(proposal(), state.context)
    staged = vault.load_note(first["staged"])

    assert len(state.validations) == len(state.handoffs) == 2
    assert state.validations[0][:3] == (TARGET, "update", "Example procedure")
    assert state.validations[0][-1] == state.envelope
    assert second["existing"] is True and Path(second["staged"]) == state.handoffs[0][0]
    assert staged.meta["refinement"] == state.envelope
    assert "refinement" not in staged.meta["authored_fields"]
    assert staged.meta["base_sha256"] == state.envelope["base_sha256"]
    assert state.handoffs[0][2] == state.handoffs[1][2]
    assert (CONFIG.vault_dir / TARGET).read_bytes() == accepted_before


def test_identical_pending_proposal_cannot_bypass_new_validation(refinement_review):
    state = refinement_review
    stage_proposal(proposal(), state.context)
    state.validation_error = "The accepted baseline changed."
    with pytest.raises(ValueError, match="baseline changed"):
        stage_proposal(proposal(), state.context)
    assert len(state.validations) == 2 and len(state.handoffs) == 1


def test_identical_body_cannot_reuse_another_refinement_case(refinement_review):
    state = refinement_review
    stage_proposal(proposal(), state.context)
    state.envelope["case_ref"] = "case-two"
    state.context["params"]["refinement_case"] = "case-two"
    with pytest.raises(ValueError, match="pending review proposal"):
        stage_proposal(proposal(), state.context)
    assert len(state.handoffs) == 1


@pytest.mark.parametrize("field", ["refinement", "evaluation_passed"])
def test_model_cannot_author_refinement_or_evaluation_metadata(refinement_review, field):
    args = proposal()
    args["metadata"][field] = True
    with pytest.raises(ValueError, match="invalid metadata fields"):
        stage_proposal(args, refinement_review.context)
    assert refinement_review.handoffs == []
    assert not list(CONFIG.staging_dir.glob("*.md"))


def test_refinement_completion_requires_exact_staged_update_and_review(refinement_review):
    state = refinement_review
    assert _generated_runbook_completion_error("review", state.context)
    assert _generated_runbook_completion_error("failed", state.context) is None
    result = stage_proposal(proposal(), state.context)
    assert _generated_runbook_completion_error("review", state.context) is None
    assert "must finish" in _generated_runbook_completion_error("completed", state.context)
    staged = vault.load_note(result["staged"])
    vault.write_note(staged.path, {**staged.meta, "refinement": {**state.envelope, "case_ref": "other"}}, staged.body)
    assert _generated_runbook_completion_error("review", state.context)
    assert _generated_runbook_completion_error("failed", state.context) is None


@pytest.mark.parametrize("error", ["The bound case is unavailable.", FileNotFoundError("The bound case is unavailable.")])
def test_invalid_refinement_context_can_finish_with_an_honest_failure(refinement_review, error):
    state = refinement_review
    state.context_error = error
    assert "case is unavailable" in _generated_runbook_completion_error("completed", state.context)
    assert _generated_runbook_completion_error("failed", state.context) is None


def test_auditor_case_binding_is_not_a_generate_runbook_completion(refinement_review):
    state = refinement_review
    state.context_error = "Only Generate Runbook can author a refinement."
    audit = {**state.context, "task": "Tasks/audit", "agent": "Heimdall", "event": "runbook.proposed"}
    assert _generated_runbook_completion_error("completed", audit) is None


def _audit_context():
    return {"task": "Tasks/audit", "agent": "Heimdall", "event": "runbook.proposed",
            "params": {"refinement_case": "case-one", "proposal": "candidate.md"},
            "_harness_evaluation": {"proposal": "candidate.md", "evaluation_report": "report-sha256", "verdict": "passed"}}


def _audit_completion(status, context):
    return _completion_error(SimpleNamespace(ref="Tasks/audit", kind="task", meta={}), status, "", [], context)


@pytest.mark.parametrize("verdict", ["passed", "not_improved", "regressed", "incomplete"])
def test_audit_completion_reports_actual_evaluation_including_negative_findings(verdict):
    context = _audit_context()
    context["_harness_evaluation"]["verdict"] = verdict
    assert _audit_completion("completed", context) is None


@pytest.mark.parametrize("field,value", [
    ("proposal", "other.md"), ("proposal", None), ("evaluation_report", ""),
    ("evaluation_report", "  "), ("evaluation_report", None), ("verdict", "success"), ("verdict", []),
])
def test_audit_cannot_complete_with_incomplete_or_mismatched_evaluation(field, value):
    context = _audit_context()
    context["_harness_evaluation"][field] = value
    assert "actual harness.evaluate result" in _audit_completion("completed", context)
    assert _audit_completion("failed", context) is None


def test_audit_cannot_substitute_model_prose_for_actual_evaluation_or_create_review():
    context = _audit_context()
    context.pop("_harness_evaluation")
    context["params"]["evaluation_report"] = "model-authored-report"
    context["params"]["verdict"] = "passed"
    assert "actual harness.evaluate result" in _audit_completion("completed", context)
    assert "does not stage its own Review" in _audit_completion("review", context)
    assert _audit_completion("failed", context) is None


def test_existing_check_refinement_can_name_only_implicit_completion():
    skills = ["[[Skills/harness.status]]"]
    params = {"output_runbook": "Runbooks/check.md", "skills": skills, "tools": ["Tools/harness.status"]}
    body = """## Prerequisites
One deterministic snapshot is required.
## Ordered Actions
Follow [Using harness.status](/Skills/harness.status.md) and call `harness.status` once.
Then call `task.complete` with the observed finding.
## Bounded Branches
Preserve a degraded finding as degraded.
## Stop Conditions
Stop after the report or an unavailable snapshot.
## Completion Criteria
Report the actual snapshot.
## Verification
Only the actual status Tool attests the finding.
## Recovery
Report failure if the snapshot cannot be obtained.
"""
    with pytest.raises(ValueError, match="Tools outside its selected Skills: task.complete"):
        validate_generated_runbook(params["output_runbook"], body, params, skills)
    validate_generated_runbook(params["output_runbook"], body, params, skills, allow_implicit_completion=True)
    for tool in ("harness.repair", "model.configure", "vault.propose"):
        with pytest.raises(ValueError, match="Tools outside its selected Skills"):
            validate_generated_runbook(params["output_runbook"], body + f"\nCall `{tool}`.\n", params, skills,
                                       allow_implicit_completion=True)
    assert skills == ["[[Skills/harness.status]]"]


@pytest.mark.parametrize("blocker", ["Independent evaluation is pending.", "Baseline reproduction failed.",
                                   "Regression cases failed.", "The evaluator is not independent."])
def test_review_listing_and_direct_approval_share_the_evaluation_blocker(refinement_review, blocker):
    state = refinement_review
    state.blocker = blocker
    result = stage_proposal(proposal(), state.context)
    name = Path(result["staged"]).name
    before = (CONFIG.vault_dir / TARGET).read_bytes()
    row = next(row for row in review.list_proposals() if row["file"] == name)
    assert row["approvable"] is False and row["blocked_reason"] == blocker
    with pytest.raises(ValueError, match=blocker):
        review.approve(name)
    assert len(state.checks) == 2
    assert (CONFIG.vault_dir / TARGET).read_bytes() == before
    assert (CONFIG.staging_dir / name).exists()


@pytest.mark.parametrize("change", ["body", "metadata"])
def test_review_rechecks_current_full_candidate_after_evaluation(refinement_review, change):
    state = refinement_review
    result = stage_proposal(proposal(), state.context)
    staged = vault.load_note(result["staged"])
    state.blocker = None
    state.evaluated_sha256 = state.handoffs[0][2]
    if change == "body":
        vault.write_note(staged.path, staged.meta, staged.body + "A later untested change.\n")
    else:
        vault.write_note(staged.path, {**staged.meta, "title": "Changed title"}, staged.body)
    row = review.list_proposals()[0]
    assert row["approvable"] is False and "changed after" in row["blocked_reason"]
    with pytest.raises(ValueError, match="changed after"):
        review.approve(Path(result["staged"]).name)


def test_passing_evaluation_uses_normal_approval_and_preserves_authority(refinement_review):
    state = refinement_review
    preserved = {ref: (CONFIG.vault_dir / ref).read_bytes()
                 for ref in ("Tasks/example.md", "Agents/Executive/Executive.md")}
    before_meta = vault.load_note(TARGET).meta
    result = stage_proposal(proposal(), state.context)
    state.blocker = None
    state.evaluated_sha256 = state.handoffs[0][2]
    assert review.list_proposals()[0]["approvable"] is True
    assert review.approve(Path(result["staged"]).name)["approved"] == TARGET
    accepted = vault.load_note(TARGET)
    assert accepted.body.strip() == proposal()["body"]
    for key in ("title", "kind", "owner_maintained", "task", "for_agent", "skills"):
        assert accepted.meta[key] == before_meta[key]
    assert "refinement" not in accepted.meta and "event_context" not in accepted.meta
    assert preserved == {ref: (CONFIG.vault_dir / ref).read_bytes() for ref in preserved}


def test_passing_evaluation_cannot_overwrite_a_changed_accepted_baseline(refinement_review):
    state = refinement_review
    result = stage_proposal(proposal(), state.context)
    state.blocker = None
    state.evaluated_sha256 = state.handoffs[0][2]
    accepted = vault.load_note(TARGET)
    vault.write_note(TARGET, accepted.meta, "An independently accepted newer procedure.\n")
    changed = (CONFIG.vault_dir / TARGET).read_bytes()
    row = review.list_proposals()[0]
    assert row["approvable"] is False and "accepted Article changed" in row["blocked_reason"]
    with pytest.raises(ValueError, match="accepted Article changed"):
        review.approve(Path(result["staged"]).name)
    assert (CONFIG.vault_dir / TARGET).read_bytes() == changed


def test_regular_proposal_keeps_ordinary_review_without_evaluation(refinement_review):
    context = {"task": "Tasks/improve", "agent": "Alexandria", "run_id": "ordinary"}
    vault.write_note("Knowledge/example.md", {"kind": "knowledge", "title": "Example"}, "An accepted fact.")
    result = stage_proposal({"target": "Knowledge/example.md", "action": "update", "title": "Example",
                             "body": "A corrected accepted fact.", "reason": "Exact source evidence."}, context)
    assert review.list_proposals()[0]["approvable"] is True
    assert review.approve(Path(result["staged"]).name)["approved"] == "Knowledge/example.md"
    assert refinement_review.handoffs == refinement_review.validations == []

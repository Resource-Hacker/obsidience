from __future__ import annotations

import json
import pytest

from obsidience.harness.capabilities.harness import status
from obsidience.harness.capabilities.review import inspect as review_inspect
from obsidience.harness.capabilities.task import inspect as task_inspect
from obsidience.harness.capabilities.vault import maintenance
from obsidience.harness.config import CONFIG
from obsidience.harness.execution import repair, scheduler
from obsidience.harness.knowledge import index, review, source, vault


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(CONFIG, "vault_dir", tmp_path / "vault")
    monkeypatch.setattr(CONFIG, "db_path", tmp_path / "index.sqlite3")
    monkeypatch.setattr(CONFIG, "git_commit", False)
    monkeypatch.setattr(maintenance, "_completed_candidates", lambda: set())
    ledger = index.Index()
    monkeypatch.setattr(index, "INDEX", ledger)
    monkeypatch.setattr(repair, "INDEX", ledger)
    monkeypatch.setattr(scheduler, "INDEX", ledger)
    yield ledger
    ledger.db.close()


def note(ref, body="One ordinary accepted fact.", **meta):
    vault.write_note(ref + ".md", {"kind": "knowledge", "title": ref.rsplit("/", 1)[-1], **meta}, body)


def lead(kind):
    return next(row for row in maintenance._maintenance_candidates()["candidates"] if row["kind"] == kind)


@pytest.mark.parametrize("change", ["body", "metadata"])
def test_unchanged_no_change_is_suppressed_but_revision_change_reopens(isolated, monkeypatch, change):
    note("Articles/one", "Broken [[Articles/missing]].")
    candidate = lead("broken_reference")
    previous = {("Tasks/improve", candidate["candidate_key"], candidate["candidate_revision"])}
    monkeypatch.setattr(maintenance, "_completed_candidates", lambda: previous)
    assert maintenance._maintenance_candidates()["candidates"] == []
    assert maintenance._maintenance_candidates()["unchanged_no_change_count"] == 1
    if change == "body":
        note("Articles/one", "Changed but still broken [[Articles/missing]].")
    else:
        note("Articles/one", "Broken [[Articles/missing]].", retrieval=False)
    assert lead("broken_reference")["candidate_revision"] != candidate["candidate_revision"]


def test_missing_index_is_a_bounded_lead_but_native_parent_needs_no_child_links(isolated):
    for number in range(12):
        note(f"Articles/entry{number}")
    candidate = lead("missing_index")
    assert candidate["recommended_task"] == "Improve"
    assert len(candidate["refs"]) == 8
    assert candidate["signals"]["index_ref"] == "Articles/Articles"
    note("Articles/Articles", "A condensation of this subject. Native hierarchy lists its entries.")
    assert maintenance._maintenance_candidates()["candidates"] == []
    note("Articles/Articles", "Summary of [[Articles/entry0]].")
    assert maintenance._maintenance_candidates()["candidates"] == []
    note("Articles/Articles", "Subject context refers to [[Articles/missing]].")
    candidate = lead("broken_reference")
    assert candidate["refs"] == ["Articles/Articles"]
    assert candidate["signals"]["missing_refs"] == ["Articles/missing"]


def test_old_coverage_invalidates_at_unchanged_revision_without_invalidating_other_work(isolated):
    note("Articles/Articles", "Subject condensation.")
    note("Articles/one")
    refs = ["Articles/Articles", "Articles/one"]
    res = vault.resolver()
    revision = maintenance.candidate_revision([res.resolve(ref) for ref in refs])
    params = {"candidate_kind": "index_coverage", "candidate_key": "old-coverage",
              "candidate_refs": refs, "candidate_revision": revision}
    result = maintenance.candidate_invalidation("Tasks/improve", params, res)
    assert result["reason"] == "native_hierarchy_coverage"
    assert result["expected_revision"] == result["current_revision"] == revision
    assert maintenance.candidate_invalidation("Tasks/link", params, res) is None
    assert maintenance.candidate_invalidation("Tasks/improve", {**params, "candidate_kind": "broken_reference"}, res) is None
    assert maintenance.candidate_invalidation("Tasks/improve", {**params, "candidate_revision": "invalid"}, res) is None


def test_age_alone_never_creates_freshness_or_archive_lead(isolated):
    note("Articles/old", approved_at="2001-01-01")
    assert maintenance._maintenance_candidates()["candidates"] == []
    note("Articles/old", review_due="2001-01-01")
    assert lead("review_due")["recommended_task"] == "Audit"
    note("Articles/new")
    note("Articles/old", superseded_by="Articles/new")
    assert lead("superseded")["signals"]["archive_ref"] == "Articles/old"


def test_runtime_observations_never_create_editorial_leads(isolated):
    note("Observations/one", "Broken [[missing]].", temporary=True, review_due="2001-01-01")
    note("Observations/two", "Broken [[missing]].", immediate=True)
    assert maintenance._maintenance_candidates()["candidates"] == []


@pytest.mark.parametrize("task_state,schedule", [("failed", None), ("blocked", None), ("draft", "0 * * * *")])
def test_health_reports_current_task_blockage(isolated, monkeypatch, task_state, schedule):
    note("Tasks/link", kind="task", status=task_state, schedule=schedule,
         event_queue=[{"event": "task.create"}])
    monkeypatch.setattr(review, "list_proposals", lambda: [])
    monkeypatch.setattr(source, "list_source_files", lambda: {"files": [], "issues": []})
    result = json.loads(status.execute({}, {}))
    assert result["status"] == "degraded"
    assert result["task_issues"][0]["queued"] == 1
    assert result["task_issue_count"] == 1


def test_historical_failure_does_not_mark_recovered_task_unhealthy(isolated, monkeypatch):
    note("Tasks/link", kind="task", status="completed")
    monkeypatch.setattr(review, "list_proposals", lambda: [])
    monkeypatch.setattr(source, "list_source_files", lambda: {"files": [], "issues": []})
    monkeypatch.setattr(isolated, "runs", lambda limit: [{"status": "failed"}])
    result = json.loads(status.execute({}, {}))
    assert result["status"] == "healthy"
    assert result["recent_failures"] == 1


def record(ledger, run_id, task_ref="Tasks/link", trace="[]"):
    ledger.record_run(id=run_id, task_ref=task_ref, agent="Alexandria", started=1, finished=2,
                      status="failed", summary="Observed failure.", trace=trace)


def test_task_inspection_exact_run_is_scoped_and_hides_prompt(isolated):
    note("Tasks/link", kind="task", status="failed")
    trace = json.dumps([{"activation_packet": "private prompt"},
                        {"tool": "vault.validate", "args": {}, "obs": "invalid edge"}])
    record(isolated, "wanted", trace=trace)
    record(isolated, "other", task_ref="Tasks/merge")
    result = json.loads(task_inspect.execute({"task": "Tasks/link", "run_id": "wanted"}, {}))
    assert result["runs"][0]["tool_evidence"][0]["result"] == "invalid edge"
    assert "private prompt" not in json.dumps(result)
    result = json.loads(task_inspect.execute({"task": "Tasks/link", "run_id": "other"}, {}))
    assert result["requested_run_missing"] is True
    assert result["runs"] == []


def test_task_inspection_reports_invalid_trace_without_guessing(isolated):
    note("Tasks/link", kind="task")
    record(isolated, "truncated", trace='[{"tool":')
    result = json.loads(task_inspect.execute({"task": "Tasks/link", "run_id": "truncated"}, {}))
    assert result["runs"][0]["tool_evidence"] == []
    assert "invalid" in result["runs"][0]["evidence_error"]


def test_review_inspection_is_pending_only_and_bounded(isolated, monkeypatch):
    note("Tasks/link", kind="task")
    rows = [{"file": f"proposal-{n}.md", "task": "Tasks/link", "target": "Articles/one.md",
             "body_preview": "x" * 3000, "approvable": False, "blocked_reason": "stale"} for n in range(10)]
    monkeypatch.setattr(review, "list_proposals", lambda: rows)
    result = json.loads(review_inspect.execute({"task": "Tasks/link"}, {}))
    assert result["count"] == 10 and len(result["pending"]) == 8 and result["truncated"]
    result = json.loads(review_inspect.execute({"proposal": "proposal-1.md"}, {}))
    assert len(result["pending"]) == 1
    assert result["pending"][0]["body_truncated"]
    assert result["pending"][0]["blocked_reason"] == "stale"

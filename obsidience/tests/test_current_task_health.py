"""Task health and native execution projection share current-issue semantics."""
import json
from importlib import import_module
from types import SimpleNamespace as NS

import pytest

from obsidience.harness.capabilities.harness import status as health
from obsidience.harness.config import CONFIG
from obsidience.harness.execution import ledger as execution_ledger
from obsidience.harness.knowledge import review, source, vault

api = import_module("obsidience.harness.interfaces.api.app")


@pytest.fixture
def projected(tmp_path, monkeypatch, isolated_task_ledger):
    monkeypatch.setattr(CONFIG, "vault_dir", tmp_path / "vault")
    monkeypatch.setattr(review, "list_proposals", lambda: [])
    monkeypatch.setattr(source, "list_source_files", lambda: {"files": [], "issues": []})
    monkeypatch.setattr(isolated_task_ledger, "graph", lambda: {"nodes": [], "links": []})
    monkeypatch.setattr(api.scheduler, "_realtime_allows", lambda *_args: True)
    monkeypatch.setattr(api.scheduler, "_resource_error", lambda *_args: None)
    return isolated_task_ledger


def task(ledger, ref="Tasks/check", **runtime):
    vault.write_note(ref + ".md", {"kind": "task", "title": ref.rsplit("/", 1)[-1],
                     "status": "failed", "last_run": "old-run", "summary": "Historical degraded snapshot.",
                     "blocked_reason": "Historical provider failure", **runtime}, "Inspect or maintain the requested scope.")
    ledger.record_run(id="old-run", task_ref=ref, agent="fixture", started=1., finished=2., status="failed",
                      summary="Historical provider failure", trace='[{"invalid":"old reply"}]')
    return vault.load_note(ref + ".md")


@pytest.mark.parametrize("ref,runtime,kind,execution_state", [
    ("Tasks/check", {"schedule": "30 */6 * * *"}, None, "idle"),
    ("Tasks/link", {}, None, "idle"),
    ("Tasks/check", {"params": {"request": "Inspect this once"}}, None, "idle"),
    ("Tasks/link", {"event_queue": [{"event": "task.create", "activation_key": "later"}]}, "unresolved_occurrence", "needs_attention"),
    ("Tasks/check", {"event_queue": [{"event": "task.create"}]}, "unresolved_occurrence", "needs_attention"),
    ("Tasks/link", {"params": {"event": "task.create", "activation_key": "active"}}, "unresolved_occurrence", "needs_attention"),
    ("Tasks/link", {"status": "blocked"}, "blocked_configuration", "needs_attention"),
    ("Tasks/link", {"status": "blocked", "event_queue": [{"event": "task.create"}]}, "unresolved_occurrence", "needs_attention"),
    ("Tasks/check", {"status": "draft", "schedule": "30 */6 * * *"}, "scheduled_draft", "needs_attention"),
    ("Tasks/check", {"status": "draft"}, None, "idle"),
    ("Tasks/check", {"status": "running"}, None, "running"),
    ("Tasks/link", {"status": "review"}, None, "review"),
    ("Tasks/link", {"status": "pending", "params": {"event": "task.create", "activation_key": "active"}}, None, "ready"),
    ("Tasks/link", {"status": "completed", "params": {"event": "task.create", "activation_key": "done"}}, None, "idle"),
])
def test_health_and_execution_agree_without_rewriting_history(projected, ref, runtime, kind, execution_state):
    note = task(projected, ref, **runtime)
    before_run = projected.run("old-run")
    before_state = projected.task_runtime(ref)
    before_bytes = (CONFIG.vault_dir / note.path).read_bytes()
    report = json.loads(health.execute({}, {}))
    execution = api.task_execution_state(note, NS())
    assert execution["state"] == execution_state
    assert execution["last_run"]["status"] == "failed"
    assert report["recent_failures"] == 1
    assert report["tasks_by_status"][note.meta["status"]] == 1
    if kind:
        assert report["status"] == "degraded" and report["task_issue_count"] == 1
        issue = report["task_issues"][0]
        assert issue["task"] == ref and issue["kind"] == kind
        assert issue["reason"] == execution["reason"]
        assert issue["queued"] == len(runtime.get("event_queue", []))
    else:
        assert report["status"] == "healthy" and report["task_issue_count"] == 0
        assert report["task_issues"] == []
    assert projected.run("old-run") == before_run
    assert projected.task_runtime(ref) == before_state
    assert (CONFIG.vault_dir / note.path).read_bytes() == before_bytes


def test_failed_fifo_without_active_params_stays_visible_but_cannot_blind_retry(projected):
    note = task(projected, "Tasks/link", event_queue=[{"event": "task.create", "activation_key": "later"}])
    execution = api.task_execution_state(note, NS())
    assert execution["state"] == "needs_attention"
    assert execution["retry_allowed"] is False
    assert "no exact durable event identity" in execution["retry_blocked_reason"]
    assert projected.task_runtime(note.ref)["event_queue"] == note.meta["event_queue"]


def test_real_source_issue_still_degrades_idle_historical_check(projected, monkeypatch):
    note = task(projected, schedule="30 */6 * * *")
    monkeypatch.setattr(source, "list_source_files", lambda: {"files": [], "issues": ["Unattested Source"]})
    report = json.loads(health.execute({}, {}))
    assert api.task_execution_state(note, NS())["state"] == "idle"
    assert report["status"] == "degraded" and report["source_issues"] == 1
    assert report["task_issue_count"] == 0 and report["recent_failures"] == 1


def test_recurring_historical_findings_do_not_latch_current_health(projected, monkeypatch):
    now = 2_000_000.
    monkeypatch.setattr(execution_ledger.time, "time", lambda: now)
    task(projected, status="completed")
    for number in range(3):
        projected.record_run(id=f"failed-{number}", task_ref="Tasks/check", agent="fixture",
                             started=now - 10, finished=now - 1, status="failed", summary="Prior failure",
                             trace="[]", runbook_ref="Runbooks/check", runbook_sha256="a" * 64)
    before = projected.task_runtime("Tasks/check")
    report = json.loads(health.execute({}, {}))
    assert report["status"] == "healthy" and report["task_issues"] == []
    assert len(report["history"]["findings"]) == 1
    assert report["history"]["findings"][0]["failure_count"] == 3
    assert projected.task_runtime("Tasks/check") == before

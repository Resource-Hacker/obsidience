"""Retired research keeps documentary origin without new execution authority."""
from copy import deepcopy

import pytest

from obsidience.harness import config
from obsidience.harness.execution import scheduler
from obsidience.harness.knowledge import source, vault


@pytest.fixture
def retired_origin(monkeypatch, tmp_path, isolated_task_ledger):
    index = isolated_task_ledger
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config.CONFIG, "vault_dir", tmp_path / "obsidience/vault")
    monkeypatch.setattr(config.CONFIG, "git_commit", False)
    events = []

    def enqueue(event, params, **_kwargs):
        events.append(deepcopy(params))
        index.mark_source_event_dispatched(params["source_id"], 1.0)
        return []

    monkeypatch.setattr(scheduler, "enqueue_named_event", enqueue)
    task_ref = "Tasks/research/retired-publisher"
    task_meta = {"kind": "task", "title": "Retired publisher",
                 "assignee": "[[Agents/Darwin/Darwin]]"}
    vault.write_note(task_ref + ".md", task_meta, "Former research procedure.")
    index.record_run(id="former-run", task_ref=task_ref, agent="Darwin", started=1.0,
                     finished=2.0, status="completed", summary="Original delivery.", trace="[]")
    raw = source.ingest_source(source_type="document", source_ref="Publisher record",
                               media_type="text/plain", captured_at="2026-09-09T10:00:00Z",
                               content="Original reporting evidence.")
    handoff = source.handoff_source(title="Original finding", content="Finding: " + raw["citation"],
                                    research_task=task_ref, research_run_id="former-run")
    params = events[-1]
    archived_meta = {**task_meta, "article_status": "deprecated", "archived_from": task_ref,
                     "enabled": False}
    vault.write_note("_archived/" + task_ref + ".md", archived_meta, "Former research procedure.")
    (config.CONFIG.vault_dir / (task_ref + ".md")).unlink()
    return index, params, handoff, task_ref, archived_meta


def test_retired_task_keeps_exact_read_only_inbox_origin(retired_origin):
    index, params, handoff, task_ref, _meta = retired_origin
    original = dict(index.source(handoff["id"]))
    assert source.research_handoff_origin(params) == {
        "research_task": task_ref, "research_run_id": "former-run"}
    assert source._research_owner(task_ref, "former-run") is False
    with pytest.raises(source.SourceError, match="exact Darwin research execution"):
        source.handoff_source(title="New output", content=source.get_source(handoff["citation"])["content"],
                              research_task=task_ref, research_run_id="former-run")
    assert dict(index.source(handoff["id"])) == original


@pytest.mark.parametrize("fault", ["kind", "lifecycle", "origin", "assignee", "run_task",
                                  "run_agent", "missing_run", "hash", "event", "params"])
def test_archived_origin_requires_definition_run_and_source_attestation(retired_origin, fault):
    index, params, _handoff, task_ref, meta = retired_origin
    if fault in {"kind", "lifecycle", "origin", "assignee"}:
        key, value = {"kind": ("kind", "knowledge"), "lifecycle": ("article_status", "stable"),
                      "origin": ("archived_from", "Tasks/research/other"),
                      "assignee": ("assignee", "[[Agents/Alexandria/Alexandria]]")}[fault]
        vault.write_note("_archived/" + task_ref + ".md", {**meta, key: value}, "Archived definition.")
    elif fault in {"run_task", "run_agent"}:
        field = "task_ref" if fault == "run_task" else "agent"
        index.db.execute(f"UPDATE runs SET {field}=? WHERE id=?", ("other", "former-run"))
    elif fault == "missing_run":
        index.db.execute("DELETE FROM runs WHERE id=?", ("former-run",))
    elif fault == "hash":
        params["source_sha256"] = "sha256:" + "0" * 64
    elif fault == "event":
        params["activation_key"] += "changed"
    else:
        params["research_run_id"] = "other-run"
    assert source.research_handoff_origin(params) is None

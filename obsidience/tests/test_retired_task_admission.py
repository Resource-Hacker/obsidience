"""Retained Task history cannot regain execution authority by path or title."""
import asyncio

import pytest
from fastapi import HTTPException

from obsidience.harness.config import CONFIG
from obsidience.harness.execution import executor
from obsidience.harness.interfaces.api import app
from obsidience.harness.knowledge.vault import load_note, write_note


@pytest.mark.parametrize("ref", ["Tasks/research/news", "_archived/Tasks/research/news", "News"])
def test_run_api_rejects_retired_task_by_exact_path_and_title(tmp_path, monkeypatch, isolated_task_ledger, ref):
    monkeypatch.setattr(CONFIG, "vault_dir", tmp_path / "vault")
    write_note("_archived/Tasks/research/news.md", {"kind": "task", "title": "News",
        "article_status": "deprecated", "archived_from": "Tasks/research/news"}, "Retained history.")
    with pytest.raises(HTTPException) as rejected:
        asyncio.run(app.run_now(ref))
    assert rejected.value.status_code == 404
    assert isolated_task_ledger.task_runtime("_archived/Tasks/research/news") is None


@pytest.mark.parametrize("path,meta", [
    ("_archived/Tasks/research/news.md", {}),
    ("_staging/proposed.md", {}),
    ("Tasks/retired.md", {"article_status": "deprecated"}),
])
def test_executor_rejects_inactive_definition_before_spine_or_claim(tmp_path, monkeypatch, isolated_task_ledger, path, meta):
    monkeypatch.setattr(CONFIG, "vault_dir", tmp_path / "vault")
    write_note(path, {"kind": "task", "title": "Retired", **meta}, "History.")
    task = load_note(path)
    monkeypatch.setattr(executor, "resolve_spine", lambda *_: pytest.fail("Inactive Task reached activation"))
    result = asyncio.run(executor.run_task(task))
    assert result["status"] == "blocked"
    assert isolated_task_ledger.task_runtime(task.ref) is None

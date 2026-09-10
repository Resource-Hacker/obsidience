from pathlib import Path

import pytest

from obsidience.harness.config import CONFIG
from obsidience.harness.knowledge import format as codec
from obsidience.harness.knowledge.links import body_links
from obsidience.harness.knowledge.vault import load_note, write_note
from obsidience.scripts.migrate_okf import apply, prepare


@pytest.fixture
def migration_vault(tmp_path, monkeypatch):
    project = tmp_path / "project"
    vault = project / "vault"
    vault.mkdir(parents=True)
    monkeypatch.setattr(CONFIG, "vault_dir", vault)
    return project, vault


def legacy(vault: Path, ref: str, meta: dict | None = None, body: str = "Article.\n") -> Path:
    path = vault / (ref + ".md")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(codec.serialize(meta or {"kind": "knowledge"}, body), encoding="utf-8")
    return path


def test_preview_is_read_only_and_rewrites_exact_hubs_and_unique_titles(migration_vault, isolated_task_ledger):
    project, vault = migration_vault
    hub = legacy(vault, "Knowledge/index", {"kind": "knowledge", "title": "Knowledge"})
    target = legacy(vault, "Knowledge/Subject Name", {"kind": "knowledge", "title": "Subject title"})
    child = legacy(vault, "Knowledge/Child", {
        "kind": "knowledge", "parent": "[[Knowledge/index#Overview|Parent]]",
        "foreign_extension": {"revision": 3},
    }, "See [[Knowledge/index|Parent]], [[Subject title]], and [relative](./Subject%20Name.md).\n")
    before = {path: path.read_bytes() for path in (hub, target, child)}

    changes, renames = prepare(vault, project)

    assert renames == {"Knowledge/index": "Knowledge/Knowledge"}
    assert {path: path.read_bytes() for path in before} == before
    assert isolated_task_ledger.task_runtime("Tasks/query") is None
    converted = next(item for item in changes if item.old == child)
    raw, body = codec.parse(converted.after)
    assert raw["obsidience"]["parent"] == "[[Knowledge/Knowledge#Overview|Parent]]"
    assert raw["foreign_extension"] == {"revision": 3}
    assert body_links(body, "Knowledge/Child.md") == ["Knowledge/Knowledge", "Knowledge/Subject Name"]
    assert "[relative](/Knowledge/Subject%20Name.md)" in body


def test_apply_preserves_task_state_model_effort_and_is_idempotent(migration_vault, isolated_task_ledger):
    project, vault = migration_vault
    legacy(vault, "Knowledge/index", {"kind": "knowledge", "title": "Knowledge"})
    legacy_state = {
        "status": "queued", "params": {"query": "pending"},
        "event_queue": [{"event": "task.create", "key": "one"}],
        "last_run": "previous-run", "summary": "Previous result",
        "generated_runbook": "Runbooks/answer",
    }
    legacy(vault, "Tasks/query", {
        "kind": "task", "title": "Query", "model": "obsidience-gemma",
        "reasoning_effort": "high", **legacy_state,
    }, "Answer the question using [[Knowledge/index]].\n")

    changes, _ = prepare(vault, project)
    apply(changes, vault, isolated_task_ledger)

    assert not (vault / "Knowledge/index.md").exists()
    assert (vault / "Knowledge/Knowledge.md").is_file()
    raw, _ = codec.parse((vault / "Tasks/query.md").read_text())
    assert raw["type"] == "task"
    assert codec.TASK_RUNTIME_FIELDS.isdisjoint(raw)
    assert codec.TASK_RUNTIME_FIELDS.isdisjoint(raw["obsidience"])
    assert raw["obsidience"]["model"] == "obsidience-gemma"
    assert raw["obsidience"]["reasoning_effort"] == "high"
    assert isolated_task_ledger.task_runtime("Tasks/query") == legacy_state
    assert load_note("Tasks/query.md").meta["status"] == "queued"

    isolated_task_ledger.mutate_task_runtime("Tasks/query", lambda state: state.update(status="running", last_run="newer-run"))
    before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in vault.rglob("*.md")}
    repeated, renames = prepare(vault, project)
    assert renames == {}
    assert all(item.before == item.after and item.old == item.new for item in repeated)
    apply(repeated, vault, isolated_task_ledger)
    assert {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in before} == before
    assert isolated_task_ledger.task_runtime("Tasks/query")["last_run"] == "newer-run"


def test_existing_task_runtime_wins_over_legacy_markdown(migration_vault, isolated_task_ledger):
    project, vault = migration_vault
    legacy(vault, "Tasks/query", {"kind": "task", "status": "draft", "last_run": "stale"})
    current = {"status": "queued", "last_run": "current", "event_queue": [{"key": "pending"}]}
    isolated_task_ledger.seed_task_runtime("Tasks/query", current)
    changes, _ = prepare(vault, project)
    apply(changes, vault, isolated_task_ledger)
    assert isolated_task_ledger.task_runtime("Tasks/query") == current


def test_renamed_task_keeps_existing_runtime_at_its_new_exact_ref(migration_vault, isolated_task_ledger):
    project, vault = migration_vault
    legacy(vault, "Tasks/Group/index", {"kind": "task", "title": "Group", "status": "draft"})
    current = {"status": "queued", "last_run": "current", "event_queue": [{"key": "pending"}]}
    isolated_task_ledger.seed_task_runtime("Tasks/Group/index", current)
    changes, _ = prepare(vault, project)
    apply(changes, vault, isolated_task_ledger)
    assert isolated_task_ledger.task_runtime("Tasks/Group/Group") == current
    assert isolated_task_ledger.task_runtime("Tasks/Group/index") is None


@pytest.mark.parametrize("folder", ["raw", "_staging", "_archived", ".reader"])
def test_nonarticle_and_immutable_storage_remains_byte_identical(migration_vault, isolated_task_ledger, folder):
    project, vault = migration_vault
    protected = legacy(vault, f"{folder}/evidence", {"kind": "knowledge", "status": "verified"}, "Exact source bytes.\n")
    outside = project / "outside-evidence.md"
    outside.write_text("Outside Vault.\n")
    accepted = legacy(vault, "Knowledge/example")
    before = {path: path.read_bytes() for path in (protected, outside)}
    changes, _ = prepare(vault, project)
    assert [item.old for item in changes] == [accepted]
    apply(changes, vault, isolated_task_ledger)
    assert {path: path.read_bytes() for path in before} == before


def test_existing_destination_collision_fails_preview_without_mutation(migration_vault):
    project, vault = migration_vault
    old = legacy(vault, "Knowledge/index")
    occupied = legacy(vault, "Knowledge/Knowledge", body="Existing independent Article.\n")
    before = {path: path.read_bytes() for path in (old, occupied)}
    with pytest.raises(ValueError, match="collision"):
        prepare(vault, project)
    assert {path: path.read_bytes() for path in before} == before


def test_destination_created_after_preview_is_not_overwritten(migration_vault, isolated_task_ledger):
    project, vault = migration_vault
    old = legacy(vault, "Knowledge/index")
    changes, _ = prepare(vault, project)
    occupied = legacy(vault, "Knowledge/Knowledge", body="New owner-authored Article.\n")
    before = {path: path.read_bytes() for path in (old, occupied)}
    with pytest.raises(ValueError, match="collision|changed|destination"):
        apply(changes, vault, isolated_task_ledger)
    assert {path: path.read_bytes() for path in before} == before


def test_changed_source_aborts_before_any_write_or_task_seed(migration_vault, isolated_task_ledger):
    project, vault = migration_vault
    old = legacy(vault, "Knowledge/index")
    task = legacy(vault, "Tasks/query", {"kind": "task", "status": "queued"})
    changes, _ = prepare(vault, project)
    task.write_text(task.read_text() + "Changed since preview.\n")
    before = {path: path.read_bytes() for path in (old, task)}
    with pytest.raises(ValueError, match="changed since preview"):
        apply(changes, vault, isolated_task_ledger)
    assert {path: path.read_bytes() for path in before} == before
    assert isolated_task_ledger.task_runtime("Tasks/query") is None


@pytest.mark.parametrize("body", [
    "```markdown\n[[Knowledge/index]]\n```\n",
    "~~~markdown\n[[Knowledge/index]]\n~~~\n",
    "`[[Knowledge/index]]`\n",
    "    [[Knowledge/index]]\n",
    "  ```markdown\n  [[Knowledge/index]]\n  ```\n",
    "``Example ` [[Knowledge/index]]``\n",
])
def test_migration_preserves_commonmark_code_examples_exactly(migration_vault, body):
    project, vault = migration_vault
    legacy(vault, "Knowledge/index")
    example = legacy(vault, "Knowledge/Example", body=body)
    changes, _ = prepare(vault, project)
    converted = next(item for item in changes if item.old == example)
    assert codec.parse(converted.after)[1] == body
    assert body_links(body, "Knowledge/Example.md") == []


def test_wikilink_heading_with_spaces_remains_a_real_markdown_link(migration_vault):
    project, vault = migration_vault
    legacy(vault, "Knowledge/index")
    child = legacy(vault, "Knowledge/Child", body="[[Knowledge/index#Long heading|Parent]]\n")
    changes, _ = prepare(vault, project)
    body = codec.parse(next(item.after for item in changes if item.old == child))[1]
    assert body_links(body, "Knowledge/Child.md") == ["Knowledge/Knowledge"]
    assert "#Long%20heading" in body


def test_canonical_article_read_write_retains_foreign_metadata_and_runtime_separation(migration_vault, isolated_task_ledger):
    _project, vault = migration_vault
    raw = {
        "type": "task", "title": "Query", "status": "stable",
        "verified": {"by": "human:foreign", "at": "2026-09-04T10:00:00Z"},
        "foreign": {"value": [1, 2]}, "obsidience": {"model": "obsidience-gemma", "reasoning_effort": "high"},
    }
    legacy(vault, "Tasks/query", raw)
    isolated_task_ledger.seed_task_runtime("Tasks/query", {"status": "queued", "last_run": "current"})
    note = load_note("Tasks/query.md")
    assert note.meta["article_status"] == "stable"
    assert note.meta["status"] == "queued"
    assert "trust" not in note.meta
    write_note(note.path, note.meta, note.body)
    assert codec.parse((vault / note.path).read_text())[0] == raw
    assert isolated_task_ledger.task_runtime("Tasks/query")["status"] == "queued"

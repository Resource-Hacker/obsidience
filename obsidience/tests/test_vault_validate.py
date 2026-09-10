from pathlib import Path

import pytest

from obsidience.harness.capabilities import registry
from obsidience.harness.capabilities.vault.validate import execute
from obsidience.harness.config import CONFIG
from obsidience.harness.knowledge import index
from obsidience.harness.knowledge.format import parse, serialize
from obsidience.harness.knowledge.vault import write_note


@pytest.fixture
def validation_vault(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(CONFIG, "vault_dir", tmp_path)
    monkeypatch.setattr(CONFIG, "db_path", tmp_path / "index.sqlite3")
    ledger = index.Index()
    monkeypatch.setattr(index, "INDEX", ledger)
    monkeypatch.setattr(registry, "REGISTRY", ("vault.read",))
    for name in ("Darwin", "Alexandria"):
        write_note(f"Agents/{name}/{name}.md", {"kind": "agent", "title": name}, "Agent.")
    for task, agent, trigger in (
        ("research/learn", "Darwin", "source.added"),
        ("research/distill", "Darwin", "source.added"),
        ("ingest", "Alexandria", "source.inbox"),
    ):
        write_note(f"Tasks/{task}.md", {
            "kind": "task", "assignee": f"[[Agents/{agent}/{agent}]]", "triggers": [trigger],
        }, "Complete the requested outcome.")
    write_note("Tools/vault.read.md", {
        "kind": "tool", "title": "vault.read", "binding": registry.binding("vault.read"),
        "source": registry.source("vault.read"),
        "sources": [{"resource": "https://example.org/provenance", "title": "Supporting docs"}],
    }, "Read accepted knowledge.")
    write_note("Skills/vault.read.md", {
        "kind": "skill", "title": "Using vault.read", "tool": "[[Tools/vault.read]]",
    }, "Supply the exact Article reference.")
    yield tmp_path
    ledger.db.close()


def test_standard_tool_provenance_does_not_replace_or_conflict_with_binding(validation_vault):
    report = execute({}, {})
    assert "No broken references" in report
    raw, _ = parse((validation_vault / "Tools/vault.read.md").read_text())
    assert raw["sources"] == [{"resource": "https://example.org/provenance", "title": "Supporting docs"}]
    assert raw["obsidience"]["source"] == registry.source("vault.read")


def test_provenance_cannot_supply_the_executable_source(validation_vault):
    write_note("Tools/vault.read.md", {
        "kind": "tool", "title": "vault.read", "binding": registry.binding("vault.read"),
        "sources": [{"resource": registry.source("vault.read")}],
    }, "Provenance alone is not an executable binding.")
    report = execute({}, {})
    assert "Capability contract: source must be the singular path" in report
    assert "No broken references" not in report


def test_existing_pairing_and_reference_checks_still_run(validation_vault):
    write_note("Skills/vault.read.md", {"kind": "skill", "tool": "[[Tools/missing]]"}, "Bad pairing.")
    write_note("Runbooks/example.md", {
        "kind": "runbook", "skills": ["[[Skills/missing]]"], "tools": ["[[Tools/vault.read]]"],
    }, "Invalid authority.")
    report = execute({}, {})
    assert "(unresolved)" in report
    assert "direct Tool grants are not allowed" in report
    assert "expected leaf tool, got unresolved" in report
    assert "paired Skill: expected 1, found 0" in report


@pytest.mark.parametrize("raw, expected", [
    ({"kind": "knowledge"}, "kind is an internal alias"),
    ({"type": "knowledge", "model": "obsidience-gemma"}, "model belongs under obsidience"),
    ({"type": "task", "obsidience": {"status": "running"}}, "Task execution state"),
    ({"type": "knowledge", "obsidience": []}, "obsidience must be a mapping"),
    ({"type": "foreign-concept"}, "type must be one of"),
    ({"type": "knowledge", "sources": ["legacy string"]}, "sources[0] must be a mapping"),
])
def test_profile_checks_persisted_metadata_before_runtime_projection(validation_vault, raw, expected):
    path = validation_vault / "example.md"
    path.write_text(serialize(raw, "Invalid profile fixture.\n"))
    original = path.read_bytes()
    report = execute({}, {})
    assert "OKF profile" in report
    assert expected in report
    assert path.read_bytes() == original


@pytest.mark.parametrize("text", ["---\ntype: knowledge\n", "---\n- scalar-list\n---\n",
                                  "---\nvalue: !!python/object/apply:builtins.str [unsafe]\n---\n"])
def test_malformed_yaml_is_reported_instead_of_crashing(validation_vault, text):
    (validation_vault / "malformed.md").write_text(text)
    report = execute({}, {})
    assert "[[malformed]] OKF profile:" in report


def test_navigation_and_history_are_excluded_but_reserved_article_names_are_reported(validation_vault):
    (validation_vault / "index.md").write_text("---\nokf_version: '0.2'\n---\n\n# Bundle\n")
    (validation_vault / "log.md").write_text("# Updates\n\n## 2026-09-04\n- Initialized.\n")
    assert "No broken references" in execute({}, {})
    (validation_vault / "index.md").write_text(serialize({"type": "knowledge"}, "Misplaced Article.\n"))
    assert "reserved OKF documents" in execute({}, {})


@pytest.mark.parametrize("folder", ["raw", "_staging", "_archived", ".reader"])
def test_profile_preflight_excludes_nonaccepted_storage(validation_vault, folder):
    directory = validation_vault / folder
    directory.mkdir()
    # A generic but non-Article document is allowed outside accepted scope.
    (directory / "foreign.md").write_text(serialize({"type": "foreign"}, "Not accepted.\n"))
    assert "No broken references" in execute({}, {})


def test_reserved_source_split_rejects_foreign_subscriber_and_wrong_owner(validation_vault):
    write_note("Tasks/unrelated.md", {"kind": "task", "triggers": ["source.added"],
               "assignee": "[[Agents/Darwin/Darwin]]"}, "Unrelated.")
    assert "source.added subscribers" in execute({}, {})
    (validation_vault / "Tasks/unrelated.md").unlink()
    write_note("Tasks/research/distill.md", {"kind": "task", "triggers": ["source.added"],
               "assignee": "[[Agents/Alexandria/Alexandria]]"}, "Wrong owner.")
    assert "[[Tasks/research/distill]] assignee: expected [[Agents/Darwin/Darwin]]" in execute({}, {})

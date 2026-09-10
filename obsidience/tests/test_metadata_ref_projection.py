from types import SimpleNamespace

import pytest

from obsidience.harness.config import CONFIG
from obsidience.harness.interfaces.api import app as api_app
from obsidience.harness.knowledge import index, vault
from obsidience.harness.knowledge.links import metadata_ref


@pytest.mark.parametrize(("raw", "expected"), [
    ("/Tools/x.md", "Tools/x"),
    ("[[/Tasks/x.md#Result|Task alias]]", "Tasks/x"),
    (" /Tasks/Child%20Task.MD#Result ", "Tasks/Child Task"),
    ("Tools/Child%20Tool.md", "Tools/Child Tool"),
    ("[[Tools/x|Display name]]", "Tools/x"),
    ("[[@library/Tasks/wiki/ingest#Details|Ingest]]", "@library/Tasks/wiki/ingest"),
    ("", ""),
])
def test_metadata_ref_normalizes_only_reference_spelling(raw, expected):
    assert metadata_ref(raw) == expected
    assert api_app._link_ref(raw) == expected


def test_native_metadata_refs_project_identically_in_api_and_graph(tmp_path, monkeypatch, isolated_task_ledger):
    monkeypatch.setattr(CONFIG, "vault_dir", tmp_path / "vault")
    monkeypatch.setattr(api_app.model_runtime, "resolve_model", lambda *_args: SimpleNamespace(id="test-model"))
    definitions = {
        "Tools/x": {"kind": "tool", "subtools": ["/Tools/Child%20Tool.md#Usage"]},
        "Tools/Child Tool": {"kind": "tool"},
        "Runbooks/x": {"kind": "runbook"},
        "Tasks/x": {
            "kind": "task", "subtasks": ["[[/Tasks/Child%20Task.md#Result|Child]]"],
            "exclude_subtasks": ["/Tasks/Child%20Task.md"],
            "assignee": "/Agents/Executive/Executive.md", "runbook": "/Runbooks/x.md#Procedure",
        },
        "Tasks/Child Task": {"kind": "task"},
        "Agents/Executive/Executive": {
            "kind": "agent", "role": "executive",
            "tasks": ["/Tasks/x.md", "[[@library/Tasks/research]]"],
        },
    }
    for ref, meta in definitions.items():
        vault.write_note(ref + ".md", {"title": ref.rsplit("/", 1)[-1], **meta}, "Authored definition.")
    before = {path: path.read_bytes() for path in CONFIG.vault_dir.rglob("*.md")}
    isolated_task_ledger.sync(embed=False)

    monkeypatch.setattr(api_app, "_reader_overrides", lambda: {})
    monkeypatch.setattr(api_app, "_navigation_manifest", lambda _overrides: {"groups": []})
    nodes = {node["id"]: node for node in api_app.graph()["nodes"]}
    assert nodes["Tools/x"]["children"] == ["Tools/Child Tool"]
    assert nodes["Tasks/x"]["children"] == ["Tasks/Child Task"]
    assert nodes["Tasks/x"]["assignee"] == "Agents/Executive/Executive"
    assert "checkouts" not in nodes["Agents/Executive/Executive"]
    assert "Tasks/x" in nodes["Agents/Executive/Executive"]["dependencies"]["tasks"]
    task = next(row for row in api_app.tasks() if row["ref"] == "Tasks/x")
    assert task["subtask_refs"] == ["Tasks/Child Task"]
    assert task["excluded_subtask_refs"] == ["Tasks/Child Task"]
    assert task["assignee"] == "Agents/Executive/Executive"
    assert task["runbook"] == "Runbooks/x"
    assert api_app._note_doc(vault.load_note("Tasks/x.md"))["children"] == ["Tasks/Child Task"]
    assignments = api_app.library_assignments()["assignments"]
    assert assignments == [{"agent": "executive", "ref": "Tasks/x", "kind": "task",
                            "direct": True, "inherited": False}]
    assert {path: path.read_bytes() for path in before} == before
    assert vault.load_note("Tasks/x.md").meta["runbook"] == "/Runbooks/x.md#Procedure"


def test_api_child_closure_uses_normalized_exact_refs():
    parent = vault.Note(path="Tools/x.md", title="x", body="", meta={
        "kind": "tool", "subtools": ["/Tools/Child%20Tool.md#Usage"],
    })
    child = vault.Note(path="Tools/Child Tool.md", title="Child Tool", body="", meta={"kind": "tool"})
    assert api_app._primitive_closure([parent], [parent, child]) == [parent, child]

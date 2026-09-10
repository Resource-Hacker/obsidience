from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException

from obsidience.harness.config import CONFIG
from obsidience.harness.interfaces.api import app
from obsidience.harness.knowledge import format
from obsidience.harness.knowledge.vault import load_note, write_note


@pytest.fixture
def assignments(tmp_path, monkeypatch, isolated_task_ledger):
    monkeypatch.setattr(CONFIG, "vault_dir", tmp_path / "vault")
    for role, ref in app.CHECKOUT_AGENTS.items():
        write_note(ref + ".md", {"kind": "agent", "title": role}, "Agent.")
    write_note("Tools/task.complete.md", {
        "kind": "tool", "title": "task.complete", "binding": "capability:task.complete",
        "source": "obsidience/harness/capabilities/task/complete.py",
    }, "Complete the current Task.")
    write_note("Skills/task.complete.md", {
        "kind": "skill", "title": "Using task.complete", "tool": "[[Tools/task.complete]]",
    }, "Record the verified result.")
    write_note("Tools/harness.status.md", {
        "kind": "tool", "title": "harness.status", "binding": "capability:harness.status",
        "source": "obsidience/harness/capabilities/harness/status.py",
    }, "Read status.")
    write_note("Skills/harness.status.md", {
        "kind": "skill", "title": "Using harness.status", "tool": "[[Tools/harness.status]]",
    }, "Read the structured status response.")
    write_note("Runbooks/check.md", {
        "kind": "runbook", "title": "Check", "skills": ["[[Skills/harness.status]]"],
    }, "Read status and verify the result.")
    for name in ("one", "two"):
        write_note(f"Tasks/{name}.md", {"kind": "task", "title": name,
            "runbook": "[[Runbooks/check]]"}, "Return verified status.")
    monkeypatch.setattr(app.INDEX, "sync", lambda: None)
    monkeypatch.setattr(app, "ensure_task_runbook", lambda *args, **kwargs: {"status": "ready"})


def test_only_tasks_can_be_assigned(assignments):
    write_note("_staging/Tasks/proposed.md", {"kind": "task"}, "Unaccepted work.")
    write_note("_archived/Tasks/retired.md", {"kind": "task"}, "Retired work.")
    for ref in ("Tools/harness.status", "Skills/harness.status", "Runbooks/check",
                "@library/Tasks/wiki", "_staging/Tasks/proposed", "_archived/Tasks/retired", "one"):
        with pytest.raises(HTTPException, match="Only an accepted Task"):
            app.set_library_assignment(ref, {"agent": "executive", "assigned": True})
    assert "tools" not in load_note("Agents/Executive/Executive.md").meta


def test_task_assignment_supplies_exact_dependencies_without_copying_grants(assignments):
    result = app.set_library_assignment("Tasks/one", {"agent": "executive", "assigned": True})
    assert result["direct"] and result["assigned"] and result["assignment_changed"]
    identity = load_note("Agents/Executive/Executive.md")
    assert identity.meta["tasks"] == ["[[Tasks/one]]"]
    assert {"tools", "skills", "runbooks"}.isdisjoint(identity.meta)
    projection = app.library_assignments()
    assert projection["assignments"] == [{"agent": "executive", "ref": "Tasks/one",
        "kind": "task", "direct": True, "inherited": False}]
    effective = {(item["kind"], item["ref"]) for item in projection["dependencies"]}
    assert {("runbook", "Runbooks/check"), ("skill", "Skills/harness.status"),
            ("tool", "Tools/harness.status")} <= effective
    app.set_library_assignment("Tasks/one", {"agent": "executive", "assigned": False})
    assert not app.library_assignments()["dependencies"]


def test_concurrent_assignment_clicks_preserve_both_tasks(assignments):
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda name: app.set_library_assignment(f"Tasks/{name}", {
            "agent": "executive", "assigned": True}), ("one", "two")))
    assert set(load_note("Agents/Executive/Executive.md").meta["tasks"]) == {
        "[[Tasks/one]]", "[[Tasks/two]]",
    }


def test_scheduled_assignment_is_visible_without_manual_selection(assignments):
    task = load_note("Tasks/one.md")
    write_note(task.path, {**task.meta, "assignee": "[[Agents/Executive/Executive]]",
                          "schedule": "*/30 * * * *"}, task.body)
    result = app.library_assignments()["assignments"]
    assert result == [{"agent": "executive", "ref": "Tasks/one", "kind": "task",
                       "direct": False, "inherited": True}]
    result = app.set_library_assignment("Tasks/one", {"agent": "executive", "assigned": False})
    assert result["assigned"] is True  # Edit the actual schedule/assignee to remove it.
    assert result["direct"] is False


def test_removing_direct_child_preserves_parent_assignment(assignments):
    write_note("Tasks/parent.md", {"kind": "task", "subtasks": ["[[Tasks/one]]"]}, "Parent scope.")
    for task in ("Tasks/parent", "Tasks/one"):
        app.set_library_assignment(task, {"agent": "executive", "assigned": True})
    result = app.set_library_assignment("Tasks/one", {"agent": "executive", "assigned": False})
    assert result["assigned"] and result["inherited"] and not result["direct"]
    row = next(item for item in app.library_assignments()["assignments"] if item["ref"] == "Tasks/one")
    assert row["inherited"] and not row["direct"]


@pytest.mark.parametrize("field", ["tools", "skills", "runbooks"])
def test_agent_profile_rejects_independent_capability_grants(field):
    assert any("derived from assigned Tasks" in error for error in format.validate_profile({
        "type": "agent", "obsidience": {field: []},
    }))


def test_retired_capability_checkout_route_is_absent():
    assert not any("/library/checkouts" in getattr(route, "path", "") for route in app.app.routes)

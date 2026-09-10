from __future__ import annotations

from pathlib import Path

import frontmatter
from obsidience.harness.knowledge.format import loads
import pytest

from obsidience.harness.capabilities.vault.propose import (
    stage_proposal,
    validate_generated_runbook,
)
from obsidience.harness.config import CONFIG
from obsidience.harness.knowledge.index import Index
from obsidience.harness.knowledge.tasks import (
    CANONICAL_TASK_BY_PATH,
    TASK_TAXONOMY_BY_PATH,
    canonical_members,
)
from obsidience.harness.knowledge.vault import iter_notes, load_note, resolver, write_note
from obsidience.harness.models.runtime import SPECIALIST_MODEL


VAULT = Path(__file__).parents[1] / "vault"


def _runbook_body(extra: str = "") -> str:
    return f"""\
# Generated procedure

## Prerequisites
- The exact Task is active.

## Ordered Actions
1. Follow [[Skills/vault.search]] and call `vault.search` for accepted context.
{extra}

## Bounded Branches
- Stop if the evidence is insufficient.

## Stop Conditions
- The outcome is established or cannot be established.

## Completion Criteria
- The result states the evidence and outcome.

## Verification
- Verify the result against the retrieved Article.

## Recovery
- Report the exact blocker without inventing another Tool.
"""


def test_generated_runbook_allows_authorized_callable_names_but_not_authority() -> None:
    validate_generated_runbook(
        "Runbooks/Generated/test/query.md",
        _runbook_body(),
        {
            "output_runbook": "Runbooks/Generated/test/query.md",
            "skills": ["Skills/vault.search"],
            "tools": ["Tools/vault.search"],
        },
        ["Skills/vault.search"],
    )


def test_generated_runbook_rejects_callable_outside_checkout() -> None:
    with pytest.raises(ValueError, match="Tools outside its selected Skills: web.search"):
        validate_generated_runbook(
            "Runbooks/Generated/test/query.md",
            _runbook_body("2. Call `web.search` for unrelated material."),
            {
                "output_runbook": "Runbooks/Generated/test/query.md",
                "skills": ["Skills/vault.search"],
                "tools": ["Tools/vault.search"],
            },
            ["Skills/vault.search"],
        )


@pytest.mark.parametrize(
    "path",
    [
        "Runbooks/Generated/curator/query.md",
        "Runbooks/Generated/guardian/query.md",
        "Runbooks/Generated/researcher/query.md",
    ],
)
def test_accepted_generated_query_runbooks_match_current_contract(path: str) -> None:
    metadata, body = loads((VAULT / path).read_text())
    post = frontmatter.Post(body, **metadata)
    skills = [str(value).strip("[]") for value in post.metadata["skills"]]
    tools = [value.replace("Skills/", "Tools/", 1) for value in skills]
    validate_generated_runbook(
        path,
        post.content,
        {"output_runbook": path, "skills": skills, "tools": tools},
        skills,
    )


@pytest.fixture
def generation_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(CONFIG, "vault_dir", tmp_path)
    write_note(
        "Agents/Darwin/Darwin.md",
        {"kind": "agent", "title": "Darwin"},
        "Research agent.",
    )
    write_note(
        "Runbooks/generated-example.md",
        {"kind": "runbook", "title": "Generated example"},
        "Complete the bounded example.",
    )
    return tmp_path


def _task_args(target: str = "Tasks/generated-example.md", **metadata: object) -> dict:
    task_metadata = {
        "kind": "task",
        "assignee": "[[Agents/Darwin/Darwin]]",
        "taxonomy_path": "research",
        "model": SPECIALIST_MODEL,
        "reasoning_effort": "high",
        "triggers": ["task.create"],
        "runbook": "[[Runbooks/generated-example]]",
        "acceptance": ["One evidence-backed result is recorded."],
        **metadata,
    }
    return {
        "action": "create",
        "target": target,
        "title": "Generated example",
        "body": "Produce one bounded evidence-backed result.",
        "reason": "A reusable result is required.",
        "metadata": task_metadata,
    }


def test_generated_task_stages_only_validated_definition_metadata(
    generation_vault: Path,
) -> None:
    result = stage_proposal(_task_args(), {"agent": "Darwin", "run_id": "test"})
    assert set(result) == {"staged", "target", "action", "review_class"}
    staged = load_note(result["staged"])
    assert staged is not None
    assert staged.meta["taxonomy_path"] == "research"
    assert staged.meta["triggers"] == ["task.create"]
    assert staged.meta["acceptance"] == ["One evidence-backed result is recorded."]
    assert "params" not in staged.meta
    assert "status" not in staged.meta


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("params", {"request": "runtime"}),
        ("status", "pending"),
        ("schedule", "* * * * *"),
        ("enabled", True),
        ("last_run", "runtime-id"),
    ],
)
def test_generated_task_rejects_runtime_metadata(
    generation_vault: Path,
    field: str,
    value: object,
) -> None:
    error = (
        "invalid documentary metadata: status must be draft, stable, or deprecated"
        if field == "status" else f"invalid metadata fields: {field}"
    )
    with pytest.raises(ValueError, match=error):
        stage_proposal(_task_args(f"Tasks/bad-{field}.md", **{field: value}), {})


@pytest.mark.parametrize(
    ("metadata", "message"),
    [
        ({"acceptance": "not a bounded list"}, "acceptance must be a nonempty list"),
        ({"triggers": "task.create"}, "triggers must be a nonempty list"),
        ({"taxonomy_path": "executive/missing"}, "unknown Task taxonomy path"),
        ({"model": "unregistered-model"}, "model is not registered"),
        ({"subtasks": ["[[Tasks/other]]"]}, "exactly one of runbook or subtasks"),
    ],
)
def test_generated_task_rejects_invalid_definition_metadata(
    generation_vault: Path,
    metadata: dict,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        stage_proposal(_task_args("Tasks/invalid.md", **metadata), {})


def test_executive_taxonomy_contains_only_real_executable_outcomes() -> None:
    assert TASK_TAXONOMY_BY_PATH["executive"].children == (
        "executive/query",
        "executive/operate",
    )
    assert TASK_TAXONOMY_BY_PATH["executive"].kind == "knowledge"
    assert TASK_TAXONOMY_BY_PATH["executive"].triggers == ()
    assert TASK_TAXONOMY_BY_PATH["executive"].routing is None
    assert CANONICAL_TASK_BY_PATH["executive/query"] == "Tasks/query"
    assert "wiki/query" not in TASK_TAXONOMY_BY_PATH
    assert canonical_members("executive", {"Tasks/query", "Tasks/executive/operate"}) == [
        "Tasks/executive/operate", "Tasks/query",
    ]
    for fake_leaf in (
        "realtime", "respond", "recall", "delegate", "plan", "schedule", "monitor",
    ):
        assert f"executive/{fake_leaf}" not in TASK_TAXONOMY_BY_PATH


def test_interactive_work_preserves_authored_model_and_effort() -> None:
    query_meta, query_body = loads((VAULT / "Tasks/query.md").read_text())
    operate_meta, operate_body = loads((VAULT / "Tasks/executive/operate.md").read_text())
    query = frontmatter.Post(query_body, **query_meta)
    operate = frontmatter.Post(operate_body, **operate_meta)
    assert query.metadata["model"] == operate.metadata["model"] == "obsidience-gemma"
    assert query.metadata["reasoning_effort"] == "none"
    assert operate.metadata["reasoning_effort"] == "none"
    assert query.metadata["taxonomy_path"] == "executive/query"
    assert not (VAULT / "Tasks/executive/realtime.md").exists()
    assert not (VAULT / "Runbooks/realtime.md").exists()
    assert not (VAULT / "Runbooks/executive.md").exists()


def test_interactive_task_graph_preserves_query_identity_and_resolves_checkouts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(CONFIG, "db_path", tmp_path / "graph.sqlite3")
    index = Index()
    try:
        index.sync(embed=False)
        graph = index.graph()
    finally:
        index.db.close()
    nodes = {node["id"]: node for node in graph["nodes"]}
    executive = nodes["@library/Tasks/executive"]
    assert executive["kind"] == "knowledge"
    assert executive["children"] == ["Tasks/query", "Tasks/executive/operate"]
    assert nodes["Tasks/query"]["children"] == []
    assert "Tasks/query" not in nodes["@library/Tasks/wiki"]["children"]
    retired = {"Tasks/executive/realtime", "Runbooks/realtime", "Runbooks/executive"}
    assert retired.isdisjoint(nodes)
    assert not any(
        edge["source"] in retired or edge["target"] in retired
        for edge in graph["links"]
    )
    res = resolver()
    for note in iter_notes():
        assert retired.isdisjoint(note.links), note.ref
        if note.ref != "Agents/Executive/Executive":
            continue
        for field, expected_kind in (("tasks", "task"), ("runbooks", "runbook")):
            for ref in note.meta.get(field, []):
                target = res.resolve(ref)
                assert target is not None, (note.ref, field, ref)
                assert target.kind == expected_kind, (note.ref, field, ref)

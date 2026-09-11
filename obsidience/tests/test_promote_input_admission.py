"""Old queued malformed summaries fail before model acquisition or Source effects."""
import asyncio
from copy import deepcopy

import pytest

from obsidience.harness.conversation import observations
from obsidience.harness.execution import executor
from obsidience.harness.knowledge import source
from obsidience.harness.knowledge.vault import Note, Resolver
from obsidience.tests.test_execution_cancellation import execution  # noqa: F401

VALID = ("Goal: Preserve the ongoing task.\n\nConstraints and corrections: Keep exact evidence.\n\n"
         "Verified state: The last action was verified.\n\nOutstanding: Complete the next requested step.")
INVALID = ("An incomplete legacy summary without the required sections. " * 4)[:197]


def inputs(body=VALID):
    note = Note(str(observations.EXECUTIVE_TEMPORARY_PATH / "isolated.md"), "Isolated summary", {
        "kind": "knowledge", "observation_scope": "temporary", "temporary": True,
        "compaction": True, "compaction_committed": True,
        "source_conversation_id": "isolated", "promotion_pending": "a" * 20,
        "through_sequence": 4,
    }, body)
    runtime = {"origin_task_ref": observations.TEMPORARY_PROMOTION_TASK_REF,
        "event": observations.TEMPORARY_PROMOTION_EVENT, "conversation_id": "isolated",
        "promotion_key": "a" * 20, "through_sequence": 4, "temporary_refs": [note.ref]}
    return note, runtime


def test_valid_promotion_reuses_exact_resolver_without_mutation(monkeypatch):
    note, runtime = inputs()
    before = deepcopy((note.meta, note.body, runtime))
    monkeypatch.setattr(observations, "resolver", lambda: pytest.fail("unexpected second resolver"))
    result = observations.resolve_temporary_promotion_inputs(runtime, Resolver([note]))
    assert result == [note] and result[0] is note
    assert (note.meta, note.body, runtime) == before


@pytest.mark.parametrize("change", ["body", "missing", "duplicate", "uncommitted", "conversation", "sequence", "event", "task"])
def test_readonly_guard_retains_existing_identity_and_completeness_checks(change):
    note, runtime = inputs()
    if change == "body":
        note.body = INVALID
        assert len(note.body) == 197
    elif change == "missing":
        runtime["temporary_refs"] = ["Knowledge/missing"]
    elif change == "duplicate":
        runtime["temporary_refs"].append(note.ref)
    elif change == "uncommitted":
        note.meta["compaction_committed"] = False
    elif change == "conversation":
        runtime["conversation_id"] = "another"
    elif change == "sequence":
        runtime["through_sequence"] = 6
    elif change == "event":
        runtime["event"] = "task.create"
    elif change == "task":
        runtime["origin_task_ref"] = "Tasks/query"
    before = deepcopy((note.meta, note.body, runtime))
    with pytest.raises(ValueError):
        observations.resolve_temporary_promotion_inputs(runtime, Resolver([note]))
    assert (note.meta, note.body, runtime) == before


def test_archive_rechecks_same_owner_before_any_source_or_article_write(monkeypatch):
    note, runtime = inputs(INVALID)
    monkeypatch.setattr(observations, "resolver", lambda: Resolver([note]))
    monkeypatch.setattr(source, "ingest_source", lambda **_kw: pytest.fail("invalid input archived"))
    monkeypatch.setattr(source, "get_source", lambda *_a: pytest.fail("invalid input restored Source"))
    monkeypatch.setattr(observations, "write_note", lambda *_a: pytest.fail("invalid Article mutated"))
    with pytest.raises(ValueError, match="not an exact committed input"):
        observations.archive_temporary_observations({}, runtime)
    assert note.body == INVALID and not note.meta.get("source_archive")


@pytest.mark.parametrize("valid", [False, True])
def test_executor_checks_promote_before_compiler_model_or_tools(execution, monkeypatch, valid):
    note, runtime = inputs(VALID if valid else INVALID)
    execution.task.ref = observations.TEMPORARY_PROMOTION_TASK_REF
    execution.task.title = "Promote"
    execution.task.meta["params"] = {key: value for key, value in runtime.items() if key != "origin_task_ref"}
    agent = Note("Agents/Executive/Executive.md", "Executive", {"kind": "agent"}, "")
    monkeypatch.setattr(executor, "resolver", lambda **_kwargs: Resolver([note, agent]))
    before = deepcopy((note.body, note.meta, execution.task.meta))
    if not valid:
        def forbidden(*_a, **_kw):
            pytest.fail("invalid Promote reached compiler/model/Tool boundary")
        monkeypatch.setattr(executor, "compile_activation", forbidden)
        monkeypatch.setattr(executor.model_runtime, "resolve_model", forbidden)
        monkeypatch.setattr(executor.model_runtime, "lease", forbidden)
        monkeypatch.setattr(executor.llm, "chat", forbidden)
        monkeypatch.setattr(executor, "execute_capability", forbidden)
    if valid:
        result = asyncio.run(execution.run(runtime_params=None, interactive=False))
    else:
        with pytest.raises(ValueError, match="not an exact committed input"):
            asyncio.run(execution.run(runtime_params=None, interactive=False))
    assert (note.body, note.meta, execution.task.meta) == before
    if valid:
        assert result["status"] == "completed"
        assert [call[0] for call in execution.calls] == ["task.complete"]
        assert execution.releases == 1
    else:
        assert execution.records[-1]["status"] == "failed"
        assert "not an exact committed input" in execution.records[-1]["summary"]
        import json
        assert all(set(row) == {"activation_id"} for row in json.loads(execution.records[-1]["trace"]))
        assert execution.calls == [] and execution.releases == 0

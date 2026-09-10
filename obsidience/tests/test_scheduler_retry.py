"""Explicit retry preserves one attested, effect-free occurrence and its FIFO."""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

from obsidience.harness.config import CONFIG
from obsidience.harness.execution import scheduler
from obsidience.harness.knowledge import vault


@pytest.fixture
def occurrence(tmp_path, monkeypatch, isolated_task_ledger):
    monkeypatch.setattr(CONFIG, "vault_dir", tmp_path / "vault")
    monkeypatch.setattr(scheduler, "_running", set())
    params = {"event": "task.create", "activation_key": "bound-key", "candidate_key": "bound-key",
              "created_by_task_ref": "Tasks/curate", "created_by_run_id": "creator",
              "candidate_refs": ["Knowledge/one", "Knowledge/two"]}
    vault.write_note("Tasks/link.md", {"kind": "task", "title": "Link", "status": "failed",
        "triggers": ["task.create"], "params": params, "last_run": "failed-run",
        "summary": "Interrupted while reading.", "blocked_reason": "Previous attempt interrupted.",
        "event_queue": [{"event": "task.create", "activation_key": "next-key", "candidate_refs": ["Knowledge/next"]}],
    }, "Reconcile the exact candidates.")
    activation = {key: params[key] for key in ("event", "activation_key", "created_by_task_ref", "created_by_run_id")}
    isolated_task_ledger.record_run(id="failed-run", task_ref="Tasks/link", agent="fixture", started=1.,
        finished=2., status="interrupted", summary="Interrupted while reading.",
        trace=json.dumps([{"activation_packet": ["Tasks/link"], "task_activation": activation},
            {"tool": "vault.read", "args": {"ref": "Knowledge/one"}, "obs": "Exact read result", "sig": "digest"},
            {"interruption_reason": "foreground_admission", "must_not_replay": True}]))
    return vault.load_note("Tasks/link.md"), isolated_task_ledger


def changed_run(ledger, change):
    run = ledger.run("failed-run")
    trace = json.loads(run["trace"])
    change(run, trace)
    if isinstance(run["trace"], str) and run["trace"].startswith("["):
        run["trace"] = json.dumps(trace)
    return run


def test_retry_preserves_original_run_inputs_fifo_and_authored_article(occurrence, monkeypatch):
    note, ledger = occurrence
    prior_run = ledger.run("failed-run")
    prior_article = (CONFIG.vault_dir / note.path).read_bytes()
    monkeypatch.setattr(scheduler, "launch", lambda *_a, **_k: pytest.fail("Retry must not launch"))
    assert scheduler.retry_blocked_reason(note) == ""
    result = scheduler.retry_failed_occurrence(note, "failed-run")
    assert result == {"task": note.ref, "status": "pending", "retry_of_run": "failed-run", "queue_depth": 1, "already_pending": False}
    current = vault.load_note(note.path)
    assert current.meta["status"] == "pending"
    for field in ("params", "event_queue", "last_run", "summary"):
        assert current.meta[field] == note.meta[field]
    assert "blocked_reason" not in current.meta
    assert ledger.run("failed-run") == prior_run
    assert (CONFIG.vault_dir / note.path).read_bytes() == prior_article
    assert scheduler.retry_failed_occurrence(current, "failed-run")["already_pending"] is True
    assert len(ledger.runs()) == 1


@pytest.mark.parametrize("entry", [
    {"tool": "vault.propose", "args": {}, "obs": "committed"},
    {"tool": "task.complete", "args": {}, "obs": "accepted"},
    {"tool": "web.feed", "args": {}, "obs": "new Source"},
    {"tool": "future.tool", "args": {}, "obs": "unknown"},
    {"tool": [], "args": {}, "obs": "malformed"},
    {"tool": "vault.read", "args": {}, "obs": "read", "interrupted": True},
    {"tool": "vault.read", "args": {}},
    {"created_tasks": [{"activation_key": "child"}]},
    {"task": "Tasks/child", "status": "completed"},
    {"resource_blocked_after_effect": True},
    {"unknown_outcome": True},
    {"interruption_reason": "unknown", "must_not_replay": True},
])
def test_unknown_or_effectful_attempts_are_not_retryable(occurrence, entry):
    note, ledger = occurrence
    run = changed_run(ledger, lambda _r, trace: trace.append(entry))
    assert scheduler.retry_blocked_reason(note, run)


@pytest.mark.parametrize("changes", [
    {"id": "different"}, {"task_ref": "Tasks/other"}, {"status": "completed"},
    {"status": []}, {"finished": None}, {"finished": float("nan")}, {"finished": False},
    {"finished": 0.}, {"trace": "broken"}, {"trace": "null"}, {"trace": "[]"},
])
def test_missing_terminal_receipt_fails_closed(occurrence, changes):
    note, ledger = occurrence
    assert scheduler.retry_blocked_reason(note, {**ledger.run("failed-run"), **changes})


@pytest.mark.parametrize("field,value", [("last_run", "newer-run"), ("params", {"event": "task.create", "activation_key": "changed"}), ("event_queue", [])])
def test_mutation_rechecks_current_runtime_under_note_lock(occurrence, monkeypatch, field, value):
    note, ledger = occurrence
    original = scheduler.mutate_note_metadata
    def race(candidate, callback):
        vault.mutate_note_metadata(candidate, lambda meta: meta.update({field: value}))
        return original(candidate, callback)
    monkeypatch.setattr(scheduler, "mutate_note_metadata", race)
    with pytest.raises(ValueError, match="changed"):
        scheduler.retry_failed_occurrence(note, "failed-run")
    assert vault.load_note(note.path).meta["status"] == "failed"
    assert ledger.run("failed-run")["status"] == "interrupted"


def test_legacy_creator_receipt_must_match_exact_parameters_once(occurrence):
    note, ledger = occurrence
    run = ledger.run("failed-run")
    trace = json.loads(run["trace"])
    trace[0].pop("task_activation")
    run["trace"] = json.dumps(trace)
    assert scheduler.retry_blocked_reason(note, run)
    original = {key: value for key, value in note.meta["params"].items()
                if key not in {"event", "activation_key", "created_by_task_ref", "created_by_run_id"}}
    receipt = {"tool": "task.create", "args": {"task": note.ref, "params": original},
               "obs": json.dumps({"task": note.ref, "state": "started"})}
    creator = dict(id="creator", task_ref="Tasks/curate", agent="fixture", started=0., finished=1.,
                   status="completed", summary="Created work.")
    ledger.record_run(**creator, trace=json.dumps([{"activation_packet": ["Tasks/curate"]}, receipt]))
    assert scheduler.retry_blocked_reason(note, run) == ""
    altered = replace(note, meta={**note.meta, "params": {**note.meta["params"], "candidate_refs": ["Knowledge/other"]}})
    assert scheduler.retry_blocked_reason(altered, run)
    ledger.record_run(**creator, trace=json.dumps([{"activation_packet": ["Tasks/curate"]}, receipt, receipt]))
    assert scheduler.retry_blocked_reason(note, run)


def test_pending_proposal_blocks_even_read_only_trace(occurrence):
    note, _ = occurrence
    CONFIG.staging_dir.mkdir(parents=True)
    (CONFIG.staging_dir / "proposal.md").write_text("---\nrun_id: failed-run\n---\nProposed knowledge.\n")
    assert "proposal" in scheduler.retry_blocked_reason(note)


def test_owner_review_decision_prevents_replay(occurrence):
    note, ledger = occurrence
    columns = [row[1] for row in ledger.db.execute("PRAGMA table_info(review_decisions)")]
    assert "run_id" in columns
    # Read-only receipt projection can still have an independent review decision.
    ledger.db.execute("INSERT INTO review_decisions(proposal_id,run_id,task_ref,target,decision,decided_at) VALUES(?,?,?,?,?,?)", ("proposal", "failed-run", note.ref, "Knowledge/one.md", "approved", 3.))
    ledger.db.commit()
    assert "review decision" in scheduler.retry_blocked_reason(note)


def test_source_retry_requires_same_immutable_material(occurrence, monkeypatch):
    note, ledger = occurrence
    params = {"event": "source.inbox", "activation_key": "source-key", "source_id": "source-id", "source_sha256": "content-hash"}
    note = replace(note, meta={**note.meta, "triggers": ["source.inbox"], "params": params})
    run = {**ledger.run("failed-run"), "trace": json.dumps([{"activation_packet": [note.ref], "source_inbox": params}])}
    source = {"event_key": "source-key", "content_sha256": "content-hash", "material": b"immutable original"}
    source["material_sha256"] = "sha256:" + hashlib.sha256(source["material"]).hexdigest()
    monkeypatch.setattr(ledger, "source", lambda _id: source)
    assert scheduler.retry_blocked_reason(note, run) == ""
    source["material"] = b"changed"
    assert scheduler.retry_blocked_reason(note, run)
    source["material"] = None
    assert scheduler.retry_blocked_reason(note, run)


def test_promotion_uses_shared_input_authority_and_rejects_archived_input(occurrence, monkeypatch):
    from obsidience.harness.conversation import observations
    note, ledger = occurrence
    params = {"event": "observations.temporary.ready", "activation_key": "promotion-key", "promotion_key": "promotion-key"}
    note = replace(note, path="Tasks/promote.md", meta={**note.meta, "triggers": [params["event"]], "params": params})
    run = {**ledger.run("failed-run"), "task_ref": note.ref}
    temporary = vault.Note("Temporary/exact.md", "Temporary", {"promotion_pending": "promotion-key"}, "Body")
    calls = []
    def resolve(runtime):
        calls.append(runtime)
        return [temporary]
    monkeypatch.setattr(observations, "resolve_temporary_promotion_inputs", resolve)
    assert scheduler.retry_blocked_reason(note, run) == ""
    assert calls == [{**params, "origin_task_ref": note.ref}]
    temporary.meta["source_archive"] = "already-archived"
    assert scheduler.retry_blocked_reason(note, run)
    def invalid(_runtime):
        raise ValueError("invalid old compaction")
    monkeypatch.setattr(observations, "resolve_temporary_promotion_inputs", invalid)
    assert scheduler.retry_blocked_reason(note, run)


@pytest.fixture
def source_interruption(occurrence):
    from obsidience.harness.knowledge import source
    note, ledger = occurrence
    vault.write_note("Tasks/research/news.md", {"kind": "task", "title": "News",
        "assignee": "[[Agents/Darwin/Darwin]]"}, "Research current events.")
    ledger.record_run(id="research-run", task_ref="Tasks/research/news", agent="Darwin", started=0.,
        finished=1., status="completed", summary="Gathered evidence.", trace="[]")
    cited = "source://11111111-2222-3333-4444-555555555555"
    raw = source.RawSource.create(source_type="research", source_ref="Finding", media_type="text/markdown",
        captured_at="2026-09-05T10:00:00Z", content=f"Evidence {cited} supports this finding.")
    material = source.render_raw_source(raw)
    key = f"source.inbox:research:research-run:Tasks/research/news:{raw.content_sha256[7:27]}"
    ledger.record_source(id=raw.source_id, path=f"inbox/2026-09-05/{raw.source_id}.md", source_type=raw.source_type,
        source_ref=raw.source_ref, media_type=raw.media_type, captured_at=raw.captured_at,
        content_sha256=raw.content_sha256, material_sha256="sha256:"+hashlib.sha256(material).hexdigest(),
        material=material, created_at=0., event_key=key, event_dispatched_at=1.)
    params = {"event": "source.inbox", "activation_key": key, "queue_after_review": True,
        "source_id": raw.source_id, "source_citation": f"source://{raw.source_id}",
        "source_path": f"obsidience/evidence/inbox/2026-09-05/{raw.source_id}.md",
        "source_type": raw.source_type, "source_ref": raw.source_ref, "source_media_type": raw.media_type,
        "source_captured_at": raw.captured_at, "source_sha256": raw.content_sha256,
        "source_citations": [cited], "research_task": "Tasks/research/news", "research_run_id": "research-run"}
    note = replace(note, path="Tasks/ingest.md", meta={**note.meta, "triggers": ["source.inbox"], "params": params})
    run = {**ledger.run("failed-run"), "task_ref": note.ref, "trace": json.dumps([
        {"activation_packet": [note.ref], "retrieval_ms": 1.},
        {"interruption_reason": "foreground_admission", "must_not_replay": True}])}
    return note, run, ledger


def test_zero_tool_foreground_interruption_recovers_exact_source_event_without_restore(source_interruption, monkeypatch):
    from obsidience.harness.knowledge import source
    note, run, _ = source_interruption
    monkeypatch.setattr(source, "_restore", lambda *_a, **_k: pytest.fail("Retry eligibility must not restore Source files"))
    assert scheduler.retry_blocked_reason(note, run) == ""


@pytest.mark.parametrize("field,value", [
    ("source_id", "different"), ("source_sha256", "different"), ("source_path", "other/path"),
    ("source_citation", "source://different"), ("source_citations", []), ("source_ref", "different"),
    ("research_run_id", "different"), ("question", "Unattested replacement objective"),
    ("queue_after_review", 1),
])
def test_recovered_source_event_rejects_any_altered_input(source_interruption, field, value):
    note, run, _ = source_interruption
    note = replace(note, meta={**note.meta, "params": {**note.meta["params"], field: value}})
    assert scheduler.retry_blocked_reason(note, run)


@pytest.mark.parametrize("change", ["no_marker", "no_boolean_attestation", "read_tool", "malformed_receipt"])
def test_missing_source_receipt_fallback_is_only_zero_tool_safe_foreground(source_interruption, change):
    note, run, _ = source_interruption
    trace = json.loads(run["trace"])
    if change == "no_marker": trace.pop()
    elif change == "no_boolean_attestation": trace[1]["must_not_replay"] = "true"
    elif change == "read_tool": trace.append({"tool": "source.read", "args": {}, "obs": "Read"})
    else: trace[0]["source_inbox"] = None
    assert scheduler.retry_blocked_reason(note, {**run, "trace": json.dumps(trace)})

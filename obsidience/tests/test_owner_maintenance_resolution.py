"""Owner review receipts suppress exact reviewed candidates, never replay effects."""

from __future__ import annotations

import copy
import hashlib
import json

import pytest

from obsidience.harness.capabilities.vault import maintenance
from obsidience.harness.config import CONFIG
from obsidience.harness.knowledge import vault


def _params():
    return {
        "event": "task.create", "target_task": "Tasks/link",
        "created_by_task_ref": "Tasks/curate", "created_by_run_id": "original-curate",
        "candidate_key": "a" * 20, "candidate_revision": "b" * 64,
        "candidate_refs": ["Knowledge/left", "Knowledge/right"],
        "candidate_kind": "missing_link", "candidate_signals": {"score": 1},
        "activation_key": "a" * 20,
    }


def _reseal(row):
    receipt = row["trace"][0]["controller_disposition"]
    params = receipt["candidate_params"]
    receipt["params_sha256"] = hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()
    row["id"] = "settled-" + hashlib.sha256(
        (row["task_ref"] + "\0" + str(params["activation_key"]) + "\0" + receipt["params_sha256"]).encode(),
    ).hexdigest()[:32]
    return row


def _row(params=None, *, reviewed_revision="c" * 64, reviewed_candidate_key="d" * 20, reviewed_articles=None):
    params = copy.deepcopy(params or _params())
    return _reseal({
        "id": "", "task_ref": "Tasks/link", "agent": "scheduler", "status": "settled",
        "started": 1.0, "finished": 2.0, "summary": "Owner reviewed the Article pair; no link is justified.",
        "trace": [{"controller_disposition": {
            "kind": "owner_maintenance_resolution", "disposition": "no_change",
            "authorization": "explicit_owner_request", "reviewed_by": "Codex",
            "target_task": "Tasks/link", "reason": "Shared terms describe unrelated facts.",
            "candidate_params": params, "activation_key": params["activation_key"],
            "previous_run_id": "original-interrupted", "effect_applied": False, "tools_executed": False,
            "reviewed_revision": reviewed_revision, "reviewed_candidate_key": reviewed_candidate_key,
            "reviewed_articles": reviewed_articles or [
                {"ref": ref, "sha256": str(number) * 64}
                for number, ref in enumerate(params["candidate_refs"], 1)
            ],
        }}],
    })


def _record(ledger, row):
    ledger.record_run(**{**row, "trace": json.dumps(row["trace"])})


@pytest.mark.parametrize("activation_form", ["legacy", "revision"])
def test_owner_no_change_retains_original_params_and_uses_reviewed_revision(isolated_task_ledger, activation_form):
    params = _params()
    if activation_form == "revision":
        params["activation_key"] = hashlib.sha256(json.dumps(
            ["Tasks/link", params["candidate_key"], params["candidate_revision"]], sort_keys=True,
        ).encode()).hexdigest()[:20]
    original_trace = [{"tool": "vault.read", "obs": "Legacy evidence remains inconclusive."}]
    isolated_task_ledger.record_run(id="original-interrupted", task_ref="Tasks/link", agent="Alexandria",
                                    started=0.0, finished=0.5, status="interrupted", summary="Interrupted legacy work.",
                                    trace=json.dumps(original_trace))
    original_run = isolated_task_ledger.run("original-interrupted")
    row = _row(params)
    _record(isolated_task_ledger, row)

    assert isolated_task_ledger.maintenance_no_change_keys() == {("Tasks/link", "d" * 20, "c" * 64)}
    assert isolated_task_ledger.run("original-interrupted") == original_run
    saved = json.loads(isolated_task_ledger.run(row["id"])["trace"])
    assert saved == row["trace"]
    assert saved[0]["controller_disposition"]["candidate_params"] == params
    assert not any(entry.get("tool") == "task.complete" for entry in saved)


@pytest.mark.parametrize("field,value", [
    ("agent", "Alexandria"), ("status", "completed"), ("status", "failed"),
    ("id", "model-authored-output"), ("task_ref", "Tasks/merge"),
])
def test_wrong_controller_envelope_cannot_suppress(isolated_task_ledger, field, value):
    row = _row()
    row[field] = value
    _record(isolated_task_ledger, row)
    assert isolated_task_ledger.maintenance_no_change_keys() == set()


@pytest.mark.parametrize("field,value", [
    ("kind", "maintenance_invalidated"), ("disposition", "invalidated"),
    ("authorization", "implicit"), ("reviewed_by", "Heimdall"),
    ("effect_applied", True), ("effect_applied", 0), ("tools_executed", True),
    ("reason", "  "), ("reason", None), ("target_task", "Tasks/merge"),
    ("params_sha256", "f" * 64), ("activation_key", "f" * 20),
    ("reviewed_revision", "c" * 63), ("reviewed_revision", "z" * 64),
    ("reviewed_candidate_key", "a" * 19), ("reviewed_candidate_key", "z" * 20),
    ("candidate_params", {}), ("reviewed_articles", []),
    ("reviewed_articles", [{"ref": "Knowledge/left", "sha256": "1" * 64}] * 2),
    ("reviewed_articles", [{"ref": "Knowledge/left", "sha256": "1" * 64},
                           {"ref": "Knowledge/other", "sha256": "2" * 64}]),
    ("reviewed_articles", [{"ref": "Knowledge/left", "sha256": "bad"},
                           {"ref": "Knowledge/right", "sha256": "2" * 64}]),
])
def test_incomplete_or_mismatched_disposition_cannot_suppress(isolated_task_ledger, field, value):
    row = _row()
    row["trace"][0]["controller_disposition"][field] = value
    _record(isolated_task_ledger, row)
    assert isolated_task_ledger.maintenance_no_change_keys() == set()


@pytest.mark.parametrize("field", [
    "kind", "disposition", "authorization", "reviewed_by", "effect_applied", "tools_executed", "reason",
    "target_task", "params_sha256", "activation_key", "reviewed_candidate_key", "reviewed_revision",
    "candidate_params", "reviewed_articles",
])
def test_each_required_owner_evidence_field_must_be_present(isolated_task_ledger, field):
    row = _row()
    del row["trace"][0]["controller_disposition"][field]
    _record(isolated_task_ledger, row)
    assert isolated_task_ledger.maintenance_no_change_keys() == set()


@pytest.mark.parametrize("field,value", [
    ("event", "task.run"), ("target_task", "Tasks/merge"), ("created_by_task_ref", "Tasks/repair"),
    ("created_by_run_id", ""), ("candidate_kind", ""), ("candidate_signals", []),
    ("candidate_key", "a" * 19), ("candidate_revision", "z" * 64),
    ("candidate_refs", ["Knowledge/left", "Knowledge/left"]),
    ("candidate_refs", ["Knowledge/left", "knowledge/LEFT"]),
    ("candidate_refs", ["Knowledge/../left", "Knowledge/right"]),
    ("candidate_refs", ["[[Knowledge/left]]", "Knowledge/right"]),
    ("candidate_refs", ["Knowledge/left.md", "Knowledge/right"]),
    ("candidate_refs", ["Knowledge/left", "Knowledge/right", "Knowledge/third"]),
    ("activation_key", "f" * 20),
])
def test_even_resigned_invalid_candidate_params_cannot_suppress(isolated_task_ledger, field, value):
    row = _row()
    row["trace"][0]["controller_disposition"]["candidate_params"][field] = value
    _record(isolated_task_ledger, _reseal(row))
    assert isolated_task_ledger.maintenance_no_change_keys() == set()


@pytest.mark.parametrize("shape", ["duplicate", "tool_wrapper", "additional_tool", "mapping", "too_large"])
def test_ambiguous_or_noncontroller_trace_cannot_suppress(isolated_task_ledger, shape):
    row = _row()
    if shape == "duplicate":
        row["trace"] *= 2
    elif shape == "tool_wrapper":
        row["trace"] = [{"tool": "harness.status", "obs": row["trace"][0]}]
    elif shape == "additional_tool":
        row["trace"].append({"tool": "task.complete", "accepted": True})
    elif shape == "mapping":
        row["trace"] = row["trace"][0]
    else:
        row["trace"][0]["controller_disposition"]["reason"] = "x" * 32_000
    _record(isolated_task_ledger, row)
    assert isolated_task_ledger.maintenance_no_change_keys() == set()


def test_params_digest_attests_original_numeric_encoding(isolated_task_ledger):
    row = _row()
    row["trace"][0]["controller_disposition"]["candidate_params"]["candidate_signals"]["score"] = 1.0
    _record(isolated_task_ledger, row)
    assert isolated_task_ledger.maintenance_no_change_keys() == set()


@pytest.mark.parametrize("correction", ["metadata", "body"])
def test_owner_no_change_suppresses_current_candidate_until_revision_changes(isolated_task_ledger, monkeypatch, tmp_path, correction):
    monkeypatch.setattr(CONFIG, "vault_dir", tmp_path / "vault")
    shared = "alpha bridge connection topology graph vault maintenance semantic accepted article relationship context evidence useful deterministic "
    left_body = shared + "left cedar birch maple oak pine spruce willow aspen elm beech"
    right_body = shared + "right amber bronze cobalt denim emerald fuchsia gold hazel indigo jade"
    vault.write_note("Knowledge/left.md", {"kind": "knowledge", "title": "Alpha bridge"}, left_body)
    vault.write_note("Knowledge/right.md", {"kind": "knowledge", "title": "Alpha connection"}, right_body)
    candidate = next(row for row in maintenance._maintenance_candidates()["candidates"] if row["kind"] == "missing_link")
    params = {**_params(), "candidate_key": candidate["candidate_key"], "activation_key": candidate["candidate_key"],
              "candidate_refs": candidate["refs"], "candidate_revision": candidate["candidate_revision"]}
    # The owner reviewed newer accepted Articles; original activation stays intact.
    reviewed_meta = {"kind": "knowledge", "title": "Alpha bridge"}
    if correction == "metadata":
        reviewed_meta["retrieval"] = False
    else:
        left_body += " The owner corrected an unsupported detail."
    vault.write_note("Knowledge/left.md", reviewed_meta, left_body)
    reviewed = next(row for row in maintenance._maintenance_candidates()["candidates"] if row["kind"] == "missing_link")
    assert reviewed["candidate_revision"] != params["candidate_revision"]
    assert (reviewed["candidate_key"] != params["candidate_key"]) is (correction == "body")
    hashes = [{"ref": ref, "sha256": hashlib.sha256((CONFIG.vault_dir / (ref + ".md")).read_bytes()).hexdigest()}
              for ref in params["candidate_refs"]]
    _record(isolated_task_ledger, _row(params, reviewed_revision=reviewed["candidate_revision"],
                                     reviewed_candidate_key=reviewed["candidate_key"], reviewed_articles=hashes))
    before = {path: path.read_bytes() for path in CONFIG.vault_dir.rglob("*.md")}

    result = maintenance._maintenance_candidates()
    assert not any(row["kind"] == "missing_link" for row in result["candidates"])
    assert result["unchanged_no_change_count"] == 1
    assert before == {path: path.read_bytes() for path in before}
    vault.write_note("Knowledge/left.md", {"kind": "knowledge", "title": "Alpha bridge"}, left_body + " A new accepted fact.")
    reopened = next(row for row in maintenance._maintenance_candidates()["candidates"] if row["kind"] == "missing_link")
    assert reopened["candidate_revision"] != reviewed["candidate_revision"]

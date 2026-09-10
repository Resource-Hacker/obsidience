"""Frozen evaluations cannot dispatch, weaken criteria, or hide incomplete pairs."""

from __future__ import annotations

import asyncio
from copy import deepcopy

import pytest

from obsidience.harness.execution.evaluation import FrozenTrial, compare_observations, validate_suite


def case(case_id="training", split="train"):
    return {"id": case_id, "split": split, "objective": "Read the exact Article and report its finding.",
            "max_steps": 3, "responses": [{"tool": "vault.read", "args": {"ref": "Knowledge/one"},
                                           "result": {"finding": "verified fixture"}}],
            "expected": {"status": "completed", "required_tools": ["vault.read"],
                         "outcome": "no_change", "summary_contains": ["verified fixture"], "max_tool_calls": 1}}


def completion(**changes):
    return {"status": "completed", "summary": "The verified fixture needs no change.",
            "outcome": "no_change", **changes}


def call(trial, name, args):
    return asyncio.run(trial.handle(name, args))


def observations(train=False, holdout=True, repetitions=1):
    return [{"case_id": identity, "split": split, "repetition": repetition, "passed": passed, "error": None}
            for identity, split, passed in [("training", "train", train), ("protected", "holdout", holdout)]
            for repetition in range(1, repetitions + 1)]


def test_exact_fixture_and_separate_completion_grade_are_frozen():
    specification = case()
    trial = FrozenTrial(specification)
    specification["responses"][0]["result"]["finding"] = "changed after construction"
    specification["expected"]["summary_contains"] = ["weakened"]
    args = {"ref": "Knowledge/one"}
    assert call(trial, "vault.read", args) == {"done": False, "observation": '{"finding":"verified fixture"}'}
    args["ref"] = "modified afterward"
    result = call(trial, "task.complete", completion())
    assert result["done"] and result["status"] == "completed"
    assert trial.passed is True and trial.error is None and trial.tool_count == 1
    assert trial.calls[0] == {"tool": "vault.read", "args": {"ref": "Knowledge/one"}}
    assert call(trial, "unknown.mutation", {}) == result
    assert len(trial.calls) == 2


@pytest.mark.parametrize("tool,args", [
    ("vault.propose", {"ref": "Knowledge/one"}),
    ("vault.read", {"ref": "Knowledge/two"}),
    ("vault.read", {"ref": "Knowledge/one", "extra": True}),
])
def test_unmatched_calls_terminate_with_fixture_error_and_never_fall_back(tool, args):
    trial = FrozenTrial(case())
    result = call(trial, tool, args)
    assert result["done"] is True and result["status"] == "failed"
    assert trial.passed is False and trial.error and trial.tool_count == 1
    assert call(trial, "task.complete", completion()) == result
    assert trial.passed is False


@pytest.mark.parametrize("changes", [
    {"status": "review"}, {"outcome": "changed"}, {"summary": "Unsupported answer"},
    {"unexpected": "ignore the expected criteria"}, {"evidence": "not a list"},
])
def test_declared_completion_status_does_not_override_fixed_grade(changes):
    trial = FrozenTrial(case())
    call(trial, "vault.read", {"ref": "Knowledge/one"})
    args = completion(**changes)
    result = call(trial, "task.complete", args)
    assert result["done"] is True and result["status"] == args["status"]
    assert result["summary"] == args["summary"]
    assert trial.passed is False and trial.error is None


@pytest.mark.parametrize("missing", ["status", "summary"])
def test_completion_requires_explicit_fields(missing):
    trial = FrozenTrial(case())
    args = completion()
    del args[missing]
    assert call(trial, "task.complete", args)["done"] is True
    assert trial.passed is False and trial.error is None


def test_required_tools_and_call_count_are_independent_fixed_criteria():
    missing = FrozenTrial(case())
    call(missing, "task.complete", completion())
    assert missing.passed is False
    repeated = FrozenTrial(case())
    for _ in range(2):
        assert call(repeated, "vault.read", {"ref": "Knowledge/one"})["done"] is False
    assert call(repeated, "task.complete", completion())["status"] == "completed"
    assert repeated.passed is False and repeated.tool_count == 2


def test_step_exhaustion_is_model_failure_not_a_fixture_gap():
    specification = case()
    specification["max_steps"] = 1
    trial = FrozenTrial(specification)
    result = call(trial, "vault.read", {"ref": "Knowledge/one"})
    assert result["done"] is True and result["status"] == "failed"
    assert trial.passed is False and trial.error is None


@pytest.mark.parametrize("tool,args", [(None, {}), ("vault.read", []), ("vault.read", {"value": float("inf")})])
def test_invalid_invocation_records_an_error_for_the_persistence_owner(tool, args):
    trial = FrozenTrial(case())
    result = call(trial, tool, args)
    assert result["done"] is True and result["status"] == "failed"
    assert trial.error and trial.passed is False


def test_expected_failed_task_can_pass_the_declared_evaluation():
    specification = case()
    specification["expected"]["status"] = "failed"
    trial = FrozenTrial(specification)
    call(trial, "vault.read", {"ref": "Knowledge/one"})
    assert call(trial, "task.complete", completion(status="failed"))["status"] == "failed"
    assert trial.passed is True


def test_fixture_keys_are_exact_and_argument_key_order_is_irrelevant():
    specification = case()
    specification["responses"][0]["args"] = {"one": 1, "two": False}
    trial = FrozenTrial(specification)
    assert call(trial, "vault.read", {"two": False, "one": 1})["done"] is False
    for args in ({"one": True, "two": False}, {"one": 1.0, "two": False}):
        mismatch = FrozenTrial(specification)
        assert call(mismatch, "vault.read", args)["done"] is True
        assert mismatch.error
    specification["responses"].append({"tool": "vault.read", "args": {"two": False, "one": 1}, "result": "duplicate"})
    with pytest.raises(ValueError, match="duplicate"):
        FrozenTrial(specification)


@pytest.mark.parametrize("mutate", [
    lambda value: value.update(max_steps=True), lambda value: value.update(max_steps=9),
    lambda value: value.update(unrecognized=True), lambda value: value.update(bindings=[]),
    lambda value: value["responses"][0].update(args={"value": float("nan")}),
    lambda value: value["responses"][0].update(args={1: "not a JSON key"}),
    lambda value: value["responses"][0].update(tool="task.complete"),
    lambda value: value["expected"].update(max_tool_calls=8),
    lambda value: value["expected"].update(required_tools=["unknown.tool"]),
])
def test_invalid_case_contracts_are_rejected_before_execution(mutate):
    specification = case()
    mutate(specification)
    with pytest.raises(ValueError):
        FrozenTrial(specification)


def test_suite_requires_distinct_training_and_holdout_cases_and_bounded_repetition():
    suite = {"schemaVersion": 1, "cases": [case(), case("protected", "holdout")], "repetitions": 3}
    assert validate_suite(suite) is None
    variants = [dict(suite, schemaVersion=True), dict(suite, repetitions=4), dict(suite, repetitions=0),
                dict(suite, cases=[case()]), dict(suite, cases=[case(), case()]),
                dict(suite, cases=[case(), case("another")]), dict(suite, override=True)]
    for invalid in variants:
        with pytest.raises(ValueError):
            validate_suite(invalid)


def test_comparison_requires_strict_training_improvement_with_all_candidate_cases_passing():
    result = compare_observations(observations(), observations(train=True))
    assert result["verdict"] == "passed"
    assert result["counts"] == {"total": 2, "train": 1, "holdout": 1, "parent_passed": 1,
                                "child_passed": 2, "fixed": 1, "regressed": 0, "unchanged": 1}
    assert result["fixed"] == [{"case_id": "training", "split": "train", "repetition": 1}]
    assert compare_observations(observations(train=True), observations(train=True))["verdict"] == "not_improved"
    assert compare_observations(observations(), observations())["verdict"] == "not_improved"
    assert compare_observations(observations(train=True, holdout=False), observations(train=True))["verdict"] == "not_improved"


def test_protected_regression_cannot_be_offset_by_training_gain_or_faster_mean():
    parent, child = observations(), observations(train=True, holdout=False)
    for row in parent:
        row["elapsed_ms"] = 100
    for row in child:
        row["elapsed_ms"] = 1
    result = compare_observations(parent, child)
    assert result["verdict"] == "regressed"
    assert result["counts"]["fixed"] == result["counts"]["regressed"] == 1
    assert result["regressed"][0]["split"] == "holdout"


@pytest.mark.parametrize("side", ["parent", "child"])
@pytest.mark.parametrize("corruption", ["drop_error", "error", "drop_row", "duplicate", "reorder", "boolean_repetition", "string_pass"])
def test_incomplete_or_invalid_observations_cannot_look_like_improvement(side, corruption):
    parent, child = observations(repetitions=2), observations(train=True, repetitions=2)
    rows = parent if side == "parent" else child
    if corruption == "drop_error":
        del rows[0]["error"]
    elif corruption == "error":
        rows[0]["error"] = "fixture gap"
    elif corruption == "drop_row":
        rows.pop()
    elif corruption == "duplicate":
        rows[1] = deepcopy(rows[0])
    elif corruption == "reorder":
        rows.reverse()
    elif corruption == "boolean_repetition":
        rows[0]["repetition"] = True
    else:
        rows[0]["passed"] = "true"
    assert compare_observations(parent, child)["verdict"] == "incomplete"


def test_one_failed_repetition_is_not_hidden_by_other_successes():
    parent, child = observations(repetitions=3), observations(train=True, repetitions=3)
    child[1]["passed"] = False
    result = compare_observations(parent, child)
    assert result["verdict"] == "not_improved" and result["counts"]["fixed"] == 2
    assert compare_observations([], [])["verdict"] == "incomplete"


@pytest.mark.parametrize("field,value", [("status", "unknown"), ("tool_count", True),
                                        ("duration_ms", -1), ("prompt_tokens", "100"),
                                        ("actions", [{"tool": "vault.read", "args": []}])])
def test_invalid_recorded_metadata_cannot_attest_a_pass(field, value):
    parent, child = observations(), observations(train=True)
    child[0][field] = value
    assert compare_observations(parent, child)["verdict"] == "incomplete"

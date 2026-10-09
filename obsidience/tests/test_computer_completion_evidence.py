"""Computer outcomes require actual executor witnesses, not public intent."""

from __future__ import annotations

import json
from types import SimpleNamespace as NS

import pytest

from obsidience.harness.capabilities.task import complete
from obsidience.harness.execution import executor

EDGE = {"kind": "application", "name": "microsoft_edge"}
TFT = {"kind": "application", "name": "teamfight_tactics"}


def terminal(status="completed", summary="The requested result is established.", **extra):
    return {"tool": "task.complete", "args": {"status": status, "summary": summary, **extra}}


def observed(*, attached=True):
    result = {"observation": {
        "status": "observed",
        "target": {"kind": "pane", "name": "reader", "surface": "usbc"},
        "visual_evidence": {"attached": True, "freshness": "validated_after_capture"},
    }}
    if attached:
        result["_private_image_png"] = b"private-test-pixels"
    return result


def clicked(*, attached=True, target=None):
    actual_target = {**(target or TFT), "surface": "samsung"}
    result = {
        "status": "completed",
        "target": actual_target,
        "delivery": "acknowledged",
        "effect": {"kind": "click", "label": "Play", "verified": True},
        "observation": {
            "status": "observed", "target": dict(actual_target),
            "visual_evidence": {"attached": True, "freshness": "validated_after_capture"},
        },
    }
    if attached:
        result["_private_image_png"] = b"private-test-pixels"
    return result


@pytest.mark.parametrize("patch", [
    {"status": "failed"},
    {"delivery": "uncertain"},
    {"effect": None},
    {"effect": {"kind": "click", "label": "Play", "verified": False}},
    {"effect": {"kind": "click", "label": "Play", "verified": 1}},
    {"effect": {"kind": "scroll", "label": "Play", "verified": True}},
    {"effect": {"kind": "click", "label": "", "verified": True}},
    {"effect": {"kind": "click", "label": "x" * 301, "verified": True}},
    {"effect": {"kind": "click", "label": "Play\nNext", "verified": True}},
    {"observation": None},
    {"observation": {"status": "unavailable"}},
])
def test_incomplete_click_result_is_not_an_attested_effect(patch):
    result = clicked()
    result.update(patch)
    witness = complete.computer_completion_evidence("computer.act", result, image_attached=True)
    assert witness == {"verified": False, "target": TFT}


@pytest.mark.parametrize("omitted", ["effect", "verified_scope", "semantic_postcondition_verified"])
def test_unscoped_verified_action_witness_cannot_complete(omitted):
    witness = complete.computer_completion_evidence("computer.act", clicked(), image_attached=True)
    witness.pop(omitted)
    result = complete.execute(terminal()["args"], {
        "task_note": NS(ref="Tasks/executive/operate", kind="task", meta={}),
        "params": {"computer_outcome": "action", "computer_scope": "input"},
        "trace": [{"tool": "computer.act", "completion_evidence": witness}],
    })
    assert result["accepted"] is False


def test_bare_verified_flag_without_a_target_is_not_a_completion_witness():
    task = NS(ref="Tasks/executive/operate", kind="task", meta={})
    result = complete.execute(terminal()["args"], {
        "task_note": task, "params": {"computer_outcome": "focus"},
        "trace": [{"tool": "window.activate", "completion_evidence": {"verified": True}}],
    })
    assert result["accepted"] is False


@pytest.mark.parametrize("outcome,scope", [
    (None, None), ("", None), ("answer", None), ("answer", ""),
    ("focus", None), ("placement", None), ("observe", None), ("launch", None),
    ("action", "input"), ("action", "state"),
])
def test_controller_outcome_validator_accepts_only_declared_contracts(outcome, scope):
    assert complete.validate_computer_outcome(outcome, scope) is None


@pytest.mark.parametrize("outcome,scope", [
    ("action", None), ("action", ""), ("action", "answer"), ("action", False),
    ("focus", "input"), (None, "state"), ("answer", "state"),
    ("match", None), (False, None), ([], None), ({}, None),
])
def test_controller_outcome_validator_rejects_ambiguous_or_malformed_scope(outcome, scope):
    assert complete.validate_computer_outcome(outcome, scope)


def state_completion_context(*, current_image=True):
    witness = complete.computer_completion_evidence("computer.act", clicked(), image_attached=True)
    context = {
        "task_note": NS(ref="Tasks/executive/operate", kind="task", meta={}),
        "objective": "Establish the requested application state.",
        "params": {"computer_outcome": "action", "computer_scope": "state",
                   "application": "teamfight_tactics"},
        "trace": [{"tool": "computer.act", "completion_evidence": witness}],
    }
    if current_image:
        context["_computer_response_observation"] = dict(witness)
    return context


def visual_verification(status="established"):
    return {"status": status, "observation": "The fresh image shows the requested destination state."}


def test_state_completion_requires_model_finding_in_addition_to_real_current_postimage():
    context = state_completion_context()
    result = complete.execute(terminal()["args"], context)
    assert result["accepted"] is False
    assert "verification" in result["error"]


@pytest.mark.parametrize("change", ["absent", "unverified", "wrong_target", "historical_only"])
def test_model_finding_cannot_replace_current_same_target_postimage(change):
    context = state_completion_context(current_image=change not in {"absent", "historical_only"})
    if change == "unverified":
        context["_computer_response_observation"]["verified"] = False
    elif change == "wrong_target":
        context["_computer_response_observation"]["target"] = EDGE
    elif change == "historical_only":
        context["historical_execution_evidence"] = context["trace"]
    result = complete.execute(terminal(verification=visual_verification())["args"], context)
    assert result["accepted"] is False
    assert "actual fresh post-action image" in result["error"]


def test_state_completion_binds_current_visual_finding_without_promoting_its_trust():
    context = state_completion_context()
    before = json.loads(json.dumps(context["trace"]))
    finding = visual_verification()
    result = complete.execute(terminal(verification=finding)["args"], context)
    assert result["accepted"] is True
    assert result["verification"] == finding
    assert context["trace"] == before
    assert context["trace"][0]["completion_evidence"]["semantic_postcondition_verified"] is False
    assert "semantic_postcondition_verified" not in result


def test_later_current_observation_can_support_state_after_same_task_verified_click():
    context = state_completion_context()
    observation = {"verified": True, "target": TFT}
    context["trace"].append({"tool": "computer.observe", "completion_evidence": observation})
    context["_computer_response_observation"] = observation
    assert complete.execute(terminal(verification=visual_verification())["args"], context)["accepted"] is True


@pytest.mark.parametrize("change", ["no_action", "failed_action", "later_uncertain_action"])
def test_current_image_and_model_finding_still_require_same_task_successful_action(change):
    context = state_completion_context()
    if change == "no_action":
        context["trace"] = [{"tool": "computer.observe", "completion_evidence": {"verified": True, "target": TFT}}]
    elif change == "failed_action":
        context["trace"][0]["completion_evidence"]["verified"] = False
    else:
        context["trace"].append({"tool": "computer.act", "completion_evidence": {"verified": False, "target": TFT}})
    assert complete.execute(terminal(verification=visual_verification())["args"], context)["accepted"] is False


def test_visual_not_established_cannot_complete_requested_state_but_failure_is_allowed():
    context = state_completion_context()
    finding = visual_verification("not_established")
    assert complete.execute(terminal(verification=finding)["args"], context)["accepted"] is False
    context["trace"] = []
    context.pop("_computer_response_observation")
    result = complete.execute(terminal("failed", "The requested state is not established.", verification=finding)["args"], context)
    assert result["accepted"] is True
    assert result["verification"] == finding


@pytest.mark.parametrize("finding", [
    {}, {"status": "established"},
    {"status": True, "observation": "A state is visible."},
    {"status": "established", "observation": " "},
    {"status": "established", "observation": "x" * 1001},
    {"status": "established", "observation": "untrusted\ncontrol"},
    {"status": "established", "observation": "The requested state is visible.", "verified": True},
])
def test_visual_finding_schema_is_bounded_and_cannot_self_assert_extra_authority(finding):
    result = complete.execute(terminal(verification=finding)["args"], state_completion_context())
    assert result["accepted"] is False
    assert "verification requires exactly" in result["error"]


def test_invalid_controller_scope_cannot_turn_query_into_success_but_can_report_failure():
    context = {"task_note": NS(ref="Tasks/query", kind="task", meta={}),
               "params": {"computer_outcome": "action"}, "trace": []}
    assert complete.execute(terminal()["args"], context)["accepted"] is False
    assert complete.execute(terminal("failed", "The requested scope is missing.")["args"], context)["accepted"] is True



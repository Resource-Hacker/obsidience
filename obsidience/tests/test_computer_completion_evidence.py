"""Computer outcomes require actual executor witnesses, not public intent."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
from types import SimpleNamespace as NS

import pytest

from obsidience.harness.capabilities.task import complete
from obsidience.harness.execution import executor

READER = {"kind": "pane", "name": "reader"}
EDGE = {"kind": "application", "name": "microsoft_edge"}
TFT = {"kind": "application", "name": "teamfight_tactics"}


def terminal(status="completed", summary="The requested result is established.", **extra):
    return {"tool": "task.complete", "args": {"status": status, "summary": summary, **extra}}


@pytest.fixture
def session(monkeypatch):
    """Exercise real dispatch and completion, without a model or desktop effects."""
    task = NS(ref="Tasks/executive/operate", title="Computer Use", kind="task", meta={})
    model = NS(id="isolated", capabilities=("text", "vision", "tools"))

    @asynccontextmanager
    async def lease(_model):
        yield model

    monkeypatch.setattr(executor.model_runtime, "configured_spec", lambda _: model)
    monkeypatch.setattr(executor.model_runtime, "lease", lease)
    monkeypatch.setattr(executor.action_trace, "emit", lambda *_args, **_kwargs: None)

    def run(actions, results=None, *, outcome="focus", allowed=None, task_ref=None,
            application=""):
        responses = iter(actions)
        returned = iter(results or [])
        dispatched = []
        requests = []
        context = {"task": task.ref, "params": {"computer_outcome": outcome}}
        if outcome == "action":
            context["params"]["computer_scope"] = "input"
        if application:
            context["params"]["application"] = application
        if task_ref:
            task.ref = task_ref
            context["task"] = task_ref

        async def chat(messages, **_kwargs):
            requests.append(json.loads(json.dumps(messages)))
            return executor.llm.ChatReply(
                content=json.dumps(next(responses)), finish_reason="stop",
                completion_tokens=8,
            )

        def execute(name, args, ctx):
            if name == "task.complete":
                return complete.execute(args, ctx)
            dispatched.append((name, args))
            value = next(returned)
            if isinstance(value, Exception):
                raise value
            return value

        monkeypatch.setattr(executor.llm, "chat", chat)
        monkeypatch.setattr(executor, "execute_capability", execute)
        trace, status, summary = asyncio.run(executor._execute_session(
            task, model, [{"role": "system", "content": "Isolated test packet"}],
            allowed or [*complete.COMPUTER_OUTCOME_TOOLS.values(), "task.complete"],
            context, "Executive", "none",
        ))
        return NS(trace=trace, status=status, summary=summary, context=context,
                  dispatched=dispatched, requests=requests)

    return run


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


def test_intent_and_model_authored_evidence_cannot_complete_an_effect(session):
    result = session([
        terminal(summary="I am bringing the application to the foreground.",
                 evidence=["The requested window is focused."]),
        terminal("failed", "Which application do you mean?"),
    ])
    assert result.status == "failed"
    assert result.summary == "Which application do you mean?"
    assert result.dispatched == []
    assert result.trace[0]["completion_rejected"] is True
    assert "window.activate" in result.trace[0]["obs"]
    assert result.trace[-1]["accepted"] is True


@pytest.mark.parametrize("tool_result", [
    {"status": "failed", "effect_applied": False, "active": False},
    {"status": "completed", "effect_applied": True, "active": False},
    RuntimeError("Shell unavailable"),
])
def test_failed_or_unverified_focus_does_not_become_success(session, tool_result):
    result = session([
        {"tool": "window.activate", "args": {"target": {"kind": "pane", "name": "reader"}}},
        terminal(), terminal("failed", "The Shell did not verify focus."),
    ], [tool_result])
    assert result.status == "failed"
    assert result.trace[0]["completion_evidence"] == {"verified": False}
    assert result.trace[1]["completion_rejected"] is True


def test_observation_cannot_substitute_for_requested_focus(session):
    result = session([
        {"tool": "computer.observe", "args": {"target": {"kind": "focused"}}},
        terminal(), terminal("failed", "Focus has not been established."),
    ], [observed()])
    assert result.trace[0]["completion_evidence"] == {"verified": True, "target": READER}
    assert result.trace[1]["completion_rejected"] is True
    assert result.status == "failed"


@pytest.mark.parametrize("effect_applied", [True, False])
def test_fresh_focus_including_already_active_is_accepted(session, effect_applied):
    result = session([
        {"tool": "window.activate", "args": {}}, terminal(),
    ], [json.dumps({"status": "completed", "active": True,
                    "effect_applied": effect_applied, "target": READER})])
    assert result.status == "completed"
    assert result.trace[0]["completion_evidence"] == {"verified": True, "target": READER}


def test_latest_requested_tool_failure_supersedes_earlier_success(session):
    result = session([
        {"tool": "window.activate", "args": {"target": {"name": "reader"}}},
        {"tool": "window.activate", "args": {"target": {"name": "terminal"}}},
        terminal(), terminal("failed", "The second target was unavailable."),
    ], [{"status": "completed", "active": True, "target": READER}, {"status": "failed"}])
    assert result.status == "failed"
    assert result.trace[2]["completion_rejected"] is True


@pytest.mark.parametrize("surface,accepted", [("usbc", True), ("samsung", False)])
def test_placement_uses_returned_destination_post_state(session, surface, accepted):
    actions = [{"tool": "window.place", "args": {}}, terminal()]
    if not accepted:
        actions.append(terminal("failed", "The requested destination was not observed."))
    result = session(actions, [{
        "status": "completed", "effect_applied": False,
        "target": READER,
        "destination": {"surface": "usbc"}, "observed": {"surface": surface},
    }], outcome="placement")
    assert (result.status == "completed") is accepted


@pytest.mark.parametrize("state,ready,window,accepted", [
    ("ready", True, {"app_id": "test"}, True),
    ("starting", False, None, False),
    ("ready", True, None, False),
])
def test_launch_dispatch_requires_a_real_ready_window(session, state, ready, window, accepted):
    actions = [{"tool": "application.launch", "args": {}}, terminal()]
    if not accepted:
        actions.append(terminal("failed", "The application is starting; readiness is unverified."))
    result = session(actions, [{"state": state, "ready": ready, "window": window,
                               "application": "microsoft_edge", "dispatched": True}], outcome="launch")
    assert (result.status == "completed") is accepted


@pytest.mark.parametrize("attached", [True, False])
def test_visual_answer_requires_the_actual_ephemeral_image(session, attached):
    actions = [{"tool": "computer.observe", "args": {}}, terminal()]
    if not attached:
        actions.append(terminal("failed", "The visual evidence was unavailable."))
    result = session(actions, [observed(attached=attached)], outcome="observe")
    assert (result.status == "completed") is attached
    assert "private-test-pixels" not in json.dumps(result.trace)
    assert "_private_image_png" not in json.dumps(result.trace)


def test_input_acknowledgement_and_control_grounding_do_not_prove_postcondition(session):
    result = session([
        {"tool": "computer.act", "args": {}}, terminal(),
        terminal("failed", "The requested postcondition was not verified."),
    ], [{"delivery": "acknowledged", "post_observation": {
        "grounding": {"matched": True, "ambiguous": False, "candidate_count": 1},
    }}], outcome="action")
    assert result.status == "failed"
    assert result.trace[1]["completion_rejected"] is True


def test_verified_click_has_only_typed_click_scope_with_actual_fresh_postimage(session):
    args = {"application": "teamfight_tactics", "action": "click",
            "target": "play", "postcondition": "game_started"}
    returned = clicked()
    # A Capability result cannot elevate an arbitrary semantic claim into the
    # controller witness, even if that field arrives alongside a real click.
    returned["semantic_postcondition_verified"] = True
    returned["postcondition"] = "game_started"
    result = session([
        {"tool": "computer.act", "args": args},
        terminal(summary="Clicked Play. The image does not establish that the game started."),
    ], [returned], outcome="action", application="teamfight_tactics")
    assert result.status == "completed"
    assert result.dispatched == [("computer.act", args)]
    witness = result.trace[0]["completion_evidence"]
    assert witness == {
        "verified": True, "target": TFT,
        "effect": {"kind": "click", "label": "play"},
        "verified_scope": "click", "semantic_postcondition_verified": False,
    }
    assert "game_started" not in json.dumps(witness)
    assert "private-test-pixels" not in json.dumps(result.trace)
    assert "_private_image_png" not in json.dumps(result.trace)
    assert result.requests[-1][-1]["content"][1]["type"] == "image_url"


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


@pytest.mark.parametrize("change", ["missing_image", "stale", "missing_visual_claim", "wrong_target", "wrong_surface"])
def test_click_requires_its_actual_fresh_matching_postimage(session, change):
    returned = clicked(attached=change != "missing_image")
    if change == "stale":
        returned["observation"]["visual_evidence"]["freshness"] = "stale"
    elif change == "missing_visual_claim":
        returned["observation"]["visual_evidence"]["attached"] = False
    elif change == "wrong_target":
        returned["observation"]["target"] = {**EDGE, "surface": "samsung"}
    elif change == "wrong_surface":
        returned["observation"]["target"]["surface"] = "usb-c"
    result = session([
        {"tool": "computer.act", "args": {"application": "teamfight_tactics", "target": "play"}},
        terminal(), terminal("failed", "The click result lacks matching fresh evidence."),
    ], [returned], outcome="action", application="teamfight_tactics")
    assert result.status == "failed"
    assert result.trace[0]["completion_evidence"] == {"verified": False, "target": TFT}
    assert result.trace[1]["completion_rejected"] is True


def test_verified_click_to_wrong_application_cannot_complete_requested_action(session):
    result = session([
        {"tool": "computer.act", "args": {"application": "microsoft_edge", "target": "Play"}},
        terminal(), terminal("failed", "The click result belongs to another application."),
    ], [clicked()], outcome="action", application="microsoft_edge")
    assert result.status == "failed"
    assert result.trace[0]["completion_evidence"]["verified_scope"] == "click"
    assert result.trace[1]["completion_rejected"] is True
    assert "requested application" in result.trace[1]["obs"]


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


def test_later_failed_action_supersedes_verified_click(session):
    result = session([
        {"tool": "computer.act", "args": {"application": "teamfight_tactics", "target": "Play"}},
        {"tool": "computer.act", "args": {"application": "teamfight_tactics", "target": "Next"}},
        terminal(), terminal("failed", "The later action did not complete."),
    ], [clicked(), {"status": "failed"}], outcome="action", application="teamfight_tactics")
    assert result.status == "failed"
    assert result.trace[0]["completion_evidence"]["verified"] is True
    assert result.trace[1]["completion_evidence"]["verified"] is False
    assert result.trace[2]["completion_rejected"] is True


def test_unavailable_tool_is_not_executed_or_attested(session):
    result = session([
        {"tool": "window.activate", "args": {}}, terminal(),
        terminal("failed", "Focus is unavailable in this Task."),
    ], allowed=["task.complete"])
    assert result.status == "failed"
    assert result.dispatched == []
    assert result.trace[0]["completion_evidence"] == {"verified": False}


def test_ordinary_query_answer_needs_no_computer_effect(session):
    result = session([terminal(summary="Yes, I can hear you.")],
                     outcome="", task_ref="Tasks/query")
    assert result.status == "completed"
    assert result.summary == "Yes, I can hear you."
    assert result.dispatched == []


def test_unclassified_computer_outcome_still_needs_actual_evidence(session):
    result = session([terminal(), terminal("failed", "Which pane do you mean?")], outcome="")
    assert result.status == "failed"
    assert result.trace[0]["completion_rejected"] is True


@pytest.mark.parametrize("outcome,name,tool_result", [
    ("focus", "window.activate", {"status": "completed", "active": True, "target": TFT}),
    ("placement", "window.place", {"status": "completed", "target": TFT,
        "destination": {"surface": "usbc"}, "observed": {"surface": "usbc"}}),
    ("launch", "application.launch", {"state": "ready", "ready": True,
        "application": "teamfight_tactics", "window": {"app_id": "tft"}}),
    ("observe", "computer.observe", {"observation": {"status": "observed", "target": TFT,
        "visual_evidence": {"attached": True, "freshness": "validated_after_capture"}},
        "_private_image_png": b"private-test-pixels"}),
])
def test_verified_wrong_application_cannot_satisfy_explicit_binding(session, outcome, name, tool_result):
    args = {"application": "microsoft_edge"} if name == "application.launch" else {"target": EDGE}
    result = session([
        {"tool": name, "args": args},
        terminal(evidence=["Microsoft Edge is the target and the result is verified."]),
        terminal("failed", "The Tool result belongs to a different application."),
    ], [tool_result], outcome=outcome, application="microsoft_edge")
    assert result.trace[0]["completion_evidence"] == {"verified": True, "target": TFT}
    assert result.trace[1]["completion_rejected"] is True
    assert "requested application" in result.trace[1]["obs"]
    assert result.status == "failed"


def test_verified_explicit_application_uses_bounded_semantic_identity_only(session):
    result = session([
        {"tool": "window.activate", "args": {"target": EDGE}}, terminal(),
    ], [{"status": "completed", "active": True, "target": {
        "kind": "application", "name": "Microsoft Edge", "surface": "samsung",
        "window_id": "must-not-enter-acceptance-witness", "pid": 123,
        "geometry": {"x": 10, "width": 100},
    }}], application="microsoft_edge")
    assert result.status == "completed"
    assert result.trace[0]["completion_evidence"] == {"verified": True, "target": EDGE}


@pytest.mark.parametrize("target", [None, {"kind": "pane", "name": "microsoft_edge"}])
def test_missing_or_wrong_kind_identity_cannot_satisfy_application(session, target):
    result = session([
        {"tool": "window.activate", "args": {"target": EDGE}}, terminal(),
        terminal("failed", "The application was not verified."),
    ], [{"status": "completed", "active": True, "target": target}], application="microsoft_edge")
    assert result.status == "failed"
    assert result.trace[1]["completion_rejected"] is True


@pytest.mark.parametrize("observed_tile,accepted", [
    ({"left": 0, "top": 0, "right": 1, "bottom": 1}, True),
    ({"left": 1, "top": 0, "right": 2, "bottom": 1}, False),
    ({"left": False, "top": 0, "right": 1, "bottom": 1}, False),
    (None, False),
])
def test_tile_placement_requires_exact_typed_attested_edges(session, observed_tile, accepted):
    actions = [{"tool": "window.place", "args": {"target": EDGE}}, terminal()]
    if not accepted:
        actions.append(terminal("failed", "The requested tile was not verified."))
    result = session(actions, [{
        "status": "completed", "effect_applied": True, "target": EDGE,
        "destination": {"surface": "usbc", "tile": {"left": 0, "top": 0, "right": 1, "bottom": 1}},
        "observed": {"surface": "usbc", "tile": observed_tile},
    }], outcome="placement", application="microsoft_edge")
    assert (result.status == "completed") is accepted


@pytest.mark.parametrize("outcome,name,args", [
    ("focus", "window.activate", {"target": TFT}),
    ("placement", "window.place", {"target": TFT, "destination": {"surface": "usbc"}}),
    ("launch", "application.launch", {"application": "teamfight_tactics"}),
    ("observe", "computer.observe", {"target": TFT, "query": "What is visible?"}),
    ("action", "computer.act", {"application": "teamfight_tactics", "target": "Shop"}),
    ("focus", "window.activate", {"target": {"kind": "pane", "name": "microsoft_edge"}}),
])
def test_explicit_contradictory_target_is_rejected_before_dispatch(session, outcome, name, args):
    result = session([
        {"tool": name, "args": args},
        terminal("failed", "The requested target was not dispatched."),
    ], outcome=outcome, application="microsoft_edge")
    assert result.dispatched == []
    assert "controller_target_mismatch" in result.trace[0]["obs"]
    assert "not_dispatched" in result.trace[0]["obs"]
    assert result.trace[0]["completion_evidence"] == {"verified": False}


def test_focused_observation_resolves_normally_but_must_return_requested_application(session):
    tool_result = observed()
    tool_result["observation"]["target"] = TFT
    args = {"target": {"kind": "focused"}, "query": "What is visible?"}
    result = session([
        {"tool": "computer.observe", "args": args}, terminal(),
        terminal("failed", "The focused application is not the requested application."),
    ], [tool_result], outcome="observe", application="microsoft_edge")
    assert result.dispatched == [("computer.observe", args)]
    assert result.trace[1]["completion_rejected"] is True


def test_canonical_alias_target_is_checked_without_rewriting_arguments(session):
    args = {"target": {"kind": "application", "name": "Microsoft Edge"}}
    result = session([
        {"tool": "window.activate", "args": args}, terminal(),
    ], [{"status": "completed", "active": True, "target": EDGE}], application="microsoft_edge")
    assert result.status == "completed"
    assert result.dispatched == [("window.activate", args)]


def test_bare_verified_flag_without_a_target_is_not_a_completion_witness():
    task = NS(ref="Tasks/executive/operate", kind="task", meta={})
    result = complete.execute(terminal()["args"], {
        "task_note": task, "params": {"computer_outcome": "focus"},
        "trace": [{"tool": "window.activate", "completion_evidence": {"verified": True}}],
    })
    assert result["accepted"] is False


def test_predispatch_target_correction_delivers_only_the_requested_application(session):
    corrected = {"target": EDGE}
    result = session([
        {"tool": "window.activate", "args": {"target": TFT}},
        {"tool": "window.activate", "args": corrected}, terminal(),
    ], [{"status": "completed", "active": True, "target": EDGE}], application="microsoft_edge")
    assert result.dispatched == [("window.activate", corrected)]
    assert result.status == "completed"
    assert "Nothing was dispatched" in result.trace[0]["obs"]


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


@pytest.mark.parametrize("outcome", list(complete.COMPUTER_OUTCOME_TOOLS))
def test_query_cannot_complete_a_controller_bound_computer_outcome(session, outcome):
    result = session([
        terminal(summary="I completed the requested action."),
        terminal("failed", "The selected Task does not provide the requested operation."),
    ], task_ref="Tasks/query", outcome=outcome)
    assert result.status == "failed"
    assert result.trace[0]["completion_rejected"] is True
    assert "selected Task does not match" in result.trace[0]["obs"]
    assert result.dispatched == []


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


def test_exact_scene_application_binding_needs_no_registry_entry(session):
    app = {"kind": "application", "name": "click-fixture.py"}
    result = session([
        {"tool": "window.activate", "args": {"target": app}}, terminal(),
    ], [{"status": "completed", "active": True, "target": app}], application=app["name"])
    assert result.status == "completed"
    assert result.dispatched == [("window.activate", {"target": app})]
    assert complete.computer_request_target_error("window.activate", {"target": TFT},
                                                {"params": {"application": app["name"]}})

"""Real current-Shell click orchestration with an isolated command boundary."""
from __future__ import annotations

import io
import json
import threading
from types import SimpleNamespace as NS
from dataclasses import replace

import pytest
from PIL import Image

from obsidience.harness.capabilities.computer import act
from obsidience.harness.computer import runtime as computer
from obsidience.harness.computer.applications import canonical_application_id, application_window_needles
from obsidience.harness.computer.capture import ScreenCapture, ScreenCaptureError
from obsidience.harness.execution.executor import resolve_spine
from obsidience.harness.capabilities.registry import REGISTRY, resolve
from obsidience.harness.host.scene import EVENT_SCHEMA, ShellSceneCache
from obsidience.harness.knowledge.vault import iter_notes, resolver


def test_application_names_share_the_central_registry() -> None:
    assert canonical_application_id("TFT") == "teamfight_tactics"
    assert canonical_application_id("teamfight_tactics") == "teamfight_tactics"
    assert application_window_needles("TFT") == application_window_needles(
        "teamfight_tactics"
    )


def test_computer_use_spine_is_generic_and_closed() -> None:
    res = resolver()
    task = res.resolve("Tasks/executive/operate")
    assert task is not None and task.title == "Computer Use"
    spine = resolve_spine(task, res)
    assert "error" not in spine
    assert set(spine["tools"]) == {
        "application.launch", "computer.act", "computer.observe", "task.complete",
        "task.create", "window.activate", "window.place",
    }
    assert {skill.title for skill in spine["skills"]} == {
        "Using application.launch", "Using computer.act", "Using computer.observe",
        "Using task.complete", "Using task.create", "Using window.activate", "Using window.place",
    }
    assert {
        "computer.act", "computer.observe", "window.activate", "window.place",
    } <= set(REGISTRY)
    assert not any(
        "play" in note.ref.casefold() and note.kind == "task" for note in iter_notes()
    )


def test_shell_scene_contract_keeps_observation_and_effects_separate() -> None:
    res = resolver()
    observe = res.resolve("Tools/computer.observe")
    observe_skill = res.resolve("Skills/computer.observe")
    scene = res.resolve("Agents/Executive/Architecture/hyprland-shell-scene")
    assert observe is not None and observe_skill is not None and scene is not None
    observe_text = " ".join(observe.body.split())
    skill_text = " ".join(observe_skill.body.split())
    assert '"focused|application|pane"' in observe_text
    assert "unique unfocused target" in observe_text
    assert "Evidence is valid only for its scene and capture revision" in observe_text
    assert "target: {kind, name, surface}" in observe_text
    assert "Display `title` and `focused` are separate observation fields" in observe_text
    assert "After any effect, observe again" not in observe_text
    assert "target_ambiguous" in observe_text
    assert "without changing focus or placement" in skill_text
    assert "action_authorized: false" in skill_text
    assert "application.state" in scene.body and "workspace.state" in scene.body
    assert "runtime state, not durable Knowledge" in scene.body

    operate = res.resolve("Tasks/executive/operate")
    assert operate is not None
    operate_spine = resolve_spine(operate, res)
    assert "error" not in operate_spine
    assert {"computer.observe", "window.activate", "window.place"} <= set(
        operate_spine["tools"]
    )

    pairs = {
        "window.activate": "Skills/window.activate",
        "window.place": "Skills/window.place",
    }
    for tool_ref, skill_ref in pairs.items():
        tool = res.resolve(f"Tools/{tool_ref}")
        skill = res.resolve(skill_ref)
        assert tool is not None and skill is not None
        assert skill.meta["tool"] == f"[[Tools/{tool_ref}]]"
        assert callable(resolve(tool_ref))
        tool_text = " ".join(tool.body.split())
        skill_text = " ".join(skill.body.split())
        assert "canonical registered application ID" in tool_text
        assert "canonical application ID" in skill_text
        assert "exact current `app_id`" in tool_text
        assert "exact current `app_id`" in skill_text
        assert "one unique semantic target" in tool_text
        assert "No match or multiple matches fails closed" in skill_text

    assert res.resolve(
        "ADMECH Workstation/Software/Desktop and Windowing/"
        "dialog-free-kwin-samsung-capture-contract--54070fc1"
    ) is None
    assert res.resolve(
        "ADMECH Workstation/Software/Desktop and Windowing/"
        "kwin-window-management-tool-usage--22f9e5a4"
    ) is None


NOW = 1_000_000_000_000
ARGS = {"application": "TFT", "action": "click", "target": "Play button",
        "point": {"x": 500, "y": 250}, "postcondition": "game_started"}


def png(color):
    data = io.BytesIO()
    Image.new("RGB", (320, 180), color).save(data, format="PNG")
    return data.getvalue()


@pytest.fixture
def pipeline(monkeypatch):
    cache = ShellSceneCache()
    generation = cache.connect()
    workspace = {
        "schema": EVENT_SCHEMA, "type": "workspace.state", "revision": 1,
        "session_locked": False,
        "workspace_tiling": [{"surface_id": surface, "columns": 8, "rows": 2, "zones": 16}
                             for surface in ("samsung", "usb-c", "dp-4")],
    }
    assert cache.accept(generation, workspace)
    window = {
        "window_id": "0x100", "stable_id": "a001", "pid": 42,
        "app_id": "tft-waydroid", "title": "gamescope", "window_kind": "application",
        "pane_id": "", "minimized": False, "visible_on_workspace": True,
        "local_rect": {"x": 10, "y": 20, "width": 640, "height": 360},
    }
    state = NS(cache=cache, generation=generation, workspace=workspace, window=window, revision=0,
               commands=[], captures=[], activations=[], context={},
               pre=png("white"), post=png("blue"), activation_hook=None,
               receipt_hook=None, capture_hook=None,
               receipt={"success": True, "delivery": "acknowledged"},
               capture_error=None, post_timestamp=NOW + 1_000_000)

    def publish(*, active="0x100", awake=True, windows=None):
        state.revision += 1
        assert cache.accept(generation, {
            "schema": EVENT_SCHEMA, "type": "application.state", "surface_id": "samsung",
            "revision": state.revision, "active_window_id": active, "surface_awake": awake,
            "windows": [window] if windows is None else windows,
        })
    state.publish = publish
    publish()
    for surface in ("usb-c", "dp-4"):
        assert cache.accept(generation, {
            "schema": EVENT_SCHEMA, "type": "application.state", "surface_id": surface,
            "revision": 1, "active_window_id": "", "surface_awake": True, "windows": [],
        })

    def bind():
        captured = ScreenCapture(image_png=state.pre, target_kind="toplevel", target="a001",
                                 width=320, height=180, captured_at_unix_ns=NOW - 1_000_000_000)
        state.context["_computer_observation_lease"] = {
            "target": cache.resolve_semantic("application", "teamfight_tactics"),
            "capture": captured, "process_start_time": 12345,
        }
        return state.context["_computer_observation_lease"]
    state.bind = bind
    bind()

    def capture(*, stable_id):
        state.captures.append(stable_id)
        assert stable_id == "a001"
        # The original capture must come from the consumed model-visible lease.
        assert len(state.commands) == len(state.captures), "act recaptured before dispatch instead of using its lease"
        if state.capture_error:
            raise state.capture_error
        if state.capture_hook:
            state.capture_hook()
        return ScreenCapture(image_png=state.post, target_kind="toplevel", target=stable_id,
                             width=320, height=180, captured_at_unix_ns=state.post_timestamp)

    def send(command, result_type, *, timeout, cancel_event):
        state.commands.append(command)
        assert result_type == "window.click.result" and timeout == 6.0
        assert cancel_event is state.context.get("_capability_cancel_event")
        assert "_computer_observation_lease" not in state.context
        if isinstance(state.receipt, Exception):
            raise state.receipt
        if state.receipt_hook:
            state.receipt_hook()
        return state.receipt

    def activate(args):
        state.activations.append(args)
        if state.activation_hook:
            state.activation_hook()
        publish()
        return {"status": "completed"}

    monkeypatch.setattr(computer, "SCENE", cache)
    monkeypatch.setattr(computer, "process_start_time", lambda pid: 12345 if pid == 42 else 0)
    monkeypatch.setattr(computer.time, "time_ns", lambda: NOW)
    monkeypatch.setattr(computer, "capture_screen", capture)
    monkeypatch.setattr(computer, "_send_command", send)
    monkeypatch.setattr(computer, "activate", activate)
    return state


def assert_no_dispatch(pipeline, result):
    assert result["status"] == "failed" and result["delivery"] == "not_dispatched"
    assert pipeline.commands == [] and pipeline.captures == []
    assert "_computer_observation_lease" not in pipeline.context
    assert result["must_not_replay"] is True


def test_image_point_click_uses_the_original_capture_and_only_one_fresh_postimage(pipeline):
    # The exact capture target stays TFT even with another Gamescope window.
    other = pipeline.window | {"window_id": "0x200", "stable_id": "b002", "app_id": "gamescope"}
    pipeline.publish(windows=[other, pipeline.window])
    pipeline.bind()
    result = act.execute(ARGS, pipeline.context)
    assert result["status"] == "completed" and result["delivery"] == "acknowledged"
    assert result["verified_scope"] == "click"
    assert result["semantic_postcondition_verified"] is False
    assert result["effect"]["kind"] == "click" and result["effect"]["verified"] is True
    assert result["effect"]["label"].casefold() == "play button"
    assert result["target"] == {"kind": "application", "name": "teamfight_tactics", "surface": "samsung"}
    assert result["_private_image_png"] == pipeline.post
    assert pipeline.captures == ["a001"] and pipeline.activations == []
    assert len(pipeline.commands) == 1
    command = pipeline.commands[0]
    assert command["type"] == "window.click" and command["window_id"] == "0x100"
    assert command["expected_revision"] == pipeline.revision
    assert command["witness"] == {
        "stable_id": "a001", "pid": 42, "process_start_time": 12345,
        "local_rect": pipeline.window["local_rect"], "image_width": 320, "image_height": 180,
        "x": 160.0, "y": 45.0, "captured_at_unix_ns": NOW - 1_000_000_000,
        "label": "Play button",
    }
    public = json.dumps({key: value for key, value in result.items() if key != "_private_image_png"})
    for private in ("a001", "0x100", "process_start_time", "local_rect", "roi_sha256", '"point"'):
        assert private not in public
    assert "_computer_observation_lease" not in pipeline.context
    pipeline.bind()  # Even a fresh observation cannot grant a second Task action.
    repeat = act.execute(ARGS, pipeline.context)
    assert repeat["status"] == "failed" and repeat["must_not_replay"] is True
    assert "_computer_observation_lease" not in pipeline.context
    assert len(pipeline.commands) == 1 and len(pipeline.captures) == 1


@pytest.mark.parametrize("point", [{"x": 0, "y": 0}, {"x": 999, "y": 999}])
def test_normalized_points_map_inside_native_image_extent(pipeline, point):
    result = act.execute(ARGS | {"point": point}, pipeline.context)
    assert result["status"] == "completed"
    witness = pipeline.commands[0]["witness"]
    assert witness["x"] == pytest.approx(point["x"] * 320 / 1000)
    assert witness["y"] == pytest.approx(point["y"] * 180 / 1000)
    assert 0 <= witness["x"] < 320 and 0 <= witness["y"] < 180


def test_state_outcome_allows_three_distinct_freshly_observed_steps(pipeline, monkeypatch):
    pipeline.context["params"] = {"computer_outcome": "action", "computer_scope": "state"}
    for step in range(3):
        now = NOW + step * 2_000_000_000
        monkeypatch.setattr(computer.time, "time_ns", lambda: now)
        lease = pipeline.bind()
        lease["capture"] = replace(lease["capture"], captured_at_unix_ns=now - 100_000_000)
        pipeline.post_timestamp = now + 1_000_000
        result = act.execute(ARGS | {"target": f"Step {step + 1}"}, pipeline.context)
        assert result["status"] == "completed"
        assert "_computer_observation_lease" not in pipeline.context
    pipeline.bind()
    result = act.execute(ARGS, pipeline.context)
    assert result["status"] == "failed"
    assert len(pipeline.commands) == 3


def test_state_outcome_rejects_reused_pre_action_image(pipeline):
    pipeline.context["params"] = {"computer_outcome": "action", "computer_scope": "state"}
    assert act.execute(ARGS, pipeline.context)["status"] == "completed"
    pipeline.bind()
    assert act.execute(ARGS, pipeline.context)["status"] == "failed"
    assert len(pipeline.commands) == 1


@pytest.mark.parametrize("failure", ["uncertain", "rejected", "postimage", "arguments"])
def test_state_outcome_cannot_continue_after_unverified_attempt(pipeline, failure):
    pipeline.context["params"] = {"computer_outcome": "action", "computer_scope": "state"}
    if failure in {"uncertain", "rejected"}:
        pipeline.receipt = {"success": False, "delivery": failure}
    elif failure == "postimage":
        pipeline.capture_error = ScreenCaptureError("unavailable")
    args = ARGS | {"point": None} if failure == "arguments" else ARGS
    assert act.execute(args, pipeline.context)["status"] == "failed"
    dispatched = len(pipeline.commands)
    pipeline.receipt = {"success": True, "delivery": "acknowledged"}
    pipeline.capture_error = None
    pipeline.bind()
    assert act.execute(ARGS, pipeline.context)["status"] == "failed"
    assert len(pipeline.commands) == dispatched


@pytest.mark.parametrize("point", [
    None, {}, {"x": 1}, {"x": 1, "y": 2, "z": 3},
    {"x": True, "y": 250}, {"x": 500, "y": False},
    {"x": 0.5, "y": 250}, {"x": "500", "y": 250},
    {"x": -1, "y": 250}, {"x": 1000, "y": 250}, {"x": 500, "y": 1000},
])
def test_malformed_point_consumes_lease_before_any_effect(pipeline, point):
    result = act.execute(ARGS | {"point": point}, pipeline.context)
    assert_no_dispatch(pipeline, result)
    assert pipeline.activations == []


@pytest.mark.parametrize("field,value", [
    ("action", "double_click"), ("application", "microsoft_edge"),
    ("target", ""), ("unknown", "extra"),
])
def test_invalid_arguments_or_wrong_application_consume_lease(pipeline, field, value):
    result = act.execute(ARGS | {field: value}, pipeline.context)
    assert_no_dispatch(pipeline, result)
    assert pipeline.activations == []


@pytest.mark.parametrize("field", ["application", "target", "point"])
def test_required_arguments_cannot_be_invented_from_the_lease(pipeline, field):
    args = dict(ARGS)
    args.pop(field)
    assert_no_dispatch(pipeline, act.execute(args, pipeline.context))


def test_omitted_action_preserves_the_existing_single_click_default(pipeline):
    args = dict(ARGS)
    args.pop("action")
    result = act.execute(args, pipeline.context)
    assert result["status"] == "completed" and len(pipeline.commands) == 1


def test_missing_observation_lease_fails_without_capture_or_activation(pipeline):
    pipeline.context.pop("_computer_observation_lease")
    result = act.execute(ARGS, pipeline.context)
    assert_no_dispatch(pipeline, result)
    assert pipeline.activations == []


@pytest.mark.parametrize("change", ["expired", "future", "capture_target", "capture_kind", "dimensions", "pixels", "process", "missing_target", "missing_capture"])
def test_invalid_or_stale_observation_lease_never_dispatches(pipeline, change):
    lease = pipeline.context["_computer_observation_lease"]
    if change == "expired":
        lease["capture"] = replace(lease["capture"], captured_at_unix_ns=NOW - 10_000_000_001)
    elif change == "future":
        lease["capture"] = replace(lease["capture"], captured_at_unix_ns=NOW + 1)
    elif change == "capture_target":
        lease["capture"] = replace(lease["capture"], target="b002")
    elif change == "capture_kind":
        lease["capture"] = replace(lease["capture"], target_kind="output")
    elif change == "dimensions":
        lease["capture"] = replace(lease["capture"], width=640)
    elif change == "pixels":
        lease["capture"] = replace(lease["capture"], image_png=b"not-png")
    elif change == "process":
        lease["process_start_time"] = 99999
    elif change == "missing_target":
        lease.pop("target")
    else:
        lease.pop("capture")
    assert_no_dispatch(pipeline, act.execute(ARGS, pipeline.context))


@pytest.mark.parametrize("failure", ["missing", "geometry", "sleeping", "minimized", "hidden", "locked"])
def test_changed_scene_cannot_reuse_the_image_lease(pipeline, failure):
    if failure == "missing":
        pipeline.publish(windows=[], active="")
    elif failure == "geometry":
        pipeline.window["local_rect"] = pipeline.window["local_rect"] | {"x": 50}
        pipeline.publish()
    elif failure == "sleeping":
        pipeline.publish(awake=False)
    elif failure in ("minimized", "hidden"):
        pipeline.window["minimized" if failure == "minimized" else "visible_on_workspace"] = failure == "minimized"
        pipeline.publish()
    else:
        assert pipeline.cache.accept(pipeline.generation, pipeline.workspace | {"revision": 2, "session_locked": True})
    assert_no_dispatch(pipeline, act.execute(ARGS, pipeline.context))


def test_unfocused_lease_uses_existing_activation_owner_once(pipeline):
    pipeline.publish(active="")
    pipeline.bind()
    result = act.execute(ARGS, pipeline.context)
    assert result["status"] == "completed"
    assert pipeline.activations == [{"target": {"kind": "application", "name": "teamfight_tactics"}}]
    assert len(pipeline.commands) == 1


@pytest.mark.parametrize("change", ["geometry", "identity", "process", "cancel"])
def test_activation_must_preserve_the_original_capture_binding(pipeline, monkeypatch, change):
    pipeline.publish(active="")
    pipeline.bind()
    event = threading.Event()
    pipeline.context["_capability_cancel_event"] = event
    def changed():
        if change == "geometry":
            pipeline.window["local_rect"] = pipeline.window["local_rect"] | {"width": 800}
        elif change == "identity":
            pipeline.window["stable_id"] = "ffff"
        elif change == "process":
            monkeypatch.setattr(computer, "process_start_time", lambda pid: 99999)
        else:
            event.set()
    pipeline.activation_hook = changed
    assert_no_dispatch(pipeline, act.execute(ARGS, pipeline.context))
    assert len(pipeline.activations) == 1


def test_cancellation_consumes_lease_without_capture_or_focus(pipeline):
    event = threading.Event()
    event.set()
    pipeline.context["_capability_cancel_event"] = event
    assert_no_dispatch(pipeline, act.execute(ARGS, pipeline.context))
    assert pipeline.activations == []


@pytest.mark.parametrize("receipt,delivery", [
    (computer.EffectNotObserved("receipt lost"), "uncertain"),
    (computer.ShellCommandUnavailable("connection refused"), "not_dispatched"),
    ({"success": False, "delivery": "not_dispatched", "reason": "stale_scene"}, "not_dispatched"),
    ({"success": True, "delivery": "uncertain"}, "uncertain"),
])
def test_command_receipt_failure_never_replays_or_fabricates_postimage(pipeline, receipt, delivery):
    pipeline.receipt = receipt
    result = act.execute(ARGS, pipeline.context)
    assert result["status"] == "failed" and result["delivery"] == delivery
    assert result["must_not_replay"] is True and "_private_image_png" not in result
    assert "_computer_observation_lease" not in pipeline.context
    assert len(pipeline.commands) == 1 and pipeline.captures == []
    act.execute(ARGS, pipeline.context)
    assert len(pipeline.commands) == 1


@pytest.mark.parametrize("failure", ["capture", "timestamp"])
def test_postcapture_failure_preserves_acknowledged_effect_without_success(pipeline, failure):
    if failure == "capture":
        pipeline.capture_error = ScreenCaptureError("capture failed")
    else:
        pipeline.post_timestamp = NOW - 1_000_000_000
    result = act.execute(ARGS, pipeline.context)
    assert result["status"] == "failed" and result["delivery"] == "acknowledged"
    assert result["effect"]["verified"] is True and result["must_not_replay"] is True
    assert result["semantic_postcondition_verified"] is False
    assert "_private_image_png" not in result
    act.execute(ARGS, pipeline.context)
    assert len(pipeline.commands) == 1


@pytest.mark.parametrize("change", ["revision", "title", "geometry", "focus"])
def test_postclick_observation_accepts_fresh_state_of_the_same_application(pipeline, change):
    original_revision = pipeline.revision
    original_rect = dict(pipeline.window["local_rect"])

    def update_after_click():
        if change == "title":
            pipeline.window["title"] = "Teamfight Tactics — Select mode"
        elif change == "geometry":
            pipeline.window["local_rect"] = {"x": 25, "y": 40, "width": 800, "height": 450}
        pipeline.publish(active="" if change == "focus" else "0x100")

    pipeline.receipt_hook = update_after_click
    result = act.execute(ARGS, pipeline.context)
    assert result["status"] == "completed" and result["delivery"] == "acknowledged"
    assert result["semantic_postcondition_verified"] is False
    assert result["observation"]["status"] == "observed"
    assert result["_private_image_png"] == pipeline.post
    assert pipeline.captures == ["a001"] and pipeline.activations == []
    assert len(pipeline.commands) == 1
    assert pipeline.commands[0]["expected_revision"] == original_revision
    assert pipeline.commands[0]["witness"]["local_rect"] == original_rect
    assert "_private_observation_lease" not in result
    assert "_computer_observation_lease" not in pipeline.context
    repeated = act.execute(ARGS, pipeline.context)
    assert repeated["status"] == "failed" and repeated["must_not_replay"] is True
    assert len(pipeline.commands) == 1 and pipeline.captures == ["a001"]


@pytest.mark.parametrize("boundary", ["after_receipt", "during_capture"])
@pytest.mark.parametrize("change", ["window_id", "stable_id", "pid", "process_start", "app_id", "surface"])
def test_postclick_observation_cannot_rebind_to_a_replacement_target(pipeline, monkeypatch, boundary, change):
    def replace_after_click():
        if change == "process_start":
            monkeypatch.setattr(computer, "process_start_time", lambda pid: 54321)
        elif change == "surface":
            pipeline.publish(windows=[], active="")
            assert pipeline.cache.accept(pipeline.generation, {
                "schema": EVENT_SCHEMA, "type": "application.state", "surface_id": "usb-c",
                "revision": 2, "active_window_id": "0x100", "surface_awake": True,
                "windows": [pipeline.window],
            })
            return
        else:
            pipeline.window[change] = {
                "window_id": "0x200", "stable_id": "b002", "pid": 43, "app_id": "other-application",
            }[change]
        pipeline.publish(active=pipeline.window["window_id"])

    if boundary == "after_receipt":
        pipeline.receipt_hook = replace_after_click
    else:
        pipeline.capture_hook = replace_after_click
    result = act.execute(ARGS, pipeline.context)
    assert result["status"] == "failed" and result["delivery"] == "acknowledged"
    assert result["effect"]["verified"] is True and result["must_not_replay"] is True
    assert "_private_image_png" not in result and "_private_observation_lease" not in result
    assert "_computer_observation_lease" not in pipeline.context
    assert len(pipeline.commands) == 1
    assert pipeline.captures == ([] if boundary == "after_receipt" else ["a001"])
    repeated = act.execute(ARGS, pipeline.context)
    assert repeated["status"] == "failed" and len(pipeline.commands) == 1

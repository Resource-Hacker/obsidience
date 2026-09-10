"""Focused contracts for exact Shell window effects."""

from __future__ import annotations

import json

import pytest

from obsidience.harness.capabilities.computer import observe
from obsidience.harness.capabilities.window import command as window_command
from obsidience.harness.computer.capture import ScreenCapture
from obsidience.harness.host.scene import EVENT_SCHEMA, ShellSceneCache


def _workspace() -> dict:
    return {
        "schema": EVENT_SCHEMA,
        "type": "workspace.state",
        "revision": 1,
        "session_locked": False,
        "workspace_tiling": [
            {"surface_id": "samsung", "columns": 8, "rows": 2, "zones": 16},
            {"surface_id": "usb-c", "columns": 3, "rows": 2, "zones": 6},
            {"surface_id": "dp-4", "columns": 4, "rows": 1, "zones": 4},
        ],
    }


def _window(*, rect: tuple[int, int, int, int] = (10, 20, 800, 600)) -> dict:
    return {
        "window_id": "0x123",
        "stable_id": "stable-123",
        "app_id": "microsoft-edge",
        "title": "Documentation",
        "pid": 42,
        "minimized": False,
        "visible_on_workspace": True,
        "window_kind": "application",
        "pane_id": "",
        "local_rect": dict(zip(("x", "y", "width", "height"), rect, strict=True)),
    }


def _applications(
    surface_id: str, revision: int, windows: list[dict], *, active: str = ""
) -> dict:
    return {
        "schema": EVENT_SCHEMA,
        "type": "application.state",
        "surface_id": surface_id,
        "revision": revision,
        "active_window_id": active,
        "surface_awake": True,
        "windows": windows,
    }


def _scene() -> tuple[ShellSceneCache, int]:
    scene = ShellSceneCache()
    generation = scene.connect()
    assert scene.accept(generation, _workspace())
    assert scene.accept(generation, _applications("samsung", 1, [_window()]))
    assert scene.accept(generation, _applications("usb-c", 1, []))
    assert scene.accept(generation, _applications("dp-4", 1, []))
    return scene, generation


def test_activate_sends_once_and_requires_the_matching_fresh_state(monkeypatch) -> None:
    scene, generation = _scene()
    sent: list[dict[str, object]] = []

    def send(command: dict[str, object], result_type: str) -> dict[str, object]:
        sent.append(command)
        assert result_type == "window.activation.result"
        assert scene.accept(
            generation,
            _applications("samsung", 2, [_window()], active="0x123"),
        )
        return {
            "schema": EVENT_SCHEMA,
            "type": result_type,
            "token": command["token"],
            "surface_id": "samsung",
            "window_id": "0x123",
            "success": True,
            "reason": "",
            "post_revision": 2,
        }

    monkeypatch.setattr(window_command, "SCENE", scene)
    monkeypatch.setattr(window_command, "_send_command", send)
    result = window_command.activate(
        {"target": {"kind": "application", "name": "microsoft-edge"}}
    )

    assert len(sent) == 1
    assert sent[0]["type"] == "window.activate"
    assert sent[0]["expected_revision"] == 1
    assert str(sent[0]["token"]).startswith("tool.")
    assert result == {
        "status": "completed",
        "effect_applied": True,
        "must_not_replay": True,
        "target": {
            "kind": "application",
            "name": "microsoft_edge",
            "surface": "samsung",
        },
        "active": True,
    }
    assert "0x123" not in json.dumps(result)
    assert str(sent[0]["token"]) not in json.dumps(result)


def test_place_moves_unfocused_target_without_activation(monkeypatch) -> None:
    scene, generation = _scene()
    sent: list[dict[str, object]] = []

    def send(command: dict[str, object], result_type: str) -> dict[str, object]:
        sent.append(command)
        assert result_type == "window.place.result"
        assert scene.accept(generation, _applications("samsung", 2, []))
        assert scene.accept(
            generation,
            _applications("usb-c", 2, [_window(rect=(5, 5, 1272, 1193))]),
        )
        return {
            "schema": EVENT_SCHEMA,
            "type": result_type,
            "token": command["token"],
            "surface_id": "samsung",
            "window_id": "0x123",
            "destination_surface_id": "usb-c",
            "verified_tile_bounds": command["tile_bounds"],
            "success": True,
            "reason": "",
            "post_revision": 2,
        }

    monkeypatch.setattr(window_command, "SCENE", scene)
    monkeypatch.setattr(window_command, "_send_command", send)
    result = window_command.place(
        {
            "target": {"kind": "application", "name": "microsoft-edge"},
            "destination": {
                "surface": "usb-c",
                "tile": {"left": 0, "top": 0, "right": 1, "bottom": 1},
            },
        }
    )

    assert len(sent) == 1
    assert sent[0]["type"] == "window.place"
    assert sent[0]["tile_bounds"] == {
        "surface_id": "usb-c",
        "columns": 3,
        "rows": 2,
        "left": 0,
        "top": 0,
        "right": 1,
        "bottom": 1,
    }
    assert result["status"] == "completed"
    assert result["effect_applied"] is True
    assert result["observed"] == {
        "surface": "usb-c",
        "active": False,
        "tile": {"left": 0, "top": 0, "right": 1, "bottom": 1},
    }
    assert result["previous"] == {"surface": "samsung"}
    assert "0x123" not in json.dumps(result)


def test_place_resolves_registered_tft_name_to_one_unfocused_live_app(
    monkeypatch,
) -> None:
    scene = ShellSceneCache()
    generation = scene.connect()
    tft = {
        **_window(),
        "window_id": "0xtft",
        "stable_id": "stable-tft",
        "app_id": "tft-waydroid",
        "title": "gamescope",
    }
    assert scene.accept(generation, _workspace())
    assert scene.accept(generation, _applications("samsung", 1, []))
    assert scene.accept(generation, _applications("usb-c", 1, [tft]))
    assert scene.accept(generation, _applications("dp-4", 1, []))
    sent: list[dict[str, object]] = []

    def send(command: dict[str, object], result_type: str) -> dict[str, object]:
        sent.append(command)
        assert result_type == "window.place.result"
        assert scene.accept(generation, _applications("usb-c", 2, []))
        assert scene.accept(generation, _applications("samsung", 2, [tft]))
        return {
            "schema": EVENT_SCHEMA,
            "type": result_type,
            "token": command["token"],
            "surface_id": "usb-c",
            "window_id": "0xtft",
            "destination_surface_id": "samsung",
            "success": True,
            "reason": "",
            "post_revision": 2,
        }

    monkeypatch.setattr(window_command, "SCENE", scene)
    monkeypatch.setattr(window_command, "_send_command", send)
    result = window_command.place(
        {
            "target": {"kind": "application", "name": "teamfight_tactics"},
            "destination": {"surface": "samsung"},
        }
    )

    assert len(sent) == 1
    assert sent[0]["type"] == "window.place"
    assert sent[0]["window_id"] == "0xtft"
    assert sent[0]["expected_revision"] == 1
    assert result["status"] == "completed"
    assert result["target"] == {
        "kind": "application",
        "name": "teamfight_tactics",
        "surface": "samsung",
    }
    assert result["observed"] == {"surface": "samsung", "active": False}
    assert result["must_not_replay"] is True
    assert "0xtft" not in json.dumps(result)


def test_pixel_tile_rejection_allows_one_distinct_valid_grid_request(monkeypatch) -> None:
    """The failed speech request used display pixels as tile edges."""
    scene, generation = _scene()
    sent = []
    monkeypatch.setattr(window_command, "SCENE", scene)

    def send(command, _result_type):
        sent.append(command)
        assert scene.accept(generation, _applications(
            "samsung", 2, [_window(rect=(5, 5, 630, 1425))]
        ))
        return {"success": True, "post_revision": 2,
                "verified_tile_bounds": command["tile_bounds"]}

    monkeypatch.setattr(window_command, "_send_command", send)
    target = {"kind": "application", "name": "microsoft_edge"}
    invalid = window_command.place({
        "target": target,
        "destination": {"surface": "samsung", "tile": {
            "left": 0, "top": 0, "right": 1920, "bottom": 1440,
        }},
    })
    assert sent == []
    assert invalid["failure"]["code"] == "invalid_destination"
    assert invalid["delivery"] == "not_dispatched"
    assert invalid["effect_applied"] is False
    assert invalid["must_not_replay"] is True
    assert invalid["correction_allowed"] is True
    contract = invalid["destination_contract"]
    assert contract["units"] == "grid_edges"
    assert contract["grids"]["samsung"] == {"columns": 8, "rows": 2}
    corrected = window_command.place({
        "target": target,
        "destination": {"surface": "samsung", "tile": {
            "left": 0, "top": 0, "right": 1,
            "bottom": contract["grids"]["samsung"]["rows"],
        }},
    })
    assert len(sent) == 1
    assert corrected["status"] == "completed"
    assert corrected["effect_applied"] is True
    assert sent[0]["tile_bounds"]["columns"] == 8


@pytest.mark.parametrize("right", [True, 1.5, -1, 0, 9, "1"])
def test_malformed_grid_edges_fail_before_dispatch(monkeypatch, right) -> None:
    scene, _generation = _scene()
    monkeypatch.setattr(window_command, "SCENE", scene)
    monkeypatch.setattr(window_command, "_send_command", lambda *args: pytest.fail("must not send"))
    result = window_command.place({
        "target": {"kind": "application", "name": "microsoft_edge"},
        "destination": {"surface": "samsung", "tile": {
            "left": 0, "top": 0, "right": right, "bottom": 2,
        }},
    })
    assert result["delivery"] == "not_dispatched"
    assert result["correction_allowed"] is True


@pytest.mark.parametrize("operation", ["activate", "place"])
def test_uncertain_delivery_never_claims_no_effect_or_allows_correction(monkeypatch, operation) -> None:
    scene, _generation = _scene()
    calls = []
    monkeypatch.setattr(window_command, "SCENE", scene)

    def send(*args):
        calls.append(args)
        raise window_command.EffectNotObserved("result lost after send")

    monkeypatch.setattr(window_command, "_send_command", send)
    args = {"target": {"kind": "application", "name": "microsoft_edge"}}
    if operation == "place":
        args["destination"] = {"surface": "usb-c"}
    result = getattr(window_command, operation)(args)
    assert len(calls) == 1
    assert result["delivery"] == "uncertain"
    assert result["effect_applied"] is None
    assert result["correction_allowed"] is False
    assert result["must_not_replay"] is True


def test_shell_rejection_does_not_offer_local_argument_correction(monkeypatch) -> None:
    scene, _generation = _scene()
    monkeypatch.setattr(window_command, "SCENE", scene)
    monkeypatch.setattr(window_command, "_send_command", lambda *args: {
        "success": False, "reason": "invalid_destination",
    })
    result = window_command.place({
        "target": {"kind": "application", "name": "microsoft_edge"},
        "destination": {"surface": "usb-c"},
    })
    assert result["delivery"] == "rejected"
    assert result["correction_allowed"] is False
    assert result["must_not_replay"] is True


def test_partial_send_is_delivery_uncertainty(monkeypatch) -> None:
    class PartialSocket:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def send(self, _payload):
            raise OSError("partial write")

    monkeypatch.setattr(window_command, "connect", lambda *args, **kwargs: PartialSocket())
    with pytest.raises(window_command.EffectNotObserved):
        window_command._send_command({"type": "window.place"}, "window.place.result")


def test_placement_already_on_requested_surface_reports_no_effect(monkeypatch) -> None:
    scene, _generation = _scene()
    monkeypatch.setattr(window_command, "SCENE", scene)
    monkeypatch.setattr(window_command, "_send_command", lambda *args: {
        "success": True, "post_revision": 1,
    })
    result = window_command.place({
        "target": {"kind": "application", "name": "microsoft_edge"},
        "destination": {"surface": "samsung"},
    })
    assert result["status"] == "completed"
    assert result["effect_applied"] is False
    assert result["previous"] == result["destination"] == {"surface": "samsung"}


def test_scene_replacement_after_placement_is_uncertain_not_an_undispatched_failure(monkeypatch) -> None:
    scene, generation = _scene()
    monkeypatch.setattr(window_command, "SCENE", scene)

    def send(*_args):
        replacement = {**_window(), "pid": 999}
        assert scene.accept(generation, _applications("samsung", 2, [replacement]))
        return {"success": True, "post_revision": 2}

    monkeypatch.setattr(window_command, "_send_command", send)
    result = window_command.place({
        "target": {"kind": "application", "name": "microsoft_edge"},
        "destination": {"surface": "samsung"},
    })
    assert result["failure"]["code"] == "stale_scene"
    assert result["delivery"] == "uncertain"
    assert result["effect_applied"] is None
    assert result["correction_allowed"] is False


@pytest.mark.parametrize("attestation", [None, "wrong_tile", "wrong_grid", "boolean_edge"])
def test_fresh_surface_without_exact_tile_attestation_cannot_complete(monkeypatch, attestation) -> None:
    scene, generation = _scene()
    monkeypatch.setattr(window_command, "SCENE", scene)
    calls = []

    def send(command, _result_type):
        calls.append(command)
        scene.accept(generation, _applications("samsung", 2, [_window()]))
        verified = dict(command["tile_bounds"])
        if attestation is None:
            verified = None
        elif attestation == "wrong_tile":
            verified["right"] = 2
        elif attestation == "wrong_grid":
            verified["columns"] = 6
        else:
            verified["right"] = True
        return {"success": True, "post_revision": 2, "verified_tile_bounds": verified}

    monkeypatch.setattr(window_command, "_send_command", send)
    result = window_command.place({
        "target": {"kind": "application", "name": "microsoft_edge"},
        "destination": {"surface": "samsung", "tile": {
            "left": 0, "top": 0, "right": 1, "bottom": 2,
        }},
    })
    assert len(calls) == 1
    assert result["failure"]["code"] == "effect_not_observed"
    assert result["delivery"] == "uncertain"
    assert result["effect_applied"] is None
    assert result["correction_allowed"] is False


def test_registered_application_alias_stays_fail_closed_when_ambiguous(
    monkeypatch,
) -> None:
    scene = ShellSceneCache()
    generation = scene.connect()
    first = {
        **_window(),
        "window_id": "0xtft1",
        "app_id": "tft-waydroid",
        "title": "gamescope",
    }
    second = {**first, "window_id": "0xtft2"}
    assert scene.accept(generation, _workspace())
    assert scene.accept(generation, _applications("samsung", 1, []))
    assert scene.accept(generation, _applications("usb-c", 1, [first]))
    assert scene.accept(generation, _applications("dp-4", 1, [second]))
    sent: list[object] = []
    monkeypatch.setattr(window_command, "SCENE", scene)
    monkeypatch.setattr(
        window_command, "_send_command", lambda *args: sent.append(args) or {}
    )

    result = window_command.place(
        {
            "target": {"kind": "application", "name": "teamfight_tactics"},
            "destination": {"surface": "samsung"},
        }
    )

    assert sent == []
    assert result["failure"]["code"] == "target_ambiguous"
    assert result["must_not_replay"] is True


def test_invalid_tile_fails_before_any_shell_effect(monkeypatch) -> None:
    scene, _generation = _scene()
    sent: list[dict[str, object]] = []
    monkeypatch.setattr(window_command, "SCENE", scene)
    monkeypatch.setattr(
        window_command,
        "_send_command",
        lambda *args: sent.append(args) or {},
    )

    result = window_command.place(
        {
            "target": {"kind": "application", "name": "microsoft-edge"},
            "destination": {
                "surface": "usb-c",
                "tile": {"left": 0, "top": 0, "right": 4, "bottom": 1},
            },
        }
    )
    assert sent == []
    assert result["failure"]["code"] == "invalid_destination"
    assert result["must_not_replay"] is True


@pytest.mark.parametrize("observe_first", [False, True])
def test_tft_scene_and_observation_target_roundtrip_to_placement(monkeypatch, observe_first):
    """Another Gamescope window must never compete with the exact TFT identity."""
    scene, generation = _scene()
    tft = {**_window(), "app_id": "tft-waydroid", "title": "gamescope"}
    controls = {**tft, "window_id": "0xcontrols", "stable_id": "controls", "app_id": "gamescope"}
    scene.accept(generation, _applications("samsung", 2, []))
    scene.accept(generation, _applications("usb-c", 2, [tft, controls], active="0x123"))
    row = scene.semantic_manifest()["surfaces"]["usb-c"][0]
    target = {"kind": row[0], "name": row[1], "surface": "usb-c"}
    assert target == {"kind": "application", "name": "teamfight_tactics", "surface": "usb-c"}
    sent, captured = [], []
    monkeypatch.setattr(observe, "SCENE", scene)
    monkeypatch.setattr(window_command, "SCENE", scene)

    def capture(*, stable_id):
        captured.append(stable_id)
        return ScreenCapture(b"private png", "toplevel", stable_id, 800, 600, 1)

    def send(command, result_type):
        sent.append(command)
        assert command["window_id"] == "0x123"
        scene.accept(generation, _applications("usb-c", 3, [controls]))
        scene.accept(generation, _applications("samsung", 3, [tft]))
        return {"success": True, "post_revision": 3}

    monkeypatch.setattr(observe, "capture_screen", capture)
    monkeypatch.setattr(window_command, "_send_command", send)
    if observe_first:
        result = observe.execute({"target": {"kind": "focused"}, "query": "What is visible?"}, {})
        assert result["observation"]["title"] == tft["title"]
        assert result["observation"]["focused"] is True
        assert result["observation"]["target"] == target
        target = result["observation"]["target"]
    result = window_command.place({"target": target, "destination": {"surface": "samsung"}})
    assert result["status"] == "completed"
    assert result["target"] == {**target, "surface": "samsung"}
    assert len(sent) == 1
    assert captured == (["stable-123"] if observe_first else [])
    assert scene.resolve(window_id="0xcontrols").surface_id == "usb-c"


@pytest.mark.parametrize("name,code", [
    ("Emulator", "target_ambiguous"),
    ("Android Emulator - TFT_4080:5554", "target_missing"),
])
def test_observe_activate_place_reject_the_same_invalid_window_names(monkeypatch, name, code):
    scene, generation = _scene()
    tft = {**_window(), "app_id": "Emulator", "title": "Android Emulator - TFT_4080:5554"}
    controls = {**tft, "window_id": "0xcontrols", "stable_id": "controls", "title": "Emulator"}
    scene.accept(generation, _applications("samsung", 2, [tft, controls]))
    monkeypatch.setattr(observe, "SCENE", scene)
    monkeypatch.setattr(window_command, "SCENE", scene)
    monkeypatch.setattr(observe, "capture_screen", lambda **kw: pytest.fail("must not capture"))
    monkeypatch.setattr(window_command, "_send_command", lambda *args: pytest.fail("must not send"))
    target = {"kind": "application", "name": name}
    observation = observe.execute({"target": target, "query": "Read it."}, {})
    activation = window_command.activate({"target": target})
    placement = window_command.place({"target": target, "destination": {"surface": "usb-c"}})
    assert observation["observation"]["failure"]["code"] == code
    assert activation["failure"]["code"] == placement["failure"]["code"] == code

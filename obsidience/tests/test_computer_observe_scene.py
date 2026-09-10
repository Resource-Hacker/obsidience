from __future__ import annotations

import json

import pytest

from obsidience.harness.capabilities.computer import observe
from obsidience.harness.computer.capture import ScreenCapture
from obsidience.harness.host.scene import EVENT_SCHEMA, ShellSceneCache


@pytest.fixture(autouse=True)
def stable_process_identity(monkeypatch):
    monkeypatch.setattr(observe, "process_start_time", lambda pid: 12345)


def _workspace(*, locked: bool = False) -> dict:
    return {
        "schema": EVENT_SCHEMA,
        "type": "workspace.state",
        "revision": 1,
        "session_locked": locked,
        "workspace_tiling": [
            {"surface_id": "samsung", "columns": 8, "rows": 2, "zones": 16},
            {"surface_id": "usb-c", "columns": 3, "rows": 2, "zones": 6},
            {"surface_id": "dp-4", "columns": 4, "rows": 1, "zones": 4},
        ],
    }


def _window(
    window_id: str,
    *,
    stable_id: str,
    app_id: str = "microsoft-edge",
    title: str = "Documentation - Microsoft Edge",
    pane_id: str = "",
    visible: bool = False,
) -> dict:
    return {
        "window_id": window_id,
        "stable_id": stable_id,
        "app_id": "io.obsidience.shell" if pane_id else app_id,
        "title": title,
        "pid": 42,
        "minimized": False,
        "visible_on_workspace": visible,
        "window_kind": "module" if pane_id else "application",
        "pane_id": pane_id,
        "local_rect": {"x": 10, "y": 20, "width": 800, "height": 600},
    }


def _scene(
    *,
    locked: bool = False,
    samsung=None,
    usb_c=None,
    active: str = "",
    samsung_awake: bool = True,
):
    cache = ShellSceneCache()
    generation = cache.connect()
    assert cache.accept(generation, _workspace(locked=locked))
    values = {
        "samsung": list(samsung or []),
        "usb-c": list(usb_c or []),
        "dp-4": [],
    }
    for surface_id, windows in values.items():
        assert cache.accept(
            generation,
            {
                "schema": EVENT_SCHEMA,
                "type": "application.state",
                "surface_id": surface_id,
                "revision": 1,
                "active_window_id": active if surface_id == "samsung" else "",
                "surface_awake": (
                    samsung_awake if surface_id == "samsung" else True
                ),
                "windows": windows,
            },
        )
    return cache


def _capture(calls: list[str]):
    def capture_screen(*, stable_id: str | None = None, output_name=None):
        assert output_name is None
        assert stable_id is not None
        calls.append(stable_id)
        return ScreenCapture(
            image_png=b"private png",
            target_kind="toplevel",
            target=stable_id,
            width=800,
            height=600,
            captured_at_unix_ns=1,
        )

    return capture_screen


def test_named_unfocused_application_is_captured_once_without_activation(monkeypatch):
    edge = _window("0xedge", stable_id="18000007")
    cache = _scene(samsung=[edge])
    calls: list[str] = []
    monkeypatch.setattr(observe, "SCENE", cache)
    monkeypatch.setattr(observe, "capture_screen", _capture(calls))

    result = observe.execute(
        {
            "target": {"kind": "application", "name": "Edge"},
            "query": "What is visible?",
        },
        {},
    )

    assert calls == ["18000007"]
    assert result[observe.PRIVATE_IMAGE_FIELD] == b"private png"
    assert result["observation"] == {
        "status": "observed",
        "target": {
            "kind": "application",
            "name": "microsoft_edge",
            "surface": "samsung",
        },
        "title": "Documentation - Microsoft Edge",
        "focused": False,
        "query": "What is visible?",
        "visual_evidence": {
            "attached": True,
            "media_type": "image/png",
            "freshness": "validated_after_capture",
        },
        "action_authorized": False,
    }
    public_text = json.dumps(result["observation"], sort_keys=True)
    assert "18000007" not in public_text
    assert "window_id" not in public_text
    assert "stable_id" not in public_text
    assert "local_rect" not in public_text
    lease = result[observe.PRIVATE_OBSERVATION_FIELD]
    assert lease["target"].window.stable_id == "18000007"
    assert lease["process_start_time"] == 12345
    assert lease["capture"].image_png is result[observe.PRIVATE_IMAGE_FIELD]
    assert set(lease) == {"target", "capture", "process_start_time"}


def test_focused_and_named_pane_selectors_use_the_same_scene(monkeypatch):
    terminal = _window(
        "0xterminal",
        stable_id="1800000c",
        title="Terminal",
        pane_id="terminal",
        visible=True,
    )
    cache = _scene(samsung=[terminal], active="0xterminal")
    calls: list[str] = []
    monkeypatch.setattr(observe, "SCENE", cache)
    monkeypatch.setattr(observe, "capture_screen", _capture(calls))

    focused = observe.execute(
        {"target": {"kind": "focused"}, "query": "Read this."}, {}
    )
    pane = observe.execute(
        {
            "target": {
                "kind": "pane",
                "name": "terminal",
                "surface": "samsung",
            },
            "query": "Read this.",
        },
        {},
    )

    assert calls == ["1800000c", "1800000c"]
    assert focused["observation"]["focused"] is True
    assert focused["observation"]["target"] == pane["observation"]["target"]
    assert pane["observation"]["target"]["kind"] == "pane"
    assert observe.PRIVATE_OBSERVATION_FIELD not in focused
    assert observe.PRIVATE_OBSERVATION_FIELD not in pane


def test_locked_or_ambiguous_scene_never_captures(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(observe, "capture_screen", _capture(calls))
    monkeypatch.setattr(observe, "SCENE", _scene(locked=True))
    locked = observe.execute(
        {"target": {"kind": "focused"}, "query": "Read this."}, {}
    )
    assert locked["observation"]["failure"]["code"] == "scene_unavailable"

    first = _window("0x1", stable_id="18000001")
    second = _window("0x2", stable_id="18000002")
    monkeypatch.setattr(observe, "SCENE", _scene(samsung=[first], usb_c=[second]))
    ambiguous = observe.execute(
        {
            "target": {"kind": "application", "name": "Edge"},
            "query": "Read this.",
        },
        {},
    )
    assert ambiguous["observation"]["failure"]["code"] == "target_ambiguous"
    assert observe.PRIVATE_IMAGE_FIELD not in ambiguous
    assert calls == []


def test_sleeping_surface_fails_before_capture(monkeypatch):
    edge = _window("0xedge", stable_id="18000007", visible=True)
    calls: list[str] = []
    monkeypatch.setattr(observe, "SCENE", _scene(samsung=[edge], samsung_awake=False))
    monkeypatch.setattr(observe, "capture_screen", _capture(calls))

    result = observe.execute(
        {
            "target": {"kind": "application", "name": "Edge"},
            "query": "What is visible?",
        },
        {},
    )

    assert result["observation"]["failure"] == {
        "code": "target_not_visible",
        "message": "The selected target's Surface is asleep.",
        "retryable": False,
    }
    assert calls == []


def test_scene_change_after_capture_discards_private_image(monkeypatch):
    edge = _window("0xedge", stable_id="18000007")
    cache = _scene(samsung=[edge])
    calls: list[str] = []
    generation = cache.snapshot().generation

    def capture_and_change(**kwargs):
        captured = _capture(calls)(**kwargs)
        assert cache.accept(
            generation,
            {
                "schema": EVENT_SCHEMA,
                "type": "application.state",
                "surface_id": "samsung",
                "revision": 2,
                "active_window_id": "0xedge",
                "surface_awake": True,
                "windows": [edge],
            },
        )
        return captured

    monkeypatch.setattr(observe, "SCENE", cache)
    monkeypatch.setattr(observe, "capture_screen", capture_and_change)

    result = observe.execute(
        {
            "target": {"kind": "application", "name": "Edge"},
            "query": "Read this.",
        },
        {},
    )

    assert calls == ["18000007"]
    assert result["observation"]["failure"]["code"] == "stale_scene"
    assert observe.PRIVATE_IMAGE_FIELD not in result
    assert observe.PRIVATE_OBSERVATION_FIELD not in result


def test_target_contract_rejects_malformed_selectors_before_capture(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(observe, "capture_screen", _capture(calls))
    monkeypatch.setattr(observe, "SCENE", _scene())

    result = observe.execute(
        {
            "target": {"kind": "focused", "name": "Edge"},
            "query": "Read this.",
        },
        {},
    )

    assert result["observation"]["failure"]["code"] == "observation_failed"
    assert calls == []


def test_each_observation_returns_one_private_lease_without_mutating_context(monkeypatch):
    args = {"target": {"kind": "application", "name": "Edge"}, "query": "Read this."}
    existing_lease = object()
    context = {"_computer_observation_lease": existing_lease, "keep": "unchanged"}
    captures = []
    events = []

    def start(pid):
        events.append(("process", pid))
        return 12345

    def capture(*, stable_id):
        events.append(("capture", stable_id))
        captures.append(ScreenCapture(
            image_png=stable_id.encode(), target_kind="toplevel", target=stable_id,
            width=800, height=600, captured_at_unix_ns=len(captures) + 1,
        ))
        return captures[-1]

    monkeypatch.setattr(observe, "process_start_time", start)
    monkeypatch.setattr(observe, "capture_screen", capture)
    results = []
    for stable_id in ("18000001", "18000002"):
        monkeypatch.setattr(observe, "SCENE", _scene(samsung=[
            _window("0xedge", stable_id=stable_id),
        ]))
        results.append(observe.execute(args, context))
    assert events == [
        ("process", 42), ("capture", "18000001"), ("process", 42),
        ("process", 42), ("capture", "18000002"), ("process", 42),
    ]
    first, second = (result[observe.PRIVATE_OBSERVATION_FIELD] for result in results)
    assert first is not second
    assert first["capture"] is captures[0] and second["capture"] is captures[1]
    assert second["target"].window.stable_id == "18000002"
    assert context == {"_computer_observation_lease": existing_lease, "keep": "unchanged"}
    failed = observe.execute({}, context)
    assert observe.PRIVATE_OBSERVATION_FIELD not in failed
    assert observe.PRIVATE_IMAGE_FIELD not in failed
    assert context["_computer_observation_lease"] is existing_lease


@pytest.mark.parametrize("failure", ["missing_before", "missing_after", "pid_reused"])
def test_process_change_or_disappearance_returns_no_image_or_action_lease(monkeypatch, failure):
    edge = _window("0xedge", stable_id="18000007")
    monkeypatch.setattr(observe, "SCENE", _scene(samsung=[edge]))
    calls = []
    monkeypatch.setattr(observe, "capture_screen", _capture(calls))
    reads = 0

    def start(pid):
        nonlocal reads
        reads += 1
        assert pid == 42
        if failure == "missing_before" or (failure == "missing_after" and reads == 2):
            raise observe.GroundingError("Process disappeared.")
        return 12346 if failure == "pid_reused" and reads == 2 else 12345

    monkeypatch.setattr(observe, "process_start_time", start)
    result = observe.execute({
        "target": {"kind": "application", "name": "Edge"}, "query": "Read this.",
    }, {})
    assert result["observation"]["failure"]["code"] == "stale_scene"
    assert observe.PRIVATE_OBSERVATION_FIELD not in result
    assert observe.PRIVATE_IMAGE_FIELD not in result
    assert calls == ([] if failure == "missing_before" else ["18000007"])


def test_capture_failure_returns_no_private_lease(monkeypatch):
    monkeypatch.setattr(observe, "SCENE", _scene(samsung=[
        _window("0xedge", stable_id="18000007"),
    ]))
    def failed_capture(**kwargs):
        raise observe.ScreenCaptureError("Capture failed.")
    monkeypatch.setattr(observe, "capture_screen", failed_capture)
    result = observe.execute({
        "target": {"kind": "application", "name": "Edge"}, "query": "Read this.",
    }, {})
    assert result["observation"]["failure"]["code"] == "capture_unavailable"
    assert observe.PRIVATE_OBSERVATION_FIELD not in result
    assert observe.PRIVATE_IMAGE_FIELD not in result

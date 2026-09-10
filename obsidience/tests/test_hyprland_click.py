"""Image-bound private click attestation with an inert helper and no capture."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import io
import time
from types import SimpleNamespace as NS

import pytest

from obsidience.shell.adapter.windows import click as backend
from obsidience.shell.adapter.windows.model import ApplicationWindow, LocalRect




class Input:
    def __init__(self):
        self.writes = []
        self.closed = False
        self.close_error = None

    def write(self, data):
        self.writes.append(data)
        return len(data)

    def flush(self):
        pass

    def close(self):
        self.closed = True
        if self.close_error:
            raise self.close_error


class Helper:
    def __init__(self, ack=b'{"status":"acknowledged"}\n'):
        self.stdin = Input()
        self.stdout = io.BytesIO(b'{"status":"positioned"}\n' + ack)
        self.returncode = None
        self.killed = False

    def wait(self, timeout):
        self.returncode = 0
        return self.returncode

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9


class Selector:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def register(self, *_):
        pass

    def select(self, _timeout):
        return [True]


@pytest.fixture
def rig(monkeypatch):
    def create(surface="samsung", *, ack=b'{"status":"acknowledged"}\n'):
        name, origin, dimensions, scale = {
            "samsung": ("HDMI-A-1", (0, 0), (5120, 1440), 1),
            "dp-4": ("HDMI-A-2", (-1920, 1440), (3840, 1100), 2),
            "usb-c": ("DP-8", (0, 1440), (3840, 2400), 2),
        }[surface]
        target = ApplicationWindow("0x123", "fixture-app", "Synthetic fixture",
                                   LocalRect(100, 20, 200, 100), pid=42, stable_id="18000001")
        witness = {
            "stable_id": target.stable_id, "pid": target.pid,
            "local_rect": asdict(target.local_rect), "process_start_time": 8765,
            "captured_at_unix_ns": time.time_ns(), "image_width": 400, "image_height": 200,
            "x": 40, "y": 50, "label": "play",
        }
        client = {"address": target.window_id, "stableId": target.stable_id,
                  "pid": target.pid, "class": target.app_id, "mapped": True,
                  "hidden": False, "visible": True, "acceptsInput": True,
                  "monitor": 7, "at": [origin[0]+100, origin[1]+20], "size": [200, 100]}
        output = {"name": name, "id": 7, "x": origin[0], "y": origin[1],
                  "width": dimensions[0], "height": dimensions[1], "scale": scale,
                  "dpmsStatus": True, "disabled": False, "transform": 0}
        data = {"clients": [client], "monitors": [output],
                "activewindow": {"address": target.window_id},
                "cursorpos": {"x": origin[0]+120, "y": origin[1]+45}, "layers": {}}
        events, popen = [], []
        helper = Helper(ack)

        def query(command):
            events.append(command)
            return deepcopy(data[command])

        def spawn(args, **kwargs):
            events.append("helper")
            popen.append((args, kwargs))
            return helper

        monkeypatch.setattr(backend.subprocess, "Popen", spawn)
        monkeypatch.setattr(backend.selectors, "DefaultSelector", Selector)
        monkeypatch.setattr(backend, "process_start_time", lambda pid: 8765)
        owner = NS(_json=query)
        return NS(surface=surface, owner=owner, target=target, witness=witness,
                  client=client, output=output, data=data, helper=helper, popen=popen,
                  events=events, run=lambda guard=lambda: True:
                  backend.click(owner, surface, target, witness, guard=guard))
    return create


@pytest.mark.parametrize("surface,output,extent", [
    ("samsung", "HDMI-A-1", (5120, 1440)),
    ("dp-4", "HDMI-A-2", (1920, 550)),
    ("usb-c", "DP-8", (1920, 1200)),
])
def test_all_surfaces_use_native_capture_to_output_local_logical_transform(rig, surface, output, extent):
    state = rig(surface)
    assert state.run() == {"ok": True, "reason": "", "delivery": "acknowledged"}
    argv, kwargs = state.popen[0]
    assert argv == [backend.POINTER_BINARY, output, "120", "45", *(str(v) for v in extent)]
    assert "shell" not in kwargs and kwargs["stderr"] == backend.subprocess.DEVNULL
    assert state.helper.stdin.writes == [b"commit\n"]
    assert state.helper.stdin.closed and state.helper.stdout.closed
    assert "capture" not in state.events and "ground" not in state.events
    assert state.events.count("cursorpos") == 2


@pytest.mark.parametrize("field,value", [
    ("stableId", "other"), ("pid", 43), ("class", "other-app"),
    ("mapped", False), ("hidden", True), ("visible", False), ("acceptsInput", False),
    ("at", [101, 20]), ("size", [201, 100]), ("monitor", 9),
])
def test_target_identity_geometry_and_visibility_drift_stop_before_motion(rig, field, value):
    state = rig()
    state.client[field] = value
    result = state.run()
    assert result["ok"] is False and result["delivery"] == "not_dispatched"
    assert not state.popen


@pytest.mark.parametrize("field,value", [("dpmsStatus", False), ("disabled", True), ("transform", 1)])
def test_output_not_available_stops_before_motion(rig, field, value):
    state = rig()
    state.output[field] = value
    assert state.run()["reason"] == "surface_not_available"
    assert not state.popen


@pytest.mark.parametrize("case", ["absent", "duplicate", "focus", "process", "old", "future", "witness"])
def test_exact_target_process_focus_and_capture_freshness_are_required(rig, monkeypatch, case):
    state = rig()
    if case == "absent":
        state.data["clients"] = []
    elif case == "duplicate":
        state.data["clients"].append(deepcopy(state.client))
    elif case == "focus":
        state.data["activewindow"]["address"] = "0x456"
    elif case == "process":
        monkeypatch.setattr(backend, "process_start_time", lambda pid: 8766)
    elif case == "old":
        state.witness["captured_at_unix_ns"] -= 11_000_000_000
    elif case == "future":
        state.witness["captured_at_unix_ns"] += 11_000_000_000
    else:
        state.witness["stable_id"] = "other"
    result = state.run()
    assert result["ok"] is False and result["delivery"] == "not_dispatched"
    assert not state.popen




@pytest.mark.parametrize("case", ["cursor", "overlay", "top"])
def test_actual_position_and_occlusion_are_rechecked_before_commit(rig, case):
    state = rig("dp-4")
    point = state.data["cursorpos"]
    if case == "cursor":
        point["x"] += 10
    else:
        state.data["layers"] = {"HDMI-A-2": {"levels": {
            "3" if case == "overlay" else "2": [
                {"x": point["x"]-5, "y": point["y"]-5, "w": 10, "h": 10},
            ],
        }}}
    result = state.run()
    assert result["ok"] is False and result["delivery"] == "not_dispatched"
    assert len(state.popen) == 1 and not state.helper.stdin.writes






@pytest.mark.parametrize("allowed", [[False], [True, False], [True, True, False]])
def test_cancellation_and_lock_guards_prevent_commit_at_every_boundary(rig, allowed):
    state = rig()
    replies = iter(allowed)
    result = state.run(lambda: next(replies, False))
    assert result["reason"] == "request_cancelled_or_locked"
    assert result["delivery"] == "not_dispatched" and not state.helper.stdin.writes


@pytest.mark.parametrize("ack", [b"", b'{"status":"positioned"}\n', b'{"status":"acknowledged"}', b"ok\n"])
def test_lost_or_malformed_postcommit_receipt_is_uncertain_and_never_replayed(rig, ack):
    state = rig(ack=ack)
    result = state.run()
    assert result["ok"] is False and result["delivery"] == "uncertain"
    assert len(state.popen) == 1 and state.helper.stdin.writes == [b"commit\n"]


def test_cleanup_failure_cannot_overwrite_acknowledged_delivery(rig):
    state = rig()
    state.helper.stdin.close_error = OSError("inert cleanup failure")
    assert state.run() == {"ok": True, "reason": "", "delivery": "acknowledged"}








def test_mapping_tolerance_remains_valid_when_actual_point_is_inside_image(rig):
    state = rig("dp-4")
    state.data["cursorpos"]["x"] += 0.5
    assert state.run()["delivery"] == "acknowledged"
    assert state.helper.stdin.writes == [b"commit\n"]


def test_occlusion_uses_actual_cursor_including_mapping_tolerance(rig):
    state = rig("dp-4")
    point = state.data["cursorpos"]
    point["x"] += 0.75
    state.data["layers"] = {"HDMI-A-2": {"levels": {"3": [
        {"x": point["x"]-0.25, "y": point["y"]-5, "w": 10, "h": 10},
    ]}}}
    assert state.run()["reason"] == "point_obscured"
    assert not state.helper.stdin.writes


@pytest.mark.parametrize("age_ns,accepted", [(9_999_999_999, True), (10_000_000_000, True), (10_000_000_001, False), (-1, False)])
def test_original_model_image_lease_has_exact_ten_second_limit(rig, monkeypatch, age_ns, accepted):
    state = rig()
    now = 123456789000000
    monkeypatch.setattr(backend.time, "time_ns", lambda: now)
    state.witness["captured_at_unix_ns"] = now-age_ns
    result = state.run()
    assert result["ok"] is accepted
    if not accepted:
        assert result["reason"] == "stale_capture" and not state.popen


@pytest.mark.parametrize("patch", [
    {"image_width": 0}, {"image_height": False}, {"image_width": 32769},
    {"image_height": 200.0}, {"x": -1}, {"x": 400}, {"y": 200},
    {"x": True}, {"x": float("nan")}, {"y": float("inf")},
])
def test_invalid_image_dimensions_or_point_aborts_before_motion(rig, patch):
    state = rig()
    state.witness.update(patch)
    result = state.run()
    assert result["ok"] is False and result["delivery"] == "not_dispatched"
    assert not state.popen


@pytest.mark.parametrize("phase", ["positioned", "final"])
def test_actual_cursor_cannot_leave_image_despite_mapping_tolerance(rig, phase):
    state = rig("dp-4")
    state.witness["x"] = 398
    requested_global = state.output["x"]+299
    state.data["cursorpos"]["x"] = requested_global
    original_query = state.owner._json
    reads = 0
    def query(command):
        nonlocal reads
        result = original_query(command)
        if command == "cursorpos":
            reads += 1
            if phase == "positioned" or reads == 2:
                result["x"] = requested_global+1
        return result
    state.owner._json = query
    assert state.run()["reason"] == "point_outside_image"
    assert not state.helper.stdin.writes


def test_focus_change_after_positioning_cannot_commit(rig):
    state = rig()
    query = state.owner._json
    reads = 0
    def changing(command):
        nonlocal reads
        result = query(command)
        if command == "activewindow":
            reads += 1
            if reads == 3:
                result["address"] = "0x456"
        return result
    state.owner._json = changing
    assert state.run()["reason"] == "focus_changed"
    assert not state.helper.stdin.writes

"""Exact Hyprland attestation around one private Wayland pointer transaction.

This is the existing window adapter's click implementation, not another
window, capture, or input service. The native helper owns only protocol I/O.
"""
from __future__ import annotations

import json
import math
import selectors
import subprocess
import time
from dataclasses import asdict

from obsidience.harness.computer.grounding import process_start_time

POINTER_BINARY = "/var/lib/ai/opt/obsidience-pointer/current/obsidience-pointer"
MAX_WITNESS_AGE_NS = 10_000_000_000


class ClickRejected(ValueError):
    pass


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise ClickRejected(reason)


def _attest(owner, surface_id, target, witness, *, point=None):
    from .hyprland import _OUTPUT_BY_SURFACE, _local_rect

    _require(target.window_kind == "application", "application_required")
    _require(witness["stable_id"] == target.stable_id and witness["pid"] == target.pid
             and witness["local_rect"] == asdict(target.local_rect), "target_changed")
    _require(process_start_time(target.pid) == witness["process_start_time"], "process_changed")
    age = time.time_ns() - witness["captured_at_unix_ns"]
    _require(0 <= age <= MAX_WITNESS_AGE_NS, "stale_capture")
    clients, monitors = owner._json("clients"), owner._json("monitors")
    matches = [c for c in clients if c.get("address") == target.window_id]
    _require(len(matches) == 1, "target_changed")
    client = matches[0]
    _require(client.get("stableId") == target.stable_id and client.get("pid") == target.pid
             and client.get("class") == target.app_id and client.get("mapped") is True
             and client.get("hidden") is False and client.get("visible") is True
             and client.get("acceptsInput") is True, "target_not_visible")
    outputs = [m for m in monitors if m.get("name") == _OUTPUT_BY_SURFACE[surface_id]
               and m.get("id") == client.get("monitor")]
    _require(len(outputs) == 1, "surface_changed")
    output = outputs[0]
    _require(output.get("dpmsStatus") is True and output.get("disabled") is False
             and output.get("transform") == 0, "surface_not_available")
    _require(_local_rect(client, output["x"], output["y"]) == target.local_rect, "geometry_changed")
    _require(owner._json("activewindow").get("address") == target.window_id, "focus_changed")
    cursor = None
    if point is not None:
        gx, gy = point
        cursor = owner._json("cursorpos")
        _require(abs(cursor["x"]-gx) <= 1 and abs(cursor["y"]-gy) <= 1, "pointer_mapping_changed")
        gx, gy = cursor["x"], cursor["y"]
        # A top/overlay layer is a separate potential input owner. Native app
        # focus alone cannot attest a point covered by a shell notification.
        levels = owner._json("layers").get(output["name"], {}).get("levels", {})
        for level in ("2", "3"):
            for layer in levels.get(level, []):
                _require(not (layer["x"] <= gx < layer["x"]+layer["w"]
                              and layer["y"] <= gy < layer["y"]+layer["h"]), "point_obscured")
    return output, cursor


def _read_status(process, expected: str, timeout: float) -> None:
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        _require(bool(selector.select(timeout)), "pointer_receipt_timeout")
    line = process.stdout.readline(256)
    _require(line == ('{"status":"' + expected + '"}\n').encode(), "pointer_receipt_missing")


def click(owner, surface_id, target, witness, *, guard) -> dict:
    process = None
    committed = False
    try:
        _require(callable(guard) and guard(), "request_cancelled_or_locked")
        output, _ = _attest(owner, surface_id, target, witness)
        image_width, image_height = witness["image_width"], witness["image_height"]
        _require(type(image_width) is int and type(image_height) is int
                 and 0 < image_width <= 32768 and 0 < image_height <= 32768, "invalid_image_dimensions")
        _require(all(type(witness[key]) in (int, float) and math.isfinite(witness[key]) for key in ("x", "y"))
                 and 0 <= witness["x"] < image_width and 0 <= witness["y"] < image_height, "point_outside_image")
        rect = target.local_rect
        local_x = rect.x + witness["x"] * rect.width / image_width
        local_y = rect.y + witness["y"] * rect.height / image_height
        scale = output["scale"]
        _require(type(scale) in (float, int) and math.isfinite(scale) and scale > 0, "invalid_output_scale")
        width, height = round(output["width"]/scale), round(output["height"]/scale)
        x, y = round(local_x), round(local_y)
        _require(0 <= x < width and 0 <= y < height, "point_outside_surface")
        _require(guard(), "request_cancelled_or_locked")
        process = subprocess.Popen(
            [POINTER_BINARY, output["name"], str(x), str(y), str(width), str(height)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        _read_status(process, "positioned", 2.0)
        global_point = (output["x"]+x, output["y"]+y)
        positioned_output, positioned_cursor = _attest(owner, surface_id, target, witness, point=global_point)
        # This checks the image coordinate boundary, not an inferred UI control.
        # The Task model proposed the point; only its fresh post-image can
        # support a further claim about the resulting application state.
        def require_image_point(current_output, cursor):
            actual_x = (cursor["x"]-current_output["x"]-rect.x) * image_width / rect.width
            actual_y = (cursor["y"]-current_output["y"]-rect.y) * image_height / rect.height
            _require(0 <= actual_x < image_width and 0 <= actual_y < image_height, "point_outside_image")

        require_image_point(positioned_output, positioned_cursor)
        final_output, final_cursor = _attest(owner, surface_id, target, witness, point=global_point)
        require_image_point(final_output, final_cursor)
        _require(guard(), "request_cancelled_or_locked")
        # After this write, every failure is uncertain and the token stays used.
        committed = True
        process.stdin.write(b"commit\n")
        process.stdin.flush()
        _read_status(process, "acknowledged", 1.0)
        _require(process.wait(timeout=0.5) == 0, "pointer_transport_failed")
        return {"ok": True, "reason": "", "delivery": "acknowledged"}
    except Exception as exc:
        reason = str(exc) if isinstance(exc, ClickRejected) else "click_precondition_or_transport_failed"
        return {"ok": False, "reason": reason[:160], "delivery": "uncertain" if committed else "not_dispatched"}
    finally:
        if process is not None:
            try:
                if process.stdin:
                    process.stdin.close()
            except OSError:
                pass
            try:
                if process.poll() is None:
                    try:
                        process.wait(timeout=0.3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=1)
            except (OSError, subprocess.TimeoutExpired):
                pass
            try:
                if process.stdout:
                    process.stdout.close()
            except OSError:
                pass

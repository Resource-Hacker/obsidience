"""Finite optical flash measurement through the existing camera/light owners.

Frames stay in RAM. Kernel camera timestamps remove host decode/receipt delay,
but remain driver timestamps, not a claim of exact sensor exposure or ear timing.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
import tempfile
import threading
import time
from pathlib import Path

import numpy as np

from ...config import CONFIG
from ...realtime import tracking
from . import set as power

_CANCEL = threading.Event()
_RUN = threading.Lock()
_STATUS = {"state": "inactive"}
RESULT_PATH = CONFIG.runtime_dir / "lights-visualizer-flashes.json"


def cancel():
    _CANCEL.set()


def status():
    return dict(_STATUS)


def _check(deadline, request_cancel):
    if _CANCEL.is_set() or (request_cancel is not None and request_cancel.is_set()):
        raise InterruptedError("Light calibration cancelled")
    if time.monotonic() > deadline:
        raise TimeoutError("Light calibration exceeded its finite time budget")


def _frame():
    item = tracking.frame(latest=True)
    if item is None:
        raise RuntimeError("Fresh camera frames are unavailable")
    image, _unix_ns, _receipt, identity, metadata = item
    stamp = metadata.get("capture_mono_ns")
    if (type(stamp) is not int
            or metadata.get("capture_timestamp_source") != "v4l2_kernel_pts_monotonic_compatible"
            or not 0 <= time.monotonic_ns() - stamp < 750_000_000):
        raise RuntimeError("Enable native camera capture timestamps before flash calibration")
    # Downsample by striding only; no video, person features or image persists.
    return stamp / 1e9, image[::8, ::8].astype(np.float32), identity


def _pose():
    state = tracking.snapshot()
    pose = state.get("pose", {})
    if state.get("state") != "running" or not all(type(pose.get(k)) in (int, float) for k in ("yaw", "pitch")):
        raise RuntimeError("Fresh camera pose is unavailable")
    return pose["yaw"], pose["pitch"]


def _collect(seconds, deadline, request_cancel, pose=None):
    until = min(deadline, time.monotonic() + seconds)
    frames = []
    while time.monotonic() < until:
        _check(deadline, request_cancel)
        item = _frame()
        if pose is not None and max(abs(a-b) for a,b in zip(pose, _pose())) > .3:
            raise RuntimeError("Camera moved during optical measurement; no timing was accepted")
        if not frames or item[0] != frames[-1][0]:
            frames.append(item)
        _CANCEL.wait(.025)
    if len(frames) < 3:
        raise RuntimeError("Too few distinct camera frames for optical timing")
    if any(item[2] != frames[0][2] for item in frames):
        raise RuntimeError("Camera identity changed during calibration")
    return frames


def _write(inventory, name, params, deadline, request_cancel):
    _check(deadline, request_cancel)
    sent = time.monotonic()
    reply = power._request(inventory[name]["ip"], "setPilot", params, _CANCEL)
    if reply.get("success") is not True:
        raise RuntimeError("Calibration flash was not acknowledged")
    return sent


def _atomic_json(path: Path, payload):
    descriptor, temporary = tempfile.mkstemp(prefix=".light-calibration-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as output:
            os.fchmod(output.fileno(), 0o600)
            json.dump(payload, output, indent=2)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def measure(request_cancel=None):
    """Measure five low-to-high colour flashes per fixture, restoring on every exit."""
    from . import visualize
    global _STATUS
    if not _RUN.acquire(blocking=False):
        raise RuntimeError("Light calibration is already active")
    # Register before waiting for arbitration; an intervening STOP is never erased.
    _CANCEL.clear()
    try:
        with visualize.power_operation(cancel_calibration=False), power._LOCK:
            return _measure(request_cancel)
    except BaseException:
        _STATUS = {**_STATUS, "state": "failed"}
        raise
    finally:
        _RUN.release()


def _measure(request_cancel):
    global _STATUS
    deadline = time.monotonic() + 150
    _STATUS = {"state": "measuring", "fixture": None, "completed": 0}
    inventory = power._inventory()
    with ThreadPoolExecutor(max_workers=6) as pool:
        before = dict(zip(power.FIXTURES, pool.map(
            lambda name: power._pilot(name, inventory, _CANCEL), power.FIXTURES)))
    for pilot in before.values():
        power._appearance(pilot)
    _check(deadline, request_cancel)
    baseline = _collect(.4, deadline, request_cancel)
    camera_identity = baseline[0][2]
    results, modified, restore_errors = {}, set(), []
    try:
        for name in power.FIXTURES:
            _check(deadline, request_cancel)
            _STATUS = {"state": "measuring", "fixture": name, "completed": len(results)}
            pose = _pose()
            low = {"state": True, "sceneId": 0, "r": 12, "g": 20, "b": 255,
                   "c": 0, "w": 0, "dimming": 12}
            high = {**low, "dimming": 85}
            modified.add(name)
            _write(inventory, name, low, deadline, request_cancel)
            dark = _collect(.85, deadline, request_cancel, pose)
            _write(inventory, name, high, deadline, request_cancel)
            bright = _collect(.85, deadline, request_cancel, pose)
            a = np.median([item[1] for item in dark[-3:]], axis=0)
            b = np.median([item[1] for item in bright[-3:]], axis=0)
            delta = b - a
            strength = np.linalg.norm(delta, axis=2)
            # Differential ROI follows this fixture's light, including its
            # reflection when the bulb itself is outside the camera view.
            mask = strength >= max(18.0, float(np.quantile(strength, .97)))
            if int(mask.sum()) < 12:
                results[name] = {"status": "not_visible", "mac": inventory[name]["mac"]}
                _restore_one(name, inventory, before)
                modified.remove(name)
                continue
            vector = delta[mask]
            scale = float(np.sum(vector * vector))
            reference = a[mask]
            def level(frame):
                return float(np.sum((frame[mask] - reference) * vector) / scale)
            delays, intervals, ramps = [], [], []
            for trial in range(5):
                _write(inventory, name, low, deadline, request_cancel)
                quiet = _collect(.55, deadline, request_cancel, pose)
                sent = _write(inventory, name, high, deadline, request_cancel)
                flash = _collect(.65, deadline, request_cancel, pose)
                frames = quiet[-2:] + flash
                if any(item[2] != camera_identity for item in frames):
                    raise RuntimeError("Camera identity changed during calibration")
                samples = [(stamp, level(frame)) for stamp, frame, _identity in frames]
                if max(value for _stamp, value in samples) < .65:
                    continue
                crossings = {}
                for threshold in (.2, .5, .8):
                    for (left, before_level), (right, after_level) in zip(samples, samples[1:]):
                        if left >= sent - .2 and before_level < threshold <= after_level:
                            crossings[threshold] = (left, right)
                            break
                if .5 not in crossings:
                    continue
                left, right = crossings[.5]
                latency = (left + right) / 2 - sent
                if not 0 <= latency <= 1 or right - left > .16:
                    continue
                delays.append(latency * 1000)
                intervals.append((right - left) * 500)
                if .2 in crossings and .8 in crossings:
                    ramps.append(max(0, (sum(crossings[.8]) - sum(crossings[.2])) * 500))
            if len(delays) < 3:
                results[name] = {"status": "inconclusive", "mac": inventory[name]["mac"],
                                 "valid_flashes": len(delays)}
            else:
                median = float(np.median(delays))
                jitter = max(abs(value - median) for value in delays)
                results[name] = {"status": "measured", "mac": inventory[name]["mac"],
                    "latency_ms": round(median, 2),
                    "uncertainty_ms": round(jitter + max(intervals), 2),
                    "p95_ms": round(float(np.quantile(delays, .95)), 2),
                    "ramp_20_80_ms": round(float(np.median(ramps)), 2) if ramps else None,
                    "valid_flashes": len(delays), "observations_ms": [round(v, 2) for v in delays]}
            # Restore each fixture before measuring the next one. Leave it
            # marked until verified, so a failed restoration stays explicit.
            _restore_one(name, inventory, before)
            modified.remove(name)
        payload = {"version": 1, "measured_at": time.time(), "fixtures": results,
            "camera_binding": {"identity": list(camera_identity), "width": 1280, "height": 720,
                "timestamp_source": "v4l2_kernel_pts_monotonic_compatible",
                "measurement": "half_transition_driver_timestamp",
                "sensor_exposure_offset_verified": False},
            "physical_output_delay_verified": False}
        _check(deadline, request_cancel)
        _atomic_json(RESULT_PATH, payload)
        _STATUS = {"state": "completed", "completed": len(results),
                   "measured": sum(row["status"] == "measured" for row in results.values())}
        return payload
    except BaseException:
        _STATUS = {"state": "failed", "completed": len(results)}
        raise
    finally:
        for name in modified:
            try:
                _restore_one(name, inventory, before)
            except (OSError, ValueError, RuntimeError):
                restore_errors.append(name)
        if restore_errors:
            _STATUS = {**_STATUS, "state": "failed", "restore_failed": restore_errors}
            raise RuntimeError("Calibration appearance restoration failed: " + ", ".join(restore_errors))


def _restore_one(name, inventory, before):
    pilot = before[name]
    appearance = power._appearance(pilot)
    reply = power._request(inventory[name]["ip"], "setPilot", {"state": pilot["state"], **appearance}, None)
    if reply.get("success") is not True:
        raise RuntimeError("Calibration restoration was not acknowledged")
    after = power._settled_pilot(name, inventory, None, pilot["state"], appearance)
    if after["state"] != pilot["state"] or (pilot["state"] and any(after.get(k) != v for k, v in appearance.items())):
        raise RuntimeError("Calibration restoration did not match")

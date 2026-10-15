"""Owner-enrolled camera tracking, leased by the existing physical media owner."""

from __future__ import annotations

import asyncio
import contextlib
import json
import threading
from pathlib import Path

from ..config import CONFIG

SETTINGS = CONFIG.runtime_dir / "camera-owner/settings.json"
_LOCK = threading.RLock()
_tracker = None
_error = None
_wanted = False
_intent_revision = 0
_endpoint = None
_usb = None
_loop = None
_events = None
_monitor = None
_recovery = None
_attempted = False
_recovery_state = {"state": "idle"}
_FAILURES = {"camera_motor_unresponsive", "camera_capture_ended", "camera_capture_error",
             "camera_frame_stalled", "camera_inference_ended", "camera_inference_unresponsive"}


def _physical_identity():
    from .camera import _selected
    device, name, identity = _selected()
    path = Path(identity[4])
    for parent in path.parents:
        if (parent / "idVendor").exists():
            serial = (parent / "serial").read_text().strip() if (parent / "serial").exists() else ""
            usb = (str(parent), (parent / "idVendor").read_text().strip(),
                   (parent / "idProduct").read_text().strip(), serial)
            return device, name, identity, usb
    raise RuntimeError("The selected camera has no attestable USB identity")


def set_intent(active: bool) -> None:
    """Called under the media owner's lock; explicit requests disarm old recovery."""
    global _wanted, _intent_revision, _attempted, _recovery_state
    with _LOCK:
        _wanted = active
        _intent_revision += 1
        _attempted = False
        _recovery_state = {"state": "idle"}


def _post(reason, source=None):
    # Failure callbacks run outside Tracker._lock and never join their own thread.
    if _loop is not None and not _loop.is_closed():
        _loop.call_soon_threadsafe(_enqueue, reason, source)


def _enqueue(reason, source):
    if reason == "motor_motion_verified" and (_recovery_state.get("state") not in {"verifying_motor", "reacquired"}
                                               or _recovery_state.get("motor_motion_verified")):
        return
    if _events is not None and not _events.full():
        _events.put_nowait((reason, source, _intent_revision))


async def open_lifecycle():
    global _loop, _events, _monitor, _recovery
    _loop = asyncio.get_running_loop()
    _events = asyncio.Queue(maxsize=32)
    _recovery = asyncio.create_task(_recover_events(), name="camera-owner-recovery")
    _monitor = asyncio.create_task(_watch_endpoint(), name="camera-owner-hotplug")


async def close_lifecycle():
    global _loop, _events, _monitor, _recovery
    for task in (_monitor, _recovery):
        if task is not None:
            task.cancel()
    for task in (_monitor, _recovery):
        if task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await task
    _monitor = _recovery = _events = _loop = None
    await asyncio.to_thread(stop)


async def _watch_endpoint():
    global _recovery_state
    child = None
    spawn = None
    try:
        spawn = asyncio.create_task(asyncio.create_subprocess_exec(
            "/usr/bin/udevadm", "monitor", "--udev", "--property", "--subsystem-match=video4linux",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL))
        child = await asyncio.shield(spawn)
        properties = {}
        while line := await child.stdout.readline():
            line = line.decode("utf-8", "replace").strip()
            if line:
                if "=" in line:
                    key, value = line.split("=", 1)
                    properties[key] = value
                continue
            action, path = properties.get("ACTION"), properties.get("DEVPATH")
            properties = {}
            if action not in {"add", "remove"} or not path:
                continue
            # Match the admitted physical endpoint, never just any reused /dev/videoN.
            if (_endpoint is not None and ("/sys" + path == _endpoint[4]
                    or (action == "add" and _usb is not None
                        and ("/sys" + path).startswith(_usb[0] + "/")))):
                _enqueue("endpoint_" + action, None)
        with _LOCK:
            _recovery_state = {"state": "monitor_failed", "error": "camera hotplug subscription ended"}
    except asyncio.CancelledError:
        raise
    except Exception as error:
        with _LOCK:
            _recovery_state = {"state": "monitor_failed", "error": str(error)[:240]}
    finally:
        if child is None and spawn is not None:
            with contextlib.suppress(OSError):
                child = await spawn
        if child is not None:
            if child.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    child.terminate()
            try:
                await asyncio.wait_for(child.wait(), timeout=3)
            except TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    child.kill()
                await child.wait()


async def _recover_events():
    while True:
        reason, source, revision = await _events.get()
        work = asyncio.create_task(asyncio.to_thread(_recover_once, reason, source, revision))
        # Stop/SDK/start is one owned operation: drain before lifespan teardown.
        cancelled = False
        while not work.done():
            try:
                await asyncio.shield(work)
            except asyncio.CancelledError:
                cancelled = True
        work.result()
        if cancelled:
            raise asyncio.CancelledError


def _recover_once(reason, source, revision):
    global _attempted, _endpoint, _recovery_state, _error
    from . import devices
    with devices._CAMERA_LOCK:
        with _LOCK:
            if revision != _intent_revision or not _wanted:
                return
            if source is not None and source is not _tracker:
                return
            if reason == "motor_motion_verified":
                if (_recovery_state.get("state") in {"verifying_motor", "reacquired"}
                        and _tracker is not None and _tracker.snapshot().get("fresh")
                        and _tracker.snapshot().get("state") == "running"):
                    state = "recovered" if _recovery_state["state"] == "verifying_motor" else "reacquired"
                    _recovery_state = {**_recovery_state, "state": state,
                                       "motor_motion_verified": True}
                return
            if reason == "endpoint_remove":
                stop()
                _recovery_state = {"state": "waiting_for_camera"}
                return
            if reason != "endpoint_add" and reason not in _FAILURES:
                return
            if reason == "endpoint_add":
                try:
                    # V4L2 numbers can change. Resolve the same USB device and
                    # capture interface before updating its saved node through
                    # the media owner; never select whichever reused videoN.
                    if devices.settings()["camera"] != _endpoint[0]:
                        return
                    old_interface = Path(_endpoint[4]).parent
                    candidates = []
                    for entry in Path("/sys/class/video4linux").glob("video*"):
                        if (entry.resolve().parent == old_interface
                                and (entry / "index").read_text().strip() == "0"):
                            candidates.append(entry.name)
                    if len(candidates) != 1:
                        raise RuntimeError("The selected camera capture endpoint has not returned")
                    selection = "v4l2:/dev/" + candidates[0]
                    # Attest USB properties before mutating the saved selection.
                    parent = Path(_usb[0])
                    serial = (parent / "serial").read_text().strip() if (parent / "serial").exists() else ""
                    returned = (str(parent), (parent / "idVendor").read_text().strip(),
                                (parent / "idProduct").read_text().strip(), serial)
                    if returned != _usb:
                        raise RuntimeError("The selected physical camera identity changed")
                    if selection != _endpoint[0]:
                        devices.set_interface("camera", selection)
                    _, _, identity, usb = _physical_identity()
                    if usb != _usb or identity == _endpoint:
                        return
                    _endpoint = identity
                    _attempted = False
                except Exception as error:
                    _recovery_state = {"state": "waiting_for_camera", "error": str(error)[:240]}
                    return
            if _attempted:
                _recovery_state = {"state": "recovery_failed", "error": reason,
                                   "attempted": True}
                return
            # A new USB generation needs ordinary acquisition, not a fault reset;
            # leave its one automatic fault-recovery allowance available.
            _attempted = reason != "endpoint_add"
            _recovery_state = {"state": "recovering", "reason": reason, "attempted": True}
            stop()
            try:
                _, _, _, usb = _physical_identity()
                if usb != _usb:
                    raise RuntimeError("The selected physical camera identity changed")
                if reason in {"camera_motor_unresponsive", "endpoint_add"}:
                    devices._obsbot_control("camera", "on")
                state = start()
                if state.get("state") not in {"starting", "running"}:
                    raise RuntimeError(state.get("error") or "Camera owner did not reacquire")
                _recovery_state = {"state": "verifying_motor" if reason == "camera_motor_unresponsive" else "reacquired",
                                   "reason": reason, "attempted": True,
                                   "motor_reset_verified": reason == "camera_motor_unresponsive",
                                   "motor_motion_verified": False}
            except Exception as error:
                _error = str(error)[:240]
                _recovery_state = {"state": "recovery_failed", "reason": reason,
                                   "error": _error, "attempted": True}


def _config() -> dict:
    if not SETTINGS.exists():
        return {}
    return json.loads(SETTINGS.read_text())


def restore() -> dict:
    """Resume enabled tracking on an awake camera independently of microphone choice."""
    global _error, _wanted
    with _LOCK:
        if _config().get("enabled") is True:
            try:
                from .devices import obsbot_camera_state
                if obsbot_camera_state()["active"]:
                    _wanted = True
                    return start()
            except RuntimeError as error:
                _error = type(error).__name__ + ": " + str(error)[:240]
        return snapshot()


def start() -> dict:
    """Acquire capture and motors only after the media owner has powered camera on."""
    global _tracker, _error, _endpoint, _usb
    with _LOCK:
        if _tracker is not None and _tracker.snapshot().get("state") in {"starting", "running"}:
            return snapshot()
        if _tracker is not None:
            # A terminal owner has no usable stream. One explicit acquisition
            # may replace it after draining; never restart it in a loop.
            _tracker.close()
            _tracker = None
        config = _config()
        if config.get("enabled") is not True:
            return {"enabled": False, "state": "disabled"}
        try:
            from .camera import _selected
            from .devices import _obsbot_control
            from .owner_tracking import Tracker

            device, name, identity, usb = _physical_identity()
            if _usb is not None and usb != _usb:
                raise RuntimeError("The selected physical camera identity changed")
            _endpoint, _usb = identity, usb
            config["identity_check"] = lambda: _selected()[2]
            # Native tracking and software PTZ must never compete for the motor.
            _obsbot_control("tracking-zone", "off")
            _obsbot_control("off")
            # A wake may leave the head in its parked position. Establish and
            # verify the straight-ahead view before custom tracking can steer.
            _obsbot_control("center")
            tracker = Tracker()
            config["on_failure"] = lambda reason: _post(reason, tracker)
            config["on_motion"] = lambda: _post("motor_motion_verified", tracker)
            try:
                tracker.start(device, name, identity, config)
            except Exception:
                tracker.close()
                raise
            _tracker = tracker
            _error = None
        except Exception as error:
            # Optional eyes cannot take down the owner's microphone/voice session.
            _error = type(error).__name__ + ": " + str(error)[:240]
        return snapshot()


def stop() -> None:
    global _tracker
    with _LOCK:
        if _tracker is not None:
            _tracker.close()
            _tracker = None


def snapshot() -> dict:
    with _LOCK:
        if _tracker is not None:
            return {"enabled": True, **_tracker.snapshot(), "desired_active": _wanted,
                    "recovery": dict(_recovery_state)}
        return {"enabled": _config().get("enabled") is True,
                "state": "error" if _error else "inactive", "error": _error,
                "desired_active": _wanted, "recovery": dict(_recovery_state)}


def frame():
    with _LOCK:
        return _tracker.frame() if _tracker is not None else None


def begin_look(direction: str) -> int:
    """Start one look step and return its id; callers poll snapshot for the settle."""
    with _LOCK:
        if _tracker is None:
            raise ValueError("camera_tracker_not_running")
        try:
            return _tracker.begin_look(direction)
        except RuntimeError as error:
            raise ValueError(str(error)) from error


def end_look(look_id: int) -> None:
    """Send that look back now, after a failed or cancelled capture."""
    # Without _LOCK: a recovery or wake holds it for seconds, and the capture
    # that waits here cannot be cancelled. A tracker being closed has already
    # cleared its look, and ids are never reused, so a stale reference is inert.
    tracker = _tracker
    if tracker is not None:
        tracker.end_look(look_id)


def enroll() -> dict:
    with _LOCK:
        if _tracker is None:
            raise ValueError("Enable the camera and owner tracking before enrollment")
        try:
            _tracker.begin_enrollment()
        except RuntimeError as error:
            raise ValueError(str(error)) from error
        return snapshot()

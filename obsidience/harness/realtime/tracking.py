"""Owner-enrolled camera tracking, leased by the existing physical media owner."""

from __future__ import annotations

import json
import threading
from pathlib import Path

SETTINGS = Path(__file__).resolve().parents[2] / "state/camera-owner/settings.json"
_LOCK = threading.RLock()
_tracker = None
_error = None


def _config() -> dict:
    if not SETTINGS.exists():
        return {}
    return json.loads(SETTINGS.read_text())


def restore() -> dict:
    """Resume enabled tracking on an awake camera independently of microphone choice."""
    global _error
    with _LOCK:
        if _config().get("enabled") is True:
            try:
                from .media import obsbot_camera_state
                if obsbot_camera_state()["active"]:
                    return start()
            except RuntimeError as error:
                _error = type(error).__name__ + ": " + str(error)[:240]
        return snapshot()


def start() -> dict:
    """Acquire capture and motors only after the media owner has powered camera on."""
    global _tracker, _error
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
            from .media import _obsbot_control
            from .owner_tracking import Tracker

            device, name, identity = _selected()
            config["identity_check"] = lambda: _selected()[2]
            # Native tracking and software PTZ must never compete for the motor.
            _obsbot_control("tracking-zone", "off")
            _obsbot_control("off")
            tracker = Tracker()
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
            return {"enabled": True, **_tracker.snapshot()}
        return {"enabled": _config().get("enabled") is True,
                "state": "error" if _error else "inactive", "error": _error}


def frame():
    with _LOCK:
        return _tracker.frame() if _tracker is not None else None


def enroll() -> dict:
    with _LOCK:
        if _tracker is None:
            raise ValueError("Enable the camera and owner tracking before enrollment")
        try:
            _tracker.begin_enrollment()
        except RuntimeError as error:
            raise ValueError(str(error)) from error
        return snapshot()

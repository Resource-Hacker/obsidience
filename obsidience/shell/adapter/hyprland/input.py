"""Read the live input state exposed by the Hyprland adapter boundary."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path


PROFILE_STATUS = Path.home() / ".local/state/admech-mouse-profile/status.json"
KEYD_CONFIG = Path("/etc/keyd/default.conf")
HYPRLAND_CONFIG = Path(__file__).with_name("hyprland.lua")
HYPRCTL = "/usr/bin/hyprctl"
HYPRLAND_INSTANCE = "0"
HYPRLAND_MOUSE_NAMES = {
    "mmo7classic": "saitek-cyborg-m.m.o.7-gaming-mouse",
    "g502": "logitech-g502-x-plus",
    "mmo7": "mad-catz-mad-catz-m.m.o.-7+",
}


def _hyprctl(*arguments: str) -> str:
    try:
        return subprocess.run(
            [HYPRCTL, "-i", HYPRLAND_INSTANCE, *arguments],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _devices() -> dict:
    try:
        value = json.loads(_hyprctl("devices", "-j"))
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _integer_option(name: str) -> int | None:
    match = re.search(r"^int:\s*(-?\d+)\s*$", _hyprctl("getoption", name), re.M)
    return int(match.group(1)) if match else None


def _profile_status() -> dict:
    try:
        value = json.loads(PROFILE_STATUS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _configured_mouse(name: str) -> tuple[str | None, float | None]:
    try:
        config = HYPRLAND_CONFIG.read_text(encoding="utf-8")
    except OSError:
        return None, None
    for match in re.finditer(r"hl\.device\(\{(?P<body>.*?)\}\)", config, re.S):
        body = match.group("body")
        configured_name = re.search(r'\bname\s*=\s*"([^"]+)"', body)
        if not configured_name or configured_name.group(1) != name:
            continue
        profile = re.search(r'\baccel_profile\s*=\s*"([^"]+)"', body)
        sensitivity = re.search(r"\bsensitivity\s*=\s*(-?\d+(?:\.\d+)?)", body)
        return (
            profile.group(1) if profile else None,
            float(sensitivity.group(1)) if sensitivity else None,
        )
    return None, None


def _custom_linear_multiplier(profile: str | None) -> float | None:
    if not profile:
        return None
    fields = profile.split()
    if len(fields) != 4 or fields[0] != "custom":
        return None
    try:
        step, origin, point = map(float, fields[1:])
    except ValueError:
        return None
    return point / step if step > 0 and origin == 0 else None


def _caps_lock_mapping() -> str | None:
    try:
        config = KEYD_CONFIG.read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(r"^\s*capslock\s*=\s*([^#\s]+)", config, re.M | re.I)
    return match.group(1) if match else None


def input_snapshot() -> dict:
    """Return actual mouse and keyboard state without creating another store."""
    status = _profile_status()
    profile = status.get("profile") if isinstance(status.get("profile"), dict) else {}
    profile_id = str(status.get("active_profile") or "")
    device_name = HYPRLAND_MOUSE_NAMES.get(profile_id, "")
    devices = _devices()
    mice = devices.get("mice") if isinstance(devices.get("mice"), list) else []
    mouse_device = next(
        (row for row in mice if isinstance(row, dict) and row.get("name") == device_name),
        None,
    )
    acceleration_profile, sensitivity = _configured_mouse(device_name)
    hardware_dpi = profile.get("hardware_dpi")
    hardware_dpi = hardware_dpi if isinstance(hardware_dpi, int) else None
    multiplier = _custom_linear_multiplier(acceleration_profile)
    effective_dpi = (
        round(hardware_dpi * multiplier)
        if hardware_dpi is not None and multiplier is not None else None
    )

    keyboards = (
        devices.get("keyboards")
        if isinstance(devices.get("keyboards"), list) else []
    )
    keyboard = next(
        (row for row in keyboards if isinstance(row, dict) and row.get("main") is True),
        None,
    ) or {}

    return {
        "schema": "obsidience.input.v1",
        "mouse": {
            "profile_id": profile_id,
            "name": profile.get("input_name") or device_name or "No supported mouse",
            "hyprland_name": device_name,
            "connected": mouse_device is not None,
            "hardware_dpi": hardware_dpi,
            "hardware_maximum_verified": status.get("tuner_verified") is True,
            "acceleration_profile": acceleration_profile,
            "sensitivity": sensitivity,
            "multiplier": round(multiplier, 8) if multiplier is not None else None,
            "effective_dpi": effective_dpi,
            "compositor_applied": (
                mouse_device is not None
                and multiplier is not None
                and not _hyprctl("configerrors").strip()
            ),
        },
        "keyboard": {
            "name": keyboard.get("name") or "No primary keyboard",
            "layout": keyboard.get("active_keymap") or keyboard.get("layout") or "",
            "layout_code": keyboard.get("layout") or "",
            "repeat_rate_hz": _integer_option("input:repeat_rate"),
            "repeat_delay_ms": _integer_option("input:repeat_delay"),
            "caps_lock_mapping": _caps_lock_mapping(),
        },
    }

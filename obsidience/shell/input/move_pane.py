#!/usr/bin/env python3
"""Apply one active-pane shortcut through the shell command authority."""

from __future__ import annotations

import json
import secrets
import subprocess
import sys
import time

from websockets.sync.client import connect

SHELL_URL = "ws://127.0.0.1:8768"
SUBPROTOCOL = "obsidience.shell.v1"
SURFACES = frozenset(("samsung", "usb-c", "dp-4"))
DIRECTIONS = frozenset(("left", "right", "top", "bottom"))
ACTIONS = {
    "close": ("pane.dismiss_active", "pane.dismissed", "pane.dismiss.failed"),
    "surface": ("pane.move_active", "pane.moved", "pane.move.failed"),
    "resize": ("pane.tile_active", "pane.tiled", "pane.tile.failed"),
    "tile": ("pane.tile_move_active", "pane.tiled", "pane.tile.failed"),
}
SURFACE_BY_OUTPUT = {
    "HDMI-A-1": "samsung",
    "DP-8": "usb-c",
    "HDMI-A-2": "dp-4",
}


def focused_surface() -> str | None:
    """Resolve the focused Hyprland output to one logical Surface."""

    try:
        result = subprocess.run(
            ["/usr/bin/hyprctl", "monitors", "-j"],
            check=True,
            capture_output=True,
            text=True,
            timeout=0.5,
        )
        monitors = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, ValueError, TypeError):
        return None
    for monitor in monitors if isinstance(monitors, list) else ():
        if isinstance(monitor, dict) and monitor.get("focused") is True:
            return SURFACE_BY_OUTPUT.get(str(monitor.get("name", "")))
    return None


def apply_active_pane_action(surface_id: str, action: str, direction: str = "") -> bool:
    if (
        surface_id not in SURFACES
        or action not in ACTIONS
        or (action != "close" and direction not in DIRECTIONS)
    ):
        return False
    command_type, success_type, failure_type = ACTIONS[action]
    try:
        with connect(
            SHELL_URL,
            subprotocols=[SUBPROTOCOL],
            compression=None,
            proxy=None,
            open_timeout=0.5,
            close_timeout=0.1,
            ping_interval=None,
            max_size=16_384,
        ) as socket:
            command = {
                "schema": "obsidience.shell.command.v1",
                "type": command_type,
                "source_surface_id": surface_id,
            }
            if action != "close":
                command["direction"] = direction
            socket.send(json.dumps(command, separators=(",", ":")))
            deadline = time.monotonic() + 0.75
            unowned = False
            while time.monotonic() < deadline:
                message = socket.recv(timeout=max(0.01, deadline - time.monotonic()))
                event = json.loads(message)
                if event.get("schema") != "obsidience.shell.event.v1":
                    continue
                if event.get("type") == success_type:
                    return True
                if event.get("type") == failure_type:
                    unowned = event.get("reason") == "no_active_pane"
                    break
            if not unowned:
                return False
            token = secrets.token_hex(12)
            native_command = {
                "schema": "obsidience.shell.command.v1",
                "type": "window.close_active"
                if action == "close"
                else "window.layout_active",
                "token": token,
                "source_surface_id": surface_id,
            }
            if action != "close":
                native_command["action"] = action
                native_command["direction"] = direction
            socket.send(json.dumps(native_command, separators=(",", ":")))
            deadline = time.monotonic() + 0.75
            while time.monotonic() < deadline:
                message = socket.recv(timeout=max(0.01, deadline - time.monotonic()))
                event = json.loads(message)
                if (
                    event.get("schema") == "obsidience.shell.event.v1"
                    and event.get("type")
                    == (
                        "window.close.result"
                        if action == "close"
                        else "window.layout.result"
                    )
                    and event.get("token") == token
                ):
                    return event.get("success") is True
    except (OSError, TimeoutError, ValueError, json.JSONDecodeError):
        return False
    return False


def move_active_pane(surface_id: str, direction: str) -> bool:
    """Retain the original surface-transfer entrypoint."""

    return apply_active_pane_action(surface_id, "surface", direction)


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) == 2 and arguments[1] == "close":
        surface_argument, action = arguments
        direction = ""
    elif len(arguments) == 2:
        surface_argument, direction = arguments
        action = "surface"
    elif len(arguments) == 3:
        surface_argument, action, direction = arguments
    else:
        return 2
    surface_id = (
        focused_surface() if surface_argument == "focused" else surface_argument
    )
    if surface_id is None:
        return 1
    return 0 if apply_active_pane_action(surface_id, action, direction) else 1


if __name__ == "__main__":
    raise SystemExit(main())

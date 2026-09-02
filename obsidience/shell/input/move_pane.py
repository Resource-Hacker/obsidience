#!/usr/bin/env python3
"""Move the active Obsidience pane through the shell command authority."""

from __future__ import annotations

import json
import sys
import time

from websockets.sync.client import connect


SHELL_URL = "ws://127.0.0.1:8768"
SUBPROTOCOL = "obsidience.shell.v1"
SURFACES = frozenset(("samsung", "usb-c", "dp-4"))
DIRECTIONS = frozenset(("left", "right", "top", "bottom"))


def move_active_pane(surface_id: str, direction: str) -> bool:
    if surface_id not in SURFACES or direction not in DIRECTIONS:
        return False
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
            socket.send(
                json.dumps(
                    {
                        "schema": "obsidience.shell.command.v1",
                        "type": "pane.move_active",
                        "source_surface_id": surface_id,
                        "direction": direction,
                    },
                    separators=(",", ":"),
                )
            )
            deadline = time.monotonic() + 0.75
            while time.monotonic() < deadline:
                message = socket.recv(timeout=max(0.01, deadline - time.monotonic()))
                event = json.loads(message)
                if event.get("schema") != "obsidience.shell.event.v1":
                    continue
                if event.get("type") == "pane.moved":
                    return True
                if event.get("type") == "pane.move.failed":
                    return False
    except (OSError, TimeoutError, ValueError, json.JSONDecodeError):
        return False
    return False


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 2:
        return 2
    return 0 if move_active_pane(arguments[0], arguments[1]) else 1


if __name__ == "__main__":
    raise SystemExit(main())

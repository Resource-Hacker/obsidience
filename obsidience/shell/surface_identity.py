"""The one Surface identity map: which physical monitor each Surface is.

``surface-layout.json`` is the authority. The installation copy under
``$XDG_CONFIG_HOME/obsidience-shell`` wins; the repository default seeds it.
Each Surface may name its monitor by Hyprland ``description`` (EDID make,
model and serial, exactly as ``hyprctl -j monitors`` reports it), matched as a
prefix like Hyprland's ``desc:`` selector, so connector or card renumbering
keeps the Surface on its monitor. Its ``output`` connector is the fallback for
a Surface whose description is empty or matches no present monitor.
``adapter/hyprland/surfaces.lua`` applies the same rule inside the compositor.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

SURFACE_IDS = ("samsung", "usb-c", "dp-4")
DEFAULT_LAYOUT = Path(__file__).resolve().parent / "defaults" / "initial-surface-layout.json"
OUTPUT = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


@dataclass(frozen=True, slots=True)
class SurfaceIdentity:
    surface_id: str
    output: str
    description: str


def layout_path() -> Path:
    config = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(config) / "obsidience-shell" / "surface-layout.json"


def _identities(record: object) -> tuple[SurfaceIdentity, ...]:
    surfaces = record.get("surfaces") if isinstance(record, dict) else None
    if not isinstance(surfaces, list):
        return ()
    identities: list[SurfaceIdentity] = []
    for value in surfaces:
        if not isinstance(value, dict):
            return ()
        surface_id = value.get("id")
        output = value.get("output")
        description = value.get("description", "")
        if (
            surface_id not in SURFACE_IDS
            or not isinstance(output, str)
            or (output and OUTPUT.fullmatch(output) is None)
            or not isinstance(description, str)
            or len(description) > 256
        ):
            return ()
        identities.append(SurfaceIdentity(surface_id, output, description.strip()))
    if sorted(identity.surface_id for identity in identities) != sorted(SURFACE_IDS):
        return ()
    return tuple(identities)


def load_identities() -> tuple[SurfaceIdentity, ...]:
    """Read the installation map, or the repository default if it is unusable."""

    for path in (layout_path(), DEFAULT_LAYOUT):
        try:
            identities = _identities(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
        if identities:
            return identities
    return ()


def _description(monitor: object) -> str:
    value = monitor.get("description") if isinstance(monitor, dict) else None
    return value if isinstance(value, str) else ""


def surface_for_monitor(
    identities: tuple[SurfaceIdentity, ...], monitor: dict, monitors: list
) -> str | None:
    description = _description(monitor)
    for identity in identities:
        if identity.description and description.startswith(identity.description):
            return identity.surface_id
    for identity in identities:
        if not identity.output or identity.output != monitor.get("name"):
            continue
        # A connector never claims a Surface whose own monitor is present elsewhere.
        if identity.description and any(
            other is not monitor and _description(other).startswith(identity.description)
            for other in monitors
        ):
            return None
        return identity.surface_id
    return None


def resolve(identities: tuple[SurfaceIdentity, ...], monitors: object) -> dict[str, str]:
    """Map each present connector to its Surface; a Surface takes one monitor."""

    resolved: dict[str, str] = {}
    if not isinstance(monitors, list):
        return resolved
    taken: set[str] = set()
    for monitor in monitors:
        if not isinstance(monitor, dict):
            continue
        name = monitor.get("name")
        if not isinstance(name, str) or OUTPUT.fullmatch(name) is None:
            continue
        surface_id = surface_for_monitor(identities, monitor, monitors)
        if surface_id is not None and surface_id not in taken:
            resolved[name] = surface_id
            taken.add(surface_id)
    return resolved


def surface_outputs(monitors: object) -> dict[str, str]:
    """Return connector -> Surface for ``hyprctl -j monitors`` output."""

    return resolve(load_identities(), monitors)


def present_output(surface_id: str) -> str:
    """The connector ``surface_id`` is on now, or "" when its monitor is absent.

    Live monitors decide when Hyprland answers. A caller outside the session's
    environment (no or a stale Hyprland signature) gets the connector the Shell
    last recorded for that Surface in ``output``.
    """

    try:
        done = subprocess.run(["hyprctl", "-j", "monitors"], capture_output=True,
                              timeout=5, check=True, stdin=subprocess.DEVNULL)
        monitors = json.loads(done.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        for identity in load_identities():
            if identity.surface_id == surface_id:
                return identity.output
        return ""
    for output, resolved in surface_outputs(monitors).items():
        if resolved == surface_id:
            return output
    return ""


if __name__ == "__main__":
    # `python -m obsidience.shell.surface_identity SURFACE` prints that Surface's
    # connector for programs that address a screen by connector name.
    if len(sys.argv) != 2 or sys.argv[1] not in SURFACE_IDS:
        sys.exit("usage: python -m obsidience.shell.surface_identity " + "|".join(SURFACE_IDS))
    connector = present_output(sys.argv[1])
    if not connector:
        sys.exit(f"the {sys.argv[1]} Surface has no present monitor")
    print(connector)

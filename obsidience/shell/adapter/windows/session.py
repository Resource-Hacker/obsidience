"""Persist external application windows and restore them once per session.

The adapter owns ``application-session.json``. A snapshot is committed only
after the window set has been stable for a few seconds, never while the
adapter or the session is being torn down and never while a Surface is
missing, so a logout or reboot that closes applications one by one cannot
shrink the record. Restore runs once per compositor instance: it launches each
saved, allow-listed application at most once through the manager-owned
launcher and places matching windows with the adapter's verified ``place``.

The record also carries each Surface's owner-moved dividers, exactly as the
layout owner exports them. The same restore hands them back once, after the
windows are placed; the layout refuses them on a changed grid or work area and
where a divider has already been moved in the new session.
"""

from __future__ import annotations

import contextlib
import difflib
import itertools
import json
import logging
import math
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path

from obsidience.harness.computer.applications import APPLICATIONS

from ...surface_identity import SURFACE_IDS, layout_path, surface_outputs
from .hyprland import HyprlandSurfaceWindows, _local_rect, _number
from .model import (
    MODULE_APP_ID,
    ApplicationWindow,
    LocalRect,
    WindowStateStore,
    clean_text,
)
from .transport import ShellWindowTransport

LOGGER = logging.getLogger(__name__)

SCHEMA = "obsidience.application-session.v1"
STATE_PATH = (
    Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    / "obsidience-shell"
    / "application-session.json"
)
# Cleared by reboot; holds the compositor instance already restored, so an
# adapter restart never relaunches anything and a new session restores once.
RESTORED_MARKER = (
    Path(os.environ.get("XDG_RUNTIME_DIR", "/run/user/1000"))
    / "obsidience-application-session.restored"
)
LAUNCHER = "/home/wissenschafter/bin/agent-launch-gui"
STABLE_SECONDS = 5.0
RESTORE_SECONDS = 120.0
SETTLE_SECONDS = 3.0
# An app that reopens several windows itself (Edge) shows placeholder titles
# first; wait this long for all of them and their real titles before pairing by
# order (seen 2026-10-12: two Edge windows restored into each other's tiles).
MULTI_WINDOW_SECONDS = 25.0
HELPER_EXTENT = 48
# Games keep their own launch contracts, leases and placement.
NO_RELAUNCH = ("world_of_warcraft", "teamfight_tactics")
_GAME_DESKTOP_IDS = frozenset(APPLICATIONS[name]["desktop_id"] for name in NO_RELAUNCH)
_DESKTOP_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+-]*\.desktop$")
_SIGNATURE = re.compile(r"^[A-Za-z0-9_]{1,128}$")


def _desktop_fields(path: Path) -> dict[str, str]:
    fields: dict[str, str] = {}
    group = ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return fields
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("["):
            if group == "[Desktop Entry]":
                break
            group = line
        elif group == "[Desktop Entry]" and "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            fields.setdefault(key.strip(), value.strip())
    return fields


def desktop_entries() -> list[tuple[str, str]]:
    """Launchable top-level desktop ids and StartupWMClass, in XDG precedence.

    These are exactly the roots ``agent-launch-gui`` searches; Flatpak exports
    arrive through ``XDG_DATA_DIRS``.
    """

    data_home = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    data_dirs = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    entries: list[tuple[str, str]] = []
    seen: set[str] = set()
    for root in (data_home, *data_dirs.split(":")):
        if not root:
            continue
        for path in sorted(Path(root, "applications").glob("*.desktop")):
            if path.name in seen:
                continue
            seen.add(path.name)
            fields = _desktop_fields(path)
            if (
                _DESKTOP_ID.fullmatch(path.name)
                and fields.get("Type", "Application") == "Application"
                and fields.get("Hidden", "").casefold() != "true"
            ):
                entries.append((path.name, fields.get("StartupWMClass", "")))
    return entries


def resolve_launch(
    app_id: str, entries: list[tuple[str, str]]
) -> tuple[str, bool, str]:
    """Return (desktop_id, relaunch, skip_reason) from allow-listed identities."""

    key = app_id.casefold()
    for name, spec in APPLICATIONS.items():
        if key in spec["window_app_ids"]:
            game = name in NO_RELAUNCH
            return spec["desktop_id"], not game, "game" if game else ""
    desktop_id = next(
        (name for name, wm_class in entries if wm_class.casefold() == key), ""
    ) or next(
        (name for name, _ in entries if name.removesuffix(".desktop").casefold() == key),
        "",
    )
    if not desktop_id:
        return "", False, "no_desktop_entry"
    if desktop_id in _GAME_DESKTOP_IDS:
        return desktop_id, False, "game"
    return desktop_id, True, ""


def _round(value: float) -> int:
    return math.floor(value + 0.5)  # JavaScript Math.round, as the Shell tiles


def tile_bounds(
    surface_id: str, rect: LocalRect, width: float, height: float,
    grid: tuple[int, int],
) -> dict[str, object]:
    """The tiles a rect occupies, as the Shell's WorkspaceTiler projects them."""

    columns, rows = grid
    left = max(0, min(columns - 1, _round(rect.x * columns / width)))
    top = max(0, min(rows - 1, _round(rect.y * rows / height)))
    right = max(left + 1, min(columns, _round((rect.x + rect.width) * columns / width)))
    bottom = max(top + 1, min(rows, _round((rect.y + rect.height) * rows / height)))
    return {
        "surface_id": surface_id, "columns": columns, "rows": rows,
        "left": left, "top": top, "right": right, "bottom": bottom,
    }


def build_record(
    clients: object,
    monitors: object,
    grids: dict[str, tuple[int, int]],
    entries: list[tuple[str, str]],
) -> dict | None:
    """Project one native snapshot into the record; None while incomplete."""

    surface_by_output = surface_outputs(monitors)
    if (
        not isinstance(clients, list)
        or not isinstance(monitors, list)
        or sorted(surface_by_output.values()) != sorted(SURFACE_IDS)
        or any(surface_id not in grids for surface_id in SURFACE_IDS)
    ):
        return None
    geometry: dict[int, tuple[str, float, float, float, float]] = {}
    for monitor in monitors:
        if not isinstance(monitor, dict):
            continue
        surface_id = surface_by_output.get(str(monitor.get("name", "")))
        values = [_number(monitor.get(field))
                  for field in ("x", "y", "width", "height", "scale")]
        if surface_id is None or None in values or values[4] <= 0:
            continue
        x, y, width, height, scale = values
        if monitor.get("transform") in (1, 3, 5, 7):
            width, height = height, width
        geometry[monitor.get("id")] = (surface_id, x, y, width / scale, height / scale)
    windows: list[tuple[int, dict]] = []
    for client in clients[:256]:
        if not isinstance(client, dict) or client.get("mapped") is False:
            continue
        monitor = geometry.get(client.get("monitor"))
        app_id = clean_text(client.get("class") or client.get("initialClass"), 256)
        title = clean_text(client.get("title"))
        if (
            monitor is None
            or not app_id
            or MODULE_APP_ID in (app_id, client.get("initialClass"))
        ):
            continue
        surface_id, origin_x, origin_y, width, height = monitor
        rect = _local_rect(client, origin_x, origin_y)
        # Helper windows (Wine's tiny untitled explorer.exe) are not restored.
        if rect is None or not title or min(rect.width, rect.height) < HELPER_EXTENT:
            continue
        floating = client.get("floating") is True
        desktop_id, relaunch, skip_reason = resolve_launch(app_id, entries)
        history = client.get("focusHistoryID")
        if isinstance(history, bool) or not isinstance(history, int) or history < 0:
            history = 1 << 30
        windows.append((history, {
            "app_id": app_id,
            "title": title,
            "surface_id": surface_id,
            "tile_bounds": None if floating else tile_bounds(
                surface_id, rect, width, height, grids[surface_id]
            ),
            "local_rect": {
                "x": rect.x, "y": rect.y, "width": rect.width, "height": rect.height,
            },
            "floating": floating,
            "fullscreen": int(client.get("fullscreen", 0) or 0) > 0,
            "desktop_id": desktop_id,
            "relaunch": relaunch,
            "skip_reason": skip_reason,
        }))
    windows.sort(key=lambda item: (
        item[0], item[1]["surface_id"], item[1]["local_rect"]["y"],
        item[1]["local_rect"]["x"],
    ))
    return {
        "schema": SCHEMA,
        "saved_at": int(time.time()),
        "windows": [
            {**window, "focus_rank": rank}
            for rank, (_history, window) in enumerate(windows)
        ],
    }


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise


def write_record(record: dict, path: Path = STATE_PATH) -> None:
    _write_atomic(path, json.dumps(record, indent=2) + "\n")


def _saved_entry(value: object) -> dict | None:
    if not isinstance(value, dict):
        return None
    app_id = value.get("app_id")
    title = value.get("title")
    surface_id = value.get("surface_id")
    floating = value.get("floating")
    rect = value.get("local_rect")
    if (
        not isinstance(app_id, str)
        or not app_id
        or not isinstance(title, str)
        or surface_id not in SURFACE_IDS
        or not isinstance(floating, bool)
        or not isinstance(rect, dict)
    ):
        return None
    local_rect = LocalRect(
        rect.get("x"), rect.get("y"), rect.get("width"), rect.get("height")
    ).normalized()
    tile = value.get("tile_bounds")
    tile = None if tile is None else ShellWindowTransport._tile_bounds(tile, surface_id)
    if local_rect is None or (tile is None and not floating):
        return None
    return {
        "app_id": app_id, "title": title, "surface_id": surface_id,
        "floating": floating, "rect": local_rect, "tile_bounds": tile,
    }


def load_record(path: Path = STATE_PATH) -> tuple[list[dict], dict[str, str]]:
    """Saved window entries, and each Surface's saved cuts."""

    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return [], {}
    except (OSError, ValueError) as error:
        LOGGER.warning("Application session record unreadable: %s", error)
        return [], {}
    if not isinstance(record, dict) or record.get("schema") != SCHEMA:
        return [], {}
    windows = record.get("windows")
    if not isinstance(windows, list):
        return [], {}
    cuts = record.get("cuts")
    return (
        [entry for entry in map(_saved_entry, windows[:256]) if entry],
        {
            surface_id: value
            for surface_id, value in (cuts.items() if isinstance(cuts, dict) else ())
            if surface_id in SURFACE_IDS and isinstance(value, str)
        },
    )


def launch_plan(
    entries: list[dict],
    live_app_ids: set[str],
    resolutions: dict[str, tuple[str, bool, str]],
) -> tuple[list[str], list[tuple[str, str]]]:
    """Desktop ids to launch once, and (app_id, reason) for apps left alone."""

    launches: list[str] = []
    skipped: list[tuple[str, str]] = []
    seen: set[str] = set()
    for entry in entries:
        key = entry["app_id"].casefold()
        if key in seen:
            continue
        seen.add(key)
        desktop_id, relaunch, reason = resolutions[key]
        if not relaunch:
            skipped.append((entry["app_id"], reason))
        elif key in live_app_ids:
            skipped.append((entry["app_id"], "already_running"))
        elif desktop_id not in launches:
            launches.append(desktop_id)
    return launches, skipped


def assign(
    pending: list[tuple[int, dict]], windows: list[ApplicationWindow]
) -> tuple[list[tuple[int, ApplicationWindow]], bool]:
    """Pair saved entries with free windows of one app by title similarity.

    Returns the best pairing and whether the titles decided it: with several
    windows, a pairing that barely beats the alternative (placeholder titles) is
    not decisive and the caller may wait for real titles.
    """

    if not pending or not windows:
        return [], True
    if max(len(pending), len(windows)) > 6:  # bounded search; such an app is paired in order
        return list(zip((index for index, _ in pending), windows)), False

    def similarity(slot: int, choice: int) -> float:
        return difflib.SequenceMatcher(
            None, pending[slot][1]["title"].casefold(), windows[choice].title.casefold()
        ).ratio()

    # Every way to pair the smaller side into the larger one, as (entry, window) slots.
    if len(windows) <= len(pending):
        options = [list(zip(slots, range(len(windows))))
                   for slots in itertools.permutations(range(len(pending)), len(windows))]
    else:
        options = [list(zip(range(len(pending)), choices))
                   for choices in itertools.permutations(range(len(windows)), len(pending))]
    ranked = sorted(
        ((sum(similarity(slot, choice) for slot, choice in option), option) for option in options),
        key=lambda item: -item[0],
    )
    best_score, best = ranked[0]
    decisive = len(ranked) == 1 or best_score - ranked[1][0] >= 0.15
    return [(pending[slot][0], windows[choice]) for slot, choice in best], decisive


def _candidate(window: ApplicationWindow) -> bool:
    return (
        window.window_kind == "application"
        and window.app_id != MODULE_APP_ID
        and min(window.local_rect.width, window.local_rect.height) >= HELPER_EXTENT
    )


def _tearing_down() -> bool:
    """A reboot, poweroff or stopping graphical session never shrinks the record."""

    try:
        system = subprocess.run(
            ["systemctl", "is-system-running"],
            capture_output=True, text=True, timeout=2, check=False,
        ).stdout.strip()
        graphical = subprocess.run(
            ["systemctl", "--user", "is-active", "graphical-session.target"],
            capture_output=True, text=True, timeout=2, check=False,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return True
    return system in ("", "stopping") or graphical != "active"


class ApplicationSession:
    """Own the application-session record and its once-per-session restore."""

    def __init__(
        self,
        store: WindowStateStore,
        snapshot: Callable[[], tuple[object, object]],
        place: Callable[..., tuple[bool, str, int]],
        place_floating: Callable[[str, str, LocalRect], tuple[bool, str]],
        grids: Callable[[], dict[str, tuple[int, int]] | None],
        cuts: Callable[[], dict[str, str]],
        restore_cuts: Callable[[str, str], tuple[bool, str]],
    ) -> None:
        self.store = store
        self._snapshot = snapshot
        self._place = place
        self._place_floating = place_floating
        self._grids = grids
        self._cuts = cuts
        self._restore_cuts = restore_cuts
        self._written: tuple[list, dict] | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="obsidience-window-session", daemon=True
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        # Every launch, placement and commit checks this before its effect.
        self._stop.set()

    def _run(self) -> None:
        try:
            entries, cuts = load_record()
            if self._claim_restore():
                self._restore(entries, cuts)
        except Exception as error:  # restore is best effort; recording continues
            LOGGER.warning("Application session restore stopped: %s", error)
        self._record()

    @staticmethod
    def _claim_restore() -> bool:
        """Claim this compositor instance's single restore before any launch."""

        signature = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE", "")
        if _SIGNATURE.fullmatch(signature) is None:
            LOGGER.warning("Application session restore skipped: no compositor instance")
            return False
        with contextlib.suppress(FileNotFoundError):
            if RESTORED_MARKER.read_text(encoding="utf-8").strip() == signature:
                return False
        _write_atomic(RESTORED_MARKER, signature + "\n")
        return True

    def _live(self) -> list[tuple[str, int, ApplicationWindow]]:
        return [
            (state.surface_id, state.revision, window)
            for state in self.store.snapshots()
            for window in state.windows
            if _candidate(window)
        ]

    def _restore(self, entries: list[dict], cuts: dict[str, str]) -> None:
        if not entries:
            LOGGER.info("Application session: nothing saved to restore")
            return
        deadline = time.monotonic() + RESTORE_SECONDS
        while {state.surface_id for state in self.store.snapshots()} != set(SURFACE_IDS):
            if self._stop.wait(0.2) or time.monotonic() >= deadline:
                return
        available = desktop_entries()
        resolutions = {
            entry["app_id"].casefold(): resolve_launch(entry["app_id"], available)
            for entry in entries
        }
        live_apps = {window.app_id.casefold() for _, _, window in self._live()}
        launches, skipped = launch_plan(entries, live_apps, resolutions)
        launched: list[str] = []
        for desktop_id in launches:
            if self._stop.is_set():
                return
            launched.append(f"{desktop_id}={self._launch(desktop_id)}")
        placeable = [
            (index, entry) for index, entry in enumerate(entries)
            if resolutions[entry["app_id"].casefold()][2] != "game"
        ]
        results = self._place_until(placeable, deadline)
        placed = sum(result == "placed" for result in results.values())
        unplaced = [
            f"{entries[index]['app_id']}:{results.get(index) or 'no_window'}"
            for index, _entry in placeable
            if results.get(index) != "placed"
        ]
        LOGGER.info(
            "Application session restored %d of %d windows; launched [%s]; "
            "not relaunched [%s]; unplaced [%s]",
            placed, len(entries), ", ".join(launched),
            ", ".join(f"{app}:{reason}" for app, reason in skipped),
            ", ".join(unplaced),
        )
        # Once, after placement: the layout then holds this session's windows,
        # grids and resize limit, and refuses dividers already moved since.
        for surface_id, value in sorted(cuts.items()):
            if self._stop.is_set() or self._grids() is None:
                return
            success, reason = self._restore_cuts(surface_id, value)
            LOGGER.info(
                "Application session dividers on %s: %s",
                surface_id, "restored" if success else reason,
            )

    def _launch(self, desktop_id: str) -> str:
        """Dispatch exactly once; a failed or uncertain launch is never retried."""

        if _DESKTOP_ID.fullmatch(desktop_id) is None:
            return "invalid"
        try:
            result = subprocess.run(
                [LAUNCHER, desktop_id],
                capture_output=True, text=True, timeout=30, check=False,
            )
        except subprocess.TimeoutExpired:
            return "uncertain"
        except OSError as error:
            LOGGER.warning("Application session launch of %s failed: %s", desktop_id, error)
            return "failed"
        if result.returncode != 0:
            LOGGER.warning(
                "Application session launch of %s failed: %s",
                desktop_id, (result.stderr or result.stdout).strip()[:200],
            )
            return "failed"
        return "accepted"

    def _place_until(
        self, entries: list[tuple[int, dict]], deadline: float
    ) -> dict[int, str]:
        windows: dict[int, str] = {}
        results: dict[int, str] = {}
        first_seen: dict[str, float] = {}
        titled: dict[str, tuple[str, float]] = {}
        saved = dict(entries)
        while (
            not self._stop.is_set()
            and time.monotonic() < deadline
            and len(results) < len(entries)
        ):
            now = time.monotonic()
            live = {window.window_id: (surface_id, revision, window)
                    for surface_id, revision, window in self._live()}
            for window_id, (_, _, window) in live.items():
                first_seen.setdefault(window_id, now)
                if titled.get(window_id, ("", 0.0))[0] != window.title:
                    titled[window_id] = (window.title, now)
            # A window that closed (a login window replaced by the main one)
            # frees its entry for the next window of that app.
            for index, window_id in list(windows.items()):
                if window_id not in live:
                    del windows[index]
                    results.pop(index, None)
            for key in {entry["app_id"].casefold() for _, entry in entries}:
                free = sorted(
                    (window for _, _, window in live.values()
                     if window.app_id.casefold() == key
                     and window.window_id not in windows.values()),
                    key=lambda window: (first_seen[window.window_id], window.window_id),
                )
                pending = [(index, entry) for index, entry in entries
                           if entry["app_id"].casefold() == key and index not in windows]
                # Let an app finish opening its windows and settle their titles.
                if not free or not pending or any(
                    now - titled[window.window_id][1] < SETTLE_SECONDS for window in free
                ):
                    continue
                pairs, decisive = assign(pending, free)
                waited = now - min(first_seen[window.window_id] for window in free)
                if (len(pending) > 1 and waited < MULTI_WINDOW_SECONDS
                        and (len(free) < len(pending) or not decisive)):
                    continue
                for index, window in pairs:
                    if self._stop.is_set():
                        return results
                    surface_id, revision, _ = live[window.window_id]
                    try:
                        result = self._place_entry(
                            saved[index], surface_id, revision, window
                        )
                    except Exception as error:  # uncertain: never placed twice
                        LOGGER.warning("Application session placement failed: %s", error)
                        result = "placement_error"
                    if result != "retry":
                        windows[index] = window.window_id
                        results[index] = result
            self._stop.wait(0.5)
        return results

    def _place_entry(
        self, entry: dict, surface_id: str, revision: int, window: ApplicationWindow
    ) -> str:
        """Place once; "retry" only when nothing was dispatched."""

        destination = entry["surface_id"]
        if not any(state.surface_id == destination and state.output
                   for state in self.store.snapshots()):
            return "retry"
        if entry["floating"]:
            success, reason = self._place_floating(
                window.window_id, destination, entry["rect"]
            )
            return "placed" if success else reason
        grids = self._grids()
        tile = entry["tile_bounds"]
        if grids is None:
            return "retry"
        if grids.get(destination) != (tile["columns"], tile["rows"]):
            return "grid_changed"
        success, reason, _revision = self._place(
            surface_id, window.window_id, revision, destination, grids, tile
        )
        if not success and reason == "stale_or_invalid":
            return "retry"
        return "placed" if success else reason

    def _record(self) -> None:
        window_set: frozenset | None = None
        since = built_at = 0.0
        built: tuple | None = None
        while not self._stop.wait(1.0):
            snapshots = self.store.snapshots()
            now = time.monotonic()
            current = frozenset(
                (state.surface_id, window.window_id)
                for state in snapshots
                for window in state.windows
                if window.window_kind == "application"
            )
            revisions = tuple((state.surface_id, state.revision) for state in snapshots)
            if current != window_set:
                window_set, since = current, now
            if (
                revisions == built
                or now - since < STABLE_SECONDS
                or now - built_at < STABLE_SECONDS
            ):
                continue
            built_at = now
            try:
                if self._commit():
                    built = revisions
            except Exception as error:  # one failed read never ends recording
                LOGGER.warning("Application session not recorded: %s", error)

    def _commit(self) -> bool:
        grids = self._grids()
        if grids is None:
            return False
        clients, monitors = self._snapshot()
        record = build_record(clients, monitors, grids, desktop_entries())
        if record is None:
            return False
        record["cuts"] = self._cuts()
        written = (record["windows"], record["cuts"])
        if written == self._written:
            return True
        if self._stop.is_set() or _tearing_down():
            return False
        write_record(record)
        self._written = written
        return True


def _layout_grids() -> dict[str, tuple[int, int]]:
    """Dry run only: the Shell's saved grids stand in for its live state."""

    grids = {"samsung": (8, 2), "usb-c": (3, 2), "dp-4": (4, 1)}
    with contextlib.suppress(OSError, ValueError, AttributeError, TypeError):
        tiling = json.loads(layout_path().read_text(encoding="utf-8"))["workspace_tiling"]
        for surface_id in SURFACE_IDS:
            value = tiling[surface_id]
            grids[surface_id] = (int(value["columns"]), int(value["rows"]))
    return grids


def dry_run(output: Path) -> None:
    """Read-only: record the live desktop to ``output`` and print a restore plan."""

    clients, monitors = HyprlandSurfaceWindows(lambda *_args: None).clients_and_monitors()
    available = desktop_entries()
    record = build_record(clients, monitors, _layout_grids(), available)
    if record is None:
        raise SystemExit("Incomplete native snapshot; nothing recorded")
    write_record(record, output)
    entries = [entry for entry in map(_saved_entry, record["windows"]) if entry]
    resolutions = {
        entry["app_id"].casefold(): resolve_launch(entry["app_id"], available)
        for entry in entries
    }
    surface_by_output = surface_outputs(monitors)
    origins = {
        monitor.get("id"): (monitor.get("x"), monitor.get("y"))
        for monitor in monitors
        if isinstance(monitor, dict)
        and surface_by_output.get(str(monitor.get("name", "")))
    }
    live: list[ApplicationWindow] = []
    for client in clients:
        origin = origins.get(client.get("monitor")) if isinstance(client, dict) else None
        rect = _local_rect(client, *origin) if origin else None
        app_id = str(client.get("class") or client.get("initialClass") or "") if origin else ""
        if rect is None or not app_id:
            continue
        window = ApplicationWindow(
            window_id=str(client.get("address", "")), app_id=app_id,
            title=str(client.get("title") or app_id), local_rect=rect,
        ).normalized()
        if window is not None and _candidate(window):
            live.append(window)
    print(f"Recorded {len(record['windows'])} application windows to {output}")
    for entry in record["windows"]:
        where = entry["tile_bounds"] or entry["local_rect"]
        print(f"  {entry['focus_rank']}: {entry['app_id']} on {entry['surface_id']} "
              f"{json.dumps(where)} floating={entry['floating']} "
              f"desktop_id={entry['desktop_id'] or '-'} relaunch={entry['relaunch']}"
              f"{' (' + entry['skip_reason'] + ')' if entry['skip_reason'] else ''}")
    for label, windows in (("Fresh session", []), ("Current desktop", live)):
        launches, skipped = launch_plan(
            entries, {window.app_id.casefold() for window in windows}, resolutions
        )
        print(f"{label}: launch {launches or 'nothing'}; not relaunched {skipped}")
        for key in {entry["app_id"].casefold() for entry in entries}:
            if resolutions[key][2] == "game":
                continue
            pending = [(index, entry) for index, entry in enumerate(entries)
                       if entry["app_id"].casefold() == key]
            free = [window for window in windows if window.app_id.casefold() == key]
            for index, window in assign(pending, free)[0]:
                entry = entries[index]
                target = entry["tile_bounds"] or entry["rect"]
                print(f"  place {window.window_id} ({window.title[:48]!r}) -> "
                      f"{entry['surface_id']} {target}")


def main() -> None:
    if len(sys.argv) != 3 or sys.argv[1] != "--dry-run":
        raise SystemExit("usage: python -m obsidience.shell.adapter.windows.session --dry-run OUTPUT")
    dry_run(Path(sys.argv[2]))


if __name__ == "__main__":
    main()

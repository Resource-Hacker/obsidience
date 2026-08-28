"""Bounded read-only KWin state for the native Shell module."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable


BUS_NAME = "org.obsidience.Shell.WindowObserver"
OBJECT_PATH = "/org/obsidience/Shell/WindowObserver"
INTERFACE = "org.obsidience.Shell.WindowObserver"
SCRIPT_NAME = "obsidience-shell-window-observer"
KWIN_BUS = "org.kde.KWin"
RECORD_SEPARATOR = "\x1f"
FIELD_SEPARATOR = "\x1e"
MAX_WINDOWS = 256
MAX_PAYLOAD = 128_000
MAX_FIELD = 512

_INTROSPECTION = f"""
<node>
  <interface name="{INTERFACE}">
    <method name="NotifyActiveWindow">
      <arg type="s" direction="in" name="caption"/>
      <arg type="s" direction="in" name="app_id"/>
      <arg type="s" direction="in" name="window_id"/>
    </method>
    <method name="NotifyWindowList">
      <arg type="s" direction="in" name="payload"/>
    </method>
    <method name="GetState">
      <arg type="s" direction="out" name="state_json"/>
    </method>
  </interface>
</node>
"""


def _text(value: object, maximum: int = MAX_FIELD) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.replace("\x00", "").split())[:maximum]


@dataclass(frozen=True, slots=True)
class WindowState:
    window_id: str
    app_id: str
    title: str
    desktop_ids: tuple[str, ...]
    output_name: str


def parse_window_list(payload: object) -> tuple[WindowState, ...]:
    """Parse the bounded record format emitted by the KWin observer script."""
    if not isinstance(payload, str) or len(payload) > MAX_PAYLOAD:
        return ()
    rows: list[WindowState] = []
    for raw in payload.split(RECORD_SEPARATOR):
        if not raw or len(rows) >= MAX_WINDOWS:
            continue
        fields = raw.split(FIELD_SEPARATOR)
        if len(fields) != 5:
            continue
        window_id, app_id, title, desktops, output_name = map(_text, fields)
        if not window_id or not app_id:
            continue
        desktop_ids = tuple(
            value for value in (_text(item, 128) for item in desktops.split(",")) if value
        )
        rows.append(WindowState(window_id, app_id, title, desktop_ids, output_name))
    return tuple(rows)


class KWinObserver:
    """Own one read-only D-Bus endpoint and one matching KWin script."""

    def __init__(self, on_change: Callable[[], None]) -> None:
        self.on_change = on_change
        self.active_title = ""
        self.active_app_id = ""
        self.active_window_id = ""
        self.workspace_id = ""
        self.workspace_name = "Workspace"
        self.windows: tuple[WindowState, ...] = ()
        self._connection = None
        self._desktop_proxy = None
        self._registration_id = 0
        self._script_loaded = False

    def start(self) -> None:
        import gi

        gi.require_version("Gio", "2.0")
        from gi.repository import Gio, GLib

        connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self._connection = connection
        interface_info = Gio.DBusNodeInfo.new_for_xml(_INTROSPECTION).interfaces[0]
        self._registration_id = connection.register_object(
            OBJECT_PATH, interface_info, self._handle_method, None, None
        )
        reply = connection.call_sync(
            "org.freedesktop.DBus",
            "/org/freedesktop/DBus",
            "org.freedesktop.DBus",
            "RequestName",
            GLib.Variant("(su)", (BUS_NAME, 0)),
            GLib.VariantType.new("(u)"),
            Gio.DBusCallFlags.NONE,
            3_000,
            None,
        )
        if reply.unpack()[0] not in (1, 4):
            raise RuntimeError(f"D-Bus name is already owned: {BUS_NAME}")

        self._desktop_proxy = Gio.DBusProxy.new_for_bus_sync(
            Gio.BusType.SESSION,
            Gio.DBusProxyFlags.NONE,
            None,
            KWIN_BUS,
            "/VirtualDesktopManager",
            "org.kde.KWin.VirtualDesktopManager",
            None,
        )
        self._desktop_proxy.connect("g-properties-changed", self._desktop_changed)
        self._read_desktop()
        self._call_scripting("unloadScript", GLib.Variant("(s)", (SCRIPT_NAME,)))
        result = self._call_scripting(
            "loadScript",
            GLib.Variant(
                "(ss)",
                (str(Path(__file__).with_name("kwin-observer.js")), SCRIPT_NAME),
            ),
            GLib.VariantType.new("(i)"),
        )
        if result is None or result.unpack()[0] < 0:
            raise RuntimeError("KWin rejected the Obsidience observer script")
        self._call_scripting("start", None)
        self._script_loaded = True

    def stop(self) -> None:
        if self._script_loaded:
            try:
                from gi.repository import GLib

                self._call_scripting("unloadScript", GLib.Variant("(s)", (SCRIPT_NAME,)))
            except Exception:
                pass
        self._script_loaded = False
        if self._connection is not None and self._registration_id:
            self._connection.unregister_object(self._registration_id)
            self._registration_id = 0
        if self._connection is not None:
            try:
                from gi.repository import Gio, GLib

                self._connection.call_sync(
                    "org.freedesktop.DBus",
                    "/org/freedesktop/DBus",
                    "org.freedesktop.DBus",
                    "ReleaseName",
                    GLib.Variant("(s)", (BUS_NAME,)),
                    GLib.VariantType.new("(u)"),
                    Gio.DBusCallFlags.NONE,
                    3_000,
                    None,
                )
            except Exception:
                pass
        self._connection = None

    def state(self) -> dict:
        return {
            "schema": "obsidience.shell-state.v1",
            "active_window": {
                "id": self.active_window_id,
                "app_id": self.active_app_id,
                "title": self.active_title,
            },
            "workspace": {"id": self.workspace_id, "name": self.workspace_name},
            "windows": [asdict(window) for window in self.windows],
            "read_only": True,
        }

    def _call_scripting(self, method: str, parameters, reply_type=None):
        from gi.repository import Gio

        if self._connection is None:
            raise RuntimeError("KWin observer is not connected")
        try:
            return self._connection.call_sync(
                KWIN_BUS,
                "/Scripting",
                "org.kde.kwin.Scripting",
                method,
                parameters,
                reply_type,
                Gio.DBusCallFlags.NONE,
                3_000,
                None,
            )
        except Exception:
            if method == "unloadScript":
                return None
            raise

    def _handle_method(
        self, _connection, _sender, _path, _interface, method, parameters, invocation
    ) -> None:
        if method == "NotifyActiveWindow":
            caption, app_id, window_id = parameters.unpack()
            next_state = (_text(caption), _text(app_id), _text(window_id, 128))
            before = (self.active_title, self.active_app_id, self.active_window_id)
            self.active_title, self.active_app_id, self.active_window_id = next_state
            invocation.return_value(None)
            if next_state != before:
                self.on_change()
            return
        if method == "NotifyWindowList":
            windows = parse_window_list(parameters.unpack()[0])
            before = self.windows
            self.windows = windows
            invocation.return_value(None)
            if windows != before:
                self.on_change()
            return
        if method == "GetState":
            from gi.repository import GLib

            invocation.return_value(
                GLib.Variant("(s)", (json.dumps(self.state(), separators=(",", ":")),))
            )
            return
        invocation.return_dbus_error("org.obsidience.Shell.UnknownMethod", method)

    def _desktop_changed(self, *_args) -> None:
        before = (self.workspace_id, self.workspace_name)
        self._read_desktop()
        if before != (self.workspace_id, self.workspace_name):
            self.on_change()

    def _read_desktop(self) -> None:
        if self._desktop_proxy is None:
            return
        current = self._desktop_proxy.get_cached_property("current")
        desktops = self._desktop_proxy.get_cached_property("desktops")
        self.workspace_id = _text(current.unpack() if current else "", 128)
        self.workspace_name = "Workspace"
        for row in desktops.unpack() if desktops else ():
            if len(row) >= 3 and _text(row[1], 128) == self.workspace_id:
                self.workspace_name = _text(row[2]) or "Workspace"
                break

"""Event-driven X11 window observation and exact EWMH activation."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from Xlib import X, Xatom, display, error, protocol
from Xlib.Xutil import IconicState

from .model import ApplicationWindow


class X11SurfaceWindows:
    def __init__(
        self,
        *,
        surface_id: str,
        display_name: str,
        on_change: Callable[[str, str, tuple[ApplicationWindow, ...]], None],
    ) -> None:
        self.surface_id = surface_id
        self.display_name = display_name
        self.on_change = on_change
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run,
            name=f"obsidience-windows-{self.surface_id}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def activate(self, window_id: str, timeout: float = 2.0) -> tuple[bool, str]:
        try:
            xid = int(window_id, 16)
        except (TypeError, ValueError):
            return False, "invalid_window_id"
        connection = display.Display(self.display_name)
        try:
            screen = connection.screen()
            root = screen.root
            clients = self._window_ids(connection, root, "_NET_CLIENT_LIST")
            if xid not in clients:
                return False, "stale_window"
            target = connection.create_resource_object("window", xid)
            active_atom = connection.intern_atom("_NET_ACTIVE_WINDOW")
            event = protocol.event.ClientMessage(
                window=target,
                client_type=active_atom,
                data=(32, [2, X.CurrentTime, 0, 0, 0]),
            )
            root.send_event(
                event,
                event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask,
            )
            connection.flush()
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                active = self._window_ids(connection, root, "_NET_ACTIVE_WINDOW")
                if active and active[0] == xid:
                    return True, ""
                time.sleep(0.02)
            return False, "activation_not_confirmed"
        except (error.XError, OSError):
            return False, "x11_error"
        finally:
            connection.close()

    def _run(self) -> None:
        connection = display.Display(self.display_name)
        try:
            root = connection.screen().root
            root.change_attributes(
                event_mask=X.PropertyChangeMask | X.SubstructureNotifyMask
            )
            self._publish(connection, root)
            while not self._stop.is_set():
                event = connection.next_event()
                if event.type in (
                    X.PropertyNotify,
                    X.CreateNotify,
                    X.DestroyNotify,
                    X.MapNotify,
                    X.UnmapNotify,
                    X.ReparentNotify,
                ):
                    self._publish(connection, root)
        except (error.DisplayConnectionError, OSError):
            return
        finally:
            connection.close()

    def _publish(self, connection: display.Display, root) -> None:
        active_ids = self._window_ids(connection, root, "_NET_ACTIVE_WINDOW")
        active = f"0x{active_ids[0]:08x}" if active_ids else ""
        windows: list[ApplicationWindow] = []
        for xid in self._window_ids(connection, root, "_NET_CLIENT_LIST")[:256]:
            try:
                window = connection.create_resource_object("window", xid)
                record = self._record(connection, window, xid)
                if record is not None:
                    window.change_attributes(
                        event_mask=X.PropertyChangeMask | X.StructureNotifyMask
                    )
                    windows.append(record)
            except error.XError:
                continue
        connection.flush()
        self.on_change(self.surface_id, active, tuple(windows))

    def _record(
        self, connection: display.Display, window, xid: int
    ) -> ApplicationWindow | None:
        types = set(self._atom_values(connection, window, "_NET_WM_WINDOW_TYPE"))
        excluded_types = {
            connection.intern_atom(name)
            for name in (
                "_NET_WM_WINDOW_TYPE_DESKTOP",
                "_NET_WM_WINDOW_TYPE_DOCK",
                "_NET_WM_WINDOW_TYPE_TOOLBAR",
                "_NET_WM_WINDOW_TYPE_MENU",
                "_NET_WM_WINDOW_TYPE_UTILITY",
                "_NET_WM_WINDOW_TYPE_SPLASH",
                "_NET_WM_WINDOW_TYPE_DROPDOWN_MENU",
                "_NET_WM_WINDOW_TYPE_POPUP_MENU",
                "_NET_WM_WINDOW_TYPE_TOOLTIP",
                "_NET_WM_WINDOW_TYPE_NOTIFICATION",
            )
        }
        if types & excluded_types:
            return None
        states = set(self._atom_values(connection, window, "_NET_WM_STATE"))
        if connection.intern_atom("_NET_WM_STATE_SKIP_TASKBAR") in states:
            return None
        wm_class = window.get_wm_class() or ()
        resource_name = str(wm_class[0] if wm_class else "").strip()
        app_id = resource_name.split(" (", 1)[0].strip()
        if not app_id and wm_class:
            app_id = str(wm_class[-1]).strip()
        if not app_id:
            return None
        title = self._text_property(connection, window, "_NET_WM_NAME")
        if not title:
            title = window.get_wm_name() or app_id
        pid_values = self._cardinals(connection, window, "_NET_WM_PID")
        state = window.get_wm_state()
        return ApplicationWindow(
            window_id=f"0x{xid:08x}",
            app_id=app_id,
            title=str(title),
            pid=int(pid_values[0]) if pid_values else 0,
            minimized=bool(state and state.state == IconicState),
        )

    @staticmethod
    def _window_ids(connection: display.Display, window, name: str) -> list[int]:
        atom = connection.intern_atom(name)
        prop = window.get_full_property(atom, Xatom.WINDOW)
        return [int(value) for value in prop.value] if prop else []

    @staticmethod
    def _atom_values(connection: display.Display, window, name: str) -> list[int]:
        atom = connection.intern_atom(name)
        prop = window.get_full_property(atom, Xatom.ATOM)
        return [int(value) for value in prop.value] if prop else []

    @staticmethod
    def _cardinals(connection: display.Display, window, name: str) -> list[int]:
        atom = connection.intern_atom(name)
        prop = window.get_full_property(atom, Xatom.CARDINAL)
        return [int(value) for value in prop.value] if prop else []

    @staticmethod
    def _text_property(connection: display.Display, window, name: str) -> str:
        atom = connection.intern_atom(name)
        utf8 = connection.intern_atom("UTF8_STRING")
        prop = window.get_full_property(atom, utf8)
        if not prop:
            return ""
        value = prop.value
        return value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value)

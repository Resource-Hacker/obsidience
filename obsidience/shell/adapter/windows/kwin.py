"""KWin application state projection and exact-ID activation."""

from __future__ import annotations

import json
import os
import secrets
import threading
import time
from pathlib import Path

import dbus

from obsidience.shell.adapter.kwin import KWinObserver

from .model import ApplicationWindow

_ACTIVATE_SCRIPT = r"""
(function () {
  const expectedId = String(__obsidienceWindowId);
  const matches = workspace.windowList().filter(function (window) {
    return String(window.internalId) === expectedId;
  });
  if (matches.length !== 1) return;
  const target = matches[0];
  target.minimized = false;
  workspace.activeWindow = target;
})();
"""


class KWinSurfaceWindows:
    """Keep Noctalia-derived observation read-only; mutate only in this adapter."""

    _activation_lock = threading.Lock()

    def __init__(self, on_change) -> None:
        self.on_change = on_change
        self.observer = KWinObserver(self._publish)

    def start(self) -> None:
        self.observer.start()
        self._publish()

    def stop(self) -> None:
        self.observer.stop()

    def activate(self, window_id: str) -> tuple[bool, str]:
        if not window_id or len(window_id) > 128 or any(ord(char) < 32 for char in window_id):
            return False, "invalid_window_id"
        with self._activation_lock:
            runtime = Path(os.environ.get("XDG_RUNTIME_DIR", "/run/user/1000"))
            scratch = runtime / "obsidience-shell" / "window-activation"
            scratch.mkdir(mode=0o700, parents=True, exist_ok=True)
            token = secrets.token_hex(8)
            name = f"obsidience-window-activate-{token}"
            path = scratch / f"{name}.js"
            path.write_text(
                f"const __obsidienceWindowId = {json.dumps(window_id)};\n"
                + _ACTIVATE_SCRIPT,
                encoding="utf-8",
            )
            bus = dbus.SessionBus()
            scripting = dbus.Interface(
                bus.get_object("org.kde.KWin", "/Scripting"),
                "org.kde.kwin.Scripting",
            )
            loaded = False
            try:
                script_id = int(
                    scripting.loadScript(
                        str(path), name, signature="ss", timeout=3
                    )
                )
                if script_id < 0:
                    return False, "kwin_rejected_script"
                loaded = True
                script = dbus.Interface(
                    bus.get_object("org.kde.KWin", f"/Scripting/Script{script_id}"),
                    "org.kde.kwin.Script",
                )
                script.run(timeout=3)
                time.sleep(0.02)
                return True, ""
            except (dbus.DBusException, TypeError, ValueError):
                return False, "kwin_error"
            finally:
                if loaded:
                    try:
                        scripting.unloadScript(name, timeout=3)
                    except dbus.DBusException:
                        pass
                path.unlink(missing_ok=True)
                bus.close()

    def _publish(self) -> None:
        windows = tuple(
            ApplicationWindow(
                window_id=window.window_id,
                app_id=window.app_id,
                title=window.title,
            )
            for window in self.observer.windows
        )
        self.on_change("samsung", self.observer.active_window_id, windows)

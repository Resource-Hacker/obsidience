"""Credentials for the Shell command socket (127.0.0.1:8768, obsidience.shell.v1).

Any web page can open a loopback WebSocket and name the subprotocol, so the
Shell admits only clients presenting a token from a user-only runtime file.
The Shell host unit writes fresh tokens on every start; read them for every
connection so clients follow a Shell restart without restarting themselves.
``adapter.token`` is the window adapter's own credential: it is never served
over HTTP, and only its holder may subscribe as the adapter and publish the
Scene.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

_TOKEN = re.compile(r"[0-9a-f]{64}")


def token_path() -> Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return Path(runtime) / "obsidience-shell" / "command.token"


def adapter_token_path() -> Path:
    return token_path().with_name("adapter.token")


def _read(path: Path) -> str:
    token = path.read_text(encoding="ascii", errors="replace").strip()
    if _TOKEN.fullmatch(token) is None:
        raise OSError(f"Shell token is invalid: {path}")
    return token


def read_token() -> str:
    """Return the current token; raise OSError when the Shell has not written one."""
    return _read(token_path())


def command_url(url: str) -> str:
    """Return ``url`` (``ws://host:port``) carrying the current token."""
    return f"{url}/?token={read_token()}"


def adapter_url(url: str) -> str:
    """Return ``url`` carrying the window adapter's credential."""
    return f"{url}/?token={_read(adapter_token_path())}"

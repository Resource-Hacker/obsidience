"""Project the Obsidience palette into native application chrome.

Applications remain ordinary Hyprland/Openbox clients.  This module only writes
supported theme surfaces; it never embeds, reparents, launches, or sizes an
application window.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import tempfile
from pathlib import Path


PALETTE_PATH = Path(__file__).with_name("palette.json")
EDGE_POLICY_PATH = Path("/etc/opt/edge/policies/managed/obsidience-theme.json")
OPENBOX_THEME_PATH = Path.home() / ".themes/Obsidience/openbox-3/themerc"
OPENBOX_CONFIGS = (
    Path.home() / ".config/openbox/usb-monitor-rc.xml",
    Path.home() / ".config/openbox/rc.xml",
)
COLOR_KEYS = frozenset(
    {
        "surface",
        "inactive_surface",
        "accent",
        "strong_accent",
        "inactive_border",
        "separator",
        "hover",
        "text",
        "muted",
        "inactive_text",
        "selection",
        "shadow",
    }
)
METRIC_KEYS = frozenset(
    {
        "border_width",
        "corner_radius",
        "title_height",
        "title_font",
        "title_font_size",
        "title_letter_spacing",
    }
)
COLOR = re.compile(r"^#[0-9a-f]{6}(?:[0-9a-f]{2})?$", re.IGNORECASE)


def load_palette(path: Path = PALETTE_PATH) -> dict:
    record = json.loads(path.read_text(encoding="utf-8"))
    if set(record) != {"schema", "name", "colors", "metrics"}:
        raise ValueError("theme must contain only schema, name, colors, and metrics")
    if record["schema"] != "obsidience.shell-theme.v1" or record["name"] != "Obsidience":
        raise ValueError("unsupported Obsidience theme")
    colors = record["colors"]
    metrics = record["metrics"]
    if not isinstance(colors, dict) or set(colors) != COLOR_KEYS:
        raise ValueError("theme color contract is incomplete")
    if any(not isinstance(value, str) or not COLOR.fullmatch(value) for value in colors.values()):
        raise ValueError("theme colors must be #RRGGBB or #AARRGGBB")
    if not isinstance(metrics, dict) or set(metrics) != METRIC_KEYS:
        raise ValueError("theme metric contract is incomplete")
    if not isinstance(metrics["title_font"], str) or not metrics["title_font"].strip():
        raise ValueError("theme title font is invalid")
    for key in ("border_width", "corner_radius", "title_height", "title_font_size"):
        value = metrics[key]
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ValueError(f"theme metric {key} must be a positive integer")
    spacing = metrics["title_letter_spacing"]
    if not isinstance(spacing, (int, float)) or isinstance(spacing, bool) or spacing < 0:
        raise ValueError("theme title letter spacing is invalid")
    return record


def opaque(color: str) -> str:
    """Return RGB from QML's #AARRGGBB or preserve an RGB color."""
    if not COLOR.fullmatch(color):
        raise ValueError("invalid theme color")
    return ("#" + color[3:] if len(color) == 9 else color).lower()


def render_edge_policy(theme: dict) -> str:
    payload = {
        "BrowserThemeColor": opaque(theme["colors"]["surface"]),
        "BrowserColorScheme": "device",
    }
    return json.dumps(payload, indent=2) + "\n"


def render_openbox_theme(theme: dict) -> str:
    colors = theme["colors"]
    metrics = theme["metrics"]
    active = opaque(colors["surface"])
    inactive = opaque(colors["inactive_surface"])
    accent = opaque(colors["accent"])
    inactive_border = opaque(colors["inactive_border"])
    text = opaque(colors["text"])
    inactive_text = opaque(colors["inactive_text"])
    selection = opaque(colors["selection"])
    border_width = metrics["border_width"]
    return f"""# Generated from obsidience/shell/theme/palette.json.
border.width: {border_width}
padding.width: 4
padding.height: 3
window.client.padding.width: 0
window.handle.width: 1
menu.overlap: 0
*.justify: center

window.active.border.color: {accent}
window.inactive.border.color: {inactive_border}
window.active.title.bg: flat solid
window.active.title.bg.color: {active}
window.inactive.title.bg: flat solid
window.inactive.title.bg.color: {inactive}
window.active.title.separator.color: {accent}
window.inactive.title.separator.color: {inactive_border}
window.active.label.bg: parentrelative
window.inactive.label.bg: parentrelative
window.active.label.text.color: {text}
window.inactive.label.text.color: {inactive_text}

window.active.button.*.bg: parentrelative
window.inactive.button.*.bg: parentrelative
window.active.button.*.image.color: {text}
window.inactive.button.*.image.color: {inactive_text}
window.active.button.hover.bg: flat solid border
window.active.button.hover.bg.color: {selection}
window.active.button.hover.bg.border.color: {accent}
window.active.button.hover.image.color: {text}
window.active.button.pressed.bg: flat solid border
window.active.button.pressed.bg.color: {accent}
window.active.button.pressed.bg.border.color: {accent}

window.*.handle.bg: flat solid
window.*.handle.bg.color: {active}
window.*.grip.bg: flat solid
window.*.grip.bg.color: {active}

menu.border.width: {border_width}
menu.border.color: {accent}
menu.title.bg: flat solid
menu.title.bg.color: {active}
menu.title.text.color: {text}
menu.items.bg: flat solid
menu.items.bg.color: {active}
menu.items.text.color: {text}
menu.items.disabled.text.color: {inactive_text}
menu.items.active.bg: flat solid
menu.items.active.bg.color: {selection}
menu.items.active.text.color: {text}
menu.separator.width: 1
menu.separator.padding.width: 0
menu.separator.padding.height: 3
menu.separator.color: {inactive_border}

osd.border.width: {border_width}
osd.border.color: {accent}
osd.bg: flat solid
osd.bg.color: {active}
osd.active.label.bg: parentrelative
osd.active.label.text.color: {text}
osd.inactive.label.bg: parentrelative
osd.inactive.label.text.color: {inactive_text}
osd.hilight.bg: flat solid
osd.hilight.bg.color: {selection}
osd.unhilight.bg: flat solid
osd.unhilight.bg.color: {inactive}
"""


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _configure_openbox(path: Path, font: str) -> None:
    source = path.read_text(encoding="utf-8")
    match = re.search(r"<theme>.*?</theme>", source, re.DOTALL)
    if not match:
        raise RuntimeError(f"Openbox theme block missing: {path}")
    block = re.sub(r"<name>[^<]*</name>", "<name>Obsidience</name>", match.group(), count=1)
    block = block.replace("<name>sans</name>", f"<name>{font}</name>")
    updated = source[: match.start()] + block + source[match.end() :]
    if updated != source:
        _atomic_write(path, updated)


def _run(command: list[str], *, env: dict[str, str] | None = None, timeout: int = 8) -> None:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"theme command failed: {command[0]}: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[:500]
        raise RuntimeError(f"theme command failed: {' '.join(command)}: {detail}")


def _install_edge_policy(content: str) -> None:
    directory = EDGE_POLICY_PATH.parent
    metadata = directory.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or directory.is_symlink() or metadata.st_uid != 0:
        raise RuntimeError("Edge managed policy directory is not a root-owned directory")
    if EDGE_POLICY_PATH.is_symlink() or EDGE_POLICY_PATH.is_dir():
        raise RuntimeError("Edge theme policy destination is not a regular file")
    descriptor, temporary = tempfile.mkstemp(prefix="obsidience-edge-theme-")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        _run(
            [
                "/usr/bin/sudo",
                "-n",
                "/usr/bin/install",
                "-m",
                "0644",
                "-o",
                "root",
                "-g",
                "root",
                "-T",
                temporary,
                str(EDGE_POLICY_PATH),
            ]
        )
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def apply(theme: dict) -> None:
    metrics = theme["metrics"]
    _atomic_write(OPENBOX_THEME_PATH, render_openbox_theme(theme))
    for path in OPENBOX_CONFIGS:
        _configure_openbox(path, metrics["title_font"])

    _install_edge_policy(render_edge_policy(theme))
    for display in (":2.0", ":2.1"):
        _run(
            ["/usr/bin/openbox", "--reconfigure"],
            env={**os.environ, "DISPLAY": display, "SESSION_MANAGER": ""},
        )
    if subprocess.run(
        ["/usr/bin/pgrep", "-x", "msedge"],
        capture_output=True,
        check=False,
    ).returncode == 0:
        _run(
            [
                "/usr/bin/microsoft-edge-stable",
                "--refresh-platform-policy",
                "--no-startup-window",
            ]
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply the Obsidience application theme")
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate and print the supported projections without changing the system",
    )
    args = parser.parse_args()
    theme = load_palette()
    if args.check:
        print(render_edge_policy(theme), end="")
        return 0
    apply(theme)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

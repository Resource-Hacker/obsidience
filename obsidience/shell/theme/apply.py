"""Project the Obsidience palette into supported application-native chrome."""

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
    _install_edge_policy(render_edge_policy(theme))
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

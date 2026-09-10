"""One-shot, in-memory Wayland screen capture."""

from __future__ import annotations

import re
import struct
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


WAYSHOT_BINARY = Path("/var/lib/ai/opt/obsidience-wayshot/current/wayshot")
MAX_CAPTURE_BYTES = 64 * 1024 * 1024
MAX_CAPTURE_PIXELS = 16_000_000
_CAPTURE_TIMEOUT_SECONDS = 10
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_PNG_IEND = b"\x00\x00\x00\x00IEND\xaeB`\x82"
_STABLE_ID = re.compile(r"[0-9a-fA-F]{1,32}\Z")


class ScreenCaptureError(ValueError):
    """A one-shot screen capture failed its bounded contract."""


@dataclass(frozen=True, slots=True)
class ScreenCapture:
    """One PNG held only in memory, with its exact capture target."""

    image_png: bytes
    target_kind: str
    target: str
    width: int
    height: int
    captured_at_unix_ns: int

    def metadata(self) -> dict[str, str | int]:
        return {
            "mime_type": "image/png",
            "target_kind": self.target_kind,
            "target": self.target,
            "width": self.width,
            "height": self.height,
            "size_bytes": len(self.image_png),
            "captured_at_unix_ns": self.captured_at_unix_ns,
        }


def _output_name(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 128:
        raise ScreenCaptureError("output_name must contain 1-128 characters")
    if value != value.strip() or any(ord(character) < 32 for character in value):
        raise ScreenCaptureError("output_name contains invalid characters")
    return value


def _hyprland_stable_id(value: object) -> str:
    if not isinstance(value, str) or _STABLE_ID.fullmatch(value) is None:
        raise ScreenCaptureError("stable_id must be a 1-32 character hexadecimal value")
    return value.lower()


def _png_size(image: bytes) -> tuple[int, int]:
    if len(image) > MAX_CAPTURE_BYTES:
        raise ScreenCaptureError("captured image exceeded 64 MiB")
    if (
        len(image) < 45
        or not image.startswith(_PNG_SIGNATURE)
        or image[8:16] != b"\x00\x00\x00\rIHDR"
        or not image.endswith(_PNG_IEND)
    ):
        raise ScreenCaptureError("capture did not return a complete PNG")
    width, height = struct.unpack(">II", image[16:24])
    if not width or not height or width * height > MAX_CAPTURE_PIXELS:
        raise ScreenCaptureError("captured image dimensions exceeded the pixel bound")
    return width, height


def capture_screen(
    *,
    output_name: str | None = None,
    stable_id: str | None = None,
) -> ScreenCapture:
    """Capture exactly one output or Hyprland stable toplevel identifier."""
    if (output_name is None) == (stable_id is None):
        raise ScreenCaptureError("provide exactly one of output_name or stable_id")

    if output_name is not None:
        target_kind = "output"
        target = _output_name(output_name)
        selector = "--output"
    else:
        target_kind = "toplevel"
        target = _hyprland_stable_id(stable_id)
        selector = "--toplevel"

    command = [
        str(WAYSHOT_BINARY),
        "--config",
        "/dev/null",
        "--encoding",
        "png",
        selector,
        target,
        "-",
    ]
    try:
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            timeout=_CAPTURE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise ScreenCaptureError("screen capture timed out") from exc
    except OSError as exc:
        raise ScreenCaptureError(f"screen capture could not start: {exc}") from exc

    if completed.returncode:
        detail = completed.stderr[:512].decode("utf-8", errors="replace").strip()
        suffix = f": {detail}" if detail else ""
        raise ScreenCaptureError(f"screen capture failed{suffix}")

    image = bytes(completed.stdout)
    width, height = _png_size(image)
    return ScreenCapture(
        image_png=image,
        target_kind=target_kind,
        target=target,
        width=width,
        height=height,
        captured_at_unix_ns=time.time_ns(),
    )

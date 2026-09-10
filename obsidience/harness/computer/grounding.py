"""Private process identity for the image-bound computer action controller."""
from __future__ import annotations

from pathlib import Path


class GroundingError(ValueError):
    pass


def process_start_time(pid: int) -> int:
    """Linux starttime disambiguates a reused PID without inspecting argv."""
    if type(pid) is not int or pid <= 0:
        raise GroundingError("The target has no process identity.")
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return int(fields[19])
    except (OSError, IndexError, ValueError) as exc:
        raise GroundingError("The target process is no longer available.") from exc


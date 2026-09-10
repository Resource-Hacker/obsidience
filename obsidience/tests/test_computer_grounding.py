"""Process identity uses kernel start time, never names or command lines."""
from __future__ import annotations

import pytest

from obsidience.harness.computer import grounding


def test_process_start_time_uses_stat_identity_despite_spaces_and_parentheses(monkeypatch):
    seen = []
    def read(path):
        seen.append(str(path))
        return "42 (a name ) with (brackets)) " + " ".join(["S"] + ["0"] * 18 + ["123456"] + ["0"] * 3)
    monkeypatch.setattr(grounding.Path, "read_text", read)
    assert grounding.process_start_time(42) == 123456
    assert seen == ["/proc/42/stat"]


@pytest.mark.parametrize("pid", [0, -1, True, 4.2, "42"])
def test_invalid_process_identity_is_rejected_without_reading(pid, monkeypatch):
    monkeypatch.setattr(grounding.Path, "read_text", lambda path: pytest.fail("invalid PID read"))
    with pytest.raises(grounding.GroundingError):
        grounding.process_start_time(pid)


def test_disappeared_process_cannot_reuse_old_identity(monkeypatch):
    def vanished(path):
        raise FileNotFoundError
    monkeypatch.setattr(grounding.Path, "read_text", vanished)
    with pytest.raises(grounding.GroundingError, match="no longer available"):
        grounding.process_start_time(42)

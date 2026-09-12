from __future__ import annotations

import struct
import subprocess

import pytest

from obsidience.harness.computer import capture


@pytest.fixture(autouse=True)
def graphical_session_environment(monkeypatch):
    # Unit tests use a fake Wayland name and never connect to the workstation.
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-test")


def _png(width: int = 2, height: int = 3) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\rIHDR"
        + struct.pack(">II", width, height)
        + b"\x08\x06\x00\x00\x00"
        + b"\x00\x00\x00\x00"
        + b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )


def _successful_run(calls: list[list[str]]):
    def run(command, **kwargs):
        calls.append(command)
        assert kwargs == {
            "stdin": subprocess.DEVNULL,
            "capture_output": True,
            "check": False,
            "timeout": 10,
        }
        return subprocess.CompletedProcess(command, 0, _png(), b"")

    return run


def test_captures_exact_output_to_memory(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(capture.subprocess, "run", _successful_run(calls))

    result = capture.capture_screen(output_name="DP-8")

    assert calls == [
        [
            str(capture.WAYSHOT_BINARY),
            "--config",
            "/dev/null",
            "--encoding",
            "png",
            "--output",
            "DP-8",
            "-",
        ]
    ]
    assert result.image_png == _png()
    metadata = result.metadata()
    assert metadata.pop("captured_at_unix_ns") > 0
    assert metadata == {
        "mime_type": "image/png",
        "target_kind": "output",
        "target": "DP-8",
        "width": 2,
        "height": 3,
        "size_bytes": len(_png()),
    }


def test_captures_exact_hyprland_stable_id(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(capture.subprocess, "run", _successful_run(calls))

    result = capture.capture_screen(stable_id="18ABC002")

    assert calls[0][-3:] == ["--toplevel", "18abc002", "-"]
    assert result.target_kind == "toplevel"
    assert result.target == "18abc002"


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({}, "provide exactly one"),
        ({"output_name": "DP-8", "stable_id": "18000002"}, "provide exactly one"),
        ({"output_name": " DP-8"}, "invalid characters"),
        ({"stable_id": "window-1"}, "hexadecimal"),
    ],
)
def test_rejects_ambiguous_or_invalid_targets(arguments, message):
    with pytest.raises(capture.ScreenCaptureError, match=message):
        capture.capture_screen(**arguments)


def test_rejects_failed_or_unbounded_capture(monkeypatch):
    monkeypatch.setattr(
        capture.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command, 1, b"", b"No output named 'missing' found",
        ),
    )
    with pytest.raises(capture.ScreenCaptureError, match="No output named"):
        capture.capture_screen(output_name="missing")

    monkeypatch.setattr(capture, "MAX_CAPTURE_BYTES", len(_png()) - 1)
    monkeypatch.setattr(capture.subprocess, "run", _successful_run([]))
    with pytest.raises(capture.ScreenCaptureError, match="exceeded 64 MiB"):
        capture.capture_screen(output_name="DP-8")


def test_rejects_malformed_or_oversized_png(monkeypatch):
    def result(image: bytes):
        return lambda command, **kwargs: subprocess.CompletedProcess(
            command, 0, image, b""
        )

    monkeypatch.setattr(capture.subprocess, "run", result(b"not a png"))
    with pytest.raises(capture.ScreenCaptureError, match="complete PNG"):
        capture.capture_screen(output_name="DP-8")

    monkeypatch.setattr(capture.subprocess, "run", result(_png(5000, 5000)))
    with pytest.raises(capture.ScreenCaptureError, match="pixel bound"):
        capture.capture_screen(output_name="DP-8")


@pytest.mark.parametrize("display", [None, "", "   "])
def test_missing_session_fails_before_native_capture(monkeypatch, display):
    if display is None:
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    else:
        monkeypatch.setenv("WAYLAND_DISPLAY", display)
    monkeypatch.setattr(capture.subprocess, "run", lambda *args, **kwargs:
                        pytest.fail("must not guess another Wayland socket"))
    with pytest.raises(capture.ScreenCaptureError, match="no Wayland display") as error:
        capture.capture_screen(stable_id="18000007")
    assert error.value.code == "capture_session_unavailable"


def test_session_recovery_uses_exported_name_without_persistent_failure(monkeypatch):
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    with pytest.raises(capture.ScreenCaptureError):
        capture.capture_screen(output_name="HDMI-A-1")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-17")
    calls = []
    run = _successful_run(calls)
    def native(command, **kwargs):
        assert capture.os.environ["WAYLAND_DISPLAY"] == "wayland-17"
        return run(command, **kwargs)
    monkeypatch.setattr(capture.subprocess, "run", native)
    assert capture.capture_screen(output_name="HDMI-A-1").image_png == _png()
    assert len(calls) == 1


def test_harness_autostart_waits_for_exported_graphical_environment():
    from configparser import ConfigParser
    from pathlib import Path

    units = Path(__file__).resolve().parents[1] / "shell" / "systemd"
    path = units / "obsidience-harness-dev.service.d" / "10-graphical-session.conf"
    text = path.read_text()
    config = ConfigParser(strict=False)
    config.read_string(text)
    assert "graphical-session.target" in config["Unit"]["After"].split()
    assert "graphical-session.target" in config["Unit"]["PartOf"].split()
    # Empty assignment clears inherited default.target enablement.
    assert [line for line in text.splitlines() if line.startswith("WantedBy=")] == [
        "WantedBy=", "WantedBy=obsidience-shell-session.target",
    ]
    assert config["Install"]["WantedBy"] == "obsidience-shell-session.target"
    assert "Wants=obsidience-harness-dev.service" in (
        units / "obsidience-shell-session.target").read_text()
    assert "After=obsidience-harness-dev.service" in (
        units / "obsidience-shell-host.service").read_text()

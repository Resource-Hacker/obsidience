from __future__ import annotations

from pathlib import Path

import pytest

from obsidience.harness.realtime import media as media_runtime


def _patch_catalog(monkeypatch: pytest.MonkeyPatch, settings_path: Path) -> None:
    monkeypatch.setattr(media_runtime, "MEDIA_SETTINGS_PATH", settings_path)
    monkeypatch.setattr(
        media_runtime,
        "_audio_options",
        lambda kind: [{
            "id": f"{kind}:available",
            "label": f"Available {kind}",
            "available": True,
            "detail": "test",
        }],
    )
    monkeypatch.setattr(
        media_runtime,
        "_camera_options",
        lambda: [
            {"id": "none", "label": "No camera", "available": True, "detail": "test"},
            {
                "id": "v4l2:/dev/video0",
                "label": "Test camera",
                "available": True,
                "detail": "/dev/video0",
            },
        ],
    )


def test_interface_settings_are_one_persisted_exact_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings_path = tmp_path / "media-settings.json"
    _patch_catalog(monkeypatch, settings_path)

    media_runtime.set_interface("microphone", "microphone:available")
    media_runtime.set_interface("speaker", "speaker:available")
    media_runtime.set_interface("camera", "v4l2:/dev/video0")

    assert media_runtime.settings() == {
        "microphone": "microphone:available",
        "speaker": "speaker:available",
        "camera": "v4l2:/dev/video0",
        "tts_voice": "starfleet",
    }
    assert settings_path.stat().st_mode & 0o777 == 0o600


def test_interface_selection_fails_closed_for_missing_device(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_catalog(monkeypatch, tmp_path / "media-settings.json")

    with pytest.raises(ValueError, match="not currently available"):
        media_runtime.set_interface("camera", "v4l2:/dev/video99")
    with pytest.raises(ValueError, match="interface must be"):
        media_runtime.set_interface("display", "anything")


def test_fixed_speech_runtime_preserves_canonical_voice_ids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_catalog(monkeypatch, tmp_path / "media-settings.json")
    selected = media_runtime.set_voice("HAL")
    assert selected["voice"] == "hal"
    assert selected["transport"] == "Pipecat LocalAudioTransport 0.0.98"
    assert selected["turn_taking"] == "NVIDIA NeMo Voice Agent"
    assert selected["asr_chunk_ms"] == 160
    assert selected["tts"] == "Pocket TTS 3.0.2"
    assert selected["tts_device"] == "CPU"

    with pytest.raises(ValueError, match="voice must be"):
        media_runtime.set_voice("piper")


def test_saved_audio_name_resolves_to_current_pipewire_node(monkeypatch) -> None:
    selected = "alsa_input.usb-test.analog-stereo"
    command = ("/usr/bin/pactl", "-f", "json", "list", "sources")
    monkeypatch.setattr(
        media_runtime,
        "_run_json",
        lambda actual: [
            {
                "name": selected,
                "properties": {
                    "media.class": "Audio/Source",
                    "object.serial": "72",
                },
            }
        ]
        if actual == command
        else None,
    )

    assert media_runtime.resolve_audio_target("microphone", selected) == "72"


def test_obsbot_microphone_power_follows_the_camera(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        media_runtime,
        "resolve_audio_target",
        lambda kind, selection: calls.append(f"resolve:{kind}:{selection}") or "2396",
    )
    monkeypatch.setattr(
        media_runtime, "_obsbot_control", lambda *args: calls.append(":".join(args)) or ""
    )
    monkeypatch.setattr(
        media_runtime,
        "_set_microphone_unmuted",
        lambda selection: calls.append(f"unmute:{selection}"),
    )

    media_runtime.set_realtime_camera_active(media_runtime.DEFAULT_MICROPHONE, True)
    media_runtime.set_realtime_camera_active(media_runtime.DEFAULT_MICROPHONE, False)

    assert calls == [
        f"resolve:microphone:{media_runtime.DEFAULT_MICROPHONE}",
        "camera:on",
        "microphone:on",
        f"unmute:{media_runtime.DEFAULT_MICROPHONE}",
        f"resolve:microphone:{media_runtime.DEFAULT_MICROPHONE}",
        "camera:off",
    ]


def test_obsbot_camera_control_reads_once_and_sets_exact_state(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(media_runtime, "_OBSBOT_CAMERA_ACTIVE", None)
    monkeypatch.setattr(
        media_runtime,
        "_obsbot_control",
        lambda *args: calls.append(":".join(args))
        or "OBSBOT dev_status=0 auto_sleep_time=120",
    )

    assert media_runtime.obsbot_camera_state() == {"active": False}
    assert media_runtime.obsbot_camera_state() == {"active": False}
    assert media_runtime.set_obsbot_camera_active(True) == {"active": True}
    assert calls == ["status", "camera:on"]


def test_obsbot_camera_control_requires_boolean() -> None:
    with pytest.raises(ValueError, match="must be a boolean"):
        media_runtime.set_obsbot_camera_active("on")


def test_realtime_aec_wraps_the_selected_physical_route(monkeypatch) -> None:
    calls: list[object] = []
    microphone = "alsa_input.test"
    speaker = "alsa_output.test"

    monkeypatch.setattr(
        media_runtime,
        "resolve_audio_target",
        lambda kind, selection: calls.append(("resolve", kind, selection))
        or ("72" if kind == "microphone" else "74"),
    )
    monkeypatch.setattr(media_runtime, "_AEC_PROCESS", None)

    class Input:
        def __init__(self) -> None:
            self.writes: list[str] = []

        def write(self, material: str) -> None:
            self.writes.append(material)

        def flush(self) -> None:
            return None

        def close(self) -> None:
            return None

    class Process:
        def __init__(self) -> None:
            self.stdin = Input()
            self.returncode = None

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            self.returncode = 0
            return 0

        def terminate(self) -> None:
            self.returncode = -15

        def kill(self) -> None:
            self.returncode = -9

    process = Process()

    def popen(command, **kwargs):
        calls.append((command, kwargs))
        return process

    monkeypatch.setattr(media_runtime.subprocess, "Popen", popen)

    assert media_runtime.start_realtime_aec(microphone, speaker) == (
        media_runtime.REALTIME_AEC_SOURCE,
        media_runtime.REALTIME_AEC_SINK,
    )
    load = process.stdin.writes[0]
    assert "libpipewire-module-echo-cancel" in load
    assert "monitor.mode = false" in load
    assert "node.latency = 1440/48000" in load
    assert 'target.object = "72"' in load
    assert 'target.object = "74"' in load
    assert "audio.channels = 1" in load
    assert "load-module module-echo-cancel" not in load
    assert "aec.args" not in load
    assert "playback.props" in load
    assert "media.class = Audio/Sink" in load
    assert load.count("node.dont-move = true") == 2
    assert load.count("node.dont-fallback = true") == 2
    assert media_runtime.REALTIME_AEC_CAPTURE in load
    assert media_runtime.REALTIME_AEC_SINK in load
    assert media_runtime.REALTIME_AEC_PLAYBACK in load
    assert ("resolve", "microphone", media_runtime.REALTIME_AEC_SOURCE) in calls
    assert ("resolve", "speaker", media_runtime.REALTIME_AEC_SINK) in calls
    media_runtime.stop_realtime_aec()
    assert process.stdin.writes[-1] == "quit\n"


def test_audio_target_resolution_fails_closed_for_missing_or_ambiguous_node(
    monkeypatch,
) -> None:
    monkeypatch.setattr(media_runtime, "_run_json", lambda _command: [])
    with pytest.raises(RuntimeError, match="does not resolve to one"):
        media_runtime.resolve_audio_target("microphone", "missing")
    with pytest.raises(ValueError, match="microphone or speaker"):
        media_runtime.resolve_audio_target("camera", "anything")


def test_prepare_obsbot_enables_then_attests_exact_audio_packet_count(monkeypatch) -> None:
    calls: list[object] = []
    monkeypatch.setattr(
        media_runtime,
        "set_realtime_camera_active",
        lambda selection, enabled: calls.append(("enabled", selection, enabled)),
    )
    monkeypatch.setattr(
        media_runtime,
        "resolve_audio_target",
        lambda kind, selection: calls.append((kind, selection)) or "2396",
    )
    monkeypatch.setattr(
        media_runtime.subprocess,
        "run",
        lambda command, **_kwargs: calls.append(command)
        or media_runtime.subprocess.CompletedProcess(
            command,
            1,
            stdout=b"\x01\x00"
            + bytes((media_runtime.MICROPHONE_PROBE_SAMPLES * 2) - 2),
            stderr=b"",
        ),
    )

    assert media_runtime.prepare_microphone(media_runtime.DEFAULT_MICROPHONE) == "2396"
    assert calls[:2] == [
        ("enabled", media_runtime.DEFAULT_MICROPHONE, True),
        ("microphone", media_runtime.DEFAULT_MICROPHONE),
    ]
    assert "--target" in calls[2]
    assert calls[2][calls[2].index("--target") + 1] == "2396"


@pytest.mark.parametrize("sample_count", [0, 1, media_runtime.MICROPHONE_PROBE_SAMPLES - 1])
def test_prepare_microphone_rejects_missing_or_incomplete_audio_packets(
    monkeypatch, sample_count,
) -> None:
    monkeypatch.setattr(media_runtime, "set_realtime_camera_active", lambda *_args: None)
    monkeypatch.setattr(media_runtime, "resolve_audio_target", lambda *_args: "72")
    monkeypatch.setattr(
        media_runtime.subprocess,
        "run",
        lambda *_args, **_kwargs: media_runtime.subprocess.CompletedProcess(
            (), 0, stdout=bytes(sample_count * 2), stderr=b""
        ),
    )

    with pytest.raises(RuntimeError, match="expected audio packets"):
        media_runtime.prepare_microphone("some-other-microphone")


def test_prepare_microphone_accepts_complete_clocked_digital_silence(monkeypatch) -> None:
    monkeypatch.setattr(media_runtime, "set_realtime_camera_active", lambda *_args: None)
    monkeypatch.setattr(media_runtime, "resolve_audio_target", lambda *_args: "72")
    monkeypatch.setattr(
        media_runtime.subprocess,
        "run",
        lambda *_args, **_kwargs: media_runtime.subprocess.CompletedProcess(
            (),
            1,
            stdout=bytes(media_runtime.MICROPHONE_PROBE_SAMPLES * 2),
            stderr=b"",
        ),
    )

    assert media_runtime.prepare_microphone("some-other-microphone") == "72"


def test_prepare_microphone_rejects_a_stalled_audio_clock(monkeypatch) -> None:
    monkeypatch.setattr(media_runtime, "set_realtime_camera_active", lambda *_args: None)
    monkeypatch.setattr(media_runtime, "resolve_audio_target", lambda *_args: "72")

    def stalled(command, **_kwargs):
        raise media_runtime.subprocess.TimeoutExpired(command, 3)

    monkeypatch.setattr(media_runtime.subprocess, "run", stalled)
    with pytest.raises(RuntimeError, match="did not produce audio packets"):
        media_runtime.prepare_microphone("some-other-microphone")

"""Physical media inventory and the fixed Obsidience speech runtime."""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path("/home/wissenschafter/Projects/obsidience")
MEDIA_SETTINGS_PATH = PROJECT_ROOT / "obsidience/state/media-settings.json"
DEFAULT_MICROPHONE = (
    "alsa_input.usb-Remo_Tech_Co.__Ltd._OBSBOT_Tiny_2_Lite-02.analog-stereo"
)
DEFAULT_SPEAKER = "alsa_output.pci-0000_7a_00.6.analog-stereo"
DEFAULT_CAMERA = "v4l2:/dev/video0"
DEFAULT_TTS_VOICE = "starfleet"
REALTIME_AEC_SOURCE = "obsidience_realtime_aec_source"
REALTIME_AEC_CAPTURE = "obsidience_realtime_aec_capture"
REALTIME_AEC_SINK = "obsidience_realtime_aec_sink"
REALTIME_AEC_PLAYBACK = "obsidience_realtime_aec_playback"
INTERFACE_KINDS = ("microphone", "speaker", "camera")
TTS_VOICES = ("starfleet", "hal", "ultron")
MAX_PACTL_BYTES = 2 * 1024 * 1024
OBSBOT_CONTROL = Path("/home/wissenschafter/src/obsbot/obsbot_ctl")
MICROPHONE_PROBE_SAMPLES = 16_000

_SETTINGS_LOCK = threading.RLock()
_AEC_LOCK = threading.RLock()
_CAMERA_LOCK = threading.RLock()
_AEC_PROCESS: subprocess.Popen[str] | None = None
_OBSBOT_CAMERA_ACTIVE: bool | None = None


def _defaults() -> dict[str, Any]:
    return {
        "schema_version": 3,
        "microphone": DEFAULT_MICROPHONE,
        "speaker": DEFAULT_SPEAKER,
        "camera": DEFAULT_CAMERA,
        "tts_voice": DEFAULT_TTS_VOICE,
    }


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    material = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    temporary.write_text(material, encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def _read_settings() -> dict[str, Any]:
    with _SETTINGS_LOCK:
        settings = _defaults()
        try:
            raw = json.loads(MEDIA_SETTINGS_PATH.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return settings
        if not isinstance(raw, dict):
            return settings
        for key in (*INTERFACE_KINDS, "tts_voice"):
            value = raw.get(key)
            if isinstance(value, str) and value and "\x00" not in value and len(value) <= 512:
                settings[key] = (
                    DEFAULT_CAMERA if key == "camera" and value == "adb:tft" else value
                )
        if settings["tts_voice"] not in TTS_VOICES:
            settings["tts_voice"] = DEFAULT_TTS_VOICE
        return settings


def _write_settings(settings: dict[str, Any]) -> None:
    with _SETTINGS_LOCK:
        _atomic_json(MEDIA_SETTINGS_PATH, settings)


def settings() -> dict[str, Any]:
    current = _read_settings()
    return {
        key: current[key]
        for key in (*INTERFACE_KINDS, "tts_voice")
    }


def _run_json(command: tuple[str, ...], *, timeout: float = 3.0) -> Any:
    try:
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode or len(completed.stdout) > MAX_PACTL_BYTES:
        return None
    try:
        return json.loads(completed.stdout)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def _audio_options(kind: str) -> list[dict[str, Any]]:
    pactl_kind = "sources" if kind == "microphone" else "sinks"
    rows = _run_json(("/usr/bin/pactl", "-f", "json", "list", pactl_kind))
    options: list[dict[str, Any]] = []
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name", ""))
            description = str(row.get("description", "")).strip()
            properties = row.get("properties")
            media_class = properties.get("media.class") if isinstance(properties, dict) else None
            if not name or "\x00" in name or len(name) > 512:
                continue
            if name.startswith("obsidience_realtime_aec_"):
                continue
            if kind == "microphone" and (name.endswith(".monitor") or media_class != "Audio/Source"):
                continue
            if kind == "speaker" and media_class != "Audio/Sink":
                continue
            options.append({
                "id": name,
                "label": description or name,
                "available": str(row.get("state", "")).upper() != "UNAVAILABLE",
                "detail": "PipeWire input" if kind == "microphone" else "PipeWire output",
            })
    return sorted(options, key=lambda item: (str(item["label"]).casefold(), str(item["id"])))


def resolve_audio_target(kind: str, selection: str) -> str:
    """Resolve one stable saved PipeWire name to its current object serial.

    ``pw-record`` accepts a node name syntactically but, on the workstation's
    current PipeWire stack, does not link the OBSBOT capture stream by name.
    Its numeric ``object.serial`` links immediately and remains unambiguous.
    Persist the stable name in Hardware and resolve only at Realtime startup so
    device reconnects remain safe.
    """

    if kind not in {"microphone", "speaker"}:
        raise ValueError("audio target must be microphone or speaker")
    if not isinstance(selection, str) or not selection or "\x00" in selection:
        raise ValueError("audio selection must be a nonempty PipeWire node name")
    expected_class = "Audio/Source" if kind == "microphone" else "Audio/Sink"
    document = _run_json(("/usr/bin/pw-dump",))
    matches: list[str] = []
    if isinstance(document, list):
        for row in document:
            if not isinstance(row, dict) or row.get("type") != "PipeWire:Interface:Node":
                continue
            info = row.get("info")
            props = info.get("props") if isinstance(info, dict) else None
            if not isinstance(props, dict):
                continue
            object_serial = props.get("object.serial")
            serial_text = (
                str(object_serial)
                if isinstance(object_serial, int) and not isinstance(object_serial, bool)
                else object_serial
            )
            if (
                props.get("node.name") == selection
                and props.get("media.class") == expected_class
                and isinstance(serial_text, str)
                and serial_text.isdecimal()
                and int(serial_text) > 0
            ):
                matches.append(serial_text)
    if len(matches) != 1:
        raise RuntimeError(
            f"selected {kind} does not resolve to one live PipeWire node: {selection}"
        )
    return str(matches[0])


def _set_microphone_unmuted(selection: str) -> None:
    completed = subprocess.run(
        ("/usr/bin/pactl", "set-source-mute", selection, "0"),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
        timeout=2,
    )
    if completed.returncode:
        raise RuntimeError("the selected microphone could not be unmuted")


def _obsbot_control(*args: str) -> str:
    if not OBSBOT_CONTROL.is_file():
        raise RuntimeError("the OBSBOT hardware control is unavailable")
    completed = subprocess.run(
        (str(OBSBOT_CONTROL), *args),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
        text=True,
        timeout=8,
    )
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()[-512:]
        raise RuntimeError(
            "the OBSBOT camera state command failed"
            + (f": {detail}" if detail else "")
        )
    return completed.stdout.strip()


def obsbot_camera_state() -> dict[str, bool]:
    """Return the cached physical camera state, reading the SDK once at startup."""

    global _OBSBOT_CAMERA_ACTIVE
    with _CAMERA_LOCK:
        if _OBSBOT_CAMERA_ACTIVE is None:
            status = _obsbot_control("status")
            match = re.search(r"(?:^|\s)dev_status=(\d+)(?:\s|$)", status)
            if match is None:
                raise RuntimeError("the OBSBOT camera state could not be read")
            _OBSBOT_CAMERA_ACTIVE = match.group(1) == "1"
        return {"active": _OBSBOT_CAMERA_ACTIVE}


def set_obsbot_camera_active(active: object) -> dict[str, bool]:
    """Set the physical camera power through the existing official SDK control."""

    global _OBSBOT_CAMERA_ACTIVE
    if type(active) is not bool:
        raise ValueError("camera active must be a boolean")
    with _CAMERA_LOCK:
        _obsbot_control("camera", "on" if active else "off")
        _OBSBOT_CAMERA_ACTIVE = active
        return {"active": active}


def set_realtime_camera_active(selection: str, enabled: bool) -> None:
    """Bind the OBSBOT camera, and therefore its microphone, to Realtime."""

    resolve_audio_target("microphone", selection)
    if selection == DEFAULT_MICROPHONE:
        set_obsbot_camera_active(enabled)
        if enabled:
            _obsbot_control("microphone", "on")
    if enabled:
        _set_microphone_unmuted(selection)


def _realtime_aec_command(microphone: str, speaker: str) -> str:
    """Route Pocket through PipeWire's native four-stream WebRTC AEC."""

    return (
        "load-module libpipewire-module-echo-cancel { "
        "monitor.mode = false "
        "audio.rate = 48000 "
        "node.latency = 1440/48000 "
        "audio.channels = 1 "
        "audio.position = [ MONO ] "
        "library.name = aec/libspa-aec-webrtc "
        "capture.props = { "
        f"node.name = {json.dumps(REALTIME_AEC_CAPTURE)} "
        f"target.object = {json.dumps(microphone)} "
        "node.dont-move = true "
        "node.dont-fallback = true "
        "node.dont-reconnect = true "
        "} "
        "source.props = { "
        f"node.name = {json.dumps(REALTIME_AEC_SOURCE)} "
        'node.description = "Obsidience Realtime AEC Microphone" '
        "media.class = Audio/Source "
        "} "
        "sink.props = { "
        f"node.name = {json.dumps(REALTIME_AEC_SINK)} "
        'node.description = "Obsidience Realtime AEC Speaker" '
        "media.class = Audio/Sink "
        "} "
        "playback.props = { "
        f"node.name = {json.dumps(REALTIME_AEC_PLAYBACK)} "
        f"target.object = {json.dumps(speaker)} "
        "node.dont-move = true "
        "node.dont-fallback = true "
        "node.dont-reconnect = true "
        "} "
        "}"
    )


def _terminate_aec_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        if process.stdin is not None:
            process.stdin.write("quit\n")
            process.stdin.flush()
            process.stdin.close()
        process.wait(timeout=3)
        return
    except (BrokenPipeError, OSError, ValueError, subprocess.TimeoutExpired):
        pass
    process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)


def stop_realtime_aec() -> None:
    """Stop the exact native echo-cancel module owned by Realtime."""

    global _AEC_PROCESS
    with _AEC_LOCK:
        process = _AEC_PROCESS
        if process is None:
            return
        try:
            _terminate_aec_process(process)
        finally:
            if _AEC_PROCESS is process:
                _AEC_PROCESS = None


def start_realtime_aec(microphone: str, speaker: str) -> tuple[str, str]:
    """Expose the clean microphone and the exact Pocket playback sink."""

    global _AEC_PROCESS
    microphone_target = resolve_audio_target("microphone", microphone)
    speaker_target = resolve_audio_target("speaker", speaker)
    stop_realtime_aec()
    with _AEC_LOCK:
        try:
            process = subprocess.Popen(
                ("/usr/bin/pw-cli",),
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            _AEC_PROCESS = process
            assert process.stdin is not None
            process.stdin.write(
                _realtime_aec_command(microphone_target, speaker_target) + "\n"
            )
            process.stdin.flush()
        except (OSError, BrokenPipeError) as exc:
            stop_realtime_aec()
            raise RuntimeError(f"WebRTC echo cancellation could not start: {exc}") from exc

    deadline = time.monotonic() + 5
    last_error: RuntimeError | None = None
    try:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("the native PipeWire AEC process exited during startup")
            try:
                resolve_audio_target("microphone", REALTIME_AEC_SOURCE)
                resolve_audio_target("speaker", REALTIME_AEC_SINK)
                return REALTIME_AEC_SOURCE, REALTIME_AEC_SINK
            except RuntimeError as exc:
                last_error = exc
                time.sleep(0.05)
        raise RuntimeError(
            "the native PipeWire AEC source did not become ready"
            + (f": {last_error}" if last_error else "")
        )
    except Exception:
        stop_realtime_aec()
        raise


def prepare_microphone(selection: str) -> str:
    """Enable and attest one selected microphone, returning its live serial."""

    set_realtime_camera_active(selection, True)
    target = resolve_audio_target("microphone", selection)
    try:
        completed = subprocess.run(
            (
                "/usr/bin/pw-record",
                "--raw",
                "--format", "s16",
                "--rate", "16000",
                "--channels", "1",
                "--latency", "80ms",
                "--sample-count", str(MICROPHONE_PROBE_SAMPLES),
                "--target", target,
                "-",
            ),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"selected microphone did not produce audio packets: {exc}") from exc
    expected_bytes = MICROPHONE_PROBE_SAMPLES * 2
    # pw-cat currently exits 1 after satisfying --sample-count even though it
    # delivered the complete bounded packet.  The exact byte count is the
    # useful attestation; a stalled OBSBOT clock returns no packet at all.
    if len(completed.stdout) != expected_bytes:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()[-512:]
        raise RuntimeError(
            "selected microphone did not produce the expected audio packets"
            + (f": {detail}" if detail else "")
        )
    if not any(completed.stdout):
        raise RuntimeError("selected microphone produced only digital silence")
    return target


def _camera_options() -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = [{
        "id": "none", "label": "No preferred camera", "available": True,
        "detail": "Camera viewing and Camera Tools require an explicit device.",
    }]
    sys_root = Path("/sys/class/video4linux")
    for entry in sorted(sys_root.glob("video*"), key=lambda path: int(re.sub(r"\D", "", path.name) or 0)):
        device = Path("/dev") / entry.name
        try:
            sys_device = entry.resolve(strict=True)
            canonical = device.resolve(strict=True)
            label = (entry / "name").read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError):
            continue
        if (
            canonical != device
            or not re.fullmatch(r"/dev/video\d+", str(device))
            or "/devices/virtual/" in str(sys_device)
        ):
            continue
        try:
            probe = subprocess.run(
                ("/usr/bin/v4l2-ctl", "-d", str(device), "--get-fmt-video"),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                check=False,
                timeout=2,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if probe.returncode:
            continue
        options.append({
            "id": f"v4l2:{device}",
            "label": label or entry.name,
            "available": True,
            "detail": str(device),
        })
    return options


def _with_saved(options: list[dict[str, Any]], selected: str) -> list[dict[str, Any]]:
    if selected not in {str(option["id"]) for option in options}:
        options.append({
            "id": selected,
            "label": f"Unavailable · {selected}",
            "available": False,
            "detail": "Saved device is not currently present",
        })
    return options


def interface_catalog() -> list[dict[str, Any]]:
    current = _read_settings()
    definitions = (
        ("microphone", "Microphone input", "input", _audio_options("microphone"),
         "Realtime speech input. The selected PipeWire source is opened on the next session."),
        ("speaker", "Speaker output", "output", _audio_options("speaker"),
         "Realtime speech output. Selection does not change the system-wide default."),
        ("camera", "Preferred camera", "camera", _camera_options(),
         "Used by the local Camera pane and Camera Tools. Agent video feeds are selected separately."),
    )
    return [{
        "id": kind,
        "label": label,
        "kind": slot_kind,
        "selected": current[kind],
        "options": _with_saved(options, current[kind]),
        "note": note,
    } for kind, label, slot_kind, options, note in definitions]


def set_interface(kind: object, selection: object) -> dict[str, Any]:
    selected_kind = str(kind or "").strip().lower()
    selected_value = str(selection or "").strip()
    if selected_kind not in INTERFACE_KINDS:
        raise ValueError("interface must be microphone, speaker, or camera")
    slot = next(item for item in interface_catalog() if item["id"] == selected_kind)
    option = next((item for item in slot["options"] if item["id"] == selected_value), None)
    if option is None or not option["available"]:
        raise ValueError(f"{selected_kind} selection is not currently available")
    current = _read_settings()
    current[selected_kind] = selected_value
    _write_settings(current)
    return settings()


def speech_runtime() -> dict[str, Any]:
    current = _read_settings()
    return {
        "transport": "Pipecat LocalAudioTransport 0.0.98",
        "turn_taking": "NVIDIA NeMo Voice Agent",
        "asr": "Nemotron Speech Streaming EN 0.6B",
        "asr_device": "RTX 4080 SUPER",
        "asr_chunk_ms": 160,
        "tts": "Pocket TTS 3.0.2",
        "tts_device": "CPU",
        "voice": current["tts_voice"],
        "voices": [
            {"id": "starfleet", "label": "Star Trek Computer"},
            {"id": "hal", "label": "HAL"},
            {"id": "ultron", "label": "Ultron"},
        ],
    }


def set_voice(voice: object) -> dict[str, Any]:
    selected = str(voice or "").strip().lower()
    if selected not in TTS_VOICES:
        raise ValueError("voice must be starfleet, hal, or ultron")
    current = _read_settings()
    current["tts_voice"] = selected
    _write_settings(current)
    return speech_runtime()


__all__ = [
    "interface_catalog",
    "set_interface",
    "set_voice",
    "speech_runtime",
    "settings",
]

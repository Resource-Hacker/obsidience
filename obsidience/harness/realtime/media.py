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
UMA8_SOURCE = "alsa_input.usb-miniDSP_miniDSP_VocalFusion_Spk__UAC2.0_-00.analog-stereo"
UMA8_REFERENCE_SINK = "alsa_output.usb-miniDSP_miniDSP_VocalFusion_Spk__UAC2.0_-00.analog-stereo"
DEFAULT_CAMERA = "v4l2:/dev/video0"
DEFAULT_TTS_VOICE = "starfleet"
REALTIME_AEC_SOURCE = "obsidience_realtime_aec_source"
REALTIME_AEC_CAPTURE = "obsidience_realtime_aec_capture"
REALTIME_AEC_REFERENCE = "obsidience_realtime_aec_reference"
INTERFACE_KINDS = ("microphone", "speaker", "camera")
TTS_VOICES = ("starfleet", "hal", "ultron")
MAX_PACTL_BYTES = 2 * 1024 * 1024
OBSBOT_CONTROL = Path("/home/wissenschafter/src/obsbot/obsbot_ctl")
MICROPHONE_PROBE_SAMPLES = 16_000

_SETTINGS_LOCK = threading.RLock()
_AEC_LOCK = threading.RLock()
_CAMERA_LOCK = threading.RLock()
_AEC_PROCESS: subprocess.Popen[str] | None = None
_AEC_BACKEND = "none"
_AEC_IDENTITIES: tuple[tuple[int, int], ...] = ()
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
    device reconnects remain safe.  Query only the selected interface class;
    the complete PipeWire graph can contain unrelated display-audio nodes.
    """

    if kind not in {"microphone", "speaker"}:
        raise ValueError("audio target must be microphone or speaker")
    if not isinstance(selection, str) or not selection or "\x00" in selection:
        raise ValueError("audio selection must be a nonempty PipeWire node name")
    expected_class = "Audio/Source" if kind == "microphone" else "Audio/Sink"
    pactl_kind = "sources" if kind == "microphone" else "sinks"
    document = _run_json(("/usr/bin/pactl", "-f", "json", "list", pactl_kind))
    matches: list[str] = []
    if isinstance(document, list):
        for row in document:
            if not isinstance(row, dict):
                continue
            props = row.get("properties")
            if not isinstance(props, dict):
                continue
            object_serial = props.get("object.serial")
            serial_text = (
                str(object_serial)
                if isinstance(object_serial, int) and not isinstance(object_serial, bool)
                else object_serial
            )
            if (
                row.get("name") == selection
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
        from . import tracking
        if not active:
            tracking.stop()
        _obsbot_control("camera", "on" if active else "off")
        _OBSBOT_CAMERA_ACTIVE = active
        if active:
            tracking.start()
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
    """Cancel the selected speaker mix from the sole microphone feed."""

    return (
        "load-module libpipewire-module-echo-cancel { "
        "monitor.mode = true "
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
        f"node.name = {json.dumps(REALTIME_AEC_REFERENCE)} "
        'node.description = "Obsidience Realtime Speaker Reference" '
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
    """Release the native echo-cancel module or reference links owned by Realtime."""

    global _AEC_PROCESS, _AEC_BACKEND, _AEC_IDENTITIES
    with _AEC_LOCK:
        _AEC_BACKEND = "none"
        _AEC_IDENTITIES = ()
        process = _AEC_PROCESS
        if process is None:
            return
        try:
            _terminate_aec_process(process)
        finally:
            if _AEC_PROCESS is process:
                _AEC_PROCESS = None


def realtime_aec_backend() -> str:
    """Report only an established backend with its owning process still alive."""

    # Snapshot callers run on the event loop; never wait for startup's graph
    # attestation while the worker thread holds the AEC lifecycle lock.
    process = _AEC_PROCESS
    if process is None or process.poll() is not None:
        return "none"
    return _AEC_BACKEND


def _uma8_reference_graph(speaker: str, *, require_capture: bool = True) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Attest the paired DSP device and exact stereo reference ports."""

    graph = _run_json(("/usr/bin/pw-dump",))
    if not isinstance(graph, list):
        raise RuntimeError("the UMA-8 reference graph is unavailable")
    endpoints = []
    for name, media_class in (
        (UMA8_SOURCE, "Audio/Source"),
        (UMA8_REFERENCE_SINK, "Audio/Sink"),
        (speaker, "Audio/Sink"),
    ):
        matches = [row for row in graph if row.get("type") == "PipeWire:Interface:Node"
                   and row.get("info", {}).get("props", {}).get("node.name") == name]
        if len(matches) != 1 or matches[0]["info"]["props"].get("media.class") != media_class:
            raise RuntimeError("the UMA-8 reference endpoints are not unique")
        endpoints.append(matches[0])
    mic, usb_sink, speaker_node = endpoints
    if (mic["info"]["props"].get("node.group") != "obsidience.uma8.duplex"
            or usb_sink["info"]["props"].get("node.group") != "obsidience.uma8.duplex"):
        raise RuntimeError("the UMA-8 requires its shared duplex clock configuration")
    if speaker_node["id"] == usb_sink["id"]:
        raise RuntimeError("the UMA-8 reference requires a separate physical speaker")
    device_id = mic["info"]["props"].get("device.id")
    devices = [row for row in graph if row.get("type") == "PipeWire:Interface:Device"
               and row.get("id") == device_id]
    if (len(devices) != 1 or usb_sink["info"]["props"].get("device.id") != device_id
            or devices[0]["info"]["props"].get("device.vendor.id") != "0x2752"
            or devices[0]["info"]["props"].get("device.product.id") != "0x001c"):
        raise RuntimeError("the UMA-8 capture and reference are not the paired USB device")
    for node in (mic, usb_sink):
        props = node["info"]["props"]
        formats = node["info"].get("params", {}).get("Format", [])
        if (props.get("device.profile.name") != "analog-stereo"
                or props.get("audio.channels") != 2
                or any(fmt.get("channels") != 2 or fmt.get("rate") != 48000 for fmt in formats)):
            raise RuntimeError("the UMA-8 requires its 48 kHz stereo DSP profile")
    if require_capture and not mic["info"].get("params", {}).get("Format"):
        raise RuntimeError("the prepared UMA-8 DSP capture format is unavailable")
    ports = []
    for node, direction, prefix in (
        (speaker_node, "output", "monitor"),
        (usb_sink, "input", "playback"),
    ):
        for channel in ("FL", "FR"):
            matches = [row for row in graph if row.get("type") == "PipeWire:Interface:Port"
                       and row.get("info", {}).get("direction") == direction
                       and row["info"].get("props", {}).get("node.id") == node["id"]
                       and row["info"]["props"].get("port.name") == f"{prefix}_{channel}"
                       and row["info"]["props"].get("audio.channel") == channel
                       and (prefix != "monitor" or row["info"]["props"].get("port.monitor") is True)]
            if len(matches) != 1:
                raise RuntimeError("the UMA-8 stereo reference ports are not unique")
            ports.append(matches[0])
    endpoints = [*endpoints, devices[0], *ports]
    for row in endpoints:
        serial = row["info"]["props"].get("object.serial")
        if type(row.get("id")) is not int or type(serial) is not int or serial <= 0:
            raise RuntimeError("the UMA-8 reference identity is unavailable")
    return graph, endpoints


def uma8_reference_state(speaker: str) -> tuple[bool, tuple | None]:
    """Check admitted resources on an audio-device event, never by idle polling.

    Returned endpoints may be idle: normal acquisition prepares capture before
    attesting the active DSP format and links. A new object serial is a new
    recovery opportunity even when PipeWire reuses the numeric object ID.
    """
    try:
        graph, endpoints = _uma8_reference_graph(speaker, require_capture=False)
    except RuntimeError:
        return False, None
    generation = tuple((row["id"], row["info"]["props"]["object.serial"]) for row in endpoints)
    identities = {(row["id"], row.get("info", {}).get("props", {}).get("object.serial"))
                  for row in graph}
    intact = (realtime_aec_backend() == "uma8" and bool(_AEC_IDENTITIES)
              and all(identity in identities for identity in _AEC_IDENTITIES))
    return intact, generation


def _start_uma8_reference(speaker: str) -> tuple[str, str]:
    """Use the hardware DSP with two directly owned speaker-monitor links."""

    global _AEC_PROCESS, _AEC_BACKEND, _AEC_IDENTITIES
    _, endpoints = _uma8_reference_graph(speaker)
    identities = [(row["id"], row["info"]["props"]["object.serial"]) for row in endpoints]
    mic, usb_sink, speaker_node, _, left_out, right_out, left_in, right_in = endpoints
    # Command mode waits for the registry roundtrip; an immediate interactive
    # set-param can reject a valid node before pw-cli has learned its globals.
    subprocess.run(
        ("/usr/bin/pw-cli", "set-param", str(usb_sink["id"]), "Props",
         "{ mute = false volume = 1.0 channelVolumes = [ 1.0 1.0 ] }"),
        stdin=subprocess.DEVNULL, capture_output=True, check=True, timeout=2,
    )
    process = subprocess.Popen(
        ("/usr/bin/pw-cli",), stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True,
    )
    _AEC_PROCESS = process
    assert process.stdin is not None
    # Global port IDs are accepted by PipeWire's link factory, which verifies
    # membership in the supplied node. Non-lingering links die with this client.
    for output, input_port in ((left_out, left_in), (right_out, right_in)):
        process.stdin.write(
            f'create-link {speaker_node["id"]} {output["id"]} '
            f'{usb_sink["id"]} {input_port["id"]} {{ object.linger = false }}\n'
        )
    process.stdin.flush()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("the UMA-8 reference owner exited during startup")
        graph, current = _uma8_reference_graph(speaker)
        if [(row["id"], row["info"]["props"]["object.serial"]) for row in current] != identities:
            raise RuntimeError("the UMA-8 reference endpoint identity changed")
        clients = {row["id"] for row in graph if row.get("type") == "PipeWire:Interface:Client"
                   and str(row.get("info", {}).get("props", {}).get("application.process.id")) == str(process.pid)}
        links = [row for row in graph if row.get("type") == "PipeWire:Interface:Link"
                 and row.get("info", {}).get("props", {}).get("client.id") in clients]
        pairs = {(left_out["id"], left_in["id"]), (right_out["id"], right_in["id"])}
        active = {(row["info"].get("output-port-id"), row["info"].get("input-port-id"))
                  for row in links if row["info"].get("state") == "active"
                  and row["info"].get("output-node-id") == speaker_node["id"]
                  and row["info"].get("input-node-id") == usb_sink["id"]}
        props = current[1]["info"].get("params", {}).get("Props", [])
        unity = any(row.get("mute") is False and row.get("channelVolumes") == [1.0, 1.0]
                    for row in props)
        shared_clock = all(row["info"]["props"].get("node.driver-id", row["id"]) == mic["id"]
                           for row in current[:3])
        if (len(links) == 2 and active == pairs and unity and shared_clock
                and current[1]["info"].get("params", {}).get("Format")):
            _AEC_IDENTITIES = tuple(identities + [
                (row["id"], row["info"]["props"]["object.serial"]) for row in links])
            _AEC_BACKEND = "uma8"
            return UMA8_SOURCE, speaker
        time.sleep(0.05)
    raise RuntimeError("the UMA-8 stereo hardware reference did not become ready")


def start_realtime_aec(microphone: str, speaker: str) -> tuple[str, str]:
    """Expose clean capture using the selected physical speaker as reference."""

    global _AEC_PROCESS, _AEC_BACKEND
    microphone_target = resolve_audio_target("microphone", microphone)
    speaker_target = resolve_audio_target("speaker", speaker)
    stop_realtime_aec()
    with _AEC_LOCK:
        try:
            if microphone == UMA8_SOURCE:
                return _start_uma8_reference(speaker)
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
        except Exception as exc:
            stop_realtime_aec()
            backend = "UMA-8 hardware" if microphone == UMA8_SOURCE else "WebRTC"
            raise RuntimeError(f"{backend} echo cancellation could not start: {exc}") from exc

    deadline = time.monotonic() + 5
    last_error: RuntimeError | None = None
    try:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("the native PipeWire AEC process exited during startup")
            try:
                resolve_audio_target("microphone", REALTIME_AEC_SOURCE)
                resolve_audio_target("speaker", speaker)
                _AEC_BACKEND = "webrtc"
                return REALTIME_AEC_SOURCE, speaker
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
    # Clocked silence is valid audio, including a quiet or noise-gated room.
    # Readiness attests delivery from the selected input, not acoustic activity.
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

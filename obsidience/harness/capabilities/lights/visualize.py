"""Opt-in, CPU-only light animation with native delayed PipeWire forwarding.

One session retains the existing lights lock, exact audio identities and rollback.
PCM is bounded RAM only. Future features are a bounded lookahead history; each
fixture admits at most one UDP request, never a queued backlog or retry.
"""
from __future__ import annotations

from collections import deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
import math
import os
import re
import selectors
import signal
import subprocess
import threading
import time
import uuid

import numpy as np

from ...config import CONFIG
from . import set as power

_CONTROL = threading.RLock()
_STATE = threading.Lock()
_SESSION = None
_LAST = {"state": "inactive", "calibrated": False}
RATE = 48000
BLOCK = RATE // 10
BLOCK_BYTES = BLOCK * 4  # Stereo s16, 100 ms.
PROFILE_PATH = CONFIG.runtime_dir / "lights-visualizer-calibration.json"


def _command(args, *, timeout=2):
    result = subprocess.run(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, timeout=timeout, check=True)
    if len(result.stdout) > 8 * 1024 * 1024:
        raise RuntimeError("audio_graph_exceeds_bound")
    return result.stdout


def _graph():
    rows = json.loads(_command(["pw-dump"]))
    nodes = {row["id"]: row for row in rows if row.get("type") == "PipeWire:Interface:Node"}
    metadata = next((row.get("metadata", []) for row in rows
                     if row.get("type") == "PipeWire:Interface:Metadata"
                     and row.get("props", {}).get("metadata.name") == "default"), [])
    return rows, nodes, metadata


def _props(node):
    return node.get("info", {}).get("props", {})


def _identity(node):
    props = _props(node)
    return node["id"], str(props.get("object.serial")), props.get("node.name")


def _process_identity(node):
    pid = str(_props(node).get("application.process.id", ""))
    if not pid.isdigit():
        raise RuntimeError("audio_stream_process_unavailable")
    with open(f"/proc/{pid}/stat", encoding="utf-8") as source:
        start = source.read().rsplit(")", 1)[1].split()[19]
    return pid, start


def _linked_sinks(rows, nodes, stream_id):
    return {row["info"]["input-node-id"] for row in rows
            if row.get("type") == "PipeWire:Interface:Link"
            and row.get("info", {}).get("output-node-id") == stream_id
            and _props(nodes.get(row.get("info", {}).get("input-node-id"), {})).get("media.class") == "Audio/Sink"}


def sources():
    _rows, nodes, _metadata = _graph()
    return [{"stream_id": identifier, "serial": str(_props(node).get("object.serial")),
             "application": _props(node).get("application.name", ""),
             "name": _props(node).get("node.name", "")}
            for identifier, node in nodes.items()
            if _props(node).get("media.class") == "Stream/Output/Audio"
            and node.get("info", {}).get("state") == "running"][:64]


def _select(stream_id):
    rows, nodes, metadata = _graph()
    candidates = [node for identifier, node in nodes.items()
                  if _props(node).get("media.class") == "Stream/Output/Audio"
                  and node.get("info", {}).get("state") == "running"
                  and (identifier == stream_id if stream_id is not None else
                       _props(node).get("application.name") == "WEBRTC VoiceEngine"
                       and _props(node).get("application.process.binary", "").lower() == "discord")]
    if len(candidates) != 1:
        raise ValueError("Select one unique currently playing audio stream from visualizer sources")
    stream = candidates[0]
    sinks = [nodes[identifier] for identifier in _linked_sinks(rows, nodes, stream["id"])
             if _props(nodes[identifier]).get("device.api") == "alsa"]
    if len(sinks) != 1:
        raise ValueError("The selected stream must have one observed physical ALSA output")
    sink = sinks[0]
    old_target = next((dict(row) for row in metadata if row.get("subject") == stream["id"]
                       and row.get("key") == "target.object"), None)
    return stream, sink, _process_identity(stream), old_target


def _metadata(identifier, entry):
    args = ["pw-metadata", "-n", "default"]
    if entry is None:
        _command([*args, "-d", str(identifier), "target.object"])
    else:
        value = entry["value"]
        value = json.dumps(value, separators=(",", ":")) if isinstance(value, (dict, list)) else str(value)
        _command([*args, str(identifier), "target.object", value, entry["type"]])


def _calibration(value, delay, stream, sink, inventory):
    if value is None:
        return None
    if (not isinstance(value, dict) or set(value) != {"version", "profile_id", "measured_at", "sink_name",
            "stream_serial", "output_serial", "camera_binding", "requested_audio_delay_ms", "native_audio_delay_ms",
            "capture_latency_ms", "output_latency_ms", "fixtures"}
            or not isinstance(value["profile_id"], str) or not 1 <= len(value["profile_id"]) <= 96
            or value["version"] != 1 or type(value["version"]) is not int
            or value["sink_name"] != _props(sink)["node.name"]
            or str(value["stream_serial"]) != _identity(stream)[1]
            or str(value["output_serial"]) != _identity(sink)[1]
            or not isinstance(value["camera_binding"], dict) or not value["camera_binding"]
            or len(json.dumps(value["camera_binding"])) > 4096
            or value["requested_audio_delay_ms"] != delay
            or type(value["measured_at"]) not in (int, float)
            or not math.isfinite(value["measured_at"]) or value["measured_at"] <= 0
            or value["measured_at"] > time.time() + 60
            or not isinstance(value["fixtures"], dict) or set(value["fixtures"]) != set(power.FIXTURES)):
        raise ValueError("Calibration profile must bind the observed output and all six fixtures")
    for key in ("native_audio_delay_ms", "capture_latency_ms", "output_latency_ms"):
        if type(value[key]) not in (int, float) or not math.isfinite(value[key]) or not 0 <= value[key] <= (4000 if key == "native_audio_delay_ms" else 2000):
            raise ValueError("Invalid audio calibration latency")
    for name, row in value["fixtures"].items():
        if not isinstance(row, dict) or set(row) != {"mac", "latency_ms", "uncertainty_ms"} or row["mac"] != inventory[name]["mac"]:
            raise ValueError("Calibration fixture identity changed")
        for key in ("latency_ms", "uncertainty_ms"):
            if type(row[key]) not in (int, float) or not math.isfinite(row[key]) or not 0 <= row[key] <= 2000:
                raise ValueError("Invalid fixture timing")
        if value["native_audio_delay_ms"] < row["latency_ms"] + row["uncertainty_ms"] + value["capture_latency_ms"] + 150:
            raise ValueError("Audio delay does not cover the supplied light/analysis timing budget")
    return json.loads(json.dumps(value))


class _Session:
    def __init__(self, stream, sink, process, old_target, delay, profile, inventory, cancel):
        self.stream, self.sink = stream, sink
        self.stream_identity, self.sink_identity = _identity(stream), _identity(sink)
        self.process_identity, self.old_target = process, old_target
        self.delay, self.profile, self.inventory = delay, profile, inventory
        self.effective_delay = profile["native_audio_delay_ms"] if profile else delay
        self.cancel = cancel
        self.stop_event = threading.Event()
        self.ready = threading.Event()
        self.finished = threading.Event()
        self.children = []
        self.before = {}
        self.mutated = set()
        self.route_owned = False
        self.virtual_identity = None
        self.name = "obsidience_lights_" + uuid.uuid4().hex[:12]
        self.state = "starting"
        self.error = None
        self.cleanup_errors = []
        self.frames = self.dropped = self.updates = 0
        self.thread = threading.Thread(target=self._run, name="lights-visualizer", daemon=True)

    def snapshot(self):
        return {"state": self.state, "calibrated": False,
                "calibration_state": "owner_profile_supplied" if self.profile else "uncalibrated",
                "profile_id": self.profile["profile_id"] if self.profile else None,
                "timing_verified_by_runtime": False, "audio_delay_ms": self.delay,
                "measured_monitor_delay_ms": self.profile["native_audio_delay_ms"] if self.profile else None,
                "physical_output_delay_verified": False, "analysis_interval_ms": 100, "source": {"stream_id": self.stream_identity[0],
                    "serial": self.stream_identity[1], "application": _props(self.stream).get("application.name")},
                "output": self.sink_identity[2], "audio_scope": "selected_stream_mix",
                "frames": self.frames, "dropped": self.dropped, "updates": self.updates,
                "error": self.error, "cleanup_errors": list(self.cleanup_errors)}

    def _check_stop(self):
        if self.stop_event.is_set() or (self.cancel is not None and self.cancel.is_set()):
            raise InterruptedError("visualizer_stopped")

    def _spawn(self, args, *, capture=False, stdin=False):
        child = subprocess.Popen(args, stdin=subprocess.PIPE if stdin else subprocess.DEVNULL,
                                 stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, start_new_session=True)
        self.children.append(child)
        return child

    def _current_nodes(self, *, routed=False):
        rows, nodes, metadata = _graph()
        stream, sink = nodes.get(self.stream_identity[0]), nodes.get(self.sink_identity[0])
        if (not stream or _identity(stream) != self.stream_identity
                or _process_identity(stream) != self.process_identity
                or not sink or _identity(sink) != self.sink_identity):
            raise RuntimeError("audio_stream_or_output_replaced")
        if routed:
            target = next((row for row in metadata if row.get("subject") == stream["id"]
                           and row.get("key") == "target.object"), None)
            if target is None or str(target.get("value")) != self.virtual_identity[1]:
                raise RuntimeError("audio_route_changed")
        return rows, nodes, metadata

    def _wait(self, check, *, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self._check_stop()
            if any(child.poll() is not None for child in self.children):
                raise RuntimeError("audio_child_failed")
            value = check()
            if value:
                return value
            self.stop_event.wait(.05)
        raise TimeoutError("audio_route_not_ready")

    def _audio_start(self):
        self._spawn(["pw-cli", "-m", "create-node", "adapter",
            '{ factory.name=support.null-audio-sink node.name=%s media.class=Audio/Sink '
            'audio.position=[FL FR] object.linger=false priority.session=0 }' % self.name], stdin=True)
        def virtual():
            _rows, nodes, _meta = self._current_nodes()
            return next((node for node in nodes.values() if _props(node).get("node.name") == self.name), None)
        self.virtual_identity = _identity(self._wait(virtual))
        self._spawn(["pw-loopback", "-n", self.name + "_delay", "-C", self.name,
            "--capture-props", "stream.capture.sink=true node.dont-fallback=true node.name=" + self.name + "_tap",
            "-P", self.sink_identity[1], "--playback-props", "node.dont-fallback=true node.name=" + self.name + "_forward",
            "--delay", str(self.delay / 1000), "--latency", "20"])
        capture = self._spawn(["pw-record", "--target", self.name,
            "--properties", "stream.capture.sink=true node.dont-fallback=true",
            "--raw", "--format", "s16", "--rate", str(RATE), "--channels", "2", "--latency", "20ms", "-"], capture=True)
        self._current_nodes()
        # Mark possible dispatch before the exact owner metadata mutation.
        self.route_owned = True
        _metadata(self.stream_identity[0], {"value": self.virtual_identity[1], "type": "Spa:Id"})
        def routed():
            rows, nodes, _meta = self._current_nodes(routed=True)
            forward = next((node for node in nodes.values() if _props(node).get("node.name") == self.name + "_forward"), None)
            return (self.virtual_identity[0] in _linked_sinks(rows, nodes, self.stream_identity[0])
                    and forward is not None and self.sink_identity[0] in _linked_sinks(rows, nodes, forward["id"]))
        self._wait(routed)
        return capture

    def _write(self, name, params):
        self._check_stop()
        self.mutated.add(name)
        result = power._request(self.inventory[name]["ip"], "setPilot", params, self.stop_event, timeout=.085)
        if result.get("success") is not True:
            raise RuntimeError("light_update_not_acknowledged")
        return True

    def _animate(self, capture):
        history = deque(maxlen=math.ceil(self.effective_delay / 100) + 25)
        pending = {}
        last = {}
        failures = {name: 0 for name in power.FIXTURES}
        remainder = bytearray()
        window = np.hanning(BLOCK)
        bins = np.fft.rfftfreq(BLOCK, 1 / RATE)
        bands = [(bins >= low) & (bins < high) for low, high in ((40, 220), (220, 1800), (1800, 8000))]
        next_render = next_audit = time.monotonic()
        os.set_blocking(capture.stdout.fileno(), False)
        with selectors.DefaultSelector() as selector, ThreadPoolExecutor(max_workers=6, thread_name_prefix="light-frame") as pool:
            selector.register(capture.stdout, selectors.EVENT_READ)
            while True:
                self._check_stop()
                for _key, _events in selector.select(.02):
                    chunk = os.read(capture.stdout.fileno(), 65536)
                    if not chunk:
                        raise RuntimeError("audio_capture_ended")
                    received = time.monotonic()
                    remainder.extend(chunk)
                    if len(remainder) > BLOCK_BYTES * 3:
                        self.dropped += len(remainder) // BLOCK_BYTES - 2
                        discard = ((len(remainder) - BLOCK_BYTES * 2) // 4) * 4
                        del remainder[:discard]
                    while len(remainder) >= BLOCK_BYTES:
                        pcm = bytes(remainder[:BLOCK_BYTES]); del remainder[:BLOCK_BYTES]
                        samples = np.frombuffer(pcm, dtype="<i2").reshape(-1, 2).mean(axis=1) / 32768
                        rms = float(np.sqrt(np.mean(samples * samples)))
                        spectrum = np.abs(np.fft.rfft(samples * window))
                        energy = np.array([float(np.sqrt(np.mean(spectrum[mask] ** 2))) for mask in bands])
                        weights = energy / (float(energy.max()) + 1e-9)
                        self.frames += 1
                        history.append((received - len(remainder) / (RATE * 4) - .05, self.frames, rms, weights))
                        if not self.ready.is_set():
                            self.state = "running"
                            self.ready.set()
                now = time.monotonic()
                if now >= next_audit:
                    rows, nodes, _metadata_rows = self._current_nodes(routed=True)
                    forward = next((node for node in nodes.values() if _props(node).get("node.name") == self.name + "_forward"), None)
                    if (self.virtual_identity[0] not in _linked_sinks(rows, nodes, self.stream_identity[0])
                            or forward is None or self.sink_identity[0] not in _linked_sinks(rows, nodes, forward["id"])):
                        raise RuntimeError("audio_link_lost")
                    if any(child.poll() is not None for child in self.children):
                        raise RuntimeError("audio_child_failed")
                    next_audit = now + 1
                if now < next_render:
                    continue
                next_render = now + .1
                for index, name in enumerate(power.FIXTURES):
                    prior = pending.get(name)
                    if prior is not None and not prior.done():
                        self.dropped += 1
                        continue
                    if prior is not None:
                        try:
                            prior.result(); failures[name] = 0; self.updates += 1
                        except InterruptedError:
                            raise
                        except (OSError, ValueError, RuntimeError):
                            failures[name] += 1
                            if failures[name] >= 3:
                                raise RuntimeError("light_update_failed") from None
                        pending.pop(name)
                    profile = self.profile
                    latency = profile["fixtures"][name]["latency_ms"] if profile else 0
                    capture_latency = profile["capture_latency_ms"] if profile else 0
                    output_latency = profile["output_latency_ms"] if profile else 0
                    reference = now - (self.effective_delay + output_latency - latency - capture_latency) / 1000
                    feature = next((item for item in reversed(history) if item[0] <= reference), None)
                    if feature is None or feature[1] == last.get(name):
                        continue
                    if now - feature[0] > self.effective_delay / 1000 + 1:
                        self.dropped += 1
                        continue
                    last[name] = feature[1]
                    _stamp, _seq, rms, weights = feature
                    # A restrained envelope avoids per-sample flicker; each fixture
                    # rotates the same three current musical bands.
                    dim = max(5, min(100, round(math.sqrt(min(1, rms * 8)) * 100)))
                    rgb = np.roll(weights, index % 3)
                    params = {"state": True, "sceneId": 0, "dimming": dim,
                              **dict(zip(("r", "g", "b"), (max(1, round(float(v) * 255)) for v in rgb)))}
                    pending[name] = pool.submit(self._write, name, params)

    def _restore(self):
        # Restore metadata before removing its temporary audio destination.
        if self.route_owned:
            try:
                _rows, nodes, metadata = _graph()
                stream = nodes.get(self.stream_identity[0])
                current = next((row for row in metadata if row.get("subject") == self.stream_identity[0]
                                and row.get("key") == "target.object"), None)
                if stream and _identity(stream) == self.stream_identity and _process_identity(stream) == self.process_identity:
                    if current and str(current.get("value")) == self.virtual_identity[1]:
                        _metadata(self.stream_identity[0], self.old_target)
                        deadline = time.monotonic() + 2
                        while True:
                            restored_rows, restored_nodes, restored_meta = _graph()
                            restored_stream = restored_nodes.get(self.stream_identity[0])
                            if restored_stream is None or _identity(restored_stream) != self.stream_identity:
                                break  # The exact source ended; never write to a replacement.
                            target = next((row for row in restored_meta if row.get("subject") == self.stream_identity[0]
                                           and row.get("key") == "target.object"), None)
                            matches = (target is None and self.old_target is None) or (
                                target is not None and self.old_target is not None
                                and str(target.get("value")) == str(self.old_target.get("value"))
                                and target.get("type") == self.old_target.get("type"))
                            if matches and self.sink_identity[0] in _linked_sinks(restored_rows, restored_nodes, self.stream_identity[0]):
                                break
                            if time.monotonic() >= deadline:
                                raise RuntimeError("audio_restore_not_verified")
                            time.sleep(.05)
                    elif current != self.old_target:
                        self.cleanup_errors.append("audio_target_superseded")
                # A replaced stream must never receive a stale metadata write.
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
                self.cleanup_errors.append("audio_target_restore_failed")
        for child in reversed(self.children):
            if child.poll() is None:
                try:
                    os.killpg(child.pid, signal.SIGTERM)
                    child.wait(timeout=2)
                except (OSError, subprocess.SubprocessError):
                    try:
                        os.killpg(child.pid, signal.SIGKILL)
                        child.wait(timeout=1)
                    except (OSError, subprocess.SubprocessError):
                        self.cleanup_errors.append("audio_child_cleanup_failed")
        def restore_light(name):
            before = self.before[name]
            appearance = power._appearance(before)
            acknowledgement = power._request(self.inventory[name]["ip"], "setPilot",
                {"state": before["state"], **appearance}, None)
            if acknowledgement.get("success") is not True:
                raise RuntimeError("light_restore_not_acknowledged")
            after = power._settled_pilot(name, self.inventory, None, before["state"], appearance)
            if after["state"] != before["state"] or (before["state"] and any(after.get(k) != v for k, v in appearance.items())):
                raise RuntimeError("light_restore_readback_mismatch")
        with ThreadPoolExecutor(max_workers=6, thread_name_prefix="light-restore") as pool:
            jobs = {name: pool.submit(restore_light, name) for name in self.mutated}
            for name, job in jobs.items():
                try:
                    job.result()
                except (OSError, ValueError, RuntimeError):
                    self.cleanup_errors.append("light_restore_failed:" + name)

    def _run(self):
        try:
            with power._LOCK:
                try:
                    with ThreadPoolExecutor(max_workers=6) as pool:
                        values = pool.map(lambda name: power._pilot(name, self.inventory, self.stop_event), power.FIXTURES)
                        self.before = dict(zip(power.FIXTURES, values))
                    for value in self.before.values():
                        power._appearance(value)  # Snapshot must be restorable before any effect.
                    self._check_stop()
                    capture = self._audio_start()
                    self._animate(capture)
                finally:
                    self.state = "restoring"
                    self.stop_event.set()
                    self._restore()
        except InterruptedError:
            pass
        except Exception as error:
            # No raw command/device exception text enters status.
            code = str(error)
            self.error = code if re.fullmatch(r"[a-z_]{3,80}", code) else type(error).__name__
        finally:
            self.state = "failed" if self.error or self.cleanup_errors else "stopped"
            self.ready.set()
            self.finished.set()


def status():
    with _STATE:
        return _SESSION.snapshot() if _SESSION else dict(_LAST)


def stop(*, cancel_calibration=True):
    global _SESSION, _LAST
    from . import calibration
    if cancel_calibration:
        calibration.cancel()
    with _STATE:
        session = _SESSION
        if session:
            session.stop_event.set()
    with _CONTROL:
        if session and session.thread is not threading.current_thread():
            session.thread.join(timeout=12)
            if session.thread.is_alive():
                raise RuntimeError("visualizer_cleanup_incomplete")
        with _STATE:
            if session is not None and _SESSION is session:
                _LAST = session.snapshot()
                _SESSION = None
        return status()


@contextmanager
def power_operation(*, cancel_calibration=True):
    """Power changes preempt and drain visual effects before taking the light lock."""
    if cancel_calibration:
        from . import calibration
        calibration.cancel()
    with _STATE:
        if _SESSION:
            _SESSION.stop_event.set()
    with _CONTROL:
        result = stop(cancel_calibration=False)
        if result.get("cleanup_errors"):
            raise RuntimeError("visualizer_restore_requires_attention")
        yield


def start(payload, cancel=None):
    global _SESSION
    from . import calibration
    calibration.cancel()
    with _CONTROL:
        with _STATE:
            if _SESSION and not _SESSION.finished.is_set():
                raise ValueError("Visualizer is already active; stop it before a new start")
        previous = stop()
        if previous.get("cleanup_errors"):
            raise RuntimeError("visualizer_restore_requires_attention")
        if type(payload.get("audio_delay_ms")) not in (int, float) or not math.isfinite(payload["audio_delay_ms"]) or not 250 <= payload["audio_delay_ms"] <= 3000:
            raise ValueError("Choose an explicit audio delay between 250 and 3000 ms")
        stream_id = payload.get("stream_id")
        if stream_id is not None and (type(stream_id) is not int or stream_id <= 0):
            raise ValueError("Choose an observed positive stream_id")
        inventory = power._inventory()
        stream, sink, process, old_target = _select(stream_id)
        profile_value = payload.get("calibration")
        if profile_value is None and payload.get("uncalibrated") is not True and PROFILE_PATH.exists():
            if PROFILE_PATH.stat().st_size > 32768:
                raise ValueError("Calibration profile exceeds bound")
            profile_value = json.loads(PROFILE_PATH.read_text())
        profile = _calibration(profile_value, payload["audio_delay_ms"], stream, sink, inventory)
        if profile is None and payload.get("uncalibrated") is not True:
            raise ValueError("Supply a timing profile or explicitly choose uncalibrated:true")
        session = _Session(stream, sink, process, old_target, payload["audio_delay_ms"], profile, inventory, cancel)
        with _STATE:
            _SESSION = session
        session.thread.start()
        if not session.ready.wait(timeout=12):
            stop()
            raise RuntimeError("visualizer_start_not_ready")
        if session.state != "running":
            result = stop()
            raise RuntimeError("visualizer_start_failed:" + str(result.get("error")))
        return status()


def control(payload, cancel=None):
    if not isinstance(payload, dict) or set(payload) - {"action", "stream_id", "audio_delay_ms", "uncalibrated", "calibration"}:
        raise ValueError("Invalid visualizer request")
    action = payload.get("action")
    if action in {"status", "stop"}:
        if set(payload) != {"action"}:
            raise ValueError("Status/stop accept action only")
        return status() if action == "status" else stop()
    if action == "start":
        return start(payload, cancel)
    raise ValueError("Choose visualizer action start, stop or status")


def execute(args, context):
    if context.get("_agent_ref") != "Agents/Executive/Executive" or context.get("task") != "Agents/Executive/Executive":
        raise PermissionError("Music light control belongs to the Executive conversation")
    before = status()
    result = control(args, context.get("_capability_cancel_event"))
    failed = result.get("state") == "failed" or bool(result.get("cleanup_errors"))
    applied = (args.get("action") == "start" and result.get("state") == "running") or (
        args.get("action") == "stop" and before.get("state") in {"starting", "running", "restoring"})
    return {"status": "failed" if failed else "completed", "delivery": "visualizer_state_observed",
            "visualizer": result, "effect_applied": None if failed else applied, "must_not_replay": True}

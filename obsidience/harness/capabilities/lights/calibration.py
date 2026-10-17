"""Finite optical flash measurement through the existing camera/light owners.

Frames stay in RAM. Kernel camera timestamps remove host decode/receipt delay,
but remain driver timestamps, not a claim of exact sensor exposure or ear timing.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
import tempfile
import threading
import time
from pathlib import Path

import numpy as np

from ...config import CONFIG
from ...realtime import tracking
from . import set as power

_CANCEL = threading.Event()
_RUN = threading.Lock()
_STATUS = {"state": "inactive"}
RESULT_PATH = CONFIG.runtime_dir / "lights-visualizer-flashes.json"


def cancel():
    _CANCEL.set()


def status():
    return dict(_STATUS)


def _check(deadline, request_cancel):
    if _CANCEL.is_set() or (request_cancel is not None and request_cancel.is_set()):
        raise InterruptedError("Light calibration cancelled")
    if time.monotonic() > deadline:
        raise TimeoutError("Light calibration exceeded its finite time budget")


def _frame():
    item = tracking.frame(latest=True)
    if item is None:
        raise RuntimeError("Fresh camera frames are unavailable")
    image, _unix_ns, _receipt, identity, metadata = item
    stamp = metadata.get("capture_mono_ns")
    if (type(stamp) is not int
            or metadata.get("capture_timestamp_source") != "v4l2_kernel_pts_monotonic_compatible"
            or not 0 <= time.monotonic_ns() - stamp < 750_000_000):
        raise RuntimeError("Enable native camera capture timestamps before flash calibration")
    # Downsample by striding only; no video, person features or image persists.
    return stamp / 1e9, image[::8, ::8].astype(np.float32), identity


def _pose():
    state = tracking.snapshot()
    pose = state.get("pose") or {}
    if state.get("state") != "running" or not all(type(pose.get(k)) in (int, float) for k in ("yaw", "pitch")):
        raise RuntimeError("Fresh camera pose is unavailable")
    return pose["yaw"], pose["pitch"]


def _collect(seconds, deadline, request_cancel, pose=None):
    until = min(deadline, time.monotonic() + seconds)
    frames = []
    while time.monotonic() < until:
        _check(deadline, request_cancel)
        item = _frame()
        if pose is not None and max(abs(a-b) for a,b in zip(pose, _pose())) > .3:
            raise RuntimeError("Camera moved during optical measurement; no timing was accepted")
        if not frames or item[0] != frames[-1][0]:
            frames.append(item)
        _CANCEL.wait(.025)
    if len(frames) < 3:
        raise RuntimeError("Too few distinct camera frames for optical timing")
    if any(item[2] != frames[0][2] for item in frames):
        raise RuntimeError("Camera identity changed during calibration")
    return frames


def _write(inventory, name, params, deadline, request_cancel, method="matter_zero"):
    if method != "matter_zero":
        raise ValueError("Only zero-transition Matter measurement is supported")
    _check(deadline, request_cancel)
    sent = time.monotonic()
    power._frame(name, inventory, params, _CANCEL, readback=True)
    return sent


def _atomic_json(path: Path, payload):
    descriptor, temporary = tempfile.mkstemp(prefix=".light-calibration-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as output:
            os.fchmod(output.fileno(), 0o600)
            json.dump(payload, output, indent=2)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def measure(request_cancel=None, fixtures=None, method="matter_zero"):
    """Measure five low-to-high colour flashes per fixture, restoring on every exit."""
    from . import visualize
    global _STATUS
    names = tuple(power.FIXTURES if fixtures is None else fixtures)
    if type(method) is not str or method != "matter_zero":
        raise ValueError("Choose a supported light command method")
    if not names or len(set(names)) != len(names) or any(name not in power.FIXTURES for name in names):
        raise ValueError("Choose registered fixtures once each")
    if not _RUN.acquire(blocking=False):
        raise RuntimeError("Light calibration is already active")
    # Register before waiting for arbitration; an intervening STOP is never erased.
    _CANCEL.clear()
    try:
        with visualize.power_operation(cancel_calibration=False), power._LOCK:
            lease = tracking.begin_measurement_hold()
            try:
                # Wait for two stationary motor reports before using fixed pixels.
                deadline = time.monotonic() + 4
                previous = None
                while True:
                    _check(deadline, request_cancel)
                    pose = _pose()
                    speed = tracking.snapshot().get("submitted_speed") or {}
                    if previous is not None and max(abs(a-b) for a,b in zip(pose, previous)) <= .1 and speed == {"yaw": 0.0, "pitch": 0.0}:
                        break
                    previous = pose
                    _CANCEL.wait(.25)
                return _measure(request_cancel, names, method)
            finally:
                tracking.end_measurement_hold(lease)
    except BaseException:
        _STATUS = {**_STATUS, "state": "failed"}
        raise
    finally:
        _RUN.release()


def _measure(request_cancel, names, method="matter_zero"):
    global _STATUS
    deadline = time.monotonic() + 150
    _STATUS = {"state": "measuring", "fixture": None, "completed": 0}
    inventory = power._inventory()
    with ThreadPoolExecutor(max_workers=6) as pool:
        before = dict(zip(names, pool.map(
            lambda name: power._read(name, inventory, _CANCEL), names)))
    for pilot in before.values():
        power._appearance(pilot)
    _check(deadline, request_cancel)
    baseline = _collect(.4, deadline, request_cancel)
    camera_identity = baseline[0][2]
    results, modified, restore_errors = {}, set(), []
    try:
        for name in names:
            _check(deadline, request_cancel)
            _STATUS = {"state": "measuring", "fixture": name, "completed": len(results)}
            pose = _pose()
            low = {"state": True, "r": 12, "g": 20, "b": 255,
                   "dimming": 12}
            high = {**low, "dimming": 85}
            modified.add(name)
            _write(inventory, name, low, deadline, request_cancel, method)
            dark = _collect(1.2, deadline, request_cancel, pose)
            _write(inventory, name, high, deadline, request_cancel, method)
            bright = _collect(1.2, deadline, request_cancel, pose)
            a = np.median([item[1] for item in dark[-3:]], axis=0)
            b = np.median([item[1] for item in bright[-3:]], axis=0)
            delta = b - a
            strength = np.linalg.norm(delta, axis=2)
            # Differential ROI follows this fixture's light, including its
            # reflection when the bulb itself is outside the camera view.
            mask = strength >= max(18.0, float(np.quantile(strength, .97)))
            if int(mask.sum()) < 12:
                results[name] = {"status": "not_visible", **inventory[name]}
                modified.remove(name)  # Register the one restoration attempt before dispatch.
                try:
                    _restore_one(name, inventory, before)
                except (OSError, ValueError, RuntimeError):
                    restore_errors.append(name)
                    raise
                continue
            vector = delta[mask]
            scale = float(np.sum(vector * vector))
            reference = a[mask]
            def level(frame):
                return float(np.sum((frame[mask] - reference) * vector) / scale)
            delays, intervals, ramps = [], [], []
            for trial in range(5):
                # Rebase between flashes: slow mechanical drift must not turn
                # into accumulated ROI brightness error over all five trials.
                pose = _pose()
                _write(inventory, name, low, deadline, request_cancel, method)
                quiet = _collect(1.0, deadline, request_cancel, pose)
                reference = np.median([item[1] for item in quiet[-3:]], axis=0)[mask]
                sent = _write(inventory, name, high, deadline, request_cancel, method)
                flash = _collect(1.2, deadline, request_cancel, pose)
                frames = quiet[-2:] + flash
                if any(item[2] != camera_identity for item in frames):
                    raise RuntimeError("Camera identity changed during calibration")
                samples = [(stamp, level(frame)) for stamp, frame, _identity in frames]
                if max(value for _stamp, value in samples) < .65:
                    continue
                crossings = {}
                for threshold in (.2, .5, .8):
                    for (left, before_level), (right, after_level) in zip(samples, samples[1:]):
                        if left >= sent - .2 and before_level < threshold <= after_level:
                            crossings[threshold] = (left, right)
                            break
                if .5 not in crossings:
                    continue
                left, right = crossings[.5]
                latency = (left + right) / 2 - sent
                if not 0 <= latency <= 1.5 or right - left > .16:
                    continue
                delays.append(latency * 1000)
                intervals.append((right - left) * 500)
                if .2 in crossings and .8 in crossings:
                    ramps.append(max(0, (sum(crossings[.8]) - sum(crossings[.2])) * 500))
            if len(delays) < 3:
                results[name] = {"status": "inconclusive", **inventory[name],
                                 "valid_flashes": len(delays)}
            else:
                median = float(np.median(delays))
                jitter = max(abs(value - median) for value in delays)
                results[name] = {"status": "measured", **inventory[name],
                    "latency_ms": round(median, 2),
                    "uncertainty_ms": round(jitter + max(intervals), 2),
                    "p95_ms": round(float(np.quantile(delays, .95)), 2),
                    "ramp_20_80_ms": round(float(np.median(ramps)), 2) if ramps else None,
                    "valid_flashes": len(delays), "observations_ms": [round(v, 2) for v in delays]}
            # Restore once before the next fixture; uncertain outcomes stay failed.
            modified.remove(name)  # An uncertain restoration must never replay.
            try:
                _restore_one(name, inventory, before)
            except (OSError, ValueError, RuntimeError):
                restore_errors.append(name)
                raise
        payload = {"version": 2, "measured_at": time.time(), "fixtures": results,
            "camera_binding": {"identity": list(camera_identity), "width": 1280, "height": 720,
                "timestamp_source": "v4l2_kernel_pts_monotonic_compatible",
                "measurement": "half_transition_driver_timestamp", "protocol": "matter", "command_method": method,
                "sensor_exposure_offset_verified": False},
            "physical_output_delay_verified": False}
        _check(deadline, request_cancel)
        _atomic_json(RESULT_PATH, payload)
        _STATUS = {"state": "completed", "completed": len(results),
                   "measured": sum(row["status"] == "measured" for row in results.values())}
        return payload
    except BaseException:
        _STATUS = {"state": "failed", "completed": len(results), "results": results}
        raise
    finally:
        for name in modified:
            try:
                _restore_one(name, inventory, before)
            except (OSError, ValueError, RuntimeError):
                restore_errors.append(name)
        if restore_errors:
            _STATUS = {**_STATUS, "state": "failed", "restore_failed": restore_errors}
            raise RuntimeError("Calibration appearance restoration failed: " + ", ".join(restore_errors))


def _restore_one(name, inventory, before):
    power._restore(name, inventory, before[name])


def impulse(payload, request_cancel):
    """One zero-transition Matter level up/down and click; numeric evidence only."""
    from . import visualize
    import io
    import selectors
    import signal
    import subprocess
    import wave
    global _STATUS
    if (not isinstance(payload, dict) or set(payload) - {"fixture", "microphone_id", "sink_id", "light_lead_ms"}
            or not {"fixture", "microphone_id", "sink_id"} <= set(payload)
            or type(payload["fixture"]) is not str or payload["fixture"] not in power.FIXTURES
            or any(type(payload[k]) is not int or payload[k] <= 0 for k in ("microphone_id", "sink_id"))
            or type(payload.get("light_lead_ms", 0)) not in (int, float)
            or not np.isfinite(payload.get("light_lead_ms", 0)) or not -1500 <= payload.get("light_lead_ms", 0) <= 1500):
        raise ValueError("Choose one fixture, observed microphone_id/sink_id and light_lead_ms between -1500 and 1500")
    if not _RUN.acquire(blocking=False):
        raise RuntimeError("Another light measurement is active")
    _CANCEL.clear()
    lease, before, modified = None, None, False
    children, playback, dispatch = [], [], {}
    try:
        with visualize.power_operation(cancel_calibration=False), power._LOCK:
            try:
                deadline = time.monotonic() + 18
                _check(deadline, request_cancel)
                inventory, name = power._inventory(), payload["fixture"]
                _rows, nodes, _meta = visualize._graph()
                bindings = []
                for key, kind in (("microphone_id", "Audio/Source"), ("sink_id", "Audio/Sink")):
                    node = nodes.get(payload[key], {})
                    if visualize._props(node).get("media.class") != kind or visualize._props(node).get("device.api") != "alsa":
                        raise ValueError("Choose observed physical ALSA capture and output nodes")
                    bindings.append(visualize._identity(node))
                def verify_audio():
                    _r, current, _m = visualize._graph()
                    if any(visualize._identity(current.get(b[0], {"id": -1})) != b for b in bindings):
                        raise RuntimeError("Impulse audio device identity changed")
                lease = tracking.begin_measurement_hold()
                previous, settled = None, False
                until = time.monotonic() + 4
                while time.monotonic() < until:
                    _check(deadline, request_cancel)
                    pose = _pose()
                    if (previous is not None and max(abs(a-b) for a,b in zip(pose, previous)) <= .1
                            and tracking.snapshot().get("submitted_speed") == {"yaw": 0.0, "pitch": 0.0}):
                        settled = True
                        break
                    previous = pose
                    request_cancel.wait(.1)
                if not settled:
                    raise RuntimeError("Camera did not settle for impulse measurement")
                before = {name: power._read(name, inventory, _CANCEL)}
                power._appearance(before[name])
                modified = True
                _write(inventory, name, {"state": True, "r": 0, "g": 0, "b": 255, "dimming": 10}, deadline, request_cancel)
                until = time.monotonic() + 2
                while time.monotonic() < until:
                    _check(deadline, request_cancel)
                    request_cancel.wait(.05)
                verify_audio()
                # A reproducible short, band-limited click, generated only in RAM.
                rate = 48000
                click = np.random.default_rng(0).normal(size=1536) * np.hanning(1536)
                spectrum = np.fft.rfft(click); bins = np.fft.rfftfreq(len(click), 1 / rate)
                spectrum[(bins < 600) | (bins > 4500)] = 0
                click = np.fft.irfft(spectrum, len(click))
                click = np.round(click / max(abs(click)) * .35 * 32767).astype("<i2")
                material = io.BytesIO()
                with wave.open(material, "wb") as wav:
                    wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(rate); wav.writeframes(click.tobytes())
                t0 = time.monotonic(); end = t0 + 6
                click_due = t0 + 3
                pulse_due = click_due - payload.get("light_lead_ms", 0) / 1000
                def check():
                    _check(deadline, request_cancel)
                def spawn(args, **kwargs):
                    check()
                    child = subprocess.Popen(args, stderr=subprocess.DEVNULL, start_new_session=True, **kwargs)
                    children.append(child)
                    return child
                def timed(action, due):
                    try:
                        while time.monotonic() < due:
                            check(); request_cancel.wait(min(.01, max(0, due-time.monotonic())))
                        check()
                        return action()
                    except BaseException:
                        request_cancel.set()
                        raise
                def pulse():
                    sent = time.monotonic()
                    dispatch["pulse"] = sent
                    raised = False
                    try:
                        raised = True  # Possible dispatch is registered before IPC.
                        power._set(name, inventory, {"level":254}, _CANCEL, readback=False)
                        up_ack = time.monotonic()
                        request_cancel.wait(max(0, sent + .2 - time.monotonic()))
                    finally:
                        if raised:
                            # Exactly one down command; shared lane makes it follow
                            # a possibly uncertain up command. Original restore follows.
                            down_request = time.monotonic()
                            power._set(name, inventory, {"level":25}, readback=True, timeout=60)
                    return {"pulse_request_mono":sent,"pulse_up_ack_mono":up_ack,
                            "pulse_down_request_mono":down_request,"pulse_down_ack_mono":time.monotonic(),
                            "pulse_dispatch_duration_ms":1000 * (down_request - sent),
                            "pulse_up_ack_after_down_deadline":up_ack > sent + .2}
                def play():
                    sent = time.monotonic()
                    child = spawn(["pw-play", "--target", bindings[1][1], "--properties", "node.dont-fallback=true",
                                   "--latency", "20ms", "-"], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL)
                    playback.append(child)
                    child.stdin.write(material.getvalue()); child.stdin.close()
                    return {"click_spawn_mono": sent, "click_stdin_closed_mono": time.monotonic()}
                def audio():
                    child = spawn(["pw-record", "--target", bindings[0][1], "--properties", "node.dont-fallback=true",
                        "--raw", "--format", "s16", "--rate", str(rate), "--channels", "2", "--latency", "20ms", "-"],
                        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, bufsize=0)
                    chunks, clocks, total = [], [], 0
                    try:
                        with selectors.DefaultSelector() as sel:
                            sel.register(child.stdout, selectors.EVENT_READ)
                            while time.monotonic() < end:
                                check()
                                if not sel.select(.04): continue
                                chunk = os.read(child.stdout.fileno(), 8192)
                                if not chunk: raise RuntimeError("Impulse microphone capture ended")
                                total += len(chunk)
                                if total > rate * 4 * 7: raise RuntimeError("Impulse audio exceeded bound")
                                chunks.append(chunk); clocks.append((time.monotonic(), total/(rate*4)))
                        if not clocks: raise RuntimeError("Impulse microphone returned no PCM")
                        samples = np.frombuffer(b"".join(chunks), dtype="<i2").reshape(-1,2).mean(axis=1) / 32768
                        offsets = np.array([a-b for a,b in clocks])
                        return samples, float(np.quantile(offsets,.1)), float(np.std(offsets)*1000)
                    except BaseException:
                        request_cancel.set(); raise
                def camera():
                    frames, identity = [], None
                    try:
                        while time.monotonic() < end:
                            check(); frame = _frame()
                            if identity is None: identity = frame[2]
                            if frame[2] != identity: raise RuntimeError("Impulse camera identity changed")
                            if max(abs(a-b) for a,b in zip(pose, _pose())) > .3:
                                raise RuntimeError("Camera moved during impulse measurement")
                            if not frames or frame[0] > frames[-1][0]: frames.append(frame)
                            if len(frames) > 180: raise RuntimeError("Impulse camera exceeded bound")
                            request_cancel.wait(.02)
                        if len(frames) < 20: raise RuntimeError("Too few impulse camera frames")
                        return frames
                    except BaseException:
                        request_cancel.set(); raise
                _STATUS = {"state": "impulse", "fixture": name}
                with ThreadPoolExecutor(max_workers=4, thread_name_prefix="light-impulse") as pool:
                    sound = pool.submit(timed, audio, t0); pictures = pool.submit(timed, camera, t0)
                    light = pool.submit(timed, pulse, pulse_due); speaker = pool.submit(timed, play, click_due)
                    samples, origin, jitter = sound.result(); frames = pictures.result()
                    clocks = {**light.result(), **speaker.result()}
                check(); verify_audio()
                if not playback or playback[0].poll() != 0:
                    raise RuntimeError("Impulse audio playback failed")
                stamps = np.array([f[0] for f in frames]); images = np.stack([f[1] for f in frames])
                pre = stamps < pulse_due-.2; post = (stamps >= clocks["pulse_request_mono"]) & (stamps <= pulse_due+1.5)
                if pre.sum() < 3 or post.sum() < 3: raise RuntimeError("Impulse frame timing incomplete")
                baseline = np.median(images[pre], axis=0)
                delta = np.quantile(images[post], .95, axis=0)-baseline
                strength = np.maximum(0, delta[:,:,0]-.5*(delta[:,:,1]+delta[:,:,2]))  # Camera owner supplies BGR.
                mask = strength >= max(5.,float(np.quantile(strength,.99)))
                trace = None
                if mask.sum() >= 6:
                    difference = images-baseline
                    trace = (difference[:,:,:,0]-.5*(difference[:,:,:,1]+difference[:,:,:,2]))[:,mask].mean(axis=1)
                template = click.astype(float)/32768; n = 1 << (len(samples)+len(template)-2).bit_length()
                matched = np.fft.irfft(np.fft.rfft(samples,n)*np.fft.rfft(template[::-1],n),n)
                corr = matched[len(template)-1:len(samples)]
                energy = np.r_[0.,np.cumsum(samples*samples)]
                norm = np.sqrt(np.maximum(1e-20,(energy[len(template):]-energy[:-len(template)])*np.sum(template*template)))
                score = corr/norm; times = origin + np.arange(len(score))/rate
                valid = np.flatnonzero((times >= clocks["click_spawn_mono"]-.05)&(times <= clocks["click_spawn_mono"]+1.5))
                if not len(valid): raise RuntimeError("Impulse click timing incomplete")
                found = valid[np.argmax(abs(score[valid]))]
                audio_ok = abs(score[found]) >= .15
                optical_ok = trace is not None and float(trace[post].max()) >= 8
                peak = int(np.flatnonzero(post)[np.argmax(trace[post])]) if optical_ok else None
                result = {"state": "completed", "fixture": name, "light_lead_ms": payload.get("light_lead_ms",0),
                    "command_method": "matter_zero", "protocol":"matter", "fixture_binding":dict(inventory[name]), "pulse_params": {"up_level":254,"down_level":25,"requested_duration_ms":200},
                    "transition_time": 0, "optical_step_shape_verified": False, "clocks": clocks, "scheduled_mono": {"light":pulse_due,"click":click_due},
                    "audio": {"status":"matched" if audio_ok else "inconclusive", "matched_start_mono":float(times[found]) if audio_ok else None,
                        "correlation":float(score[found]),"receipt_clock_jitter_ms":jitter,"microphone_processing_delay_verified":False},
                    "optical": {"status":"visible" if optical_ok else "inconclusive", "roi_pixels":int(mask.sum()),
                        "capture_mono":stamps.tolist(),"blue_excess":trace.tolist() if trace is not None else [],
                        "peak_mono":float(stamps[peak]) if peak is not None else None,
                        "frame_interval_ms":float(np.median(np.diff(stamps))*1000),"sensor_exposure_offset_verified":False},
                    "visible_peak_minus_audio_start_ms":float((stamps[peak]-times[found])*1000) if optical_ok and audio_ok else None,
                    "calibrated":False}
                _STATUS = {"state":"completed","measurement":"single_impulse"}
                return result
            finally:
                cleanup_failed = False
                try:
                    for child in children:
                        try:
                            if child.poll() is None:
                                os.killpg(child.pid, signal.SIGTERM)
                                try: child.wait(timeout=1)
                                except subprocess.TimeoutExpired:
                                    os.killpg(child.pid, signal.SIGKILL); child.wait(timeout=1)
                        except (OSError, subprocess.SubprocessError):
                            cleanup_failed = True
                        finally:
                            for channel in (child.stdin, child.stdout):
                                if channel is not None and not channel.closed:
                                    try: channel.close()
                                    except OSError: cleanup_failed = True
                    if modified:
                        _restore_one(name, inventory, before)
                    if cleanup_failed:
                        raise RuntimeError("Impulse child cleanup incomplete")
                finally:
                    if lease is not None: tracking.end_measurement_hold(lease)
    except BaseException:
        _STATUS = {"state":"failed","measurement":"single_impulse"}
        raise
    finally:
        _RUN.release()

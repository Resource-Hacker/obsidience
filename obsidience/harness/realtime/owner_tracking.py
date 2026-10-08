"""One CPU camera capture owner with local owner recognition and bounded follow.

The host disables native AI/Zone tracking before start and owns camera power.
This module never controls power, native tracking, authentication or services.
Model artifacts: OpenCV Zoo YuNet (MIT), SFace (Apache-2.0).
Optional person_module supplies existing pure PersonDetector/ImageTracker code.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import logging
import math
import os
import select
from pathlib import Path
import subprocess
import tempfile
import threading
import time

import cv2
import numpy as np


MODEL_HASHES = {
    "detector_model": "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
    "recognizer_model": "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
}
PERSON_HASH = "a77dd863933f184a19e84361c64b788228a7c7dacc2c78939239a96ad3efca3b"
WIDTH, HEIGHT = 1280, 720


class Tracker:
    """start/close are host lifecycle calls; frame is the only camera image seam."""

    def __init__(self):
        self._lock = threading.RLock()
        self._motor_lock = threading.Lock()
        self._stop = threading.Event()
        self._stop.set()
        self._threads = []
        self._capture = None
        self._helper = None
        self._latest = None
        self._observed = None
        self._generation = 0
        self._status = {"state": "stopped", "enrollment": {"state": "idle", "samples": 0}}

    def start(self, device, name, identity, config):
        """Start once; errors tear down acquired resources. No automatic restart."""
        self.close()
        config = dict(config)
        for key, expected in MODEL_HASHES.items():
            if hashlib.sha256(Path(config[key]).read_bytes()).hexdigest() != expected:
                raise ValueError("camera_model_checksum_mismatch")
        cv2.setNumThreads(1)
        detector = cv2.FaceDetectorYN.create(
            str(config["detector_model"]), "", (WIDTH, HEIGHT), .9, .3, 5000,
            cv2.dnn.DNN_BACKEND_OPENCV, cv2.dnn.DNN_TARGET_CPU)
        recognizer = cv2.FaceRecognizerSF.create(
            str(config["recognizer_model"]), "", cv2.dnn.DNN_BACKEND_OPENCV,
            cv2.dnn.DNN_TARGET_CPU)
        person_detector = person_tracker = None
        if config.get("person_model"):
            if hashlib.sha256(Path(config["person_model"]).read_bytes()).hexdigest() != PERSON_HASH:
                raise ValueError("camera_person_model_checksum_mismatch")
            spec = importlib.util.spec_from_file_location("_camera_person_vision", config["person_module"])
            if spec is None or spec.loader is None:
                raise ValueError("camera_person_module_unavailable")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            person_detector = module.PersonDetector(Path(config["person_model"]))
            person_tracker = module.ImageTracker()
        templates = self._load_templates(Path(config["template_path"]))
        home = (float(config.get("home_yaw", 0)), float(config.get("home_pitch", 0)))
        limits = (tuple(config.get("yaw_limits", (-35, 60))),
                  tuple(config.get("pitch_limits", (-20, 20))))
        if (not all(math.isfinite(x) for x in home + limits[0] + limits[1]) or
                any(len(pair) != 2 or pair[0] >= pair[1] for pair in limits) or
                not all(pair[0] <= value <= pair[1] for value, pair in zip(home, limits))):
            raise ValueError("camera_invalid_motor_bounds")
        with self._lock:
            self._generation += 1
            generation = self._generation
            self._stop = threading.Event()
            self._config = config
            self._identity = identity
            self._detector, self._recognizer = detector, recognizer
            self._person_detector, self._person_tracker = person_detector, person_tracker
            self._templates = templates
            self._home, self._limits = home, limits
            self._max_age = min(.75, max(.1, float(config.get("frame_max_age_s", .75))))
            self._latest = None
            self._observed = None
            self._samples = []
            self._enrollment_started = None
            self._last_sample = 0.
            self._match_times = []
            self._last_match = 0.
            self._owner_confirmed = False
            self._owner_resume_until = 0.
            self._body_id = None
            self._framing_anchor = None
            self._lost_since = time.monotonic()
            self._started_mono = self._lost_since
            self._home_verified = False
            self._desired_motion = None
            self._last_sequence = 0
            self._errors = []
            self._status = {"state": "starting", "name": str(name)[:96],
                            "enrolled": bool(templates), "frames": 0, "inferences": 0,
                            "face_count": 0, "owner_score": None, "pose": None,
                            "target_center": None, "inference_ms": None, "pose_read_ms": None,
                            "motor_ms": None, "motor_commands": 0, "reported_speed": None,
                            "submitted_speed": None, "feedback_age_s": None, "velocity_submitted": False,
                            "body_count": 0, "body_id": None, "bound_body_id": None,
                            "framing_anchor": None,
                            "motion_reason": "holding", "motor_state": "idle",
                            "target": "unknown", "enrollment": {"state": "idle", "samples": 0}}
        command = [str(config.get("ffmpeg_path", "ffmpeg")), "-nostdin", "-hide_banner",
                   "-loglevel", "error", "-fflags", "+discardcorrupt", "-err_detect", "explode", "-f", "v4l2",
                   "-input_format", "mjpeg", "-video_size", "1280x720", "-framerate", "15",
                   "-threads", "1", "-i", str(device), "-an", "-sn", "-vf", "scale=1280:720",
                   "-threads", "1", "-pix_fmt", "bgr24", "-f", "rawvideo", "pipe:1"]
        try:
            with self._lock:
                if not self._current(generation):
                    raise RuntimeError("camera_start_cancelled")
                self._helper_buffer = bytearray()
                self._helper = subprocess.Popen([str(config["gimbal_helper"])], stdin=subprocess.PIPE,
                                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                                bufsize=0, start_new_session=True)
            ready = self._helper_line(generation, timeout=10)
            if ready.get("ready") is not True or ready.get("ok") is not True:
                raise RuntimeError("camera_gimbal_start_failed")
            with self._lock:
                if not self._current(generation):
                    raise RuntimeError("camera_start_cancelled")
                process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                           stdin=subprocess.DEVNULL, bufsize=0, start_new_session=True)
                self._capture = process
                self._threads = [
                    threading.Thread(target=self._read_frames, args=(generation, process), name="camera-reader"),
                    threading.Thread(target=self._read_errors, args=(generation, process), name="camera-stderr"),
                    threading.Thread(target=self._infer, args=(generation,), name="camera-owner-inference"),
                    threading.Thread(target=self._motor_loop, args=(generation,), name="camera-motor-control"),
                ]
                for thread in self._threads:
                    thread.start()
        except Exception:
            self.close()
            raise
        return self.snapshot()

    def _load_templates(self, path):
        if not path.exists():
            return []
        if path.stat().st_size > 128_000 or path.stat().st_mode & 0o077:
            raise ValueError("camera_template_permissions_or_size")
        data = json.loads(path.read_text())
        if data.get("format") != "sface-owner-v1" or data.get("model_sha256") != MODEL_HASHES["recognizer_model"]:
            raise ValueError("camera_template_format_mismatch")
        arrays = [np.asarray(row, dtype=np.float32).reshape(1, -1) for row in data["templates"]]
        if not 1 <= len(arrays) <= 20 or any(x.shape != (1, 128) or not np.isfinite(x).all() for x in arrays):
            raise ValueError("camera_template_invalid")
        return [self._normalize(x) for x in arrays]

    @staticmethod
    def _normalize(feature):
        norm = float(np.linalg.norm(feature))
        if not math.isfinite(norm) or norm < 1e-8:
            raise ValueError("camera_invalid_feature")
        return np.asarray(feature, dtype=np.float32) / norm

    def _current(self, generation):
        return generation == self._generation and not self._stop.is_set()

    def _fail(self, generation, reason):
        with self._lock:
            if not self._current(generation):
                return
            self._status.update(state="failed", error=reason, target="unknown")
            if self._enrollment_started is not None:
                self._status["enrollment"] = {"state": "cancelled", "samples": len(self._samples)}
                self._samples = []
                self._enrollment_started = None
            self._stop.set()
            self._latest = None
            self._observed = None
            self._desired_motion = None
            for child in (self._capture, self._helper):
                if child is not None and child.poll() is None:
                    try:
                        child.terminate()
                    except ProcessLookupError:
                        pass

    def _read_errors(self, generation, process):
        # Drain always; keep no hardware paths or raw ffmpeg diagnostics publicly.
        try:
            while process.stderr.read(4096):
                if generation != self._generation:
                    return
        except (OSError, ValueError):
            pass

    def _read_frames(self, generation, process):
        size = WIDTH * HEIGHT * 3
        try:
            while self._current(generation):
                payload = bytearray()
                while len(payload) < size:
                    chunk = process.stdout.read(size - len(payload))
                    if not chunk:
                        self._fail(generation, "camera_capture_ended")
                        return
                    payload.extend(chunk)
                image = np.frombuffer(payload, dtype=np.uint8).reshape(HEIGHT, WIDTH, 3)
                now, unix_ns = time.monotonic(), time.time_ns()
                with self._lock:
                    if not self._current(generation):
                        return
                    self._status["frames"] += 1
                    sequence = self._status["frames"]
                    self._latest = (image, unix_ns, now, self._identity, sequence)
                    if self._status["state"] == "starting":
                        self._status["state"] = "running"
        except (OSError, ValueError):
            self._fail(generation, "camera_capture_error")

    def frame(self):
        with self._lock:
            item = self._observed
            if item is None or time.monotonic()-item[2] > self._max_age:
                raw = self._latest
                item = None if raw is None else (*raw[:4], {
                    "analyzed": False, "target": "unknown", "cosine": None,
                    "face_box": None, "checked_unix_ns": None})
            if self._stop.is_set() or item is None or time.monotonic() - item[2] > self._max_age:
                return None
            return item[0].copy(), item[1], item[2], item[3], dict(item[4])

    def snapshot(self):
        with self._lock:
            result = json.loads(json.dumps(self._status))
            item = self._latest
            result["frame_age_s"] = None if item is None else round(time.monotonic() - item[2], 3)
            result["fresh"] = (not self._stop.is_set() and item is not None and
                               time.monotonic() - item[2] <= getattr(self, "_max_age", .75))
            result["authentication"] = False
            analyzed = self._observed
            result["recognition_age_s"] = None if analyzed is None else round(time.monotonic()-analyzed[2], 3)
            return result

    def begin_enrollment(self):
        with self._lock:
            if self._stop.is_set():
                raise RuntimeError("camera_tracker_not_running")
            if self._enrollment_started is not None:
                raise RuntimeError("camera_enrollment_already_active")
            self._samples = []
            self._last_sample = 0.
            self._enrollment_started = time.monotonic()
            self._match_times = []
            self._owner_confirmed = False
            self._owner_resume_until = 0.
            self._body_id = None
            self._framing_anchor = None
            self._observed = None
            self._desired_motion = None
            self._status["enrollment"] = {"state": "sampling", "samples": 0, "required": 20,
                                          "deadline_s": 40, "last_rejection": None}
            return self.snapshot()

    def _quality_feature(self, image, face, *, enrollment=True):
        x, y, width, height = face[:4]
        if min(width, height) < (80 if enrollment else 48) or x < 2 or y < 2 or x + width > WIDTH - 2 or y + height > HEIGHT - 2:
            return None, "small_or_clipped"
        landmarks = face[4:14].reshape(5, 2)
        if not np.isfinite(face).all() or np.linalg.norm(landmarks[0] - landmarks[1]) < (20 if enrollment else 12):
            return None, "landmarks"
        crop = self._recognizer.alignCrop(image, face)
        if float(cv2.Laplacian(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var()) < 40:
            return None, "blur"
        return self._normalize(self._recognizer.feature(crop)), None

    def _enroll(self, generation, image, faces, now):
        with self._lock:
            started = self._enrollment_started
        if started is None:
            return
        if now - started >= 40:
            with self._lock:
                self._status["enrollment"].update(state="insufficient_quality", samples=len(self._samples))
                self._samples = []
                self._enrollment_started = None
            return
        rejection = "exactly_one_face_required"
        feature = None
        if len(faces) == 1:
            feature, rejection = self._quality_feature(image, faces[0])
        with self._lock:
            if not self._current(generation) or self._enrollment_started != started:
                return
            if feature is not None and now - self._last_sample < .5:
                rejection = "sample_interval"
            if feature is not None and self._samples:
                similarities = [(feature @ sample.T).item() for sample in self._samples]
                if max(similarities) >= .9985:
                    rejection = "duplicate_view"
                elif similarities[0] < .5:
                    rejection = "identity_changed"
            if rejection is not None:
                self._status["enrollment"]["last_rejection"] = rejection
                return
            self._samples.append(feature.copy())
            self._last_sample = now
            self._status["enrollment"].update(samples=len(self._samples), last_rejection=None)
            if len(self._samples) < 20:
                return
            # Save embeddings only. Publication and cancellation share this lock.
            path = Path(self._config["template_path"])
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            data = {"format": "sface-owner-v1", "model_sha256": MODEL_HASHES["recognizer_model"],
                    "templates": [sample.ravel().tolist() for sample in self._samples]}
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                                 prefix=".owner-template-", delete=False) as output:
                    temporary = output.name
                    os.fchmod(output.fileno(), 0o600)
                    json.dump(data, output, separators=(",", ":"))
                    output.flush()
                    os.fsync(output.fileno())
                if not self._current(generation):
                    return
                os.replace(temporary, path)
                temporary = None
                self._templates = list(self._samples)
                self._samples = []
                self._enrollment_started = None
                self._match_times = []
                self._status.update(enrolled=True)
                self._status["enrollment"].update(state="complete", samples=20)
            finally:
                if temporary is not None:
                    Path(temporary).unlink(missing_ok=True)

    def _bodies(self, image, now):
        if self._person_detector is None:
            return []
        from PIL import Image
        # Existing detector uses 640x480. Letterbox wide frame into y=60..420.
        small = cv2.resize(image, (640, 360))
        padded = np.zeros((480, 640, 3), dtype=np.uint8)
        padded[60:420] = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
        detections, _ = self._person_detector.detect(Image.fromarray(padded))
        tracks = self._person_tracker.update(detections, now)
        return [{**track, "box": [track["box"][0]*2, (track["box"][1]-60)*2,
                                  track["box"][2]*2, (track["box"][3]-60)*2]} for track in tracks
                if track.get("current_detection")]

    @staticmethod
    def _containing_body(face, bodies):
        x, y, width, height = face[:4]
        cx, cy = x + width/2, y + height/2
        candidates = [body for body in bodies if body["box"][0] <= cx <= body["box"][2]
                      and body["box"][1] <= cy <= body["box"][3]]
        return candidates[0] if len(candidates) == 1 else None

    @staticmethod
    def _body_unambiguous(body, bodies):
        if body is None:
            return False
        a = body["box"]
        area = max(1, (a[2]-a[0])*(a[3]-a[1]))
        for other in bodies:
            if other["id"] == body["id"]:
                continue
            b = other["box"]
            intersection = max(0, min(a[2],b[2])-max(a[0],b[0]))*max(0, min(a[3],b[3])-max(a[1],b[1]))
            if intersection/min(area, max(1, (b[2]-b[0])*(b[3]-b[1]))) > .2:
                return False
        return True

    def _infer(self, generation):
        try:
            while self._current(generation):
                tick = time.monotonic()
                with self._lock:
                    item = self._latest
                    if item is not None:
                        item = (item[0].copy(), *item[1:])
                    templates = list(self._templates)
                    enrolling = self._enrollment_started is not None
                if item is None or tick - item[2] > self._max_age or item[4] == self._last_sequence:
                    last_frame = self._started_mono if item is None else item[2]
                    if tick-last_frame > (5 if item is None else 3):
                        self._fail(generation, "camera_frame_stalled")
                        return
                    self._stop.wait(.05)
                    continue
                self._last_sequence = item[4]
                image, _, observed, _, _ = item
                _, detected = self._detector.detect(image)
                faces = [] if detected is None else list(detected)
                self._enroll(generation, image, faces, observed)
                bodies = self._bodies(image, observed) if templates and not enrolling else []
                matches = []
                best = None
                quality_rejections = {}
                if templates and not enrolling:
                    for face in faces:
                        feature, rejection = self._quality_feature(image, face, enrollment=False)
                        if feature is None:
                            quality_rejections[rejection] = quality_rejections.get(rejection, 0)+1
                            continue
                        # Require agreement with multiple exemplars, not one lucky maximum.
                        scores = sorted(((feature @ template.T).item() for template in templates), reverse=True)
                        score = float(np.mean(scores[:min(3, len(scores))]))
                        best = score if best is None else max(best, score)
                        if score >= .5:
                            matches.append(face)
                now = time.monotonic()
                if not self._current(generation):
                    break
                # No actuation can use work that outlived its original source frame.
                if now - observed > self._max_age:
                    self._stop.wait(.02)
                    continue
                target = None
                selected_body_id = None
                label = "unknown"
                body = next((b for b in bodies if b["id"] == self._body_id and b["score"] >= .5), None)
                bound = self._body_unambiguous(body, bodies)
                if self._body_id is not None and not bound:
                    self._body_id = None
                    self._framing_anchor = None
                    self._owner_confirmed = False
                    self._match_times = []
                retained = self._owner_confirmed and (bound or (self._body_id is None and observed-self._last_match <= 1.5))
                if not retained:
                    self._owner_confirmed = False
                if len(matches) == 1:
                    matched_body = self._containing_body(matches[0], bodies)
                    if self._body_id is not None and (matched_body is None or matched_body["id"] != self._body_id):
                        # A new body needs its own initial repeated face proof.
                        self._body_id = None
                        self._framing_anchor = None
                        self._owner_confirmed = False
                        self._match_times = []
                        retained = False
                    if self._match_times and observed - self._match_times[-1] > .6:
                        self._match_times = []
                    self._match_times.append(observed)
                    self._match_times = [value for value in self._match_times if observed-value <= 2]
                    if retained or (len(self._match_times) >= 3 and observed-self._match_times[0] >= .8):
                        face = matches[0]
                        body = matched_body
                        self._body_id = body["id"] if self._body_unambiguous(body, bodies) and body["score"] >= .5 else None
                        selected_body_id = self._body_id
                        self._last_match = observed
                        self._owner_confirmed = True
                        target = (face[0]+face[2]/2, face[1]+face[3]/2)
                        if self._body_id is not None:
                            x1,y1,x2,y2 = body["box"]
                            relative = ((target[0]-x1)/max(1,x2-x1), (target[1]-y1)/max(1,y2-y1))
                            if all(math.isfinite(value) for value in relative):
                                fractions = (max(.1,min(.9,float(relative[0]))), max(.05,min(.75,float(relative[1]))))
                                previous = self._framing_anchor
                                if previous is not None and previous[0] == self._body_id:
                                    fractions = tuple(float(.7*old+.3*new) for old,new in zip(previous[1],fractions))
                                self._framing_anchor = (self._body_id, fractions)
                                target = (float(x1+fractions[0]*(x2-x1)), float(y1+fractions[1]*(y2-y1)))
                        else:
                            self._framing_anchor = None
                        label = "owner_verified"
                    else:
                        label = "confirming_owner"
                elif len(matches) > 1:
                    self._match_times = []
                    self._body_id = None
                    self._framing_anchor = None
                    self._owner_confirmed = False
                    self._owner_resume_until = 0.
                    label = "ambiguous"
                else:
                    self._match_times = []
                    # Identity is historical face evidence; continuity is the exact
                    # current unambiguous body track. Profile scores are not new IDs.
                    if bound and self._owner_confirmed:
                        x1,y1,x2,y2 = body["box"]
                        anchor = self._framing_anchor
                        fractions = anchor[1] if anchor is not None and anchor[0] == self._body_id else (.5,.35)
                        target = (float(x1+fractions[0]*(x2-x1)), float(y1+fractions[1]*(y2-y1)))
                        selected_body_id = self._body_id
                        label = "owner_track_continuity"
                    else:
                        self._body_id = None
                        self._framing_anchor = None
                        self._owner_confirmed = False
                        self._owner_resume_until = 0.
                # Person framing and owner identification are separate outcomes.
                # A single repeated anonymous person may bring their face into view.
                if target is None and not enrolling and len(matches) <= 1 and len(bodies) == 1:
                    person = bodies[0]
                    if person["score"] >= .5 and person.get("observations", 0) >= 2:
                        x1,y1,x2,y2 = person["box"]
                        target = ((x1+x2)/2, y1+.35*(y2-y1))
                        selected_body_id = person["id"]
                        label = "person_unidentified"
                with self._lock:
                    if not self._current(generation):
                        break
                    self._status.update(face_count=len(faces), owner_score=None if best is None else round(best, 3), target=label)
                    self._status.update(target_center=None if target is None else [round(float(v), 1) for v in target],
                                        inference_ms=round((now-tick)*1000, 1), quality_rejections=quality_rejections)
                    self._status.update(body_count=len(bodies), body_id=bodies[0]["id"] if len(bodies)==1 else None,
                                        bound_body_id=self._body_id)
                    anchor = self._framing_anchor
                    self._status["framing_anchor"] = None if anchor is None else {
                        "body_id": int(anchor[0]), "x_fraction": round(float(anchor[1][0]),4), "y_fraction": round(float(anchor[1][1]),4)}
                    self._status["inferences"] += 1
                    metadata = {"analyzed": True, "target": label,
                                "cosine": None if best is None else round(best, 3),
                                "face_box": [round(float(v), 1) for v in matches[0][:4]] if len(matches)==1 else None,
                                "checked_unix_ns": time.time_ns()}
                    metadata["target_center"] = self._status["target_center"]
                    self._observed = (image, item[1], observed, item[3], metadata)
                    if enrolling:
                        self._lost_since = now
                        self._desired_motion = None
                    elif target is not None:
                        self._lost_since = now
                        self._home_verified = False
                        self._desired_motion = {"generation": generation, "at": observed, "center": target,
                                                "reason": "follow", "binding": selected_body_id}
                    elif now-self._lost_since >= 4 and not self._home_verified:
                        self._desired_motion = {"generation": generation, "at": observed, "center": None,
                                                "reason": "return_home", "binding": None}
                    else:
                        self._desired_motion = None
                    self._status["motion_reason"] = "holding" if self._desired_motion is None else self._desired_motion["reason"]
                self._stop.wait(max(0, .2-(time.monotonic()-tick)))
        except Exception:
            logging.exception("Camera owner inference failed")
            self._fail(generation, "camera_inference_error")

    def _helper_line(self, generation, timeout):
        deadline = time.monotonic()+timeout
        child = self._helper
        while self._current(generation) and child is not None:
            if b"\n" in self._helper_buffer:
                line, _, remaining = self._helper_buffer.partition(b"\n")
                self._helper_buffer = bytearray(remaining)
                return json.loads(line)
            remaining_time = deadline-time.monotonic()
            if remaining_time <= 0 or child.poll() is not None:
                break
            readable, _, _ = select.select([child.stdout], [], [], min(.1, remaining_time))
            if not readable:
                continue
            chunk = os.read(child.stdout.fileno(), 4096)
            if not chunk:
                break
            self._helper_buffer.extend(chunk)
            if len(self._helper_buffer) > 4096:
                raise RuntimeError("camera_motor_protocol_error")
        raise RuntimeError("camera_motor_response_unavailable")

    def _gimbal(self, generation, velocity=None, motion=None):
        operation_started = time.monotonic()
        command = "get\n" if velocity is None else "speed " + " ".join(format(float(v), ".4f") for v in velocity) + "\n"
        moving = velocity is not None and any(abs(float(v)) > 1e-6 for v in velocity)
        if moving:
            check = self._config.get("identity_check")
            try:
                identity_valid = callable(check) and check() == self._identity
            except Exception:
                identity_valid = False
            if not identity_valid:
                self._fail(generation, "camera_identity_changed")
                return None
        try:
            with self._lock:
                if not self._current(generation):
                    return None
                if moving:
                    current = self._desired_motion
                    if (self._enrollment_started is not None or current is None or motion is None
                            or current["generation"] != generation or current["reason"] != motion["reason"]
                            or current["binding"] != motion["binding"]
                            or time.monotonic()-motion["at"] > self._max_age):
                        return None
                child = self._helper
                child.stdin.write(command.encode("ascii"))
                child.stdin.flush()
                if velocity is not None:
                    self._status["motor_commands"] += 1
            data = self._helper_line(generation, timeout=1)
            pose = (float(data["yaw_motor"]), float(data["pitch_motor"]))
            reported = (float(data["reported_yaw_speed"]), float(data["reported_pitch_speed"]))
            submitted = (float(data["submitted_yaw_speed"]), float(data["submitted_pitch_speed"]))
            feedback_age = float(data["feedback_age_s"])
            if (data.get("ok") is not True or data.get("feedback_valid") is not True
                    or feedback_age > .7 or not all(math.isfinite(v) for v in pose+reported+submitted+(feedback_age,))):
                raise ValueError("unavailable motor feedback")
        except (OSError, ValueError, RuntimeError, KeyError, TypeError):
            # SIGTERM reaches the helper's independent zero-velocity shutdown path.
            # The previous nonzero speed is never replayed.
            self._fail(generation, "camera_velocity_delivery_uncertain" if velocity is not None else "camera_pose_unavailable")
            return None
        with self._lock:
            if not self._current(generation):
                return None
            self._status.update(pose={"yaw": round(pose[0],2), "pitch": round(pose[1],2)},
                                reported_speed={"yaw": round(reported[0],3), "pitch": round(reported[1],3)},
                                submitted_speed={"yaw": round(submitted[0],3), "pitch": round(submitted[1],3)},
                                feedback_age_s=round(feedback_age,3), velocity_submitted=velocity is not None)
            self._status["motor_ms" if velocity is not None else "pose_read_ms"] = round(
                float(time.monotonic()-operation_started)*1000,1)
            self._velocity = submitted
        return pose

    def _motor_loop(self, generation):
        self._velocity = (0.,0.)
        previous = time.monotonic()
        try:
            while self._current(generation):
                tick = time.monotonic()
                with self._motor_lock:
                    feedback = self._gimbal(generation)
                    if feedback is None:
                        return
                    pose = feedback
                    with self._lock:
                        motion = self._desired_motion
                        fresh = (motion is not None and motion["generation"] == generation
                                 and time.monotonic()-motion["at"] <= self._max_age
                                 and self._enrollment_started is None)
                    wanted = (0.,0.)
                    reason = "stopped_no_fresh_target"
                    if fresh and motion["reason"] == "follow":
                        ex,ey = float(motion["center"][0])-640., float(motion["center"][1])-360.
                        # SDK speed readbacks fluctuate at rest; use actual pose
                        # and proportional image error, not noisy speed damping.
                        wanted = (0. if abs(ex)<8 else -1.4*ex/17.18,
                                  0. if abs(ey)<6 else 1.4*ey/17.78)
                        reason = "continuous_centering"
                    elif fresh and motion["reason"] == "return_home":
                        error = (self._home[0]-pose[0], self._home[1]-pose[1])
                        wanted = tuple(0. if abs(v)<.3 else 1.4*v for v in error)
                        reason = "smooth_return_home"
                        if max(abs(v) for v in error)<.3:
                            with self._lock:
                                if self._desired_motion is motion:
                                    self._home_verified = True
                            wanted = (0.,0.)
                    dt = min(.3,max(.01,tick-previous))
                    previous = tick
                    if fresh:
                        wanted = (max(-12.,min(12.,wanted[0])), max(-8.,min(8.,wanted[1])))
                        # One gentle acceleration limit; loss/cancellation stops immediately.
                        step = 20.*dt
                        velocity = tuple(float(old+max(-step,min(step,new-old))) for old,new in zip(self._velocity,wanted))
                    else:
                        velocity = (0.,0.)
                    with self._lock:
                        self._status["motor_state"] = reason
                    if self._gimbal(generation,velocity=velocity,motion=motion if fresh else None) is None:
                        # A target replaced between compute and dispatch is cancelled;
                        # stop it explicitly instead of letting the previous speed persist.
                        if self._current(generation):
                            self._gimbal(generation,velocity=(0.,0.))
                self._stop.wait(max(0,.2-(time.monotonic()-tick)))
        except Exception:
            logging.exception("Camera velocity control failed")
            self._fail(generation,"camera_motor_control_error")

    def close(self):
        # Disarm before waiting: no new child or motor action can pass the lock.
        with self._lock:
            self._stop.set()
            self._generation += 1
            children = [child for child in (self._capture, self._helper) if child is not None]
            threads = list(self._threads)
            self._latest = None
            self._observed = None
            self._desired_motion = None
            if getattr(self, "_enrollment_started", None) is not None:
                self._status["enrollment"] = {"state": "cancelled", "samples": len(self._samples)}
                self._enrollment_started = None
                self._samples = []
            for child in children:
                if child.poll() is None:
                    try:
                        child.terminate()
                    except ProcessLookupError:
                        pass
        for child in children:
            try:
                child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=2)
        for thread in threads:
            if thread is not threading.current_thread():
                thread.join()
        with self._motor_lock:
            with self._lock:
                self._capture = self._helper = None
                self._threads = []
                self._status.update(state="stopped", target="unknown")
        for child in children:
            for pipe in (child.stdin, child.stdout, child.stderr):
                if pipe is not None:
                    pipe.close()

"""On-demand, CPU-only PP-OCRv6-small evidence from caller-owned native PNGs.

DB geometry, normalization and CTC decoding adapted narrowly from the existing
PaddleOCR DB/CTC adapter; see artifacts.lock.json ppocr_v6_cpu. No capture,
input, TensorRT, GPU, download, worker thread or queue is owned by this module.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import threading
import time
from collections.abc import Callable, Mapping
from pathlib import Path


class OCRBusy(RuntimeError):
    pass


class OCRCancelled(RuntimeError):
    pass


class _Deadline(Exception):
    pass


_ARTIFACTS = {
    "det/inference.onnx": "d73e0058b7a8086bbd57f3d10b8bcd4ff95363f67e06e2762b5e814fe9c9410e",
    "rec/inference.onnx": "5435fd747c9e0efe15a96d0b378d5bd157e9492ed8fd80edf08f30d02fa24634",
    "det/inference.yml": "193f435274bf9f0b5f71a929bbfbcf148282df7e633b34e7c373e8f44741b516",
    "rec/inference.yml": "ab078671bb49f06228eadccd34f1bb501e157f7a047095ffb943ba81512c77d1",
}


def _ordered_points(points):
    import numpy as np

    array = np.asarray(points, dtype=np.float32).reshape(4, 2)
    ordered = np.zeros((4, 2), dtype=np.float32)
    sums = array.sum(axis=1)
    differences = np.diff(array, axis=1).reshape(-1)
    ordered[0] = array[np.argmin(sums)]
    ordered[2] = array[np.argmax(sums)]
    ordered[1] = array[np.argmin(differences)]
    ordered[3] = array[np.argmax(differences)]
    return ordered


class CpuOCR:
    """One explicit session owner. Concurrent reads fail busy; close drains.

    Cancellation is checked around each native call, including session loading.
    It discards all output. Deadlines return explicitly incomplete evidence;
    an already running native call must finish before either can be observed.
    Caller runs blocking read/warm/close off its realtime event loop and drains
    its executor on cancellation. Construction itself imports no numeric runtime.
    """

    def __init__(self, model_dir: Path):
        self._root = Path(model_dir)
        self._lock = threading.Lock()
        self._closing = threading.Event()
        self._sessions = {}
        self._characters = ()
        self._det_config = None

    def close(self) -> None:
        self._closing.set()
        with self._lock:
            self._sessions.clear()
            self._characters = ()
            self._det_config = None

    def diagnostics(self) -> dict:
        return {"model": "PP-OCRv6-small", "artifacts": dict(_ARTIFACTS),
                "providers": ["CPUExecutionProvider"], "threads": 2}

    def _session(self, kind: str):
        if kind in self._sessions:
            return self._sessions[kind]
        import onnxruntime as ort
        import yaml

        for suffix in ("onnx", "yml"):
            relative = f"{kind}/inference.{suffix}"
            if hashlib.sha256((self._root / relative).read_bytes()).hexdigest() != _ARTIFACTS[relative]:
                raise ValueError("OCR artifact differs from pinned identity")
        config = yaml.safe_load((self._root / kind / "inference.yml").read_text())
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        options.add_session_config_entry("session.intra_op.allow_spinning", "0")
        options.add_session_config_entry("session.inter_op.allow_spinning", "0")
        session = ort.InferenceSession(str(self._root / kind / "inference.onnx"),
                                       sess_options=options, providers=["CPUExecutionProvider"])
        if session.get_providers() != ["CPUExecutionProvider"]:
            raise ValueError("OCR session must be CPU-only")
        if kind == "rec":
            self._characters = ("blank", *config["PostProcess"]["character_dict"], " ")
            if len(self._characters) != 18710:
                raise ValueError("OCR vocabulary does not match pinned model")
        else:
            self._det_config = config["PostProcess"]
        self._sessions[kind] = session
        return session

    def warm(self, *, detector: bool = True) -> None:
        if not self._lock.acquire(blocking=False):
            raise OCRBusy("OCR is already in use")
        try:
            self._check(None, None)
            self._session("rec")
            self._check(None, None)
            if detector:
                self._session("det")
            self._check(None, None)
        finally:
            self._lock.release()

    def _check(self, deadline, cancelled):
        if self._closing.is_set() or (cancelled is not None and cancelled()):
            raise OCRCancelled("OCR request cancelled")
        if deadline is not None and time.monotonic() >= deadline:
            raise _Deadline

    @staticmethod
    def _box_score(probability, points):
        import cv2
        import numpy as np

        height, width = probability.shape
        left = max(int(np.floor(points[:, 0].min())), 0)
        right = min(int(np.ceil(points[:, 0].max())), width - 1)
        top = max(int(np.floor(points[:, 1].min())), 0)
        bottom = min(int(np.ceil(points[:, 1].max())), height - 1)
        if right <= left or bottom <= top:
            return 0.0
        mask = np.zeros((bottom - top + 1, right - left + 1), dtype=np.uint8)
        shifted = points - np.asarray([left, top], dtype=np.float32)
        cv2.fillPoly(mask, [shifted.astype(np.int32)], 1)
        return float(cv2.mean(probability[top:bottom + 1, left:right + 1], mask)[0])

    def _detect(self, image, check, coverage, max_side):
        import cv2
        import numpy as np
        import pyclipper

        session = self._session("det")
        check()
        height, width = image.shape[:2]
        scale = min(1.0, max_side / max(height, width))
        rh = max(32, int(round(height * scale / 32) * 32))
        rw = max(32, int(round(width * scale / 32) * 32))
        coverage["detector_size"] = [rw, rh]
        coverage["detector_resized"] = [rw, rh] != [width, height]
        normalized = cv2.resize(image, (rw, rh)).astype(np.float32) / 255.0
        normalized -= np.asarray([0.485, 0.456, 0.406], dtype=np.float32)
        normalized /= np.asarray([0.229, 0.224, 0.225], dtype=np.float32)
        tensor = np.ascontiguousarray(normalized.transpose(2, 0, 1)[None])
        probability = session.run(None, {session.get_inputs()[0].name: tensor})[0][0, 0]
        check()
        config = self._det_config
        bitmap = (probability > float(config["thresh"])).astype(np.uint8) * 255
        contours, _ = cv2.findContours(bitmap, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        coverage["contours"] = len(contours)
        limit = min(int(config["max_candidates"]), 3000)
        coverage["contour_limit_reached"] = len(contours) > limit
        coverage["contours_examined"] = 0
        results = []
        for contour in contours[:limit]:
            check()
            coverage["contours_examined"] += 1
            rectangle = cv2.minAreaRect(contour)
            if min(rectangle[1]) < 3:
                continue
            points = _ordered_points(cv2.boxPoints(rectangle))
            score = self._box_score(probability, points)
            if score < float(config["box_thresh"]):
                continue
            area = abs(float(cv2.contourArea(points)))
            perimeter = float(cv2.arcLength(points, True))
            if area <= 0 or perimeter <= 0:
                continue
            clipper = pyclipper.PyclipperOffset()
            clipper.AddPath(points.astype(np.int32).tolist(), pyclipper.JT_ROUND,
                            pyclipper.ET_CLOSEDPOLYGON)
            expanded = clipper.Execute(area * float(config["unclip_ratio"]) / perimeter)
            if len(expanded) != 1:
                continue
            rectangle = cv2.minAreaRect(np.asarray(expanded[0], dtype=np.float32))
            if min(rectangle[1]) < 5:
                continue
            points = _ordered_points(cv2.boxPoints(rectangle))
            points[:, 0] = (points[:, 0] * width / rw).clip(0, width - 1)
            points[:, 1] = (points[:, 1] * height / rh).clip(0, height - 1)
            results.append((points, score))
        coverage["detection_complete"] = not coverage["contour_limit_reached"]
        # Confidence ranks candidate work, never establishes correctness/authority.
        results.sort(key=lambda item: (-item[1], float(item[0][:, 1].min()),
                                      float(item[0][:, 0].min())))
        return results

    @staticmethod
    def _crop(image, points):
        import cv2
        import numpy as np

        points = _ordered_points(points)
        width = max(int(np.linalg.norm(points[0] - points[1])),
                    int(np.linalg.norm(points[2] - points[3])), 1)
        height = max(int(np.linalg.norm(points[0] - points[3])),
                     int(np.linalg.norm(points[1] - points[2])), 1)
        destination = np.asarray([[0, 0], [width - 1, 0],
                                  [width - 1, height - 1], [0, height - 1]], dtype=np.float32)
        matrix = cv2.getPerspectiveTransform(points.astype(np.float32), destination)
        crop = cv2.warpPerspective(image, matrix, (width, height),
                                   borderMode=cv2.BORDER_REPLICATE)
        return np.rot90(crop) if height / max(width, 1) >= 1.5 else crop

    def _recognize(self, crop, check):
        import cv2
        import numpy as np

        session = self._session("rec")
        check()
        width = max(160, math.ceil(48 * crop.shape[1] / crop.shape[0]))
        if width > 2048:
            return None  # Explicitly omit overlong lines; never squash their text.
        resized_width = max(1, math.ceil(48 * crop.shape[1] / crop.shape[0]))
        resized = cv2.resize(crop, (resized_width, 48)).astype(np.float32)
        tensor = np.zeros((1, 3, 48, width), dtype=np.float32)
        tensor[0, :, :, :resized_width] = (resized.transpose(2, 0, 1) / 255.0 - 0.5) / 0.5
        sequence = session.run(None, {session.get_inputs()[0].name: tensor})[0][0]
        check()
        indices, scores = sequence.argmax(axis=1), sequence.max(axis=1)
        selected, selected_scores = [], []
        previous = -1
        for class_id, score in zip(indices.tolist(), scores.tolist(), strict=True):
            if class_id != 0 and class_id != previous:
                selected.append(self._characters[class_id])
                selected_scores.append(float(score))
            previous = class_id
        return "".join(selected), (sum(selected_scores) / len(selected_scores) if selected_scores else 0.0)

    def read(self, png: bytes, *, source: Mapping[str, object],
             roi: tuple[int, int, int, int] | None = None,
             recognition_only: bool = False, max_regions: int = 12,
             detector_max_side: int = 1280, deadline: float | None = None,
             cancelled: Callable[[], bool] | None = None) -> dict:
        """ROI is [left, top, right, bottom) in input PNG native pixels.

        Recognition-only asserts the ROI is one text row; it does no detection.
        `source` is the caller's JSON metadata, echoed without trust or authority.
        Output boxes are native pixels in that exact PNG, with right/bottom
        exclusive for bounds. Quads are native sample coordinates. No minimum
        confidence gate is claimed to make text true. Sessions remain warm.
        """
        if not isinstance(png, bytes) or not 0 < len(png) <= 32 * 1024 * 1024:
            raise ValueError("OCR requires PNG bytes bounded to 32 MiB")
        if type(max_regions) is not int or not 1 <= max_regions <= 128:
            raise ValueError("OCR region limit must be 1..128")
        if type(detector_max_side) is not int or not 320 <= detector_max_side <= 1920:
            raise ValueError("OCR detector side must be 320..1920")
        if deadline is not None and (not math.isfinite(deadline)):
            raise ValueError("OCR deadline must be finite monotonic time")
        metadata = json.dumps(dict(source), allow_nan=False)
        if len(metadata.encode()) > 8192:
            raise ValueError("OCR source metadata exceeds 8 KiB")
        if not self._lock.acquire(blocking=False):
            raise OCRBusy("OCR is already in use")
        started = time.monotonic()
        coverage = {"detection_complete": False, "recognition_complete": False,
                    "semantic_text_coverage": "unknown",
                    "contour_limit_reached": False, "candidates": None,
                    "recognized": 0, "omitted": None, "overlong_lines": 0,
                    "ranking": "detection_confidence_descending"}
        result = {"model": "PP-OCRv6-small-cpu", "source": json.loads(metadata),
                  "image_size": None, "roi": None, "regions": [],
                  "coverage": coverage, "partial": True, "stop_reason": None,
                  "action_authorized": False, "confidence_calibrated": False}
        check = lambda: self._check(deadline, cancelled)
        try:
            check()
            import cv2
            import numpy as np
            from PIL import Image

            with Image.open(io.BytesIO(png)) as header:
                if header.format != "PNG":
                    raise ValueError("OCR requires PNG bytes")
                width, height = header.size
            if max(width, height) > 8192 or width * height > 24_000_000:
                raise ValueError("OCR image exceeds bounded native dimensions")
            if roi is None:
                roi = (0, 0, width, height)
            if (len(roi) != 4 or any(type(v) is not int for v in roi)
                    or not 0 <= roi[0] < roi[2] <= width
                    or not 0 <= roi[1] < roi[3] <= height):
                raise ValueError("OCR ROI must be native integer bounds inside PNG")
            result["image_size"], result["roi"] = [width, height], list(roi)
            image = cv2.imdecode(np.frombuffer(png, dtype=np.uint8), cv2.IMREAD_COLOR)
            if image is None:
                raise ValueError("OCR PNG decode failed")
            image = image[roi[1]:roi[3], roi[0]:roi[2]]
            check()
            if recognition_only:
                h, w = image.shape[:2]
                candidates = [(np.asarray([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]],
                                           dtype=np.float32), None)]
                coverage.update(detection_complete=True, ranking="supplied_single_row")
            else:
                candidates = self._detect(image, check, coverage, detector_max_side)
            coverage["candidates"] = len(candidates)
            coverage["omitted"] = len(candidates)
            for points, detection_confidence in candidates[:max_regions]:
                check()
                crop = image if recognition_only else self._crop(image, points)
                recognized = self._recognize(crop, check)
                if recognized is None:
                    coverage["overlong_lines"] += 1
                    continue
                text, confidence = recognized
                native = points + np.asarray([roi[0], roi[1]], dtype=np.float32)
                bounds = ([roi[0], roi[1], roi[2], roi[3]] if recognition_only else
                          [max(roi[0], math.floor(float(native[:, 0].min()))),
                           max(roi[1], math.floor(float(native[:, 1].min()))),
                           min(roi[2], math.ceil(float(native[:, 0].max())) + 1),
                           min(roi[3], math.ceil(float(native[:, 1].max())) + 1)])
                result["regions"].append({"text": text, "bounds": bounds,
                                          "quadrilateral": native.tolist(),
                                          "confidence": confidence,
                                          "detection_confidence": detection_confidence})
                coverage["recognized"] += 1
                coverage["omitted"] -= 1
            check()
            coverage["recognition_complete"] = coverage["omitted"] == 0
            result["partial"] = not (coverage["detection_complete"] and coverage["recognition_complete"])
            result["stop_reason"] = ("overlong_line" if coverage["overlong_lines"] else
                                     "region_limit" if coverage["omitted"] else
                                     "contour_limit" if coverage["contour_limit_reached"] else None)
        except _Deadline:
            result["stop_reason"] = "deadline"
        finally:
            self._lock.release()
        result["elapsed_ms"] = round((time.monotonic() - started) * 1000, 1)
        return result

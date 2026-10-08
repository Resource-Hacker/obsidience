"""On-demand, in-memory capture of the owner's selected physical camera.

Requires the saved media selection, Linux V4L2/sysfs and installed ffmpeg.
This owner acquires only video and drains its one child before releasing capture.
"""

from __future__ import annotations

import asyncio
import re
import stat
import struct
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from obsidience.harness.realtime import media

MAX_CAPTURE_BYTES = 8 * 1024 * 1024
CAPTURE_TIMEOUT_SECONDS = 8
_CAPTURE_LOCK = asyncio.Lock()


class CameraCaptureError(ValueError):
    def __init__(self, message: str, *, code: str = "camera_unavailable") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class CameraCapture:
    image_png: bytes
    name: str
    width: int
    height: int
    captured_at_unix_ns: int
    recognition: dict | None = None


def _selected() -> tuple[str, str, tuple[object, ...]]:
    selection = media.settings()["camera"]
    if not isinstance(selection, str) or re.fullmatch(r"v4l2:/dev/video\d+", selection) is None:
        raise CameraCaptureError("Select an available physical camera in AI & Voice settings.")
    device = Path(selection.removeprefix("v4l2:"))
    entry = Path("/sys/class/video4linux") / device.name
    try:
        node = device.stat()
        physical = entry.resolve(strict=True)
        identity = physical.stat()
        name = (entry / "name").read_text(encoding="utf-8").strip()
        if (device.resolve(strict=True) != device or not stat.S_ISCHR(node.st_mode)
                or "/devices/virtual/" in str(physical)):
            raise CameraCaptureError("The selected device is not a physical camera.")
    except (OSError, UnicodeDecodeError) as exc:
        raise CameraCaptureError("The selected physical camera is unavailable.") from exc
    return str(device), name[:200] or device.name, (
        selection, node.st_dev, node.st_ino, node.st_rdev,
        str(physical), identity.st_dev, identity.st_ino, name,
    )


def _check_cancel(cancel_event: Any) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise asyncio.CancelledError


async def _read_bounded(stream: asyncio.StreamReader, maximum: int) -> bytes:
    result = bytearray()
    while chunk := await stream.read(min(65536, maximum + 1 - len(result))):
        result.extend(chunk)
        if len(result) > maximum:
            raise CameraCaptureError("Camera capture exceeded its output bound.")
    return bytes(result)


async def _join(task: asyncio.Task) -> None:
    """Drain owned cleanup even if another STOP arrives while it is running."""
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
    task.result()
    if cancelled:
        raise asyncio.CancelledError


async def wake_selected_camera(*, cancel_event: Any = None) -> None:
    """Explicit wake through the existing owner; ordinary capture stays read-only.

    SDK/motor preparation has its own bounded native waits. Drain it even on
    cancellation before releasing the selected-device operation; image capture
    then has its separate eight-second freshness budget.
    """
    async with _CAPTURE_LOCK:
        _check_cancel(cancel_event)
        device, _name, identity = _selected()
        physical = Path("/sys/class/video4linux") / Path(device).name / "device"
        usb = physical.resolve().parent
        try:
            selected_obsbot = ((usb / "idVendor").read_text().strip() == "3564"
                              and (usb / "idProduct").read_text().strip() == "fef9")
        except OSError:
            selected_obsbot = False
        if not selected_obsbot:
            raise CameraCaptureError("Wake is supported only for the selected OBSBOT Tiny 2 Lite.")
        from . import tracking
        current = await asyncio.to_thread(tracking.snapshot)
        if current.get("state") == "running" and current.get("fresh"):
            return
        _check_cancel(cancel_event)
        preparation = asyncio.create_task(asyncio.to_thread(media.set_obsbot_camera_active, True))
        try:
            await _join(preparation)
        except RuntimeError as exc:
            raise CameraCaptureError(f"Camera wake could not be verified: {exc}") from exc
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise CameraCaptureError("The native camera wake failed or timed out; delivery is unverified.") from exc
        _check_cancel(cancel_event)
        if _selected()[2] != identity:
            raise CameraCaptureError("The selected camera changed during wake.", code="camera_changed")


async def _capture(cancel_event: Any) -> CameraCapture:
    async with _CAPTURE_LOCK:
        _check_cancel(cancel_event)
        device, name, identity = _selected()
        from . import tracking
        tracking_state = await asyncio.to_thread(tracking.snapshot)
        if tracking_state.get("enabled"):
            # The existing media lease owns one persistent video stream while
            # owner tracking is enabled. Never compete with it for V4L2.
            frame = await asyncio.to_thread(tracking.frame)
            while frame is None:
                _check_cancel(cancel_event)
                tracking_state = await asyncio.to_thread(tracking.snapshot)
                if tracking_state.get("state") not in {"starting", "running"}:
                    reason = tracking_state.get("error") or tracking_state.get("state", "unavailable")
                    raise CameraCaptureError(
                        f"Owner camera tracking is {reason}. Use wake:true for a requested camera wake or recovery.")
                # Wait for actual fresh pixels, not a fixed startup delay.
                # The surrounding capture deadline and STOP remain authoritative.
                await asyncio.sleep(.05)
                frame = await asyncio.to_thread(tracking.frame)
            pixels, captured_at, captured_mono, frame_identity, recognition = frame
            if frame_identity != identity:
                raise CameraCaptureError("The selected camera changed.", code="camera_changed")
            def encode() -> bytes:
                import cv2
                ok, encoded = cv2.imencode(".png", pixels)
                if not ok:
                    raise CameraCaptureError("The camera frame could not be encoded.")
                return encoded.tobytes()
            image = await asyncio.to_thread(encode)
            _check_cancel(cancel_event)
            if _selected()[2] != identity or time.monotonic() - captured_mono > .75:
                raise CameraCaptureError("The camera frame changed or expired during capture.")
            if len(image) > MAX_CAPTURE_BYTES:
                raise CameraCaptureError("Camera capture exceeded its output bound.")
            return CameraCapture(image, name, pixels.shape[1], pixels.shape[0], captured_at,
                                 {**recognition, "authentication": False})
        spawn = asyncio.create_task(asyncio.create_subprocess_exec(
            "/usr/bin/ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
            # Stream startup can deliver a partial MJPEG packet. Reject it
            # instead of letting the decoder conceal missing rows as green.
            "-fflags", "+discardcorrupt", "-err_detect", "explode",
            "-f", "video4linux2", "-input_format", "mjpeg", "-video_size", "1280x720",
            "-framerate", "30", "-i", device, "-frames:v", "1", "-an",
            "-threads", "1", "-f", "image2pipe", "-vcodec", "png", "pipe:1",
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        ))
        readers: list[asyncio.Task] = []

        async def cleanup() -> None:
            # Shielded creation lets cleanup recover the exact child if STOP
            # interrupts process creation before its handle reaches this scope.
            try:
                child = await spawn
            except OSError:
                return
            if child.returncode is None:
                try:
                    child.kill()
                except ProcessLookupError:
                    pass
            for reader in readers:
                reader.cancel()
            await asyncio.gather(*readers, return_exceptions=True)
            # Drain the killed child's pipe tail too: Process.wait alone can
            # wait on an unread full pipe even after the native process exited.
            await child.communicate()

        try:
            child = await asyncio.shield(spawn)
            _check_cancel(cancel_event)
            assert child.stdout is not None and child.stderr is not None
            readers = [
                asyncio.create_task(_read_bounded(child.stdout, MAX_CAPTURE_BYTES)),
                asyncio.create_task(_read_bounded(child.stderr, 16384)),
            ]
            image, errors = await asyncio.gather(*readers)
            captured_at = time.time_ns()
            await child.wait()
            _check_cancel(cancel_event)
            if child.returncode:
                busy = b"busy" in errors.lower()
                raise CameraCaptureError(
                    "The selected camera is busy." if busy else "The selected camera could not supply a frame.",
                    code="camera_busy" if busy else "camera_unavailable",
                )
            if _selected()[2] != identity:
                raise CameraCaptureError("The selected camera changed during capture.", code="camera_changed")
            if (len(image) < 45 or not image.startswith(b"\x89PNG\r\n\x1a\n")
                    or image[8:16] != b"\x00\x00\x00\rIHDR"
                    or not image.endswith(b"\x00\x00\x00\x00IEND\xaeB`\x82")):
                raise CameraCaptureError("Camera capture did not return a complete PNG.")
            width, height = struct.unpack(">II", image[16:24])
            if not (0 < width <= 1280 and 0 < height <= 720):
                raise CameraCaptureError("Camera image dimensions exceeded their bound.")
            return CameraCapture(image, name, width, height, captured_at)
        except OSError as exc:
            raise CameraCaptureError("The native camera capture dependency is unavailable.") from exc
        finally:
            await _join(asyncio.create_task(cleanup()))


async def capture_selected_camera(*, cancel_event: Any = None) -> CameraCapture:
    """Capture once, without waking hardware, choosing alternatives or saving video."""
    _check_cancel(cancel_event)
    task = asyncio.create_task(_capture(cancel_event))
    try:
        async with asyncio.timeout(CAPTURE_TIMEOUT_SECONDS):
            while not task.done():
                _check_cancel(cancel_event)
                await asyncio.wait({task}, timeout=0.05)
            _check_cancel(cancel_event)
            return task.result()
    except TimeoutError as exc:
        raise CameraCaptureError("The selected camera capture timed out.", code="camera_timeout") from exc
    finally:
        if not task.done():
            task.cancel()
        # _capture owns native cleanup; never leave its child holding V4L2.
        async def drain() -> None:
            await asyncio.gather(task, return_exceptions=True)
        await _join(asyncio.create_task(drain()))

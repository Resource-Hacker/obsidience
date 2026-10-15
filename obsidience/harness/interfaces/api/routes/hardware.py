"""Physical compute, audio endpoints, camera and input devices."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from obsidience.shell.adapter.hyprland import input as input_adapter

from ....host import monitor
from ....models import runtime as model_runtime
from ....realtime import devices
from ....realtime import runtime as realtime

router = APIRouter()


@router.get("/api/hardware")
def hardware():
    """Physical compute, audio endpoints, and preferred camera."""
    return {
        **model_runtime.hardware_catalog(),
        **model_runtime.settings(),
        "interfaces": devices.interface_catalog(),
        "speech": devices.speech_runtime(),
    }


@router.get("/api/hardware/monitor")
def hardware_monitor():
    """Bounded read-only measurements shared by visible Hardware panes."""
    return monitor.snapshot()


@router.get("/api/input")
def input_state():
    """Live mouse and keyboard state from the compositor adapter."""
    return input_adapter.input_snapshot()


@router.patch("/api/hardware")
async def update_hardware(payload: dict):
    try:
        await model_runtime.set_hardware(payload.get("device"), payload.get("component"))
        return {
            **model_runtime.hardware_catalog(),
            **model_runtime.settings(),
            "interfaces": devices.interface_catalog(),
            "speech": devices.speech_runtime(),
        }
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.patch("/api/hardware/interfaces")
def update_hardware_interface(payload: dict):
    """Persist one exact audio endpoint or preferred physical camera."""

    try:
        devices.set_interface(payload.get("interface"), payload.get("selection"))
        return {
            **model_runtime.hardware_catalog(),
            **model_runtime.settings(),
            "interfaces": devices.interface_catalog(),
            "speech": devices.speech_runtime(),
        }
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.patch("/api/hardware/voice")
def update_voice(payload: dict):
    """Select the Pocket character voice; the speech engine itself is fixed."""
    try:
        return devices.set_voice(payload.get("voice"))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/api/hardware/camera")
def hardware_camera():
    """Return the physical OBSBOT camera power state."""

    try:
        return devices.obsbot_camera_state()
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc


@router.post("/api/hardware/camera")
def update_hardware_camera(payload: dict):
    """Power the physical OBSBOT camera without creating a video pipeline."""

    active = payload.get("active")
    if active is False and realtime.RUNTIME.snapshot()["enabled"]:
        raise HTTPException(409, "Realtime owns the camera while it is active")
    try:
        return devices.set_obsbot_camera_active(active)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc


@router.get("/api/hardware/camera/tracking")
def camera_tracking_status():
    from ....realtime import tracking
    return tracking.snapshot()


@router.get("/api/hardware/camera/frame")
async def camera_owner_frame():
    """One private, uncached owner preview through the same capture boundary."""
    from ....realtime.camera import CameraCaptureError, capture_selected_camera
    try:
        frame = await capture_selected_camera()
    except CameraCaptureError as error:
        raise HTTPException(503, str(error)) from error
    return Response(frame.image_png, media_type="image/png", headers={
        "Cache-Control": "no-store", "X-Captured-At-Ns": str(frame.captured_at_unix_ns),
        "X-Camera-Recognition": json.dumps(frame.recognition, separators=(",", ":")),
    })


@router.post("/api/hardware/camera/tracking/enroll")
def camera_owner_enroll():
    """Explicit local owner enrollment; never a model-exposed Tool."""
    from ....realtime import tracking
    try:
        return tracking.enroll()
    except ValueError as error:
        raise HTTPException(409, str(error)) from error

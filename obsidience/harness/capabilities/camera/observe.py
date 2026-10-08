"""Observe the saved physical camera without desktop input authority."""

from __future__ import annotations

import asyncio
from typing import Any

from obsidience.harness.realtime.camera import CameraCaptureError, capture_selected_camera, wake_selected_camera


async def execute(args: dict, context: dict) -> dict[str, Any]:
    cancel = context.get("_capability_cancel_event")
    if cancel is not None and cancel.is_set():
        raise asyncio.CancelledError
    query = args.get("query") if isinstance(args, dict) else None
    if (not isinstance(args, dict) or set(args) - {"query", "wake"}
            or not isinstance(query, str) or not query.strip()
            or ("wake" in args and type(args["wake"]) is not bool)
            or not 1 <= len(query) <= 500 or not query.isprintable()):
        return {"observation": {
            "status": "unavailable", "action_authorized": False,
            "failure": {"code": "observation_failed", "message":
                "camera.observe requires query with 1-500 printable characters and optional boolean wake.", "retryable": False},
        }}
    try:
        if args.get("wake") is True:
            await wake_selected_camera(cancel_event=cancel)
        capture = await capture_selected_camera(cancel_event=cancel)
    except CameraCaptureError as error:
        return {"observation": {
            "status": "unavailable", "action_authorized": False,
            "failure": {"code": error.code, "message": str(error),
                        "retryable": args.get("wake") is not True},
            **({"must_not_replay": True} if args.get("wake") is True else {}),
        }}
    if cancel is not None and cancel.is_set():
        raise asyncio.CancelledError
    return {"observation": {
        "status": "observed", "source_kind": "camera", "name": capture.name,
        "target": {"kind": "camera", "name": capture.name}, "query": query,
        "captured_at_unix_ns": capture.captured_at_unix_ns,
        "width": capture.width, "height": capture.height,
        "size_bytes": len(capture.image_png), "action_authorized": False,
        "recognition": capture.recognition,
        "wake_requested": args.get("wake") is True,
        "visual_evidence": {"attached": True, "media_type": "image/png",
            "freshness": "validated_after_capture", "content_role": "untrusted_visual_evidence"},
    }, "_private_image_png": capture.image_png}

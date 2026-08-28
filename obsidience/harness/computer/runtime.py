"""Bounded computer observation and one-action execution.

The model supplies an application and a semantic target.  Obsidience keeps
window identities, coordinates, image descriptors, and single-use CUA tokens
inside this module.
"""

from __future__ import annotations

import array
import base64
import fcntl
import io
import json
import os
import socket
import stat
import struct
import uuid
from typing import Any

import cbor2
from PIL import Image


OBSERVATION_SOCKET = "/run/user/1000/jarvis-observation.sock"
CUA_SOCKET = "/run/user/1000/jarvis-cua-driver/cua.sock"
_HEADER = struct.Struct(">I")
_MAX_MESSAGE = 16 * 1024 * 1024
_MAX_FRAME = 32 * 1024 * 1024
_F_GET_SEALS = getattr(fcntl, "F_GET_SEALS", 1034)
_REQUIRED_SEALS = sum(
    getattr(fcntl, name, value)
    for name, value in (
        ("F_SEAL_SEAL", 0x0001),
        ("F_SEAL_SHRINK", 0x0002),
        ("F_SEAL_GROW", 0x0004),
        ("F_SEAL_WRITE", 0x0008),
    )
)
_ALIASES = {
    "battle.net": "battle_net",
    "battlenet": "battle_net",
    "edge": "microsoft_edge",
    "microsoft edge": "microsoft_edge",
    "teamfight tactics": "teamfight_tactics",
    "tft": "teamfight_tactics",
    "world of warcraft": "world_of_warcraft",
    "wow": "world_of_warcraft",
}


class ComputerError(ValueError):
    """A fail-closed computer-use rejection suitable for a Tool observation."""


def _positive_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _rect(value: Any) -> dict[str, int] | None:
    if not isinstance(value, dict) or set(value) != {"x", "y", "width", "height"}:
        return None
    if not all(isinstance(value[key], int) and not isinstance(value[key], bool) for key in value):
        return None
    if value["width"] < 1 or value["height"] < 1:
        return None
    return {key: int(value[key]) for key in ("x", "y", "width", "height")}


def _bounded_text(value: Any, field: str, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if not text or len(text) > limit:
        raise ComputerError(f"{field} must contain 1-{limit} characters")
    return text


def _recv_exact(connection: socket.socket, length: int) -> bytes:
    chunks: list[bytes] = []
    while length:
        chunk = connection.recv(length)
        if not chunk:
            raise ComputerError("observation service closed an incomplete response")
        chunks.append(chunk)
        length -= len(chunk)
    return b"".join(chunks)


def _observation_call(
    request: dict[str, Any], *, allow_descriptor: bool = False, timeout: float = 30.0,
) -> tuple[dict[str, Any], int | None]:
    payload = cbor2.dumps(request, canonical=True)
    if not 0 < len(payload) <= _MAX_MESSAGE:
        raise ComputerError("observation request exceeded its transport bound")
    descriptors: list[int] = []
    descriptor: int | None = None
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM | socket.SOCK_CLOEXEC) as connection:
        connection.settimeout(timeout)
        connection.connect(OBSERVATION_SOCKET)
        connection.sendall(_HEADER.pack(len(payload)) + payload)
        initial, ancillary, flags, _address = connection.recvmsg(
            _HEADER.size + _MAX_MESSAGE,
            socket.CMSG_SPACE(array.array("i").itemsize),
        )
        for level, kind, data in ancillary:
            if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
                received = array.array("i")
                usable = len(data) - len(data) % received.itemsize
                received.frombytes(data[:usable])
                descriptors.extend(received.tolist())
        try:
            if flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC) or len(descriptors) > 1:
                raise ComputerError("observation response was truncated or malformed")
            if len(initial) < _HEADER.size:
                raise ComputerError("observation service returned an incomplete header")
            (length,) = _HEADER.unpack(initial[: _HEADER.size])
            if not 0 < length <= _MAX_MESSAGE:
                raise ComputerError("observation response exceeded its transport bound")
            body = bytearray(initial[_HEADER.size :])
            if len(body) > length:
                raise ComputerError("observation response contained trailing bytes")
            if len(body) < length:
                body.extend(_recv_exact(connection, length - len(body)))
            descriptor = descriptors.pop() if descriptors else None
        finally:
            for extra in descriptors:
                os.close(extra)
    try:
        if descriptor is not None and not allow_descriptor:
            raise ComputerError("observation returned an unexpected image descriptor")
        response = cbor2.loads(bytes(body))
        if (
            not isinstance(response, dict)
            or cbor2.dumps(response, canonical=True) != bytes(body)
            or response.get("request_id") != request.get("request_id")
        ):
            raise ComputerError("observation returned a mismatched response")
        if response.get("status") != "ok":
            raise ComputerError(
                f"{response.get('error_code', 'observation_failed')}: "
                f"{response.get('error', 'structured observation failed')}"
            )
        result = response.get("result")
        if not isinstance(result, dict):
            raise ComputerError("observation returned no structured result")
        return result, descriptor
    except BaseException:
        if descriptor is not None:
            os.close(descriptor)
        raise


def _cua_call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    request = {
        "method": "call",
        "name": name,
        "args": args,
        "observation_origin": "direct",
        "client_kind": "unknown",
    }
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM | socket.SOCK_CLOEXEC) as connection:
        connection.settimeout(10.0)
        connection.connect(CUA_SOCKET)
        connection.sendall((json.dumps(request, separators=(",", ":")) + "\n").encode())
        with connection.makefile("rb") as stream:
            line = stream.readline(_MAX_MESSAGE + 1)
    if not line or len(line) > _MAX_MESSAGE:
        raise ComputerError("CUA returned no bounded response")
    response = json.loads(line)
    if not isinstance(response, dict) or response.get("ok") is not True:
        raise ComputerError(str(response.get("error", "CUA request failed"))[:500])
    result = response.get("result")
    if not isinstance(result, dict):
        raise ComputerError("CUA returned no Tool result")
    return result


def _structured(result: dict[str, Any], operation: str) -> dict[str, Any]:
    if result.get("isError") is True:
        content = result.get("content") or []
        detail = content[0].get("text") if content and isinstance(content[0], dict) else "failed"
        raise ComputerError(f"{operation} failed: {str(detail)[:500]}")
    structured = result.get("structuredContent")
    if not isinstance(structured, dict):
        raise ComputerError(f"{operation} returned no structured result")
    return structured


def _application_needles(application: str) -> tuple[str, ...]:
    from .applications import APPLICATIONS

    key = _ALIASES.get(application.casefold(), application.casefold().replace(" ", "_"))
    spec = APPLICATIONS.get(key)
    if spec:
        return tuple(str(item).casefold() for item in spec["window_needles"])
    return (application.casefold(),)


def _window_row(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    bounds = _rect(raw.get("capture_bounds"))
    pid = _positive_int(raw.get("pid"))
    window_id = _positive_int(raw.get("window_id"))
    generation = _positive_int(raw.get("interrupt_generation"))
    internal_id = raw.get("internal_id")
    token = raw.get("target_token")
    if not all((bounds, pid, window_id, generation, internal_id, token)):
        return None
    return {
        "pid": pid,
        "window_id": window_id,
        "internal_id": str(internal_id),
        "capture_bounds": bounds,
        "interrupt_generation": generation,
        "target_token": str(token),
        "app_name": str(raw.get("app_name") or ""),
        "title": str(raw.get("title") or ""),
    }


def _windows() -> list[dict[str, Any]]:
    structured = _structured(_cua_call("list_windows", {"on_screen_only": True}), "list_windows")
    return [row for raw in structured.get("windows", []) if (row := _window_row(raw))]


def _resolve_exact_window(application: str) -> dict[str, Any]:
    needles = _application_needles(application)
    matches = [
        row for row in _windows()
        if any(needle in f"{row['app_name']} {row['title']}".casefold() for needle in needles)
    ]
    if not matches:
        raise ComputerError(f"no on-screen window matches {application}")
    if len(matches) != 1:
        raise ComputerError(f"{application} matches {len(matches)} on-screen windows; target is ambiguous")
    return matches[0]


def _read_frame(metadata: Any, descriptor: int) -> tuple[bytes, int, int]:
    if not isinstance(metadata, dict) or set(metadata) != {
        "pixel_format", "width", "height", "payload_bytes", "frame",
    }:
        raise ComputerError("visual observation omitted exact image metadata")
    width, height, size = metadata.get("width"), metadata.get("height"), metadata.get("payload_bytes")
    if (
        metadata.get("pixel_format") != "RGB8"
        or _positive_int(width) is None
        or _positive_int(height) is None
        or _positive_int(size) is None
        or width > 4096
        or height > 4096
        or size != width * height * 3
        or size > _MAX_FRAME
    ):
        raise ComputerError("visual observation returned invalid RGB8 dimensions")
    info = os.fstat(descriptor)
    if not stat.S_ISREG(info.st_mode) or info.st_size != size or info.st_nlink != 0:
        raise ComputerError("visual observation descriptor was not an exact anonymous frame")
    if fcntl.fcntl(descriptor, _F_GET_SEALS) & _REQUIRED_SEALS != _REQUIRED_SEALS:
        raise ComputerError("visual observation frame lacked immutable seals")
    chunks, offset = [], 0
    while offset < size:
        chunk = os.pread(descriptor, min(1024 * 1024, size - offset), offset)
        if not chunk:
            raise ComputerError("visual observation frame ended early")
        chunks.append(chunk)
        offset += len(chunk)
    return b"".join(chunks), width, height


def _observe_exact(row: dict[str, Any], query: str, *, required: bool) -> dict[str, Any]:
    result, descriptor = _observation_call(
        {
            "version": 1,
            "request_id": f"obsidience-{uuid.uuid4().hex}",
            "op": "observe",
            "target": {
                "app": row["app_name"] or None,
                "pid": row["pid"],
                "internal_id": row["internal_id"],
            },
            "query": query,
            "visual_policy": "required" if required else "fallback",
            "cdp_profile": None,
            "dbus_profiles": [],
            "cli_profiles": [],
        },
        allow_descriptor=required,
        timeout=30.0 if required else 12.0,
    )
    try:
        observation = result.get("observation")
        window = observation.get("window") if isinstance(observation, dict) else None
        if not isinstance(window, dict):
            raise ComputerError("structured observation returned no exact window")
        if window.get("pid") != row["pid"] or window.get("internal_id") != row["internal_id"]:
            raise ComputerError("structured observation resolved a different window")
        if _rect(window.get("visible")) != row["capture_bounds"]:
            raise ComputerError("observation and CUA geometry disagree")
        observation_id = observation.get("observation_id")
        if not isinstance(observation_id, str) or not observation_id:
            raise ComputerError("structured observation returned no immutable ID")
        image = None
        if required:
            if descriptor is None:
                raise ComputerError("visual observation returned no image descriptor")
            image = _read_frame(result.get("visual_image"), descriptor)
        return {"result": result, "observation": observation, "image": image}
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _label(element: dict[str, Any]) -> str:
    return next(
        (" ".join(str(element.get(key) or "").split()) for key in ("name", "value", "description") if str(element.get(key) or "").strip()),
        "",
    )


def _public_observation(observed: dict[str, Any], application: str, query: str) -> dict[str, Any]:
    observation = observed["observation"]
    elements = []
    for raw in observation.get("elements", []):
        if not isinstance(raw, dict) or raw.get("coordinate_attested") is not True:
            continue
        label = _label(raw)
        if not label or _rect(raw.get("bounds")) is None:
            continue
        elements.append({
            "element": len(elements) + 1,
            "role": str(raw.get("role") or ""),
            "label": label[:240],
            "interactable": raw.get("interactable") is True,
            "source": str(raw.get("source") or ""),
        })
        if len(elements) == 60:
            break
    grounding = observed["result"].get("grounding") or {}
    return {
        "application": application,
        "window": str(observation["window"].get("title") or "")[:240],
        "query": query,
        "elements": elements,
        "grounding": {
            "matched": bool(grounding.get("selected_token")),
            "ambiguous": grounding.get("ambiguity") is True,
            "candidate_count": len(grounding.get("candidates") or []),
        },
        "action_authorized": False,
    }


def observe_computer(args: dict[str, Any]) -> dict[str, Any]:
    if set(args) - {"application", "query"}:
        raise ComputerError("computer.observe accepts only application and query")
    application = _bounded_text(args.get("application"), "application", 200)
    query = _bounded_text(args.get("query"), "query", 500)
    row = _resolve_exact_window(application)
    return _public_observation(_observe_exact(row, query, required=False), application, query)


def _grounded_element(observed: dict[str, Any]) -> tuple[dict[str, int], str]:
    result = observed["result"]
    grounding = result.get("grounding")
    if not isinstance(grounding, dict) or grounding.get("ambiguity") is True:
        raise ComputerError("target grounding is ambiguous")
    candidates = grounding.get("candidates")
    token = grounding.get("selected_token")
    if not isinstance(candidates, list) or len(candidates) != 1 or not isinstance(token, str):
        raise ComputerError("target did not resolve to exactly one visible control")
    matches = [
        raw for raw in observed["observation"].get("elements", [])
        if isinstance(raw, dict) and raw.get("token") == token
    ]
    if len(matches) != 1 or matches[0].get("coordinate_attested") is not True:
        raise ComputerError("grounded target lacks unique coordinate attestation")
    bounds = _rect(matches[0].get("bounds"))
    label = _label(matches[0])
    if bounds is None or not label:
        raise ComputerError("grounded target has no bounded visible label")
    return bounds, label


def _validate_observation(observation_id: str) -> None:
    _result, descriptor = _observation_call(
        {
            "version": 1,
            "request_id": f"obsidience-validate-{uuid.uuid4().hex}",
            "op": "validate",
            "observation_id": observation_id,
        },
        timeout=5.0,
    )
    if descriptor is not None:
        os.close(descriptor)
        raise ComputerError("observation validation returned an image unexpectedly")


def _fresh_exact_row(previous: dict[str, Any]) -> dict[str, Any]:
    matches = [
        row for row in _windows()
        if row["pid"] == previous["pid"]
        and row["window_id"] == previous["window_id"]
        and row["internal_id"] == previous["internal_id"]
    ]
    if len(matches) != 1 or matches[0]["capture_bounds"] != previous["capture_bounds"]:
        raise ComputerError("exact target disappeared or changed geometry")
    return matches[0]


def _visual_witness(
    image: tuple[bytes, int, int], capture: dict[str, int], x: int, y: int,
) -> dict[str, Any]:
    payload, width, height = image
    if (width, height) != (capture["width"], capture["height"]):
        raise ComputerError("visual frame and exact capture dimensions disagree")
    edge_w, edge_h = min(96, width), min(96, height)
    if edge_w < 16 or edge_h < 16 or not (0 <= x < width and 0 <= y < height):
        raise ComputerError("grounded point is outside the exact visual frame")
    roi_x = max(0, min(x - edge_w // 2, width - edge_w))
    roi_y = max(0, min(y - edge_h // 2, height - edge_h))
    image_obj = Image.frombytes("RGB", (width, height), payload)
    crop = image_obj.crop((roi_x, roi_y, roi_x + edge_w, roi_y + edge_h))
    encoded = io.BytesIO()
    crop.save(encoded, format="PNG")
    preimage = encoded.getvalue()
    if not preimage or len(preimage) > 1_048_576:
        raise ComputerError("visual witness exceeded its bound")
    return {
        "roi": {"x": roi_x, "y": roi_y, "width": edge_w, "height": edge_h},
        "preimage_png_base64": base64.b64encode(preimage).decode("ascii"),
    }


def act_computer(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    if set(args) - {"application", "action", "target", "postcondition"}:
        raise ComputerError(
            "computer.act accepts only application, action, target, and postcondition"
        )
    application = _bounded_text(args.get("application"), "application", 200)
    action = str(args.get("action") or "click").strip().casefold()
    if action != "click":
        raise ComputerError("the current bounded computer.act action is click")
    target = _bounded_text(args.get("target"), "target", 300)
    postcondition = " ".join(str(args.get("postcondition") or target).split())[:500]
    if context.get("_computer_act_attempted"):
        raise ComputerError("this Task run already attempted its one computer action")

    initial = _resolve_exact_window(application)
    observed = _observe_exact(initial, target, required=True)
    bounds, label = _grounded_element(observed)
    _validate_observation(observed["observation"]["observation_id"])
    current = _fresh_exact_row(initial)
    local_x = bounds["x"] - current["capture_bounds"]["x"] + bounds["width"] // 2
    local_y = bounds["y"] - current["capture_bounds"]["y"] + bounds["height"] // 2
    witness = _visual_witness(
        observed["image"], current["capture_bounds"], local_x, local_y,
    )

    context["_computer_act_attempted"] = True
    result = _cua_call("click", {
        "pid": current["pid"],
        "window_id": current["window_id"],
        "target_token": current["target_token"],
        "interrupt_generation": current["interrupt_generation"],
        "x": local_x,
        "y": local_y,
        "button": "left",
        "count": 1,
        "delivery_mode": "foreground",
        "visual_witness": witness,
    })
    structured = result.get("structuredContent") if isinstance(result, dict) else None
    acknowledged = (
        result.get("isError") is not True
        and isinstance(structured, dict)
        and structured.get("effect") == "delivery_acknowledged"
    )
    if not acknowledged:
        return {
            "application": application,
            "action": "click",
            "target": label[:240],
            "delivery": "rejected_or_uncertain",
            "must_not_replay": True,
            "task_success": "not established",
        }

    try:
        post = _public_observation(
            _observe_exact(current, postcondition, required=False),
            application,
            postcondition,
        )
    except (ComputerError, OSError, TimeoutError) as exc:
        post = {"available": False, "error": str(exc)[:500], "action_authorized": False}
    return {
        "application": application,
        "action": "click",
        "target": label[:240],
        "delivery": "acknowledged",
        "must_not_replay": True,
        "task_success": "requires evaluation of the fresh post-observation",
        "post_observation": post,
    }

"""Verified Matter light control through the sole native controller owner."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import colorsys
import json
import os
from pathlib import Path
import socket
import threading
import time

FIXTURES = ("window_lamp", "woven_pendant", "north_lamp", "tv_floor_lamp",
            "desk_lantern", "room_lantern")
TARGETS = ("all", *FIXTURES)
_LOCK = threading.Lock()


def _inventory():
    # The controller owns commissioning. These bindings live only for this operation.
    return {name: {} for name in FIXTURES}


def _request(payload, cancel=None, *, timeout=5):
    path = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "obsidience-lights/control.sock"
    deadline = time.monotonic() + timeout
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as peer:
        peer.settimeout(min(timeout, 2))
        peer.connect(str(path))
        if cancel is not None and cancel.is_set():
            raise InterruptedError("Light operation cancelled")
        peer.sendall(json.dumps(payload, separators=(",", ":")).encode() + b"\n")
        material = bytearray()
        while b"\n" not in material:
            if cancel is not None and cancel.is_set():
                raise InterruptedError("Light operation cancelled after possible dispatch")
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Matter light receipt unavailable; delivery may be uncertain")
            peer.settimeout(min(.1, remaining))
            try:
                chunk = peer.recv(8192)
            except socket.timeout:
                continue
            if not chunk:
                raise RuntimeError("Matter controller disconnected; delivery may be uncertain")
            material.extend(chunk)
            if len(material) > 65536:
                raise ValueError("Matter light receipt exceeds bound")
    reply = json.loads(material.split(b"\n", 1)[0])
    if not isinstance(reply, dict) or reply.get("ok") is not True or not isinstance(reply.get("result"), dict):
        raise RuntimeError("Matter controller rejected light operation; do not replay")
    return reply["result"]


def _binding(state):
    node, endpoint = state.get("nodeId"), state.get("endpoint")
    if (not isinstance(node, str) or not node.isdecimal() or int(node) <= 0
            or type(endpoint) is not int or not 1 <= endpoint <= 65534):
        raise ValueError("Matter fixture identity is unavailable")
    return {"nodeId": node, "endpoint": endpoint}


def _read(name, inventory, cancel=None, *, timeout=5):
    state = _request({"command": "read", "target": name,
                      **({"endpoint": inventory[name]["endpoint"]} if inventory[name] else {})}, cancel, timeout=timeout)
    binding = _binding(state)
    if inventory[name] and inventory[name] != binding:
        raise ValueError("Matter fixture identity changed")
    if state.get("fresh") is not True or type(state.get("onOff")) is not bool:
        raise ValueError("Matter power state is unavailable")
    _appearance(state)
    inventory[name].update(binding)
    return state


def _appearance(state):
    level, mode = state.get("currentLevel"), state.get("colorMode")
    if type(level) is not int or not 0 <= level <= 254 or type(mode) is not int:
        raise ValueError("Matter native appearance is unavailable")
    if mode == 0:
        color = {"mode": "hs", "hue": state.get("currentHue"), "saturation": state.get("currentSaturation")}
        fields, maximum = ("hue", "saturation"), 254
    elif mode == 1:
        color = {"mode": "xy", "x": state.get("currentX"), "y": state.get("currentY")}
        fields, maximum = ("x", "y"), 65279
    elif mode == 2:
        color = {"mode": "temperature", "mireds": state.get("colorTemperatureMireds")}
        fields, maximum = ("mireds",), 65279
    else:
        raise ValueError("Matter native color mode is unsupported")
    if any(type(color[k]) is not int or not (1 if k == "mireds" else 0) <= color[k] <= maximum for k in fields):
        raise ValueError("Matter native color attributes are unavailable")
    return {"level": level, "color": color}


def _set(name, inventory, params, cancel=None, *, readback=True, timeout=5):
    if not inventory[name]:
        raise ValueError("Read and bind the Matter fixture before dispatch")
    result = _request({"command": "set", "target": name, **inventory[name], **params,
                       "readback": readback}, cancel, timeout=timeout)
    if result.get("delivery") != "acknowledged" or _binding(result) != inventory[name] or result.get("transitionTime") != 0:
        raise RuntimeError("Matter command receipt did not match its binding or zero transition")
    if readback:
        state = result.get("state")
        if not isinstance(state, dict) or state.get("fresh") is not True or _binding(state) != inventory[name]:
            raise RuntimeError("Matter native readback did not match its binding")
        if "onOff" in params and state.get("onOff") != params["onOff"]:
            raise RuntimeError("Matter native power readback did not match")
        if "level" in params and state.get("currentLevel") != params["level"]:
            raise RuntimeError("Matter native level readback did not match")
        if "color" in params and _appearance(state)["color"] != params["color"]:
            raise RuntimeError("Matter native color readback did not match")
    return result


def _frame(name, inventory, params, cancel=None, *, readback=False):
    hue, saturation, _value = colorsys.rgb_to_hsv(*(params[k]/255 for k in ("r", "g", "b")))
    return _set(name, inventory, {"onOff": bool(params.get("state", True)),
        "level": round(params["dimming"]*254/100),
        "color": {"mode": "hs", "hue": round(hue*254), "saturation": round(saturation*254)}},
        cancel, readback=readback)


def _restore(name, inventory, before):
    # Same controller lane: restoration follows any uncertain in-flight frame.
    return _set(name, inventory, {"onOff": before["onOff"], **_appearance(before)},
                readback=True, timeout=60)["state"]


def execute(args, context):
    if (not isinstance(args, dict) or set(args) != {"target", "state"}
            or args.get("target") not in TARGETS or args.get("state") not in ("on", "off")):
        raise ValueError("lights.set requires an exact target and state on/off")
    if (context.get("_agent_ref") != "Agents/Executive/Executive"
            or context.get("task") != "Agents/Executive/Executive"):
        raise PermissionError("Light control belongs to the Executive conversation")
    from .visualize import power_operation
    with power_operation():
        cancel = context.get("_capability_cancel_event")
        while not _LOCK.acquire(timeout=.1):
            if cancel is not None and cancel.is_set():
                raise InterruptedError("Light operation cancelled")
        try:
            return _execute(args, context)
        finally:
            _LOCK.release()


def _execute(args, context):
    cancel = context.get("_capability_cancel_event")
    names = list(FIXTURES) if args["target"] == "all" else [args["target"]]
    attempted = context.setdefault("_lights_set_attempted_targets", set())
    receipts = context.setdefault("_lights_set_target_receipts", {})
    if any(name in attempted for name in names):
        return {"status":"failed", "delivery":"not_dispatched", "effect_applied":False,
                "failure":{"code":"already_attempted"}, "must_not_replay":True}
    desired = args["state"] == "on"
    try:
        inventory = _inventory()
        with ThreadPoolExecutor(max_workers=len(names)) as pool:
            before = dict(zip(names, pool.map(lambda n: _read(n, inventory, cancel), names)))
    except (OSError, ValueError, RuntimeError) as error:
        return {"status":"failed", "delivery":"not_dispatched", "effect_applied":False,
                "failure":{"code":"light_precheck_failed", "message":str(error)}, "must_not_replay":True}
    def change(name):
        row = {"target":name,"status":"failed","delivery":"not_dispatched","effect_applied":False}
        if cancel is not None and cancel.is_set():
            row["failure"] = "cancelled"; return row
        if before[name]["onOff"] == desired:
            return {**row,"status":"completed","delivery":"not_needed","state":args["state"],"native":before[name]}
        attempted.add(name); receipts[name] = row
        row.update(delivery="uncertain",effect_applied=None)
        try:
            after = _set(name, inventory, {"onOff":desired}, cancel)["state"]
            if _appearance(after) != _appearance(before[name]):
                raise RuntimeError("Matter power change did not preserve native appearance")
            row.update(status="completed",delivery="verified",effect_applied=True,state=args["state"],native=after,verified_at=time.time())
        except (OSError, ValueError, RuntimeError) as error:
            row["failure"] = str(error)
        return row
    with ThreadPoolExecutor(max_workers=len(names)) as pool:
        rows = list(pool.map(change,names))
    completed = all(r["status"] == "completed" for r in rows)
    applied = None if any(r["effect_applied"] is None for r in rows) else any(r["effect_applied"] for r in rows)
    return {"status":"completed" if completed else "failed","target":args["target"],"requested_state":args["state"],
            "lights":rows,"effect_applied":applied,"delivery":"verified" if completed else "partial_or_uncertain","must_not_replay":True}

"""Set verified WiZ bulb power once, without acquiring room-sensing resources."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import ipaddress
import os
from pathlib import Path
import re
import socket
import tempfile
import threading
import time

FIXTURES = ("window_lamp", "woven_pendant", "north_lamp", "tv_floor_lamp",
            "desk_lantern", "room_lantern")
TARGETS = ("all", *FIXTURES)
_LOCK = threading.Lock()


def _state_path(name: str) -> Path:
    return Path(__file__).resolve().parents[3] / "state" / name


def _inventory() -> dict:
    """Private installation state supplies addresses; source contains aliases only."""
    path = _state_path("lights.json")
    try:
        with path.open("rb") as source:
            raw = source.read(8193)
        if len(raw) > 8192:
            raise ValueError
        inventory = json.loads(raw)
        if not isinstance(inventory, dict) or set(inventory) != set(FIXTURES):
            raise ValueError
        for record in inventory.values():
            if not isinstance(record, dict) or set(record) != {"ip", "mac"}:
                raise ValueError
            if not isinstance(record["ip"], str):
                raise ValueError
            address = ipaddress.IPv4Address(record["ip"])
            if (not address.is_private or address.is_loopback or address.is_multicast
                    or address.is_unspecified or address.is_reserved):
                raise ValueError
            if not isinstance(record["mac"], str) or not re.fullmatch(r"[0-9a-f]{12}", record["mac"]):
                raise ValueError
        if (len({row["ip"] for row in inventory.values()}) != len(FIXTURES)
                or len({row["mac"] for row in inventory.values()}) != len(FIXTURES)):
            raise ValueError
        return inventory
    except (OSError, ValueError, TypeError) as error:
        raise ValueError("Private light inventory unavailable or invalid") from error


def _request(ip: str, method: str, params: dict, cancel, *, timeout: float = 1.5) -> dict:
    """One datagram; its socket owns and isolates this response generation."""
    if cancel is not None and cancel.is_set():
        raise InterruptedError("Light operation cancelled")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as peer:
        peer.connect((ip, 38899))
        peer.send(json.dumps({"method": method, "params": params}).encode())
        deadline = time.monotonic() + timeout
        for _ in range(128):
            if cancel is not None and cancel.is_set():
                raise InterruptedError("Light operation cancelled")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("WiZ reply unavailable")
            peer.settimeout(min(remaining, .1))
            try:
                packet = peer.recv(16384)
            except socket.timeout:
                continue
            try:
                reply = json.loads(packet)
            except (ValueError, UnicodeError):
                continue
            if not isinstance(reply, dict) or reply.get("method") != method:
                continue
            if "error" in reply or not isinstance(reply.get("result"), dict):
                raise ValueError("WiZ rejected the request")
            return reply["result"]
    raise TimeoutError("WiZ reply unavailable")


def _pilot(name: str, inventory: dict, cancel, *, timeout: float = 1.5) -> dict:
    record = inventory[name]
    pilot = _request(record["ip"], "getPilot", {}, cancel, timeout=timeout)
    if pilot.get("mac") != record["mac"] or type(pilot.get("state")) is not bool:
        raise ValueError("WiZ bulb identity or power state did not match")
    return pilot


def _settled_pilot(name: str, inventory: dict, cancel, desired: bool, appearance: dict) -> dict:
    """An ACK precedes bulb state application; wait only through status reads."""
    deadline = time.monotonic() + 2.0
    after = None
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            if after is not None:
                return after
            raise TimeoutError("WiZ reply unavailable")
        try:
            after = _pilot(name, inventory, cancel, timeout=min(1.5, remaining))
        except TimeoutError:
            if time.monotonic() >= deadline:
                raise
        else:
            matches = after["state"] == desired and (not desired or all(
                after.get(key) == value for key, value in appearance.items()))
            if matches or time.monotonic() >= deadline:
                return after
        # Poll the asynchronous transition at 10 Hz, interruptibly. No power
        # write is repeated, and identity/protocol failures still fail at once.
        pause = min(.1, max(0, deadline - time.monotonic()))
        if cancel is not None:
            if cancel.wait(pause):
                raise InterruptedError("Light operation cancelled")
        else:
            time.sleep(pause)


def _appearance(pilot: dict) -> dict:
    """Preserve measured scene or static colour without inventing a setting."""
    dimming = pilot.get("dimming")
    if type(dimming) is not int or not 1 <= dimming <= 100:
        raise ValueError("WiZ brightness is unavailable or invalid")
    scene = pilot.get("sceneId", 0)
    if type(scene) is not int or not 0 <= scene <= 35:
        raise ValueError("WiZ scene is unavailable or unsupported")
    result = {"dimming": dimming}
    if scene:
        result["sceneId"] = scene
        for key in ("speed", "ratio"):
            if key in pilot:
                if type(pilot[key]) is not int or not 0 <= pilot[key] <= 200:
                    raise ValueError("WiZ scene parameter is invalid")
                result[key] = pilot[key]
    elif "temp" in pilot:
        if type(pilot["temp"]) is not int or not 1000 <= pilot["temp"] <= 12000:
            raise ValueError("WiZ colour temperature is invalid")
        result["temp"] = pilot["temp"]
    elif all(key in pilot for key in ("r", "g", "b")):
        for key in ("r", "g", "b", "c", "w"):
            if key in pilot:
                if type(pilot[key]) is not int or not 0 <= pilot[key] <= 255:
                    raise ValueError("WiZ colour channel is invalid")
                result[key] = pilot[key]
    else:
        raise ValueError("WiZ lighting appearance is unavailable")
    return result


def _saved_appearances() -> dict:
    try:
        with _state_path("lights-appearance.json").open("rb") as source:
            raw = source.read(8193)
        if len(raw) > 8192:
            raise ValueError
        saved = json.loads(raw)
        if not isinstance(saved, dict):
            raise ValueError
        for mac, appearance in saved.items():
            if (not re.fullmatch(r"[0-9a-f]{12}", mac) or not isinstance(appearance, dict)
                    or _appearance(appearance) != appearance):
                raise ValueError
        return saved
    except FileNotFoundError:
        return {}
    except (OSError, TypeError, ValueError) as error:
        raise ValueError("Saved light appearance is unavailable or invalid") from error


def _save_appearances(saved: dict) -> None:
    """Commit rollback appearance before OFF; preserve every other bulb's entry."""
    path = _state_path("lights-appearance.json")
    fd, temporary = tempfile.mkstemp(prefix=".lights-appearance-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as output:
            os.fchmod(output.fileno(), 0o600)
            json.dump(saved, output, sort_keys=True)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


def execute(args: dict, context: dict) -> dict:
    cancel = context.get("_capability_cancel_event")
    while not _LOCK.acquire(timeout=.1):
        if cancel is not None and cancel.is_set():
            return {"status": "failed", "delivery": "not_dispatched", "effect_applied": False,
                    "failure": {"code": "cancelled"}, "must_not_replay": True}
    try:
        return _execute(args, context)
    finally:
        _LOCK.release()


def _execute(args: dict, context: dict) -> dict:
    if (not isinstance(args, dict) or set(args) != {"target", "state"}
            or args.get("target") not in TARGETS or args.get("state") not in ("on", "off")):
        raise ValueError("lights.set requires an exact target and state on/off")
    if (context.get("_agent_ref") != "Agents/Executive/Executive"
            or context.get("task") != "Agents/Executive/Executive"):
        raise PermissionError("Light control belongs to the Executive conversation")
    cancel = context.get("_capability_cancel_event")
    names = list(FIXTURES) if args["target"] == "all" else [args["target"]]
    attempted = context.setdefault("_lights_set_attempted_targets", set())
    receipts = context.setdefault("_lights_set_target_receipts", {})
    blocked = [name for name in names if name in attempted]
    if blocked:
        return {"status": "failed", "delivery": "not_dispatched", "effect_applied": False,
                "blocked_targets": blocked, "previous_results": [receipts[name] for name in blocked],
                "failure": {"code": "already_attempted", "message":
                    "These fixtures were already dispatched in this run; use their existing receipts."},
                "must_not_replay": True}
    desired = args["state"] == "on"
    # A missing or replaced bulb blocks the entire selected group before writes.
    try:
        inventory = _inventory()
        with ThreadPoolExecutor(max_workers=len(names), thread_name_prefix="lights-precheck") as pool:
            before = dict(zip(names, pool.map(lambda name: _pilot(name, inventory, cancel), names)))
        saved = _saved_appearances()
        appearances = {name: (_appearance(saved[inventory[name]["mac"]])
                             if desired and not before[name]["state"] and inventory[name]["mac"] in saved
                             else _appearance(before[name])) for name in names}
        if not desired:
            changed = {inventory[name]["mac"]: appearances[name] for name in names if before[name]["state"]}
            if changed:
                if cancel is not None and cancel.is_set():
                    raise InterruptedError("Light operation cancelled")
                _save_appearances({**saved, **changed})
    except (OSError, ValueError) as error:
        return {"status": "failed", "delivery": "not_dispatched", "effect_applied": False,
                "failure": {"code": "light_precheck_failed", "message": str(error)},
                "must_not_replay": True}
    def change(name: str) -> dict:
        if cancel is not None and cancel.is_set():
            return {"target": name, "status": "failed", "delivery": "not_dispatched",
                    "effect_applied": False, "failure": "cancelled"}
        if before[name]["state"] == desired:
            return {"target": name, "status": "completed", "state": args["state"],
                    "appearance": appearances[name], "verified_at": time.time(),
                    "delivery": "not_needed", "effect_applied": False}
        row = {"target": name, "status": "failed", "delivery": "uncertain", "effect_applied": None}
        if not desired:
            row["saved_appearance"] = appearances[name]
        attempted.add(name)
        receipts[name] = row
        try:
            # One write per independent fixture, followed by its own readback.
            # Potential delivery is marked first; uncertainty never replays it.
            acknowledgement = _request(inventory[name]["ip"], "setPilot",
                                       {"state": desired, **(appearances[name] if desired else {})}, cancel)
            if acknowledgement.get("success") is not True:
                raise ValueError("WiZ did not acknowledge the power change")
            row["delivery"] = "acknowledged"
            after = _settled_pilot(name, inventory, cancel, desired, appearances[name])
            row.update(state="on" if after["state"] else "off", appearance=_appearance(after),
                       verified_at=time.time())
            if after["state"] != desired:
                raise ValueError("WiZ power readback did not match the requested state")
            if desired and any(after.get(key) != value for key, value in appearances[name].items()):
                raise ValueError("WiZ appearance readback did not preserve the previous settings")
            row.update(status="completed", effect_applied=True)
        except (OSError, ValueError) as error:
            row["failure"] = str(error)
        return row

    # All selected identities and rollback appearances have passed before any
    # power write. These independent fixtures can change together; join every
    # one-shot result (including failures) before releasing the operation lock.
    with ThreadPoolExecutor(max_workers=len(names), thread_name_prefix="lights-change") as pool:
        rows = list(pool.map(change, names))
    completed = all(row["status"] == "completed" for row in rows)
    applied = None if any(row["effect_applied"] is None for row in rows) else any(row["effect_applied"] for row in rows)
    return {"status": "completed" if completed else "failed", "target": args["target"],
            "requested_state": args["state"], "lights": rows, "effect_applied": applied,
            "delivery": "verified" if completed else "partial_or_uncertain", "must_not_replay": True}

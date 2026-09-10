"""Bounded, explicit host inventory facts for the existing Source owner.

No telemetry, model discovery, process control, background refresh or writes.
A failed enumeration cannot establish that its previously seen items vanished.
"""

from __future__ import annotations

import configparser
import json
import os
from pathlib import Path
import platform
import re
import subprocess

from . import inventory
from ..config import CONFIG
from ..realtime import media
from ...shell.applications import packagekit

PROC = Path("/proc")
SYS = Path("/sys")
MAX_BYTES = 2 * 1024 * 1024
MAX_DEVICES = 256
MAX_APPLICATIONS = 512
MAX_FACT_BYTES = 400_000
LSBLK_COMMAND = ("/usr/bin/lsblk", "--json", "--bytes", "--paths", "--tree", "--output",
                 "NAME,KNAME,TYPE,MODEL,SERIAL,WWN,SIZE,TRAN,RO,FSTYPE,UUID,PARTUUID,MOUNTPOINTS")


def _text(path: Path, limit: int = MAX_BYTES) -> str:
    with path.open("rb") as handle:
        raw = handle.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("Inventory input exceeded its byte bound")
    return raw.decode("utf-8", errors="strict")


def _label(value: object, limit: int = 512) -> str:
    if (not isinstance(value, str) or not value.strip() or len(value) > limit
            or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value)):
        raise ValueError("Inventory field is missing or exceeds its text bound")
    return value.strip()


def _entries(path: Path, limit: int = MAX_DEVICES) -> list[Path]:
    result = []
    for entry in path.iterdir():
        result.append(entry)
        if len(result) > limit:
            raise ValueError("Inventory enumeration exceeded its item bound; no partial inventory accepted")
    return sorted(result, key=lambda entry: entry.name)


def _driver(device: Path) -> str | None:
    path = device / "driver"
    return _label(path.resolve(strict=True).name) if path.is_symlink() else None


def _identity() -> dict:
    release = platform.freedesktop_os_release()
    uname = os.uname()
    return {"hostname": _label(uname.nodename),
            "operating_system": _label(release.get("PRETTY_NAME") or release.get("NAME")),
            "kernel": _label(uname.release), "architecture": _label(uname.machine)}


def _compute() -> dict:
    records = []
    for record in _text(PROC / "cpuinfo").strip().split("\n\n"):
        records.append({key.strip(): value.strip() for line in record.splitlines()
                        if ":" in line for key, value in [line.split(":", 1)]})
    if not records or len(records) > 512 or any("processor" not in row or "model name" not in row for row in records):
        raise ValueError("CPU identity enumeration is incomplete")
    models = sorted({_label(row["model name"]) for row in records})
    cores = ({(row["physical id"], row["core id"]) for row in records}
             if all("physical id" in row and "core id" in row for row in records) else set())
    memory = dict(line.split(":", 1) for line in _text(PROC / "meminfo").splitlines() if ":" in line)
    total = memory.get("MemTotal", "").split()
    if len(total) != 2 or total[1] != "kB" or not total[0].isdigit():
        raise ValueError("System memory capacity is unavailable")
    gpus = []
    for device in _entries(SYS / "bus/pci/devices", 1024):
        device_class = int(_text(device / "class", 64).strip(), 16)
        if device_class >> 16 != 3:
            continue
        row = {"pci_slot": device.name, "vendor_id": _text(device / "vendor", 64).strip(),
               "device_id": _text(device / "device", 64).strip(), "driver": _driver(device)}
        information = PROC / "driver/nvidia/gpus" / device.name / "information"
        if information.exists():
            fields = dict(line.split(":", 1) for line in _text(information, 16_384).splitlines() if ":" in line)
            if fields.get("Model"):
                row["label"] = _label(fields["Model"].strip())
        gpus.append(row)
    return {"cpu": {"model": ", ".join(models), "physical_cores": len(cores) or None,
                    "logical_cpus": len(records)}, "memory": {"total_bytes": int(total[0]) * 1024}, "gpus": gpus}


def _physical_drives() -> list[dict]:
    """Use util-linux's block topology; device numbering never selects a disk."""
    try:
        result = subprocess.run(LSBLK_COMMAND, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                check=False, timeout=3)
    except (OSError, subprocess.SubprocessError):
        raise ValueError("Block inventory is unavailable") from None
    if result.returncode or len(result.stdout) > MAX_BYTES:
        raise ValueError("Block inventory failed or exceeded its byte bound")
    try:
        payload = json.loads(result.stdout)
    except (ValueError, RecursionError):
        raise ValueError("Block inventory JSON is invalid or exceeds its nesting bound") from None
    if not isinstance(payload, dict) or not isinstance(payload.get("blockdevices"), list):
        raise ValueError("Block inventory is incomplete")
    roots = payload["blockdevices"]
    if len(roots) > MAX_DEVICES:
        raise ValueError("Block inventory exceeded its item bound")
    count = 0

    def optional(value: object) -> str | None:
        return None if value is None or value == "" else _label(value)

    def details(row: dict, depth: int = 0) -> dict:
        nonlocal count
        count += 1
        if count > MAX_DEVICES or depth > 8 or not isinstance(row, dict):
            raise ValueError("Block topology exceeded its bound or is incomplete")
        device = _label(row["name"])
        if not device.startswith("/dev/") or ".." in Path(device).parts:
            raise ValueError("Block device path is invalid")
        size, read_only, mounts = row["size"], row["ro"], row["mountpoints"]
        if (type(size) is not int or size < 0 or type(read_only) is not bool
                or not isinstance(mounts, list) or len(mounts) > MAX_DEVICES):
            raise ValueError("Block capacity, flags or mounts are incomplete")
        children = row.get("children", [])
        if not isinstance(children, list) or len(children) > MAX_DEVICES:
            raise ValueError("Block topology exceeded its bound or is incomplete")
        nested = [details(child, depth + 1) for child in children]
        if len({child["device"] for child in nested}) != len(nested):
            raise ValueError("Block topology has duplicate devices")
        return {"device": device, "type": _label(row["type"]), "total_bytes": size,
                "read_only": read_only, "filesystem": optional(row["fstype"]),
                "uuid": optional(row["uuid"]), "partuuid": optional(row["partuuid"]),
                "mount_points": sorted({_label(mount) for mount in mounts if mount is not None}),
                "children": sorted(nested, key=lambda child: (
                    child["partuuid"] or child["uuid"] or "", child["device"]))}

    drives, identities, wwns, devices = [], set(), set(), set()
    for row in roots:
        if not isinstance(row, dict):
            raise ValueError("Block inventory is incomplete")
        kind, name = _label(row["type"]), Path(_label(row["kname"])).name
        if kind != "disk" or re.fullmatch(r"(?:zram|nbd|loop|ram)\d+", name):
            continue
        serial, model, wwn = _label(row["serial"]), _label(row["model"]), optional(row["wwn"])
        disk = details(row)
        if (not disk["total_bytes"] or serial in identities or disk["device"] in devices
                or (wwn is not None and wwn.casefold() in wwns)):
            raise ValueError("Physical disk identity or capacity is incomplete or ambiguous")
        identities.add(serial)
        devices.add(disk["device"])
        if wwn is not None:
            wwns.add(wwn.casefold())
        disk["partitions"] = disk.pop("children")
        drives.append({**disk, "id": "serial:" + serial, "serial": serial, "model": model,
                       "wwn": wwn, "transport": optional(row["tran"])})
    return sorted(drives, key=lambda row: row["serial"])


def _storage() -> dict:
    records = []
    for line in _text(PROC / "self/mountinfo").splitlines():
        left, right = line.split(" - ", 1)
        fields, filesystem = left.split(), right.split()
        if len(fields) < 6 or len(filesystem) < 2:
            raise ValueError("Mount enumeration is incomplete")
        records.append({"mount_point": inventory._unescape_mount(fields[4]),
                        "root": inventory._unescape_mount(fields[3]), "filesystem": filesystem[0]})
    if not records:
        raise ValueError("Mount inventory is unavailable")
    locations = []
    for identifier, label, _role, path in inventory.STORAGE_LOCATIONS:
        row = {"id": identifier, "label": label, "path": str(path)}
        try:
            path.stat()
        except FileNotFoundError:
            locations.append({**row, "available": False})
            continue
        mount = inventory._mount_for(path, records)
        if mount is None:
            raise ValueError("Storage location has no observed mount")
        stats = os.statvfs(path)
        locations.append({**row, "available": True, "filesystem": mount["filesystem"],
                          "mount_point": mount["mount_point"], "subvolume": mount["root"],
                          "total_bytes": (stats.f_frsize or stats.f_bsize) * stats.f_blocks,
                          "allocation": "shared_filesystem", "quota_bytes": None})
    return {"locations": sorted(locations, key=lambda row: row["id"]),
            "drives": _physical_drives()}


def _audio(kind: str) -> list[dict]:
    values = media._run_json(("/usr/bin/pactl", "-f", "json", "list", "sources" if kind == "microphones" else "sinks"))
    if not isinstance(values, list) or len(values) > MAX_DEVICES:
        raise ValueError("PipeWire endpoint enumeration is unavailable or exceeded its bound")
    result = {}
    for value in values:
        if not isinstance(value, dict) or not isinstance(value.get("properties"), dict):
            raise ValueError("PipeWire endpoint metadata is incomplete")
        name = _label(value.get("name"))
        media_class = value["properties"].get("media.class")
        if name.startswith("obsidience_realtime_aec_") or (kind == "microphones" and name.endswith(".monitor")):
            continue
        if media_class != ("Audio/Source" if kind == "microphones" else "Audio/Sink"):
            continue
        row = {"id": name, "label": _label(value.get("description") or name)}
        for field in ("device.bus_path", "device.profile.name", "object.path"):
            if value["properties"].get(field) is not None:
                row[field] = _label(value["properties"][field])
        if name in result and result[name] != row:
            raise ValueError("PipeWire endpoint identities are ambiguous")
        result[name] = row
    return sorted(result.values(), key=lambda row: row["id"])


def _devices() -> dict:
    microphones, speakers = _audio("microphones"), _audio("speakers")
    root = SYS / "class/video4linux"
    cameras = []
    # A missing kernel class is a complete absence only when sysfs is present.
    _entries(SYS / "class", 1024)
    try:
        entries = _entries(root)
    except FileNotFoundError:
        entries = []
    for entry in entries:
        actual = entry.resolve(strict=True)
        if "/devices/virtual/" in str(actual):
            continue
        if not entry.name.startswith("video") or not entry.name[5:].isdigit():
            raise ValueError("Unexpected Video4Linux identity")
        cameras.append({"id": "v4l2:/dev/" + entry.name, "label": _label(_text(entry / "name", 1024).strip()),
                        "device": "/dev/" + entry.name})
    return {"microphones": microphones, "speakers": speakers, "cameras": cameras,
            "audio_scope": "Endpoint declarations; readiness and active audio services are not attested.",
            "camera_scope": "Physical Video4Linux nodes; capture support is not attested by inventory."}


def _network() -> dict:
    interfaces = []
    for entry in _entries(SYS / "class/net"):
        if entry.name == "lo":
            continue
        device = entry / "device"
        interfaces.append({"id": entry.name, "driver": _driver(device),
                           "device_path": str(device.resolve(strict=True)) if device.is_symlink() else None,
                           "type": int(_text(entry / "type", 64).strip())})
    return {"interfaces": interfaces}


def _applications() -> dict:
    # Reuse the native Applications owner's XDG precedence and parser. Read
    # eligibility explicitly so a malformed entry is not mistaken for removal.
    # Match the existing owner's XDG precedence, but enumerate explicitly:
    # glob/is_dir can suppress a permission error and imply a false removal.
    by_id = {}
    for root in packagekit.DESKTOP_ROOTS:
        try:
            entries = _entries(root, MAX_APPLICATIONS * 2)
        except FileNotFoundError:
            continue
        for path in entries:
            if path.suffix == ".desktop":
                by_id[path.name] = path
        if len(by_id) > MAX_APPLICATIONS:
            raise ValueError("Desktop application inventory exceeded its bound; no truncated list accepted")
    paths = list(by_id.values())
    rows = []
    for path in paths:
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        parser.optionxform = str
        parser.read_string(_text(path, 128_000))
        entry = parser["Desktop Entry"]
        if entry.get("Type", "Application") != "Application" or entry.getboolean("Hidden", fallback=False) or entry.getboolean("NoDisplay", fallback=False):
            continue
        title = _label(entry.get("Name"), 160)
        # Preserve the normal parser's chosen field semantics without its
        # display-only truncation becoming a changed inventory fact.
        existing = packagekit._desktop_entry(path)
        if existing is None or existing["label"] != title:
            raise ValueError("Desktop entry changed during enumeration")
        rows.append({"desktop_id": _label(existing["desktop_id"]), "label": title})
    return {"scope": "Visible desktop entries; package versions and launch availability are not attested.",
            "applications": sorted(rows, key=lambda row: row["desktop_id"])}


def _runtime() -> dict:
    # Saved configuration is observed directly. Do not call model catalog,
    # discovery, initialization or reconciliation from an inventory read.
    models = json.loads(_text(CONFIG.runtime_dir / "model-settings.json", 500_000))
    selections = json.loads(_text(media.MEDIA_SETTINGS_PATH, 16_384))
    if (not isinstance(models, dict) or models.get("schema_version") != 2
            or not isinstance(models.get("hardware"), dict) or not isinstance(selections, dict)
            or selections.get("schema_version") != 3):
        raise ValueError("Saved runtime configuration is unavailable")
    hardware = models["hardware"]
    devices = (inventory.CPU_DEVICE, inventory.IGPU_DEVICE, *inventory.GPU_DEVICES)
    if set(hardware) != set(devices):
        raise ValueError("Saved hardware assignment coverage is incomplete")
    fields = (*media.INTERFACE_KINDS, "tts_voice")
    configured = {key: _label(selections.get(key)) for key in fields}
    if configured["tts_voice"] not in media.TTS_VOICES or configured["camera"] == "adb:tft":
        raise ValueError("Saved media configuration requires migration or correction")
    speech = media.speech_runtime()
    return {"hardware_assignments": {key: _label(hardware[key]) for key in devices},
            "media_selections": configured,
            "speech": {key: (configured["tts_voice"] if key == "voice" else speech[key]) for key in (
                "transport", "turn_taking", "asr", "asr_device", "asr_chunk_ms", "tts", "tts_device", "voice")},
            "scope": "Saved assignments and configured speech implementation; process residency is not attested."}


def collect_system_evidence() -> dict:
    """Return deterministic complete category facts or explicit unavailability."""
    collectors = {"identity": _identity, "compute": _compute, "storage": _storage,
                  "devices": _devices, "network": _network, "applications": _applications, "runtime": _runtime}
    result = {}
    for category, collect in collectors.items():
        try:
            facts = collect()
            encoded = json.dumps(facts, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
            if len(encoded.encode("utf-8")) > MAX_FACT_BYTES:
                raise ValueError("Inventory category exceeded its byte bound; no partial facts accepted")
            result[category] = {"status": "complete", "facts": json.loads(encoded), "detail": ""}
        except (OSError, ValueError, KeyError, TypeError, configparser.Error) as exc:
            # Fixed error classes avoid persisting host exception paths or raw
            # subprocess output in an accepted Knowledge projection.
            result[category] = {"status": "unavailable", "facts": {},
                                "detail": f"{category} collection unavailable or incomplete ({type(exc).__name__}); prior evidence remains historical."}
    return result


def system_node_facts(node: dict, inventory_facts: dict) -> dict:
    """Project approved observations into one actual System descriptor.

    The schema owns identity and membership. Its collector strings are inert;
    these fixed projections never import code or invent an application branch.
    Folder condensations and unintegrated applications retain schema facts only.
    """
    key, descriptor = node["key"], node.get("descriptor")
    facts = {"system_path": node["descriptor_path"] or node["path"]}
    if descriptor is not None:
        facts["descriptor"] = descriptor
    selector = (descriptor or {}).get("selector")

    def category(name: str) -> dict:
        row = inventory_facts.get(name, {})
        if row.get("status") != "complete" or not isinstance(row.get("facts"), dict):
            raise ValueError(row.get("detail") or f"{name.capitalize()} inventory unavailable")
        return row["facts"]

    if key == "system":
        facts["observed"] = category("identity")
    elif key.startswith("hardware/compute/") and descriptor:
        compute = category("compute")
        if selector == "cpu":
            facts["observed"] = {"cpu": compute["cpu"], "memory": compute.get("memory", {})}
        elif selector in (*inventory.GPU_DEVICES, inventory.IGPU_DEVICE):
            matches = [gpu for gpu in compute["gpus"] if (
                str(gpu.get("vendor_id")).lower() == "0x1002" if selector == inventory.IGPU_DEVICE
                else inventory.DEVICE_LABELS[selector].casefold() in str(gpu.get("label", "")).casefold())]
            if len(matches) != 1:
                raise ValueError("Registered GPU does not match one observed device")
            facts["observed"] = matches[0]
    elif key.startswith("hardware/drives/") and descriptor:
        serial, model = _label(selector), _label(descriptor.get("model"))
        matches = [row for row in category("storage")["drives"]
                   if row.get("serial") == serial and row.get("model") == model]
        if len(matches) != 1:
            raise ValueError("Registered physical drive does not match one observed device")
        if descriptor.get("wwn") is not None and matches[0].get("wwn") != _label(descriptor["wwn"]):
            raise ValueError("Registered physical drive WWN does not match observed identity")
        facts["observed"] = matches[0]
    elif key.startswith("hardware/devices/") and descriptor:
        plural = {"camera": "cameras", "microphone": "microphones", "speaker": "speakers"}.get(selector)
        if plural:
            devices = category("devices")
            facts["observed"] = {"endpoints": devices[plural]}
            runtime = inventory_facts.get("runtime", {})
            if runtime.get("status") == "complete":
                selection = runtime["facts"].get("media_selections", {}).get(selector)
                if selection is not None:
                    facts["observed"]["configured_selection"] = selection
    elif key == "hardware/network":
        facts["observed"] = category("network")
    elif key == "applications/obsidience":
        facts["observed"] = {"storage_locations": category("storage")["locations"]}
    elif key == "applications/obsidience/model-assignments":
        facts["observed"] = {"hardware_assignments": category("runtime")["hardware_assignments"]}
    elif key == "applications/obsidience/speech-runtime":
        runtime = category("runtime")
        facts["observed"] = {"speech": runtime["speech"], "media_selections": runtime["media_selections"]}
    return facts

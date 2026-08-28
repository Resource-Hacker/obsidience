"""Read-only inventory and telemetry for local compute hardware."""

from __future__ import annotations

import os
import platform
import re
import subprocess
from pathlib import Path


CPU_DEVICE = "cpu"
IGPU_DEVICE = "amd-igpu"
RTX_4080_DEVICE = "rtx4080"
RTX_4000_DEVICE = "rtx4000"
GPU_DEVICES = (RTX_4080_DEVICE, RTX_4000_DEVICE)
DEVICE_LABELS = {
    CPU_DEVICE: "CPU",
    IGPU_DEVICE: "AMD Granite Ridge iGPU",
    RTX_4080_DEVICE: "RTX 4080 SUPER",
    RTX_4000_DEVICE: "RTX 4000 Ada",
}
GPU_UUIDS = {
    RTX_4080_DEVICE: "GPU-4332e1a5-17a8-7e18-5347-5a296549ee81",
    RTX_4000_DEVICE: "GPU-3b820ab6-b7e7-c26b-b400-136780611a3e",
}
PRODUCT_ROOT = Path(__file__).resolve().parents[2]
STORAGE_LOCATIONS = (
    ("obsidience", "Obsidience", "product", PRODUCT_ROOT),
    ("models", "AI Models", "models", Path("/var/lib/ai")),
)
_MOUNT_ESCAPE = re.compile(r"\\([0-7]{3})")


def gpu_snapshot() -> list[dict]:
    """Return the current NVIDIA sensor rows for known and unknown GPUs."""
    command = [
        "nvidia-smi",
        "--query-gpu=uuid,name,pstate,temperature.gpu,power.draw,power.limit,"
        "clocks.current.graphics,clocks.current.memory,utilization.gpu,"
        "utilization.memory,utilization.encoder,utilization.decoder,"
        "memory.total,memory.used,memory.free,fan.speed,"
        "pcie.link.gen.current,pcie.link.width.current",
        "--format=csv,noheader,nounits",
    ]
    try:
        output = subprocess.run(
            command, check=True, capture_output=True, text=True, timeout=5,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    rows = []
    by_uuid = {uuid: device for device, uuid in GPU_UUIDS.items()}

    def number(value: str, *, integer: bool = False):
        try:
            return int(float(value)) if integer else float(value)
        except (TypeError, ValueError):
            return None

    for line in output.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) != 18:
            continue
        (
            uuid, name, pstate, temperature, power, power_limit, graphics_clock,
            memory_clock, utilization, memory_controller, encoder, decoder,
            total, used, free, fan, pcie_generation, pcie_width,
        ) = parts
        total_mib = number(total, integer=True)
        used_mib = number(used, integer=True)
        rows.append({
            "device": by_uuid.get(uuid),
            "uuid": uuid,
            "name": name,
            "driver": "nvidia",
            "status": "online",
            "memory_label": "VRAM",
            "memory_total_mib": total_mib,
            "memory_used_mib": used_mib,
            "memory_free_mib": number(free, integer=True),
            "memory_used_percent": round(100 * used_mib / total_mib, 1)
            if total_mib and used_mib is not None else None,
            "utilization_percent": number(utilization, integer=True),
            "memory_controller_percent": number(memory_controller, integer=True),
            "encoder_percent": number(encoder, integer=True),
            "decoder_percent": number(decoder, integer=True),
            "temperature_c": number(temperature),
            "power_w": number(power),
            "power_limit_w": number(power_limit),
            "clock_core_mhz": number(graphics_clock, integer=True),
            "clock_memory_mhz": number(memory_clock, integer=True),
            "fan_percent": number(fan, integer=True),
            "pstate": pstate if pstate and pstate != "[N/A]" else None,
            "pcie_generation": number(pcie_generation, integer=True),
            "pcie_width": number(pcie_width, integer=True),
        })
    return rows


_CPU_STAT_SAMPLE: tuple[int, int] | None = None


def _read_int(path: Path) -> int | None:
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def _hwmon(name: str) -> Path | None:
    for path in sorted(Path("/sys/class/hwmon").glob("hwmon*")):
        try:
            if (path / "name").read_text().strip() == name:
                return path
        except OSError:
            continue
    return None


def _cpu_utilization() -> float | None:
    global _CPU_STAT_SAMPLE
    try:
        values = [
            int(value)
            for value in Path("/proc/stat").read_text().splitlines()[0].split()[1:]
        ]
    except (OSError, ValueError, IndexError):
        return None
    if len(values) < 5:
        return None
    total = sum(values)
    idle = values[3] + values[4]
    previous = _CPU_STAT_SAMPLE
    _CPU_STAT_SAMPLE = (total, idle)
    if previous is None or total <= previous[0]:
        return None
    busy_delta = (total - previous[0]) - (idle - previous[1])
    return round(
        max(0.0, min(100.0, 100 * busy_delta / (total - previous[0]))), 1,
    )


def _memory_snapshot() -> tuple[int | None, int | None, int | None]:
    try:
        rows = {
            parts[0].rstrip(":"): int(parts[1])
            for line in Path("/proc/meminfo").read_text().splitlines()
            if len(parts := line.split()) >= 2 and parts[1].isdigit()
        }
    except OSError:
        return None, None, None
    total_kib = rows.get("MemTotal")
    available_kib = rows.get("MemAvailable")
    if total_kib is None or available_kib is None:
        return None, None, None
    return (
        total_kib // 1024,
        (total_kib - available_kib) // 1024,
        available_kib // 1024,
    )


def _cpu_clock_mhz() -> int | None:
    values = [
        value
        for path in Path("/sys/devices/system/cpu").glob(
            "cpu[0-9]*/cpufreq/scaling_cur_freq"
        )
        if (value := _read_int(path)) is not None
    ]
    return round(sum(values) / len(values) / 1000) if values else None


def _physical_cpu_cores() -> int | None:
    try:
        records = Path("/proc/cpuinfo").read_text().strip().split("\n\n")
    except OSError:
        return None
    cores = set()
    for record in records:
        fields = {}
        for line in record.splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                fields[key.strip()] = value.strip()
        if "core id" in fields:
            cores.add((fields.get("physical id", "0"), fields["core id"]))
    return len(cores) or None


def _cpu_sensor_snapshot() -> dict:
    total_mib, used_mib, free_mib = _memory_snapshot()
    k10temp = _hwmon("k10temp")
    temperature = _read_int(k10temp / "temp1_input") if k10temp else None
    load_1m, load_5m, load_15m = os.getloadavg()
    return {
        "device": CPU_DEVICE,
        "name": "AMD Ryzen 9 9950X",
        "driver": "amd-pstate",
        "status": "online",
        "memory_label": "System RAM",
        "memory_total_mib": total_mib,
        "memory_used_mib": used_mib,
        "memory_free_mib": free_mib,
        "memory_used_percent": round(100 * used_mib / total_mib, 1)
        if total_mib and used_mib is not None else None,
        "utilization_percent": _cpu_utilization(),
        "temperature_c": round(temperature / 1000, 1)
        if temperature is not None else None,
        "clock_core_mhz": _cpu_clock_mhz(),
        "load_1m": round(load_1m, 2),
        "load_5m": round(load_5m, 2),
        "load_15m": round(load_15m, 2),
        "physical_cores": _physical_cpu_cores(),
        "threads": os.cpu_count(),
    }


def _amdgpu_device() -> Path | None:
    for card in sorted(Path("/sys/class/drm").glob("card[0-9]*")):
        driver = card / "device" / "driver"
        try:
            if driver.resolve().name == "amdgpu":
                return card / "device"
        except OSError:
            continue
    return None


def _active_dpm_clock(path: Path) -> int | None:
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return None
    active = next((line for line in lines if "*" in line), "")
    for token in active.replace("*", "").split():
        if token.lower().endswith("mhz"):
            try:
                return int(token[:-3])
            except ValueError:
                return None
    return None


def _igpu_sensor_snapshot() -> dict:
    device = _amdgpu_device()
    if device is None:
        return {
            "device": IGPU_DEVICE,
            "status": "unavailable",
            "memory_label": "GPU memory",
        }
    hwmons = sorted((device / "hwmon").glob("hwmon*"))
    hwmon = hwmons[0] if hwmons else None
    total_bytes = _read_int(device / "mem_info_vram_total")
    used_bytes = _read_int(device / "mem_info_vram_used")
    total_mib = total_bytes // (1024 * 1024) if total_bytes is not None else None
    used_mib = used_bytes // (1024 * 1024) if used_bytes is not None else None
    temperature = _read_int(hwmon / "temp1_input") if hwmon else None
    power = _read_int(hwmon / "power1_input") if hwmon else None
    core_clock = _read_int(hwmon / "freq1_input") if hwmon else None
    return {
        "device": IGPU_DEVICE,
        "name": "AMD Granite Ridge iGPU",
        "driver": "amdgpu",
        "status": "online",
        "memory_label": "GPU memory",
        "memory_total_mib": total_mib,
        "memory_used_mib": used_mib,
        "memory_free_mib": max(0, total_mib - used_mib)
        if total_mib is not None and used_mib is not None else None,
        "memory_used_percent": round(100 * used_mib / total_mib, 1)
        if total_mib and used_mib is not None else None,
        "utilization_percent": _read_int(device / "gpu_busy_percent"),
        "media_engine_percent": _read_int(device / "vcn_busy_percent"),
        "temperature_c": round(temperature / 1000, 1)
        if temperature is not None else None,
        "power_w": round(power / 1_000_000, 3) if power is not None else None,
        "clock_core_mhz": round(core_clock / 1_000_000)
        if core_clock is not None else _active_dpm_clock(device / "pp_dpm_sclk"),
        "clock_memory_mhz": _active_dpm_clock(device / "pp_dpm_mclk"),
    }


def hardware_sensor_snapshot() -> dict[str, dict]:
    """Return all local hardware sensor rows keyed by stable device ID."""
    sensors = {
        CPU_DEVICE: _cpu_sensor_snapshot(),
        IGPU_DEVICE: _igpu_sensor_snapshot(),
    }
    sensors.update({
        row["device"]: row
        for row in gpu_snapshot()
        if row.get("device") in GPU_DEVICES
    })
    return sensors


def _unescape_mount(value: str) -> str:
    return _MOUNT_ESCAPE.sub(lambda match: chr(int(match.group(1), 8)), value)


def _mount_records() -> list[dict]:
    """Read the kernel's current mount table without shelling out or polling disks."""
    try:
        lines = Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    records = []
    for line in lines:
        try:
            left, right = line.split(" - ", 1)
        except ValueError:
            continue
        fields = left.split()
        filesystem = right.split()
        if len(fields) < 6 or len(filesystem) < 2:
            continue
        records.append({
            "device_id": fields[2],
            "root": _unescape_mount(fields[3]),
            "mount_point": _unescape_mount(fields[4]),
            "filesystem": filesystem[0],
            "source": _unescape_mount(filesystem[1]),
        })
    return records


def _mount_for(path: Path, records: list[dict]) -> dict | None:
    target = path.resolve()
    matches = []
    for record in records:
        mount = Path(str(record["mount_point"]))
        if target == mount or mount in target.parents:
            matches.append((len(mount.parts), record))
    return max(matches, default=(0, None), key=lambda item: item[0])[1]


def storage_snapshot() -> dict:
    """Return actual capacity once per filesystem plus bounded product locations.

    A location is not called a partition or quota unless the host really exposes
    one. Obsidience and the model store may be separate Btrfs subvolumes while
    still sharing the same filesystem capacity.
    """
    mounts = _mount_records()
    filesystems: dict[str, dict] = {}
    locations = []
    for identifier, label, role, path in STORAGE_LOCATIONS:
        if not path.exists():
            locations.append({
                "id": identifier,
                "label": label,
                "role": role,
                "path": str(path),
                "available": False,
                "filesystem_id": None,
                "mount_point": None,
                "subvolume": None,
                "quota_bytes": None,
                "allocation": "unavailable",
            })
            continue
        record = _mount_for(path, mounts)
        stats = os.statvfs(path)
        block_size = stats.f_frsize or stats.f_bsize
        total = block_size * stats.f_blocks
        free = block_size * stats.f_bfree
        available = block_size * stats.f_bavail
        used = max(0, total - free)
        device_id = str(record["device_id"] if record else path.stat().st_dev)
        filesystem_id = f"filesystem:{device_id}"
        filesystem = filesystems.setdefault(filesystem_id, {
            "id": filesystem_id,
            "source": record["source"] if record else None,
            "filesystem": record["filesystem"] if record else None,
            "total_bytes": total,
            "used_bytes": used,
            "available_bytes": available,
            "used_percent": round(100 * used / total, 1) if total else None,
            "mount_points": [],
        })
        mount_point = str(record["mount_point"] if record else path)
        if mount_point not in filesystem["mount_points"]:
            filesystem["mount_points"].append(mount_point)
        locations.append({
            "id": identifier,
            "label": label,
            "role": role,
            "path": str(path),
            "available": True,
            "filesystem_id": filesystem_id,
            "mount_point": mount_point,
            "subvolume": record["root"] if record else None,
            "quota_bytes": None,
            "allocation": "shared_filesystem",
        })
    return {
        "schema": "obsidience.storage.v1",
        "filesystems": sorted(filesystems.values(), key=lambda row: row["id"]),
        "locations": locations,
    }


def _command_value(command: list[str]) -> str | None:
    try:
        value = subprocess.run(
            command, check=False, capture_output=True, text=True, timeout=3,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return value or None


def application_snapshot() -> dict[str, dict]:
    """Return actual application boundaries without pretending they are Tools."""
    browser = _command_value(["xdg-settings", "get", "default-web-browser"])
    return {
        "obsidience": {
            "id": "obsidience",
            "label": "Obsidience",
            "role": "desktop-shell",
            "state": "development",
            "replacement_target": "plasmashell",
            "compositor_boundary": "KWin",
            "project_path": str(PRODUCT_ROOT),
            "service": "obsidience-shell-host.service",
            "service_state": _command_value([
                "systemctl", "--user", "is-active",
                "obsidience-shell-host.service",
            ]) or "unavailable",
            "components": {
                "shell": "obsidience-shell-host.service",
                "surface_usb_c": "obsidience-shell-surface-usbc.service",
                "harness": "obsidience-harness-dev.service",
                "development_ui": "obsidience-ui-usbc-dev.service",
            },
            "integrated": True,
        },
        "web-browser": {
            "id": "web-browser",
            "label": "Web Browser",
            "role": "application",
            "state": "external-not-integrated",
            "default_desktop_entry": browser,
            "integrated": False,
        },
    }


def network_snapshot() -> list[dict]:
    """Return the kernel's current local interface identities and link state."""
    rows = []
    for interface in sorted(Path("/sys/class/net").iterdir()):
        if interface.name == "lo":
            continue
        try:
            state = (interface / "operstate").read_text().strip()
        except OSError:
            state = "unknown"
        try:
            driver = (interface / "device" / "driver").resolve().name
        except OSError:
            driver = None
        rows.append({
            "id": interface.name,
            "state": state,
            "driver": driver,
        })
    return rows


def system_snapshot() -> dict:
    """Return the real host, application, and network inventory for Source."""
    try:
        release = platform.freedesktop_os_release()
    except OSError:
        release = {}
    uname = os.uname()
    return {
        "schema": "obsidience.system.v1",
        "system": {
            "hostname": uname.nodename,
            "operating_system": release.get("PRETTY_NAME") or release.get("NAME"),
            "kernel": uname.release,
            "architecture": uname.machine,
        },
        "applications": application_snapshot(),
        "network": network_snapshot(),
    }

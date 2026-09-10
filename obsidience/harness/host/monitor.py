"""On-demand, read-only host measurements; no timer, process control, or store."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import threading
import time
import uuid

import psutil

from . import inventory


CACHE_SECONDS = 2.0
MAX_INTERVAL_SECONDS = 15.0
MAX_PROCESSES = 4096
PROCESS_ROWS = 30
MAX_DEVICES = 64
MAX_CORES = 512
SYS_BLOCK = Path("/sys/block")
SYS_NET = Path("/sys/class/net")


def _text(value: str, limit: int = 80) -> str:
    return "".join(char for char in value if char.isprintable())[:limit]


def _delta(current, previous, interval):
    if current is None or previous is None or interval is None or current < previous:
        return None
    return (current - previous) / interval


def _cpu_percent(current, previous):
    if previous is None or current.keys() != previous.keys():
        return None
    # Linux includes guest time in user/nice. Count it once, and treat iowait
    # as idle, matching psutil's Linux utilization definition.
    deltas = {key: current[key] - previous[key] for key in current}
    if any(value < 0 for value in deltas.values()):
        return None
    total = sum(deltas.values()) - deltas.get("guest", 0) - deltas.get("guest_nice", 0)
    busy = total - deltas.get("idle", 0) - deltas.get("iowait", 0)
    return round(max(0.0, min(100.0, 100 * busy / total)), 1) if total > 0 else None


class HardwareMonitor:
    """One serialized cache for all visible panes, with bounded volatile baselines.

    CPU and process percentages use the whole machine as 100%, so a fully busy
    thread on a 32-thread CPU is 3.125% of the machine. First samples, missing
    identities, counter resets and gaps over 15 seconds have unavailable rates.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._cache = None
        self._cached_at = 0.0
        self._previous = None

    def snapshot(self) -> dict:
        seen_sample = self._cache
        with self._lock:
            if self._cache is not None and (
                self._cache is not seen_sample
                or time.monotonic() - self._cached_at < CACHE_SECONDS
            ):
                # Share a collection completed while this caller waited, even
                # when a slow sensor took longer than the ordinary cache TTL.
                return deepcopy(self._cache)
            started = time.monotonic()
            captured_at = datetime.now(timezone.utc).isoformat()
            problems = []

            def read(component, callback, fallback):
                try:
                    return callback()
                except (OSError, psutil.Error, ValueError):
                    problems.append({"component": component, "message": "Current readings are unavailable."})
                    return fallback

            cpu_times = read("cpu", lambda: [row._asdict() for row in psutil.cpu_times(percpu=True)][:MAX_CORES], [])
            disk_times = read("storage", lambda: dict([
                (name, row)
                for name, row in sorted((psutil.disk_io_counters(perdisk=True, nowrap=False) or {}).items())
                if (SYS_BLOCK / name / "device").exists()
            ][:MAX_DEVICES]), {})
            net_times = read("network", lambda: dict(sorted(psutil.net_io_counters(pernic=True, nowrap=False).items())[:MAX_DEVICES]), {})
            net_stats = read("network", lambda: dict(sorted(psutil.net_if_stats().items())[:MAX_DEVICES]), {})
            processes = read("processes", lambda: self._processes(problems), {})
            current = {"time": started, "cpu": cpu_times, "disks": disk_times, "network": net_times, "processes": processes}
            previous = self._previous or {}
            elapsed = started - previous["time"] if previous else None
            interval = elapsed if elapsed is not None and 0 < elapsed <= MAX_INTERVAL_SECONDS else None
            if interval is None:
                previous = {}

            cpu = read("cpu", lambda: inventory._cpu_sensor_snapshot(include_utilization=False), {
                "device": inventory.CPU_DEVICE, "name": inventory.DEVICE_LABELS[inventory.CPU_DEVICE], "status": "unavailable",
            })
            old_cpu = previous.get("cpu", [])
            matching_cores = bool(cpu_times) and len(cpu_times) == len(old_cpu)
            cpu["per_core_percent"] = [
                _cpu_percent(row, old_cpu[index] if matching_cores else None)
                for index, row in enumerate(cpu_times)
            ]
            per_core = cpu["per_core_percent"]
            cpu["utilization_percent"] = round(sum(per_core) / len(per_core), 1) if per_core and all(value is not None for value in per_core) else None
            threads = read("cpu", psutil.cpu_count, None)
            cpu["threads"] = threads

            memory = read("memory", self._memory, {
                key: None for key in ("total_bytes", "used_bytes", "available_bytes", "used_percent", "cached_bytes", "swap_total_bytes", "swap_used_bytes", "swap_used_percent")
            })
            cpu.update({
                "memory_total_mib": memory["total_bytes"] // (1024 * 1024) if memory["total_bytes"] is not None else None,
                "memory_used_mib": memory["used_bytes"] // (1024 * 1024) if memory["used_bytes"] is not None else None,
                "memory_free_mib": memory["available_bytes"] // (1024 * 1024) if memory["available_bytes"] is not None else None,
                "memory_used_percent": memory["used_percent"],
            })
            process_rows = []
            for identity, row in processes.items():
                old = previous.get("processes", {}).get(identity)
                user = _delta(row["user"], old["user"] if old else None, interval)
                system = _delta(row["system"], old["system"] if old else None, interval)
                percent = min(100.0, 100 * (user + system) / threads) if threads and user is not None and system is not None else None
                process_rows.append({
                    "pid": identity[0], "started_at": identity[1], "name": row["name"],
                    "cpu_percent": round(percent, 2) if percent is not None else None,
                    "memory_bytes": row["rss"],
                })
            process_rows.sort(key=lambda row: (-(row["cpu_percent"] if row["cpu_percent"] is not None else -1), -row["memory_bytes"], row["pid"]))

            storage = read("storage", lambda: self._storage(problems), {"schema": "obsidience.storage.v1", "filesystems": [], "locations": []})
            storage["devices"] = []
            for name, counters in disk_times.items():
                old = previous.get("disks", {}).get(name)
                busy = _delta(getattr(counters, "busy_time", None), getattr(old, "busy_time", None), interval)
                storage["devices"].append({
                    "id": "disk:" + _text(name), "name": _text(name),
                    "read_bytes_per_second": _delta(counters.read_bytes, old.read_bytes if old else None, interval),
                    "write_bytes_per_second": _delta(counters.write_bytes, old.write_bytes if old else None, interval),
                    "io_busy_percent": round(min(100.0, busy / 10), 1) if busy is not None else None,
                })
            network = []
            for name in sorted(net_times.keys() | net_stats.keys())[:MAX_DEVICES]:
                counters, stat = net_times.get(name), net_stats.get(name)
                old = previous.get("network", {}).get(name)
                network.append({
                    "id": _text(name), "state": ("up" if stat.isup else "down") if stat else "unavailable",
                    "is_physical": (SYS_NET / name / "device").exists(),
                    "speed_mbps": stat.speed if stat and stat.speed > 0 else None,
                    "received_bytes_per_second": _delta(counters.bytes_recv if counters else None, old.bytes_recv if old else None, interval),
                    "sent_bytes_per_second": _delta(counters.bytes_sent if counters else None, old.bytes_sent if old else None, interval),
                    "total_received_bytes": counters.bytes_recv if counters else None,
                    "total_sent_bytes": counters.bytes_sent if counters else None,
                })

            gpus = read("gpus", inventory.gpu_snapshot, [])[:16]
            gpus.insert(0, read("gpus", inventory._igpu_sensor_snapshot, {"device": inventory.IGPU_DEVICE, "status": "unavailable"}))
            present = {row.get("device") for row in gpus}
            for device in inventory.GPU_DEVICES:
                if device not in present:
                    gpus.append({"device": device, "name": inventory.DEVICE_LABELS[device], "status": "unavailable", "memory_label": "VRAM"})
            for row in gpus:
                row["device"] = row.get("device") or row.get("uuid")
                if row.get("status") == "unavailable":
                    row.setdefault("name", inventory.DEVICE_LABELS.get(row["device"], row["device"]))
                    problems.append({"component": row["device"], "message": "Current sensor readings are unavailable."})

            self._previous = current
            completed = time.monotonic()
            self._cached_at = started
            self._cache = {
                "schema": "obsidience.hardware-monitor.v1", "sample_id": uuid.uuid4().hex,
                "captured_at": captured_at, "interval_seconds": interval,
                "collection_ms": round((completed - started) * 1000, 2),
                "cpu": cpu, "memory": memory, "gpus": gpus, "storage": storage,
                "network": network, "processes": process_rows[:PROCESS_ROWS], "problems": problems,
            }
            return deepcopy(self._cache)

    @staticmethod
    def _storage(problems):
        storage = inventory.storage_snapshot()
        # Preserve the existing location IDs and shared capacity, then add other
        # mounted local volumes. A Btrfs subvolume is not another physical disk.
        by_source = {
            str(Path(row["source"]).resolve()): row
            for row in storage["filesystems"] if row.get("source")
        }
        for partition in psutil.disk_partitions(all=False)[:MAX_DEVICES]:
            if not partition.device.startswith("/dev/"):
                continue
            source = str(Path(partition.device).resolve())
            row = by_source.get(source)
            if row is None:
                if len(storage["filesystems"]) >= MAX_DEVICES:
                    problems.append({"component": "storage", "message": "Mounted volume limit reached."})
                    break
                row = {"id": "filesystem:" + source, "source": source, "filesystem": partition.fstype,
                       "total_bytes": None, "used_bytes": None, "available_bytes": None,
                       "used_percent": None, "mount_points": []}
                try:
                    usage = psutil.disk_usage(partition.mountpoint)
                    row.update(total_bytes=usage.total, used_bytes=usage.used,
                               available_bytes=usage.free, used_percent=usage.percent)
                except (OSError, psutil.Error):
                    problems.append({"component": "storage", "message": "A mounted volume's capacity is unavailable."})
                by_source[source] = row
                storage["filesystems"].append(row)
            if partition.mountpoint not in row["mount_points"]:
                row["mount_points"].append(partition.mountpoint)
        storage["filesystems"].sort(key=lambda row: row["id"])
        return storage

    @staticmethod
    def _memory():
        ram, swap = psutil.virtual_memory(), psutil.swap_memory()
        return {
            "total_bytes": ram.total, "used_bytes": max(0, ram.total - ram.available),
            "available_bytes": ram.available, "used_percent": ram.percent,
            "cached_bytes": getattr(ram, "cached", None), "swap_total_bytes": swap.total,
            "swap_used_bytes": swap.used, "swap_used_percent": swap.percent,
        }

    @staticmethod
    def _processes(problems):
        result = {}
        limited = False
        denied = False
        # psutil retains Process identity/create-time fields between censuses.
        # Check reuse before reading and after oneshot; a stale cached PID is
        # discarded and upstream regenerates it on a later census. Scheduler
        # delays must not turn a finite process list into a partial data error.
        for index, process in enumerate(psutil.process_iter()):
            if index >= MAX_PROCESSES:
                limited = True
                break
            try:
                if not process.is_running():
                    continue
                with process.oneshot():
                    identity = (process.pid, process.create_time())
                    cpu = process.cpu_times()
                    # Public name() may consult argv internally on Linux. Only
                    # its bounded name is projected; argv is never retained.
                    row = {"name": _text(process.name()), "user": cpu.user, "system": cpu.system, "rss": process.memory_info().rss}
                if process.is_running():
                    result[identity] = row
            except (psutil.NoSuchProcess, psutil.ZombieProcess):
                continue
            except (psutil.AccessDenied, OSError):
                denied = True
        if limited:
            problems.append({"component": "processes", "message": "Process count limit reached; busiest rows cover the sampled processes."})
        if denied:
            problems.append({"component": "processes", "message": "Some processes could not be read."})
        return result


MONITOR = HardwareMonitor()


def snapshot() -> dict:
    return MONITOR.snapshot()

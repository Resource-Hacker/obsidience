"""Demand-driven NVML readings and bounded Edge GPU-helper reclamation."""

from __future__ import annotations

import os
import re
import select
import signal
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import psutil
import pynvml

from .inventory import GPU_UUIDS

MIB = 1024 * 1024
EDGE_EXECUTABLES = frozenset({
    "/opt/microsoft/msedge/msedge", "/opt/microsoft/msedge-beta/msedge",
    "/opt/microsoft/msedge-dev/msedge",
})
# Chromium forgives GPU crashes after 5 minutes (10 for its display compositor).
# Requiring the replacement helper to age prevents repeated reclamation from
# pushing the browser into software rendering, including across Harness reloads.
EDGE_MIN_AGE_SECONDS = 10 * 60
EDGE_RESERVE_MIB = 512


@dataclass(frozen=True)
class ProcessMemory:
    pid: int
    started: float
    mib: int
    unit: str
    edge_gpu: bool


@dataclass(frozen=True)
class DeviceMemory:
    total_mib: int
    free_mib: int
    processes: tuple[ProcessMemory, ...]


def process_identity(pid: int) -> tuple[int, float]:
    process = psutil.Process(pid)
    if process.uids().real != os.getuid():
        raise ValueError("GPU process belongs to another user")
    return pid, process.create_time()


def _edge_gpu(process: psutil.Process) -> bool:
    # Chromium rewrites /proc/cmdline into one space-separated argv entry.
    # Match a complete switch, never an arbitrary process-name substring.
    return (process.uids().real == os.getuid()
            and process.exe() in EDGE_EXECUTABLES
            and re.search(r"(?:^|\s)--type=gpu-process(?:\s|$)",
                          " ".join(process.cmdline())) is not None)


class GpuMemory:
    """One NVML lifetime per model owner; no timer or subprocess polling."""

    def __init__(self):
        self._lock = threading.RLock()
        self._initialized = False
        self._sample: dict[str, DeviceMemory] = {}
        self._sample_at = 0.0
        self._signalled: set[tuple[int, float]] = set()
        # Reclamation is an installation-owner choice, not a public-template
        # grant to terminate another application's processes.
        self.reclaim_edge_enabled = os.environ.get("OBSIDIENCE_RECLAIM_EDGE_GPU") == "1"

    def snapshot(self, *, fresh: bool = False) -> dict[str, DeviceMemory]:
        with self._lock:
            if not fresh and time.monotonic() - self._sample_at < 1.0:
                return self._sample.copy()
            if not self._initialized:
                pynvml.nvmlInit()
                self._initialized = True
            rows = {}
            for device, uuid in GPU_UUIDS.items():
                try:
                    handle = pynvml.nvmlDeviceGetHandleByUUID(uuid)
                    memory = pynvml.nvmlDeviceGetMemoryInfo(handle)
                except pynvml.NVMLError:
                    continue  # An unavailable GPU does not hide another device.
                allocations: dict[int, int] = {}
                # A C+G process appears in both lists: count it once.
                for query in (pynvml.nvmlDeviceGetComputeRunningProcesses,
                              pynvml.nvmlDeviceGetGraphicsRunningProcesses):
                    for row in query(handle):
                        if row.usedGpuMemory is not None and 0 <= row.usedGpuMemory <= memory.total:
                            allocations[row.pid] = max(allocations.get(row.pid, 0),
                                                       row.usedGpuMemory // MIB)
                processes = []
                for pid, mib in allocations.items():
                    try:
                        process = psutil.Process(pid)
                        if process.uids().real != os.getuid():
                            continue  # Still counted in device usage, never reclaimable.
                        cgroup = (Path("/proc") / str(pid) / "cgroup").read_text()
                        unit = next((line.rsplit("/", 1)[-1] for line in cgroup.splitlines()
                                     if line.startswith("0::")), "")
                        processes.append(ProcessMemory(pid, process.create_time(), mib,
                                                       unit, _edge_gpu(process)))
                    except (OSError, psutil.Error):
                        continue
                rows[device] = DeviceMemory(memory.total // MIB, memory.free // MIB,
                                            tuple(processes))
            self._sample, self._sample_at = rows, time.monotonic()
            live = {(p.pid, p.started) for row in rows.values() for p in row.processes}
            self._signalled.intersection_update(live)
            return rows.copy()

    def edge_reclaimable(self, process: ProcessMemory) -> int:
        with self._lock:
            if (not self.reclaim_edge_enabled or not process.edge_gpu
                    or time.time() - process.started < EDGE_MIN_AGE_SECONDS
                    or (process.pid, process.started) in self._signalled):
                return 0
            return max(0, process.mib - EDGE_RESERVE_MIB)

    def reclaim_edge(self, devices: tuple[str, ...]) -> list[int]:
        """Recycle each exact blocking helper once; browser/renderer PIDs stay up.

        Called only by a model admission which needs its memory. pidfd binds the
        signal to the inspected process; timeout never escalates or repeats it.
        The caller must remeasure, since a new helper may allocate memory again.
        """
        rows = self.snapshot(fresh=True)
        candidates = {p.pid: p for device in devices if device in rows
                      for p in rows[device].processes if self.edge_reclaimable(p)}
        signalled = []
        for candidate in candidates.values():
            fd = None
            try:
                fd = os.pidfd_open(candidate.pid)
                process = psutil.Process(candidate.pid)
                if process.create_time() != candidate.started or not _edge_gpu(process):
                    continue
                with self._lock:
                    identity = (candidate.pid, candidate.started)
                    if identity in self._signalled:
                        continue
                    self._signalled.add(identity)
                    signal.pidfd_send_signal(fd, signal.SIGTERM)
                # Admission readers must remain responsive while this bounded
                # native wait joins the helper's exit.
                poller = select.poll()
                poller.register(fd, select.POLLIN)
                if poller.poll(3000):
                    signalled.append(candidate.pid)
            except (OSError, psutil.Error):
                continue
            finally:
                if fd is not None:
                    os.close(fd)
        with self._lock:
            self._sample_at = 0.0
        return signalled

    def close(self) -> None:
        with self._lock:
            if self._initialized:
                pynvml.nvmlShutdown()
                self._initialized = False
            self._sample.clear()
            self._sample_at = 0.0

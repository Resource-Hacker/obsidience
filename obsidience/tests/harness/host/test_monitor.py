"""Live monitor has one bounded owner and never turns missing rates into zero."""

from collections import namedtuple
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from copy import deepcopy
import importlib
import json
import threading
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from obsidience.harness.host import inventory, monitor


Times = namedtuple("Times", "user system idle iowait guest")


@pytest.fixture
def sample(monkeypatch, tmp_path):
    state = SimpleNamespace(
        clock=100.0, cpu=[Times(100, 20, 80, 0, 0), Times(100, 20, 80, 0, 0)],
        disks={"disk0": SimpleNamespace(read_bytes=1000, write_bytes=2000, busy_time=100)},
        net={"eth0": SimpleNamespace(bytes_recv=3000, bytes_sent=4000)},
        processes={10: dict(start=40.0, name="worker\n", user=1.0, system=0.0, rss=100)},
        cpu_calls=0, gpu_calls=0,
    )
    monkeypatch.setattr(monitor.time, "monotonic", lambda: state.clock)
    (tmp_path / "disk0" / "device").mkdir(parents=True)
    monkeypatch.setattr(monitor, "SYS_BLOCK", tmp_path)
    (tmp_path / "net" / "eth0" / "device").mkdir(parents=True)
    monkeypatch.setattr(monitor, "SYS_NET", tmp_path / "net")

    def cpu_times(*, percpu):
        assert percpu is True
        state.cpu_calls += 1
        return list(state.cpu)

    monkeypatch.setattr(monitor.psutil, "cpu_times", cpu_times)
    monkeypatch.setattr(monitor.psutil, "cpu_count", lambda: 2)
    monkeypatch.setattr(monitor.psutil, "disk_io_counters", lambda *, perdisk, nowrap: deepcopy(state.disks) if perdisk and not nowrap else pytest.fail("Counters must expose resets"))
    monkeypatch.setattr(monitor.psutil, "net_io_counters", lambda *, pernic, nowrap: deepcopy(state.net) if pernic and not nowrap else pytest.fail("Counters must expose resets"))
    monkeypatch.setattr(monitor.psutil, "net_if_stats", lambda: {"eth0": SimpleNamespace(isup=True, speed=1000)})
    monkeypatch.setattr(monitor.psutil, "virtual_memory", lambda: SimpleNamespace(total=10000, available=6000, percent=40.0, cached=2000))
    monkeypatch.setattr(monitor.psutil, "swap_memory", lambda: SimpleNamespace(total=2000, used=500, percent=25.0))
    monkeypatch.setattr(monitor.psutil, "pids", lambda: list(state.processes))
    # Exercise upstream's real iterator/cache with isolated fake processes.
    monkeypatch.setattr(monitor.psutil, "_pmap", {})
    monkeypatch.setattr(monitor.psutil, "_pids_reused", set())
    monkeypatch.setattr(monitor.psutil, "disk_partitions", lambda *, all: [])

    class Process:
        def __init__(self, pid):
            self.pid = pid
            self.row = state.processes[pid]
            self.started = self.row["start"]

        def oneshot(self):
            return nullcontext()

        def create_time(self):
            return self.started

        def name(self):
            return self.row["name"]

        def cpu_times(self):
            return SimpleNamespace(user=self.row["user"], system=self.row["system"])

        def memory_info(self):
            return SimpleNamespace(rss=self.row["rss"])

        def is_running(self):
            current = state.processes.get(self.pid)
            same_identity = current is not None and current["start"] == self.started
            if not same_identity:
                monitor.psutil._pids_reused.add(self.pid)
            return same_identity

    monkeypatch.setattr(monitor.psutil, "Process", Process)
    monkeypatch.setattr(inventory, "_cpu_sensor_snapshot", lambda *, include_utilization: {"device": "cpu", "name": "Test CPU", "status": "online", "physical_cores": 2} if not include_utilization else pytest.fail("Must not advance Settings CPU sample"))
    monkeypatch.setattr(inventory, "_igpu_sensor_snapshot", lambda: {"device": "amd-igpu", "name": "AMD", "status": "online"})

    def gpu_snapshot():
        state.gpu_calls += 1
        return [{"device": key, "name": key, "status": "online"} for key in inventory.GPU_DEVICES]

    monkeypatch.setattr(inventory, "gpu_snapshot", gpu_snapshot)
    monkeypatch.setattr(inventory, "storage_snapshot", lambda: {"schema": "obsidience.storage.v1", "filesystems": [], "locations": []})
    return state, monitor.HardwareMonitor()


def advance(state, seconds=2.0):
    state.clock += seconds
    state.cpu = [Times(row.user + seconds / 2, row.system, row.idle + seconds / 2, 0, 0) for row in state.cpu]
    state.disks["disk0"].read_bytes += 100 * seconds
    state.disks["disk0"].write_bytes += 200 * seconds
    state.disks["disk0"].busy_time += 500 * seconds
    state.net["eth0"].bytes_recv += 300 * seconds
    state.net["eth0"].bytes_sent += 400 * seconds
    state.processes[10]["user"] += seconds


def test_first_sample_is_private_bounded_and_has_no_fabricated_rates(sample):
    state, sampler = sample
    result = sampler.snapshot()
    assert result["schema"] == "obsidience.hardware-monitor.v1"
    assert result["interval_seconds"] is None
    assert result["cpu"]["utilization_percent"] is None
    assert result["cpu"]["per_core_percent"] == [None, None]
    assert result["storage"]["devices"][0]["read_bytes_per_second"] is None
    assert result["network"][0]["received_bytes_per_second"] is None
    assert result["processes"] == [{"pid": 10, "started_at": 40.0, "name": "worker", "cpu_percent": None, "memory_bytes": 100}]
    assert result["memory"] == {"total_bytes": 10000, "used_bytes": 4000, "available_bytes": 6000, "used_percent": 40.0, "cached_bytes": 2000, "swap_total_bytes": 2000, "swap_used_bytes": 500, "swap_used_percent": 25.0}
    assert result["problems"] == []
    assert state.cpu_calls == state.gpu_calls == 1


def test_real_deltas_cpu_normalization_cache_and_immutable_results(sample):
    state, sampler = sample
    first = sampler.snapshot()
    first["cpu"]["per_core_percent"][0] = 999
    state.clock += 1.99
    cached = sampler.snapshot()
    assert cached["sample_id"] == first["sample_id"]
    assert cached["cpu"]["per_core_percent"] == [None, None]
    assert state.cpu_calls == state.gpu_calls == 1
    state.clock = 100
    advance(state)
    current = sampler.snapshot()
    assert current["sample_id"] != first["sample_id"]
    assert current["interval_seconds"] == 2.0
    assert current["cpu"]["per_core_percent"] == [50.0, 50.0]
    assert current["cpu"]["utilization_percent"] == 50.0
    assert current["processes"][0]["cpu_percent"] == 50.0
    assert current["storage"]["devices"][0] == {"id": "disk:disk0", "name": "disk0", "read_bytes_per_second": 100.0, "write_bytes_per_second": 200.0, "io_busy_percent": 50.0}
    assert current["network"][0]["received_bytes_per_second"] == 300.0
    assert current["network"][0]["sent_bytes_per_second"] == 400.0


def test_cache_cadence_is_measured_from_sample_start_not_collection_end(sample, monkeypatch):
    state, sampler = sample
    original = inventory.gpu_snapshot

    def gpu():
        state.clock += 0.08
        return original()

    monkeypatch.setattr(inventory, "gpu_snapshot", gpu)
    first = sampler.snapshot()
    assert first["collection_ms"] == 80.0
    state.clock = 101.99
    assert sampler.snapshot()["sample_id"] == first["sample_id"]
    state.clock = 102.0
    second = sampler.snapshot()
    assert second["sample_id"] != first["sample_id"]
    assert second["interval_seconds"] == 2.0
    assert second["collection_ms"] == 80.0
    assert state.cpu_calls == state.gpu_calls == 2


def test_gap_counter_reset_and_pid_reuse_are_unavailable_then_recover(sample):
    state, sampler = sample
    sampler.snapshot()
    advance(state, 16)
    result = sampler.snapshot()
    assert result["interval_seconds"] is None
    assert result["cpu"]["utilization_percent"] is None
    assert result["processes"][0]["cpu_percent"] is None
    assert result["network"][0]["sent_bytes_per_second"] is None
    advance(state)
    state.cpu[0] = Times(0, 0, 0, 0, 0)
    state.disks["disk0"] = SimpleNamespace(read_bytes=0, write_bytes=0, busy_time=0)
    state.net["eth0"] = SimpleNamespace(bytes_recv=0, bytes_sent=0)
    state.processes[10].update(start=117.0, user=500.0)
    reset = sampler.snapshot()
    assert reset["cpu"]["per_core_percent"] == [None, 50.0]
    assert reset["cpu"]["utilization_percent"] is None
    assert reset["processes"] == []
    assert reset["storage"]["devices"][0]["io_busy_percent"] is None
    assert reset["network"][0]["sent_bytes_per_second"] is None
    advance(state)
    # psutil 7.2.2 removes reused identities after computing its new-PID set;
    # the following census discovers the replacement without stale fields.
    assert sampler.snapshot()["processes"] == []
    advance(state)
    regenerated = sampler.snapshot()["processes"][0]
    assert regenerated["started_at"] == 117.0
    assert regenerated["cpu_percent"] is None
    advance(state)
    assert sampler.snapshot()["processes"][0]["cpu_percent"] == 50.0


def test_cpu_guest_time_and_iowait_are_not_counted_as_extra_busy_time():
    before = Times(100, 20, 80, 0, 10)._asdict()
    current = Times(102, 20, 81, 1, 11)._asdict()
    assert monitor._cpu_percent(current, before) == 50.0
    assert monitor._cpu_percent(current, current) is None


def test_monitor_cpu_sensor_mode_preserves_existing_sampler_default(monkeypatch):
    calls = []
    monkeypatch.setattr(inventory, "_cpu_utilization", lambda: calls.append(True) or 17.0)
    monkeypatch.setattr(inventory, "_memory_snapshot", lambda: (100, 60, 40))
    monkeypatch.setattr(inventory, "_hwmon", lambda name: None)
    monkeypatch.setattr(inventory, "_cpu_clock_mhz", lambda: 1000)
    monkeypatch.setattr(inventory, "_physical_cpu_cores", lambda: 2)
    monkeypatch.setattr(inventory.os, "getloadavg", lambda: (0, 0, 0))
    assert inventory._cpu_sensor_snapshot(include_utilization=False)["utilization_percent"] is None
    assert calls == []
    assert inventory._cpu_sensor_snapshot()["utilization_percent"] == 17.0
    assert calls == [True]


def test_concurrent_panes_share_one_collection(sample, monkeypatch):
    state, sampler = sample
    entered, release = threading.Event(), threading.Event()

    def gpu():
        state.gpu_calls += 1
        entered.set()
        assert release.wait(3)
        return []

    monkeypatch.setattr(inventory, "gpu_snapshot", gpu)
    with ThreadPoolExecutor(max_workers=5) as pool:
        first = pool.submit(sampler.snapshot)
        assert entered.wait(3)
        others = [pool.submit(sampler.snapshot) for _ in range(4)]
        release.set()
        results = [first.result(timeout=3)] + [future.result(timeout=3) for future in others]
    assert len({row["sample_id"] for row in results}) == 1
    assert state.gpu_calls == state.cpu_calls == 1


def test_concurrent_callers_share_a_collection_that_exceeds_cache_ttl(sample, monkeypatch):
    state, sampler = sample
    entered, release, all_waiting = threading.Event(), threading.Event(), threading.Event()

    class ObservedLock:
        def __init__(self):
            self.inner = threading.Lock()
            self.counter_lock = threading.Lock()
            self.callers = 0

        def __enter__(self):
            with self.counter_lock:
                self.callers += 1
                if self.callers == 5:
                    all_waiting.set()
            self.inner.acquire()

        def __exit__(self, *args):
            self.inner.release()

    sampler._lock = ObservedLock()

    def gpu():
        state.gpu_calls += 1
        entered.set()
        assert release.wait(3)
        state.clock += 3
        return []

    monkeypatch.setattr(inventory, "gpu_snapshot", gpu)
    with ThreadPoolExecutor(max_workers=5) as pool:
        first = pool.submit(sampler.snapshot)
        assert entered.wait(3)
        others = [pool.submit(sampler.snapshot) for _ in range(4)]
        try:
            assert all_waiting.wait(3)
        finally:
            release.set()
        results = [first.result(timeout=3)] + [future.result(timeout=3) for future in others]
    assert len({row["sample_id"] for row in results}) == 1
    assert state.gpu_calls == state.cpu_calls == 1
    assert results[0]["collection_ms"] == 3000.0


def test_top_process_rows_sort_by_machine_cpu_then_memory(sample):
    state, sampler = sample
    state.processes = {pid: dict(start=40.0, name="x" * 200, user=0.0, system=0.0, rss=pid * 10) for pid in range(1, 42)}
    first = sampler.snapshot()
    assert len(first["processes"]) == 30
    assert first["processes"][0]["pid"] == 41
    state.clock += 2
    state.processes[1]["user"] = 2
    state.processes[2]["user"] = 2
    result = sampler.snapshot()
    assert [row["pid"] for row in result["processes"][:3]] == [2, 1, 41]
    assert all(len(row["name"]) == 80 for row in result["processes"])


def test_failures_are_local_sanitized_and_missing_baselines_do_not_bridge(sample, monkeypatch):
    state, sampler = sample
    sampler.snapshot()
    advance(state)
    original = monitor.psutil.net_io_counters

    def fail(**kwargs):
        raise PermissionError("private authenticated URL secret")

    monkeypatch.setattr(monitor.psutil, "net_io_counters", fail)
    monkeypatch.setattr(inventory, "gpu_snapshot", lambda: [])
    result = sampler.snapshot()
    assert result["cpu"]["utilization_percent"] == 50.0
    assert result["network"][0]["total_received_bytes"] is None
    assert result["network"][0]["received_bytes_per_second"] is None
    assert {row["device"] for row in result["gpus"] if row["status"] == "unavailable"} == set(inventory.GPU_DEVICES)
    assert "secret" not in json.dumps(result)
    monkeypatch.setattr(monitor.psutil, "net_io_counters", original)
    advance(state)
    assert sampler.snapshot()["network"][0]["received_bytes_per_second"] is None


def test_process_exit_access_denial_and_count_cap_are_explicit(sample, monkeypatch):
    state, sampler = sample
    state.processes = {pid: {} for pid in range(6)}
    monkeypatch.setattr(monitor, "MAX_PROCESSES", 3)

    class DeniedProcess:
        def __init__(self, pid):
            self.pid = pid

        def is_running(self):
            if self.pid == 0:
                raise monitor.psutil.NoSuchProcess(self.pid)
            raise monitor.psutil.AccessDenied(self.pid, "secret")

    monkeypatch.setattr(monitor.psutil, "Process", DeniedProcess)
    result = sampler.snapshot()
    assert result["processes"] == []
    assert len([row for row in result["problems"] if row["component"] == "processes"]) == 2
    assert "secret" not in json.dumps(result)


def test_descheduling_does_not_turn_a_finite_census_into_a_partial_scan(sample, monkeypatch):
    state, sampler = sample
    state.processes = {pid: dict(start=40.0, name="worker", user=0, system=0, rss=10) for pid in range(20)}
    original = monitor.psutil.Process

    def process(pid):
        state.clock += 0.3
        return original(pid)

    monkeypatch.setattr(monitor.psutil, "Process", process)
    result = sampler.snapshot()
    assert len(result["processes"]) == 20
    assert not any(row["component"] == "processes" for row in result["problems"])


def test_pid_reused_during_oneshot_is_discarded_and_regenerated(sample, monkeypatch):
    state, sampler = sample
    original = monitor.psutil.Process.memory_info

    def replaced_during_read(process):
        value = original(process)
        state.processes[process.pid] = dict(start=101.0, name="replacement", user=100, system=0, rss=50)
        return value

    monkeypatch.setattr(monitor.psutil.Process, "memory_info", replaced_during_read)
    assert sampler.snapshot()["processes"] == []
    monkeypatch.setattr(monitor.psutil.Process, "memory_info", original)
    advance(state)
    assert sampler.snapshot()["processes"] == []
    advance(state)
    row = sampler.snapshot()["processes"][0]
    assert row == {"pid": 10, "started_at": 101.0, "name": "replacement", "cpu_percent": None, "memory_bytes": 50}


def test_network_marks_physical_interfaces_without_removing_virtual_details(sample, monkeypatch):
    state, sampler = sample
    state.net["lo"] = SimpleNamespace(bytes_recv=50, bytes_sent=50)
    state.net["virtual0"] = SimpleNamespace(bytes_recv=60, bytes_sent=60)
    monkeypatch.setattr(monitor.psutil, "net_if_stats", lambda: {
        name: SimpleNamespace(isup=True, speed=1000) for name in state.net
    })
    rows = sampler.snapshot()["network"]
    assert {row["id"]: row["is_physical"] for row in rows} == {
        "eth0": True, "lo": False, "virtual0": False,
    }
    assert all(row["received_bytes_per_second"] is None for row in rows)


def test_disk_rates_include_whole_physical_devices_once(sample):
    state, sampler = sample
    state.disks["disk0p1"] = state.disks["disk0"]
    state.disks["loop0"] = state.disks["disk0"]
    state.disks["nbd0"] = state.disks["disk0"]
    result = sampler.snapshot()
    assert [row["name"] for row in result["storage"]["devices"]] == ["disk0"]


def test_mounted_volume_capacity_is_deduplicated_and_preserves_location_mapping(sample, monkeypatch):
    state, sampler = sample
    location = {"id": "models", "filesystem_id": "filesystem:existing", "path": "/var/lib/ai"}
    monkeypatch.setattr(inventory, "storage_snapshot", lambda: {"schema": "obsidience.storage.v1", "filesystems": [{"id": "filesystem:existing", "source": "/dev/shared", "filesystem": "btrfs", "total_bytes": 100, "mount_points": ["/home", "/var/lib/ai"]}], "locations": [dict(location)]})
    partitions = [SimpleNamespace(device=device, mountpoint=mount, fstype=kind) for device, mount, kind in [
        ("/dev/shared", "/home", "btrfs"), ("/dev/shared", "/var/lib/ai", "btrfs"),
        ("/dev/root", "/", "btrfs"), ("/dev/root", "/var/log", "btrfs"),
        ("/dev/games", "/mnt/wow-drive", "ext4"), ("server:/data", "/network", "nfs"),
    ]]
    monkeypatch.setattr(monitor.psutil, "disk_partitions", lambda *, all: partitions)
    reads = []

    def usage(path):
        reads.append(path)
        return SimpleNamespace(total=1000, used=200, free=800, percent=20)

    monkeypatch.setattr(monitor.psutil, "disk_usage", usage)
    storage = sampler.snapshot()["storage"]
    assert len(storage["filesystems"]) == 3
    assert storage["locations"] == [location]
    assert reads == ["/", "/mnt/wow-drive"]
    assert next(row for row in storage["filesystems"] if row["source"] == "/dev/root")["mount_points"] == ["/", "/var/log"]


def test_monitor_route_is_get_only_and_does_not_read_or_mutate_configuration(sample, monkeypatch):
    _, sampler = sample
    api = importlib.import_module("obsidience.harness.interfaces.api.app")
    monkeypatch.setattr(monitor, "MONITOR", sampler)
    monkeypatch.setattr(api.model_runtime, "hardware_catalog", lambda: pytest.fail("Monitor must not reconcile model runtime"))
    monkeypatch.setattr(api.model_runtime, "settings", lambda: pytest.fail("Monitor must not access settings"))
    monkeypatch.setattr(api.media_runtime, "interface_catalog", lambda: pytest.fail("Monitor must not query media configuration"))
    client = TestClient(api.app)
    result = client.get("/api/hardware/monitor")
    assert result.status_code == 200
    assert result.json()["schema"] == "obsidience.hardware-monitor.v1"
    assert client.post("/api/hardware/monitor", json={}).status_code == 405
    assert client.patch("/api/hardware/monitor", json={}).status_code == 405
    assert client.delete("/api/hardware/monitor").status_code == 405

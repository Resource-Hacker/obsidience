"""Stable facts distinguish a complete removal from an unavailable inventory."""

import json
import subprocess
from types import SimpleNamespace

import pytest

from obsidience.harness import config
from obsidience.harness.host import system_evidence as evidence


@pytest.fixture
def categories(monkeypatch):
    for category in ("identity", "compute", "storage", "devices", "network", "applications", "runtime"):
        monkeypatch.setattr(evidence, "_" + category, lambda: {"stable": True})


def test_complete_categories_are_deterministic_and_failure_never_means_absence(categories, monkeypatch):
    def unavailable():
        raise PermissionError("private host diagnostic must not enter metadata")
    monkeypatch.setattr(evidence, "_devices", unavailable)
    monkeypatch.setattr(evidence, "_network", lambda: {"interfaces": []})
    first = evidence.collect_system_evidence()
    assert first == evidence.collect_system_evidence()
    assert len(first) == 7 and first["network"] == {"status": "complete", "facts": {"interfaces": []}, "detail": ""}
    assert first["devices"]["status"] == "unavailable" and first["devices"]["facts"] == {}
    assert "private host" not in first["devices"]["detail"]
    assert "detail" not in first["identity"]["facts"]


def test_fact_bound_rejects_whole_category(categories, monkeypatch):
    monkeypatch.setattr(evidence, "MAX_FACT_BYTES", 30)
    monkeypatch.setattr(evidence, "_applications", lambda: {"applications": ["x" * 100]})
    result = evidence.collect_system_evidence()
    assert result["applications"]["status"] == "unavailable" and result["applications"]["facts"] == {}
    assert result["identity"]["status"] == "complete"


def endpoint(name="speaker", label="Speaker", path="pci-1"):
    return {"name": name, "description": label, "index": 999, "state": "RUNNING", "volume": {},
            "properties": {"media.class": "Audio/Sink", "device.bus_path": path,
                           "device.profile.name": "stereo", "object.path": "alsa:pcm:1"}}


def test_audio_duplicate_declarations_coalesce_without_telemetry(monkeypatch):
    first = endpoint()
    second = {**first, "index": 1000, "state": "SUSPENDED", "volume": {"front-left": 50}}
    monkeypatch.setattr(evidence.media, "_run_json", lambda command: [first, second])
    rows = evidence._audio("speakers")
    assert len(rows) == 1 and rows[0]["id"] == "speaker"
    assert not {"index", "state", "volume"}.intersection(rows[0])


@pytest.mark.parametrize("second", [endpoint(label="Different"), endpoint(path="pci-other")])
def test_audio_duplicate_conflicting_identity_rejected(monkeypatch, second):
    monkeypatch.setattr(evidence.media, "_run_json", lambda command: [endpoint(), second])
    with pytest.raises(ValueError, match="ambiguous"):
        evidence._audio("speakers")


def test_audio_failed_query_is_not_empty_inventory(monkeypatch):
    monkeypatch.setattr(evidence.media, "_run_json", lambda command: None)
    with pytest.raises(ValueError, match="unavailable"):
        evidence._audio("speakers")
    monkeypatch.setattr(evidence.media, "_run_json", lambda command: [])
    assert evidence._audio("speakers") == []


def test_audio_raw_response_bound_is_not_bypassed_by_dedup(monkeypatch):
    monkeypatch.setattr(evidence, "MAX_DEVICES", 2)
    monkeypatch.setattr(evidence.media, "_run_json", lambda command: [endpoint()] * 3)
    with pytest.raises(ValueError, match="bound"):
        evidence._audio("speakers")


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value)


def test_network_removal_is_complete_but_read_failure_is_not(tmp_path, monkeypatch):
    monkeypatch.setattr(evidence, "SYS", tmp_path)
    root = tmp_path / "class/net"
    write(root / "lo/type", "772")
    write(root / "enp1/type", "1")
    write(root / "enp1/operstate", "down")
    before = evidence._network()
    write(root / "enp1/operstate", "up")
    assert evidence._network() == before
    (root / "enp1/type").unlink()
    with pytest.raises(FileNotFoundError):
        evidence._network()
    (root / "enp1/operstate").unlink()
    (root / "enp1").rmdir()
    assert evidence._network() == {"interfaces": []}


def test_compute_gpu_removal_and_memory_capacity_exclude_usage(tmp_path, monkeypatch):
    monkeypatch.setattr(evidence, "PROC", tmp_path / "proc")
    monkeypatch.setattr(evidence, "SYS", tmp_path / "sys")
    write(evidence.PROC / "cpuinfo", "processor: 0\nmodel name: Test CPU\nphysical id: 0\ncore id: 0\n\nprocessor: 1\nmodel name: Test CPU\nphysical id: 0\ncore id: 0\n")
    write(evidence.PROC / "meminfo", "MemTotal: 1024 kB\nMemFree: 500 kB\n")
    gpu = evidence.SYS / "bus/pci/devices/0000:01:00.0"
    for name, value in {"class": "0x030000", "vendor": "0x10de", "device": "0x1234"}.items():
        write(gpu / name, value)
    first = evidence._compute()
    assert first["cpu"]["physical_cores"] == 1 and first["cpu"]["logical_cpus"] == 2
    assert first["memory"] == {"total_bytes": 1024 * 1024} and len(first["gpus"]) == 1
    write(evidence.PROC / "meminfo", "MemTotal: 1024 kB\nMemFree: 100 kB\n")
    assert evidence._compute() == first
    for path in gpu.iterdir():
        path.unlink()
    gpu.rmdir()
    assert evidence._compute()["gpus"] == []


def desktop(path, label, extra=""):
    write(path, f"[Desktop Entry]\nType=Application\nName={label}\nExec=/bin/true\n{extra}")


def test_applications_existing_precedence_hidden_entries_and_exact_labels(tmp_path, monkeypatch):
    system, user = tmp_path / "system", tmp_path / "user"
    desktop(system / "app.desktop", "Old")
    desktop(user / "app.desktop", "Current")
    desktop(system / "hidden.desktop", "Hidden", "NoDisplay=true\n")
    monkeypatch.setattr(evidence.packagekit, "DESKTOP_ROOTS", (system, user))
    monkeypatch.setattr(evidence.packagekit, "_run", lambda *args, **kwargs: pytest.fail("No package processes"))
    assert evidence._applications()["applications"] == [{"desktop_id": "app.desktop", "label": "Current"}]
    desktop(user / "app.desktop", "x" * 161)
    with pytest.raises(ValueError, match="bound"):
        evidence._applications()


def test_applications_bound_and_unreadable_root_never_report_partial_inventory(tmp_path, monkeypatch):
    desktop(tmp_path / "first.desktop", "First")
    desktop(tmp_path / "second.desktop", "Second")
    monkeypatch.setattr(evidence.packagekit, "DESKTOP_ROOTS", (tmp_path,))
    monkeypatch.setattr(evidence, "MAX_APPLICATIONS", 1)
    with pytest.raises(ValueError, match="bound"):
        evidence._applications()
    def denied(path, limit):
        raise PermissionError("unreadable root")
    monkeypatch.setattr(evidence, "_entries", denied)
    with pytest.raises(PermissionError):
        evidence._applications()


def test_runtime_reads_saved_assignments_without_live_model_discovery(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    media_path = tmp_path / "media.json"
    monkeypatch.setattr(evidence.media, "MEDIA_SETTINGS_PATH", media_path)
    ids = (evidence.inventory.CPU_DEVICE, evidence.inventory.IGPU_DEVICE, *evidence.inventory.GPU_DEVICES)
    hardware = {identifier: "none" for identifier in ids}
    write(config.CONFIG.runtime_dir / "model-settings.json", json.dumps({"schema_version": 2, "hardware": hardware}))
    write(media_path, json.dumps({"schema_version": 3, "microphone": "mic", "speaker": "speaker", "camera": "camera", "tts_voice": "hal"}))
    result = evidence._runtime()
    assert result["hardware_assignments"] == hardware
    assert result["speech"]["voice"] == "hal" and "residency is not attested" in result["scope"]
    media_path.write_text(json.dumps({"schema_version": 999, "microphone": "mic", "speaker": "speaker", "camera": "camera", "tts_voice": "hal"}))
    with pytest.raises(ValueError, match="unavailable"):
        evidence._runtime()
    media_path.write_text("invalid-json")
    with pytest.raises(ValueError):
        evidence._runtime()


def block(name="/dev/nvme0n1", serial="disk-a", **fields):
    return {"name": name, "kname": name, "type": "disk", "model": "Test SSD",
            "serial": serial, "wwn": "wwn-" + serial if serial else None, "size": 1_000_000,
            "tran": "nvme", "ro": False, "fstype": None, "uuid": None,
            "partuuid": None, "mountpoints": [], **fields}


def lsblk(monkeypatch, rows):
    def run(command, **kwargs):
        assert command == evidence.LSBLK_COMMAND
        assert command[:5] == ("/usr/bin/lsblk", "--json", "--bytes", "--paths", "--tree")
        assert kwargs == {"stdin": subprocess.DEVNULL, "stdout": subprocess.PIPE,
                          "stderr": subprocess.DEVNULL, "check": False, "timeout": 3}
        return SimpleNamespace(returncode=0, stdout=json.dumps({"blockdevices": rows}).encode())
    monkeypatch.setattr(evidence.subprocess, "run", run)


def test_physical_drives_keep_stable_identity_and_nested_details(monkeypatch):
    partition = block("/dev/nvme0n1p1", type="part", serial=None, size=900_000,
                      fstype="btrfs", uuid="filesystem-a", partuuid="partition-a",
                      mountpoints=["/var/lib/ai", "/home", None])
    disk = block(children=[partition])
    other = block("/dev/nvme2n1", "disk-b", ro=True, mountpoints=["/external"])
    virtual = [block("/dev/" + name, model=None, serial=None, size=0)
               for name in ("nbd0", "zram0", "loop0", "ram0")]
    lsblk(monkeypatch, [other, *virtual, disk])
    before = evidence._physical_drives()
    assert [row["id"] for row in before] == ["serial:disk-a", "serial:disk-b"]
    assert before[0]["partitions"][0]["mount_points"] == ["/home", "/var/lib/ai"]
    assert before[0]["partitions"][0]["partuuid"] == "partition-a"
    assert before[1]["read_only"] is True and before[1]["mount_points"] == ["/external"]
    assert not {"free", "available_bytes", "usage", "temperature"}.intersection(before[0])
    lsblk(monkeypatch, [disk, other, *virtual])
    assert evidence._physical_drives() == before
    disk["name"] = disk["kname"] = "/dev/nvme8n1"
    partition["name"] = partition["kname"] = "/dev/nvme8n1p1"
    after = evidence._physical_drives()
    assert after[0]["id"] == before[0]["id"] and after[0]["device"] == "/dev/nvme8n1"
    assert after[0]["serial"] == before[0]["serial"] and after[0]["model"] == before[0]["model"]


@pytest.mark.parametrize("change", [
    {"serial": None}, {"model": ""}, {"size": 0}, {"size": True}, {"ro": None},
    {"mountpoints": "/home"}, {"children": {}}, {"name": "/tmp/fake"},
])
def test_incomplete_drive_fails_whole_storage_inventory(monkeypatch, change):
    lsblk(monkeypatch, [block(), {**block("/dev/nvme2n1", "disk-b"), **change}])
    with pytest.raises(ValueError):
        evidence._physical_drives()


@pytest.mark.parametrize("second", [
    block("/dev/nvme1n1", "disk-a"),
    block("/dev/nvme1n1", "disk-b", wwn="WWN-DISK-A"),
    block("/dev/nvme0n1", "disk-b"),
])
def test_duplicate_drive_identities_are_rejected(monkeypatch, second):
    lsblk(monkeypatch, [block(), second])
    with pytest.raises(ValueError, match="ambiguous"):
        evidence._physical_drives()


def test_partition_order_is_deterministic_and_duplicates_rejected(monkeypatch):
    first = block("/dev/nvme0n1p1", type="part", partuuid="a", mountpoints=["/z", "/a"])
    second = block("/dev/nvme0n1p2", type="part", partuuid="b")
    disk = block(children=[second, first])
    lsblk(monkeypatch, [disk])
    before = evidence._physical_drives()
    disk["children"].reverse()
    first["mountpoints"].reverse()
    assert evidence._physical_drives() == before
    disk["children"].append(first)
    with pytest.raises(ValueError, match="duplicate"):
        evidence._physical_drives()


def test_block_inventory_bounds_reject_instead_of_truncating(monkeypatch):
    lsblk(monkeypatch, [block(), block("/dev/nvme1n1", "disk-b")])
    monkeypatch.setattr(evidence, "MAX_DEVICES", 1)
    with pytest.raises(ValueError, match="bound"):
        evidence._physical_drives()
    lsblk(monkeypatch, [block(children=[block("/dev/nvme0n1p1", type="part")])])
    with pytest.raises(ValueError, match="bound"):
        evidence._physical_drives()
    monkeypatch.setattr(evidence, "MAX_DEVICES", 256)
    monkeypatch.setattr(evidence, "MAX_BYTES", 8)
    with pytest.raises(ValueError, match="byte bound"):
        evidence._physical_drives()


def test_block_topology_depth_is_bounded(monkeypatch):
    disk = block(); current = disk
    for depth in range(10):
        child = block(f"/dev/mapper/child-{depth}", type="crypt")
        current["children"] = [child]; current = child
    lsblk(monkeypatch, [disk])
    with pytest.raises(ValueError, match="bound"):
        evidence._physical_drives()


@pytest.mark.parametrize("failure", ["timeout", "exit", "malformed", "missing"])
def test_lsblk_failure_is_unavailable_and_never_empty_or_raw_diagnostic(categories, monkeypatch, failure):
    def run(*args, **kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired("private command", 3, output=b"private output")
        return SimpleNamespace(returncode=1 if failure == "exit" else 0,
                               stdout=b"private diagnostic" if failure == "malformed" else b"{}")
    monkeypatch.setattr(evidence.subprocess, "run", run)
    monkeypatch.setattr(evidence, "_storage", lambda: {"drives": evidence._physical_drives()})
    result = evidence.collect_system_evidence()["storage"]
    assert result["status"] == "unavailable" and result["facts"] == {}
    assert "private" not in result["detail"]


def test_storage_preserves_locations_beside_physical_disks(tmp_path, monkeypatch):
    monkeypatch.setattr(evidence, "PROC", tmp_path / "proc")
    write(evidence.PROC / "self/mountinfo", "1 0 8:1 / / rw - btrfs /dev/test rw\n")
    monkeypatch.setattr(evidence.inventory, "STORAGE_LOCATIONS", (("obsidience", "Obsidience", "project", tmp_path),))
    monkeypatch.setattr(evidence.os, "statvfs", lambda path: SimpleNamespace(f_frsize=4096, f_bsize=4096, f_blocks=100))
    lsblk(monkeypatch, [block()])
    result = evidence._storage()
    assert result["locations"][0]["id"] == "obsidience"
    assert result["locations"][0]["allocation"] == "shared_filesystem"
    assert result["locations"][0]["total_bytes"] == 409_600
    assert result["drives"][0]["serial"] == "disk-a"


def system_node(key, **descriptor):
    return {"key": key, "path": key + ".json", "descriptor_path": key + ".json",
            "descriptor": descriptor or None}


def test_drive_projection_uses_serial_model_and_wwn_not_device_number(monkeypatch):
    lsblk(monkeypatch, [block()])
    drive = evidence._physical_drives()[0]
    inventory = {"storage": {"status": "complete", "facts": {"drives": [drive]}}}
    node = system_node("hardware/drives/test", selector="disk-a", model="Test SSD", wwn="wwn-disk-a")
    assert evidence.system_node_facts(node, inventory)["observed"] == drive
    drive["device"] = "/dev/nvme7n1"
    assert evidence.system_node_facts(node, inventory)["observed"]["device"] == "/dev/nvme7n1"
    for field in ("selector", "model", "wwn"):
        changed = {**node, "descriptor": {**node["descriptor"], field: "wrong"}}
        with pytest.raises(ValueError):
            evidence.system_node_facts(changed, inventory)
    inventory["storage"]["facts"]["drives"].append(drive)
    with pytest.raises(ValueError, match="one observed device"):
        evidence.system_node_facts(node, inventory)


def test_application_storage_and_direct_network_keep_exact_schema_projection():
    locations = [{"id": "obsidience", "allocation": "shared_filesystem"}]
    inventory = {"storage": {"status": "complete", "facts": {"locations": locations}},
                 "network": {"status": "complete", "facts": {"interfaces": [{"id": "enp1"}]}}}
    app = system_node("applications/obsidience", selector="obsidience")
    assert evidence.system_node_facts(app, inventory)["observed"] == {"storage_locations": locations}
    assert evidence.system_node_facts(system_node("hardware/network", selector="interfaces"), inventory)["observed"] == inventory["network"]["facts"]
    assert "observed" not in evidence.system_node_facts(system_node("hardware/network/connections"), inventory)
    inventory["storage"]["status"] = "unavailable"
    with pytest.raises(ValueError, match="unavailable"):
        evidence.system_node_facts(app, inventory)

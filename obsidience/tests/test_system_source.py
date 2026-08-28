"""Physical System descriptors are Source files, not synthesized telemetry."""

from __future__ import annotations

import json
from pathlib import Path

from obsidience.harness.knowledge import source


PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXPECTED = {
    "obsidience/state/system/applications/obsidience/application.json",
    "obsidience/state/system/applications/obsidience/model-assignments.json",
    "obsidience/state/system/applications/obsidience/speech-runtime.json",
    "obsidience/state/system/applications/web-browser/application.json",
    "obsidience/state/system/hardware/compute/amd-igpu.json",
    "obsidience/state/system/hardware/compute/cpu.json",
    "obsidience/state/system/hardware/compute/rtx-4000-ada.json",
    "obsidience/state/system/hardware/compute/rtx-4080-super.json",
    "obsidience/state/system/hardware/devices/camera.json",
    "obsidience/state/system/hardware/devices/microphone.json",
    "obsidience/state/system/hardware/devices/speaker.json",
    "obsidience/state/system/hardware/drives/system-volume/ai-models.json",
    "obsidience/state/system/hardware/drives/system-volume/obsidience.json",
    "obsidience/state/system/network/connections.json",
    "obsidience/state/system/system.json",
}


def test_system_source_is_stable_physical_descriptors() -> None:
    system_rows = {
        row["key"]: row
        for row in source.list_source_files()["files"]
        if row["storage"] == "system"
    }
    assert set(system_rows) == EXPECTED

    for key, row in system_rows.items():
        path = PROJECT_ROOT / key
        assert path.is_file() and not path.is_symlink()
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["schema"] == "obsidience.system-node.v1"
        assert payload["read_only"] is True
        assert payload["collector"].startswith("obsidience.harness.")
        assert row["path"] == key
        assert row["modified_at"] == path.stat().st_mtime
        assert source.get_source_file(key)["content"] == path.read_text(encoding="utf-8")


def test_reading_system_source_does_not_rewrite_it() -> None:
    key = "obsidience/state/system/hardware/compute/rtx-4080-super.json"
    path = PROJECT_ROOT / key
    before = (path.read_bytes(), path.stat().st_mtime_ns)
    source.get_source_file(key)
    source.list_source_files()
    after = (path.read_bytes(), path.stat().st_mtime_ns)
    assert after == before


def test_hardware_descriptors_use_the_system_inventory_collector() -> None:
    for key in sorted(
        path for path in EXPECTED
        if path.startswith("obsidience/state/system/hardware/compute/")
    ):
        payload = json.loads((PROJECT_ROOT / key).read_text(encoding="utf-8"))
        assert payload["collector"] == (
            "obsidience.harness.host.inventory.hardware_sensor_snapshot"
        )


def test_storage_descriptors_use_the_host_storage_collector() -> None:
    for key in sorted(
        path for path in EXPECTED
        if path.startswith("obsidience/state/system/hardware/drives/")
    ):
        payload = json.loads((PROJECT_ROOT / key).read_text(encoding="utf-8"))
        assert payload["collector"] == (
            "obsidience.harness.host.inventory.storage_snapshot"
        )
        assert payload["allocation"] == "shared_filesystem"
        assert payload["quota_bytes"] is None
        assert payload["live_data_endpoint"] == "/api/hardware"


def test_application_and_system_descriptors_have_real_collectors() -> None:
    for key in (
        "obsidience/state/system/applications/obsidience/application.json",
        "obsidience/state/system/applications/web-browser/application.json",
    ):
        payload = json.loads((PROJECT_ROOT / key).read_text(encoding="utf-8"))
        assert payload["collector"] == (
            "obsidience.harness.host.inventory.application_snapshot"
        )
        assert payload["live_data_endpoint"] == "/api/system"

    for key in (
        "obsidience/state/system/system.json",
        "obsidience/state/system/network/connections.json",
    ):
        payload = json.loads((PROJECT_ROOT / key).read_text(encoding="utf-8"))
        assert payload["collector"] == (
            "obsidience.harness.host.inventory.system_snapshot"
        )
        assert payload["live_data_endpoint"] == "/api/system"

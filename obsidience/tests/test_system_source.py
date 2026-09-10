"""Physical System descriptors are Source files, not synthesized telemetry."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys

import pytest

from obsidience.harness import config
from obsidience.harness.host import inventory
from obsidience.harness.knowledge import source, system_schema, vault


PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXPECTED = {
    "obsidience/state/system/applications/obsidience/application.json",
    "obsidience/state/system/applications/obsidience/model-assignments.json",
    "obsidience/state/system/applications/obsidience/speech-runtime.json",
    "obsidience/state/system/applications/web-browser.json",
    "obsidience/state/system/hardware/compute/amd-igpu.json",
    "obsidience/state/system/hardware/compute/cpu.json",
    "obsidience/state/system/hardware/compute/rtx-4000-ada.json",
    "obsidience/state/system/hardware/compute/rtx-4080-super.json",
    "obsidience/state/system/hardware/devices/camera.json",
    "obsidience/state/system/hardware/devices/microphone.json",
    "obsidience/state/system/hardware/devices/speaker.json",
    "obsidience/state/system/hardware/drives/crucial-t705.json",
    "obsidience/state/system/hardware/drives/samsung-990-pro-games.json",
    "obsidience/state/system/hardware/drives/samsung-990-pro-storage.json",
    "obsidience/state/system/hardware/drives/samsung-990-pro-windows.json",
    "obsidience/state/system/hardware/network.json",
    "obsidience/state/system/system.json",
}


@pytest.fixture(autouse=True)
def isolated_descriptors(monkeypatch, tmp_path):
    """Descriptor tests must not mix live snapshot files with the isolated ledger."""
    for key in EXPECTED:
        target = tmp_path / key
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PROJECT_ROOT / key, target)
    monkeypatch.setattr(sys.modules[__name__], "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config.CONFIG, "vault_dir", tmp_path / "obsidience/vault")
    monkeypatch.setattr(vault, "iter_notes", lambda: [])


def test_system_source_is_stable_physical_descriptors() -> None:
    system_rows = {
        row["key"]: row
        for row in source.list_source_files(scope="obsidience/state/system")["files"]
        if row["storage"] == "system" and row["key"].endswith(".json")
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


def test_system_source_labels_and_breadcrumbs_follow_the_physical_schema() -> None:
    catalog = system_schema.system_schema()
    assert len(catalog) == 22
    assert {row["descriptor_path"] for row in catalog if row["descriptor_path"]} == EXPECTED
    rows = {row["key"]: row for row in source.list_source_files(scope="obsidience/state/system")["files"]}
    assert set(rows) == EXPECTED
    for item in catalog:
        if item["descriptor_path"]:
            row = rows[item["descriptor_path"]]
            assert row["system_label"] == item["title"]
            assert row["read_only"] is True
            assert row["system_breadcrumbs"][0] == {"path": "obsidience/state/system", "title": "System"}
    network = rows["obsidience/state/system/hardware/network.json"]
    assert [crumb["path"] for crumb in network["system_breadcrumbs"]] == [
        "obsidience/state/system", "obsidience/state/system/hardware"]
    browser = rows["obsidience/state/system/applications/web-browser.json"]
    assert [crumb["path"] for crumb in browser["system_breadcrumbs"]] == [
        "obsidience/state/system", "obsidience/state/system/applications"]
    for filename, label in (("camera", "Cameras"), ("microphone", "Microphones"), ("speaker", "Speakers")):
        assert rows[f"obsidience/state/system/hardware/devices/{filename}.json"]["system_label"] == label


@pytest.mark.parametrize("category", [
    "identity", "compute", "storage", "devices", "network", "applications", "runtime",
    "schema.hardware.compute.cpu",
])
def test_recorded_system_evidence_stays_outside_immutable_schema(category, monkeypatch) -> None:
    before = {key: ((PROJECT_ROOT / key).read_bytes(), (PROJECT_ROOT / key).stat().st_mtime_ns)
              for key in EXPECTED}
    monkeypatch.setattr(source, "_source_event", lambda *_args: pytest.fail("System capture emitted an agent event"))
    capture = source.capture_system_evidence(category, {"fixture": category})
    assert capture["source_event"] is None
    key = capture["source_path"]
    assert key.startswith("obsidience/evidence/system/" + category + "/")
    assert source.get_source(capture["citation"])["id"] == capture["id"]
    recorded = source.list_source_files(scope="obsidience/evidence/system")["files"]
    row, = recorded
    assert row["key"] == key and row["source_id"] == capture["id"]
    assert row["storage"] == "blob" and row["read_only"] is True
    assert source.get_source_file(key)["source_id"] == capture["id"]
    assert {row["key"] for row in source.list_source_files(scope="obsidience/state/system")["files"]} == EXPECTED
    assert {key: ((PROJECT_ROOT / key).read_bytes(), (PROJECT_ROOT / key).stat().st_mtime_ns)
            for key in EXPECTED} == before


@pytest.mark.parametrize("category", [
    "invented", "schema.hardware.compute.nonexistent", "schema.hardware/compute/cpu", "schema...cpu",
])
def test_unknown_capture_category_cannot_forge_a_system_schema_node(category, isolated_task_ledger) -> None:
    with pytest.raises(source.SourceError, match="System evidence"):
        source.capture_system_evidence(category, {"fake": True})
    assert isolated_task_ledger.db.execute("SELECT count(*) FROM source_evidence").fetchone()[0] == 0
    assert not config.CONFIG.source_dir.exists()


def test_hardware_descriptors_use_the_system_inventory_collector() -> None:
    for key in sorted(
        path for path in EXPECTED
        if path.startswith("obsidience/state/system/hardware/compute/")
    ):
        payload = json.loads((PROJECT_ROOT / key).read_text(encoding="utf-8"))
        assert payload["collector"] == (
            "obsidience.harness.host.inventory.hardware_sensor_snapshot"
        )


def test_drive_descriptors_select_exact_physical_disks() -> None:
    disks = {
        "crucial-t705": ("2407E897AB30", "CT1000T705SSD5", "uuid.e6533516-bf6a-44b3-a940-c039b54f34dd"),
        "samsung-990-pro-games": ("S73WNU0XB11863P", "Samsung SSD 990 PRO 2TB", "eui.0025384b41a2c2c7"),
        "samsung-990-pro-storage": ("S7KHNU0X757355N", "Samsung SSD 990 PRO 2TB", "eui.0025384741a25c94"),
        "samsung-990-pro-windows": ("S73WNU0XB11923L", "Samsung SSD 990 PRO 2TB", "eui.0025384b41a2c303"),
    }
    root = PROJECT_ROOT / "obsidience/state/system/hardware/drives"
    assert {path.name for path in root.iterdir()} == {name + ".json" for name in disks}
    for name, identity in disks.items():
        payload = json.loads((root / (name + ".json")).read_text(encoding="utf-8"))
        assert payload["collector"] == (
            "obsidience.harness.host.system_evidence._storage"
        )
        assert (payload["selector"], payload["model"], payload["wwn"]) == identity


def test_application_and_system_descriptors_have_real_collectors() -> None:
    for key in (
        "obsidience/state/system/applications/obsidience/application.json",
        "obsidience/state/system/applications/web-browser.json",
    ):
        payload = json.loads((PROJECT_ROOT / key).read_text(encoding="utf-8"))
        assert payload["collector"] == (
            "obsidience.harness.host.inventory.application_snapshot"
        )
        assert payload["live_data_endpoint"] == "/api/system"


def test_obsidience_application_descriptor_matches_live_inventory(monkeypatch) -> None:
    monkeypatch.setattr(
        inventory,
        "_command_value",
        lambda command: "active" if command[0] == "systemctl" else "browser.desktop",
    )
    descriptor = json.loads(
        (
            PROJECT_ROOT
            / "obsidience/state/system/applications/obsidience/application.json"
        ).read_text(encoding="utf-8")
    )
    live = inventory.application_snapshot()["obsidience"]
    for field in ("id", "role", "state", "compositor_boundary", "service"):
        assert descriptor[field] == live[field]
    assert {
        key: value
        for key, value in descriptor["components"].items()
        if key != "software_management"
    } == live["components"]

    for key in (
        "obsidience/state/system/system.json",
        "obsidience/state/system/hardware/network.json",
    ):
        payload = json.loads((PROJECT_ROOT / key).read_text(encoding="utf-8"))
        assert payload["collector"] == (
            "obsidience.harness.host.inventory.system_snapshot"
        )
        assert payload["live_data_endpoint"] == "/api/system"

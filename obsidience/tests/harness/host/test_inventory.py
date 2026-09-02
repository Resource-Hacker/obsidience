"""System owns physical device identity and read-only telemetry."""

from __future__ import annotations

from types import SimpleNamespace

from obsidience.harness.models import runtime as model_runtime
from obsidience.harness.host import inventory


def test_sensor_aggregation_keeps_only_known_devices(monkeypatch) -> None:
    monkeypatch.setattr(
        inventory,
        "_cpu_sensor_snapshot",
        lambda: {"device": inventory.CPU_DEVICE, "status": "online"},
    )
    monkeypatch.setattr(
        inventory,
        "_igpu_sensor_snapshot",
        lambda: {"device": inventory.IGPU_DEVICE, "status": "online"},
    )
    monkeypatch.setattr(
        inventory,
        "gpu_snapshot",
        lambda: [
            {"device": inventory.RTX_4080_DEVICE, "status": "online"},
            {"device": inventory.RTX_4000_DEVICE, "status": "online"},
            {"device": None, "status": "online"},
        ],
    )

    assert set(inventory.hardware_sensor_snapshot()) == {
        inventory.CPU_DEVICE,
        inventory.IGPU_DEVICE,
        inventory.RTX_4080_DEVICE,
        inventory.RTX_4000_DEVICE,
    }


def test_nvidia_csv_projection(monkeypatch) -> None:
    row = ", ".join([
        inventory.GPU_UUIDS[inventory.RTX_4080_DEVICE],
        "NVIDIA GeForce RTX 4080 SUPER",
        "P3", "55", "33.73", "352", "1200", "5001", "4", "6",
        "0", "0", "16376", "4989", "10941", "0", "4", "8",
    ])
    monkeypatch.setattr(
        inventory.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout=row + "\n"),
    )

    result = inventory.gpu_snapshot()
    assert result == [{
        "device": inventory.RTX_4080_DEVICE,
        "uuid": inventory.GPU_UUIDS[inventory.RTX_4080_DEVICE],
        "name": "NVIDIA GeForce RTX 4080 SUPER",
        "driver": "nvidia",
        "status": "online",
        "memory_label": "VRAM",
        "memory_total_mib": 16376,
        "memory_used_mib": 4989,
        "memory_free_mib": 10941,
        "memory_used_percent": 30.5,
        "utilization_percent": 4,
        "memory_controller_percent": 6,
        "encoder_percent": 0,
        "decoder_percent": 0,
        "temperature_c": 55.0,
        "power_w": 33.73,
        "power_limit_w": 352.0,
        "clock_core_mhz": 1200,
        "clock_memory_mhz": 5001,
        "fan_percent": 0,
        "pstate": "P3",
        "pcie_generation": 4,
        "pcie_width": 8,
    }]


def test_models_consume_the_system_telemetry_contract() -> None:
    assert model_runtime.gpu_snapshot is inventory.gpu_snapshot
    assert model_runtime.hardware_sensor_snapshot is inventory.hardware_sensor_snapshot
    assert model_runtime.GPU_DEVICES == inventory.GPU_DEVICES


def test_application_inventory_distinguishes_shell_from_external_browser(
    monkeypatch,
) -> None:
    def command_value(command: list[str]) -> str:
        return "active" if command[0] == "systemctl" else "browser.desktop"

    monkeypatch.setattr(inventory, "_command_value", command_value)
    applications = inventory.application_snapshot()

    assert applications["obsidience"]["role"] == "desktop-shell"
    assert applications["obsidience"]["compositor_boundary"] == "Hyprland"
    assert "replacement_target" not in applications["obsidience"]
    assert applications["obsidience"]["service_state"] == "active"
    assert applications["obsidience"]["service"] == (
        "obsidience-shell-host.service"
    )
    assert applications["obsidience"]["components"] == {
        "session": "obsidience-shell-session.target",
        "shell": "obsidience-shell-host.service",
        "knowledge": "obsidience-shell-knowledge.service",
        "notifications": "obsidience-shell-notifications.service",
        "harness": "obsidience-harness-dev.service",
    }
    assert applications["web-browser"]["integrated"] is False
    assert applications["web-browser"]["default_desktop_entry"] == "browser.desktop"


def test_storage_groups_product_and_models_on_one_shared_filesystem(
    monkeypatch, tmp_path,
) -> None:
    product = tmp_path / "obsidience"
    models = tmp_path / "ai"
    product.mkdir()
    models.mkdir()
    monkeypatch.setattr(inventory, "STORAGE_LOCATIONS", (
        ("obsidience", "Obsidience", "product", product),
        ("models", "AI Models", "models", models),
    ))
    monkeypatch.setattr(inventory, "_mount_records", lambda: [{
        "device_id": "0:42",
        "root": "/@home",
        "mount_point": str(tmp_path),
        "filesystem": "btrfs",
        "source": "/dev/test",
    }])
    monkeypatch.setattr(
        inventory.os,
        "statvfs",
        lambda _path: SimpleNamespace(
            f_frsize=4096,
            f_bsize=4096,
            f_blocks=100,
            f_bfree=25,
            f_bavail=20,
        ),
    )

    snapshot = inventory.storage_snapshot()

    assert len(snapshot["filesystems"]) == 1
    assert snapshot["filesystems"][0]["total_bytes"] == 409_600
    assert snapshot["filesystems"][0]["used_percent"] == 75.0
    assert [row["filesystem_id"] for row in snapshot["locations"]] == [
        "filesystem:0:42", "filesystem:0:42",
    ]
    assert all(row["allocation"] == "shared_filesystem" for row in snapshot["locations"])
    assert all(row["quota_bytes"] is None for row in snapshot["locations"])

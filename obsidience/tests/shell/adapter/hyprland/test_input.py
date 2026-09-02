"""Input state remains a projection of hardware and compositor truth."""

from __future__ import annotations

from obsidience.shell.adapter.hyprland import input as input_adapter


def test_input_snapshot_reports_live_800_effective_profile(monkeypatch) -> None:
    monkeypatch.setattr(
        input_adapter,
        "_profile_status",
        lambda: {
            "active_profile": "mmo7classic",
            "profile": {
                "input_name": "Saitek Cyborg M.M.O.7 Gaming Mouse",
                "hardware_dpi": 6400,
            },
            "tuner_verified": True,
        },
    )
    monkeypatch.setattr(
        input_adapter,
        "_devices",
        lambda: {
            "mice": [{
                "name": "saitek-cyborg-m.m.o.7-gaming-mouse",
                "defaultSpeed": -0.875,
            }],
            "keyboards": [{
                "name": "solaar-keyboard",
                "layout": "us",
                "active_keymap": "English (US)",
                "main": True,
            }],
        },
    )
    monkeypatch.setattr(
        input_adapter,
        "_integer_option",
        lambda name: {"input:repeat_rate": 25, "input:repeat_delay": 600}[name],
    )
    monkeypatch.setattr(input_adapter, "_caps_lock_mapping", lambda: "up")
    monkeypatch.setattr(input_adapter, "_hyprctl", lambda *_arguments: "")

    snapshot = input_adapter.input_snapshot()

    assert snapshot["schema"] == "obsidience.input.v1"
    assert snapshot["mouse"] == {
        "profile_id": "mmo7classic",
        "name": "Saitek Cyborg M.M.O.7 Gaming Mouse",
        "hyprland_name": "saitek-cyborg-m.m.o.7-gaming-mouse",
        "connected": True,
        "hardware_dpi": 6400,
        "hardware_maximum_verified": True,
        "acceleration_profile": "custom 1 0 0.125",
        "sensitivity": 0.0,
        "multiplier": 0.125,
        "effective_dpi": 800,
        "compositor_applied": True,
    }
    assert snapshot["keyboard"] == {
        "name": "solaar-keyboard",
        "layout": "English (US)",
        "layout_code": "us",
        "repeat_rate_hz": 25,
        "repeat_delay_ms": 600,
        "caps_lock_mapping": "up",
    }


def test_input_snapshot_fails_open_when_hyprland_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(input_adapter, "_profile_status", lambda: {})
    monkeypatch.setattr(input_adapter, "_devices", lambda: {})
    monkeypatch.setattr(input_adapter, "_integer_option", lambda _name: None)
    monkeypatch.setattr(input_adapter, "_caps_lock_mapping", lambda: None)
    monkeypatch.setattr(input_adapter, "_hyprctl", lambda *_arguments: "")

    snapshot = input_adapter.input_snapshot()

    assert snapshot["mouse"]["connected"] is False
    assert snapshot["mouse"]["effective_dpi"] is None
    assert snapshot["mouse"]["compositor_applied"] is False
    assert snapshot["keyboard"]["name"] == "No primary keyboard"

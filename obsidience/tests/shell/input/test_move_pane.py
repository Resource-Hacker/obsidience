from __future__ import annotations

import json

import pytest

from obsidience.shell.input import move_pane


class FakeSocket:
    def __init__(self, event_type: str) -> None:
        self.event_type = event_type
        self.sent: list[dict] = []

    def __enter__(self) -> FakeSocket:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def send(self, value: str) -> None:
        self.sent.append(json.loads(value))

    def recv(self, **_kwargs: float) -> str:
        return json.dumps(
            {"schema": "obsidience.shell.event.v1", "type": self.event_type}
        )


@pytest.mark.parametrize(
    ("action", "command_type", "event_type"),
    [
        ("surface", "pane.move_active", "pane.moved"),
        ("resize", "pane.tile_active", "pane.tiled"),
        ("tile", "pane.tile_move_active", "pane.tiled"),
    ],
)
def test_active_pane_actions_share_one_typed_client(
    monkeypatch: pytest.MonkeyPatch,
    action: str,
    command_type: str,
    event_type: str,
) -> None:
    socket = FakeSocket(event_type)
    monkeypatch.setattr(move_pane, "connect", lambda *_args, **_kwargs: socket)

    assert move_pane.apply_active_pane_action("samsung", action, "right") is True
    assert socket.sent == [
        {
            "schema": "obsidience.shell.command.v1",
            "type": command_type,
            "source_surface_id": "samsung",
            "direction": "right",
        }
    ]


def test_legacy_two_argument_entrypoint_remains_surface_transfer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[tuple[str, str, str]] = []
    monkeypatch.setattr(move_pane, "focused_surface", lambda: "usb-c")
    monkeypatch.setattr(
        move_pane,
        "apply_active_pane_action",
        lambda surface, action, direction: not called.append(
            (surface, action, direction)
        ),
    )

    assert move_pane.main(["focused", "left"]) == 0
    assert called == [("usb-c", "surface", "left")]


def test_invalid_active_pane_action_fails_without_connecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        move_pane,
        "connect",
        lambda *_args, **_kwargs: pytest.fail("invalid action opened a socket"),
    )

    assert move_pane.apply_active_pane_action("samsung", "unknown", "right") is False

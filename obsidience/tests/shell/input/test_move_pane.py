from __future__ import annotations

import json

import pytest

from obsidience.shell.input import move_pane


class FakeSocket:
    def __init__(self, events: str | list[dict]) -> None:
        self.events = (
            [{"schema": "obsidience.shell.event.v1", "type": events}]
            if isinstance(events, str)
            else list(events)
        )
        self.sent: list[dict] = []

    def __enter__(self) -> FakeSocket:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def send(self, value: str) -> None:
        self.sent.append(json.loads(value))

    def recv(self, **_kwargs: float) -> str:
        if not self.events:
            raise TimeoutError
        return json.dumps(self.events.pop(0))


@pytest.mark.parametrize(
    "action",
    [
        "surface",
        "resize",
        "tile",
    ],
)
def test_layout_actions_go_directly_to_the_active_native_window(
    monkeypatch: pytest.MonkeyPatch,
    action: str,
) -> None:
    socket = FakeSocket(
        [
            {
                "schema": "obsidience.shell.event.v1",
                "type": "window.layout.result",
                "token": "native-token",
                "success": True,
            }
        ]
    )
    monkeypatch.setattr(move_pane, "connect", lambda *_args, **_kwargs: socket)
    monkeypatch.setattr(move_pane.secrets, "token_hex", lambda _size: "native-token")

    assert move_pane.apply_active_window_action("samsung", action, "right") is True
    assert socket.sent == [
        {
            "schema": "obsidience.shell.command.v1",
            "type": "window.layout_active",
            "token": "native-token",
            "source_surface_id": "samsung",
            "action": action,
            "direction": "right",
        }
    ]


def test_close_goes_directly_to_the_active_native_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    socket = FakeSocket(
        [
            {
                "schema": "obsidience.shell.event.v1",
                "type": "window.close.result",
                "token": "native-token",
                "success": True,
            }
        ]
    )
    monkeypatch.setattr(move_pane, "connect", lambda *_args, **_kwargs: socket)
    monkeypatch.setattr(move_pane.secrets, "token_hex", lambda _size: "native-token")

    assert move_pane.apply_active_window_action("samsung", "close") is True
    assert socket.sent == [
        {
            "schema": "obsidience.shell.command.v1",
            "type": "window.close_active",
            "token": "native-token",
            "source_surface_id": "samsung",
        }
    ]


def test_unrelated_events_do_not_create_a_second_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    socket = FakeSocket(
        [
            {
                "schema": "obsidience.shell.event.v1",
                "type": "pane.dismissed",
            },
            {
                "schema": "obsidience.shell.event.v1",
                "type": "window.close.result",
                "token": "native-token",
                "success": True,
            },
        ]
    )
    monkeypatch.setattr(move_pane, "connect", lambda *_args, **_kwargs: socket)
    monkeypatch.setattr(move_pane.secrets, "token_hex", lambda _size: "native-token")

    assert move_pane.apply_active_window_action("usb-c", "close") is True
    assert socket.sent == [
        {
            "schema": "obsidience.shell.command.v1",
            "type": "window.close_active",
            "token": "native-token",
            "source_surface_id": "usb-c",
        },
    ]


def test_legacy_two_argument_entrypoint_remains_surface_transfer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[tuple[str, str, str]] = []
    monkeypatch.setattr(move_pane, "focused_surface", lambda: "usb-c")
    monkeypatch.setattr(
        move_pane,
        "apply_active_window_action",
        lambda surface, action, direction: (
            not called.append((surface, action, direction))
        ),
    )

    assert move_pane.main(["focused", "left"]) == 0
    assert called == [("usb-c", "surface", "left")]


def test_close_entrypoint_needs_no_direction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[tuple[str, str, str]] = []
    monkeypatch.setattr(move_pane, "focused_surface", lambda: "samsung")
    monkeypatch.setattr(
        move_pane,
        "apply_active_window_action",
        lambda surface, action, direction: (
            not called.append((surface, action, direction))
        ),
    )

    assert move_pane.main(["focused", "close"]) == 0
    assert called == [("samsung", "close", "")]


def test_invalid_active_window_action_fails_without_connecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        move_pane,
        "connect",
        lambda *_args, **_kwargs: pytest.fail("invalid action opened a socket"),
    )

    assert move_pane.apply_active_window_action("samsung", "unknown", "right") is False


def test_native_failure_is_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    socket = FakeSocket(
        [
            {
                "schema": "obsidience.shell.event.v1",
                "type": "window.layout.result",
                "token": "native-token",
                "success": False,
                "reason": "boundary",
            },
        ]
    )
    monkeypatch.setattr(move_pane, "connect", lambda *_args, **_kwargs: socket)
    monkeypatch.setattr(move_pane.secrets, "token_hex", lambda _size: "native-token")

    assert move_pane.apply_active_window_action("usb-c", "tile", "left") is False
    assert socket.sent == [
        {
            "schema": "obsidience.shell.command.v1",
            "type": "window.layout_active",
            "token": "native-token",
            "source_surface_id": "usb-c",
            "action": "tile",
            "direction": "left",
        },
    ]

"""Exercise the compiled Wayland client against an inert protocol peer.

The socketpair is inherited explicitly via WAYLAND_SOCKET. No test can connect
to a workstation display, create a real input device, or run a Task.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import selectors
import shutil
import socket
import struct
import subprocess
import threading
import time

import pytest


ROOT = Path(__file__).resolve().parents[4]
BUILD = ROOT / "shell/adapter/hyprland/build-pointer"


def words(*values: int) -> bytes:
    return struct.pack("=" + "I" * len(values), *values)


def string(value: str) -> bytes:
    raw = value.encode() + b"\0"
    return words(len(raw)) + raw + b"\0" * (-len(raw) % 4)


def message(object_id: int, opcode: int, payload: bytes = b"") -> bytes:
    return words(object_id, (len(payload) + 8) << 16 | opcode) + payload


@pytest.fixture(scope="module")
def executable(tmp_path_factory) -> Path:
    if not all(shutil.which(tool) for tool in ("cc", "pkg-config", "wayland-scanner")):
        pytest.skip("Wayland native build dependencies are not installed")
    root = tmp_path_factory.mktemp("pointer-native-build")
    result = subprocess.run([str(BUILD), str(root)], capture_output=True, text=True, check=True, timeout=30)
    binary = Path(result.stdout.strip())
    assert binary.is_file()
    assert not (root / "current").exists()
    return binary


class Peer:
    """Minimal wl_display/registry/output/virtual-pointer wire peer, no seats."""

    def __init__(self, executable: Path, *, names=("OTHER", "TARGET"), transform=0,
                 manager_version=2, drop_sync=0, hold_sync=0, args=None):
        self.socket, child = socket.socketpair()
        self.names = names
        self.transform = transform
        self.manager_version = manager_version
        self.drop_sync = drop_sync
        self.hold_sync = hold_sync
        self.syncs = 0
        self.registry = 0
        self.objects = {1: "wl_display"}
        self.outputs: dict[str, int] = {}
        self.events: list[tuple] = []
        self.errors: list[Exception] = []
        self.closed = False
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()
        env = dict(os.environ, WAYLAND_SOCKET=str(child.fileno()))
        self.process = subprocess.Popen(
            [str(executable), *(args or ["TARGET", "123", "45", "1920", "1080"])],
            env=env, pass_fds=(child.fileno(),), stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        child.close()

    def send(self, object_id, opcode, payload=b""):
        self.socket.sendall(message(object_id, opcode, payload))

    def geometry(self, output_id, transform):
        self.send(output_id, 0, words(0, 0, 500, 300, 0) + string("test") + string("inert") + words(transform))

    def handle(self, object_id, opcode, payload):
        interface = self.objects[object_id]
        if interface == "wl_display" and opcode == 1:
            self.registry, = struct.unpack("=I", payload)
            self.objects[self.registry] = "wl_registry"
            for index, _ in enumerate(self.names):
                self.send(self.registry, 0, words(10 + index) + string("wl_output") + words(4))
            self.send(self.registry, 0, words(100) + string("zwlr_virtual_pointer_manager_v1") + words(self.manager_version))
        elif interface == "wl_display" and opcode == 0:
            self.syncs += 1
            self.events.append(("sync", self.syncs))
            if self.syncs == self.drop_sync:
                self.socket.shutdown(socket.SHUT_RDWR)
                return
            if self.syncs == self.hold_sync:
                return
            callback, = struct.unpack("=I", payload)
            self.send(callback, 0, words(self.syncs))
            self.send(1, 1, words(callback))
        elif interface == "wl_registry" and opcode == 0:
            global_id, length = struct.unpack("=II", payload[:8])
            name = payload[8:8 + length - 1].decode()
            offset = 8 + (length + 3) // 4 * 4
            version, new_id = struct.unpack("=II", payload[offset:])
            self.objects[new_id] = name
            if name == "wl_output":
                label = self.names[global_id - 10]
                self.outputs[label] = new_id
                self.geometry(new_id, self.transform)
                self.send(new_id, 1, words(1, 3840, 2160, 60000))
                self.send(new_id, 3, words(2))
                self.send(new_id, 4, string(label))
                self.send(new_id, 2)
            else:
                assert name == "zwlr_virtual_pointer_manager_v1" and version == 2
        elif interface == "zwlr_virtual_pointer_manager_v1" and opcode == 2:
            seat, output, pointer = struct.unpack("=III", payload)
            self.events.append(("create", seat, output))
            self.objects[pointer] = "zwlr_virtual_pointer_v1"
        elif interface == "zwlr_virtual_pointer_v1":
            values = struct.unpack("=" + "I" * (len(payload) // 4), payload)
            self.events.append(({1: "absolute", 2: "button", 4: "frame", 8: "destroy"}[opcode], *values))
        elif interface == "zwlr_virtual_pointer_manager_v1" and opcode == 1:
            pass
        else:
            raise AssertionError((interface, opcode, payload))

    def run(self):
        pending = b""
        try:
            while raw := self.socket.recv(65536):
                pending += raw
                while len(pending) >= 8:
                    object_id, header = struct.unpack("=II", pending[:8])
                    size, opcode = header >> 16, header & 0xFFFF
                    if len(pending) < size:
                        break
                    self.handle(object_id, opcode, pending[8:size])
                    pending = pending[size:]
        except (BrokenPipeError, ConnectionResetError):
            pass
        except OSError as error:
            if not self.closed:
                self.errors.append(error)
        except Exception as error:
            self.errors.append(error)

    def positioned(self):
        with selectors.DefaultSelector() as selector:
            selector.register(self.process.stdout, selectors.EVENT_READ)
            assert selector.select(6), "helper did not publish a bounded positioning result"
        assert json.loads(self.process.stdout.readline()) == {"status": "positioned"}

    def finish(self, command=b"commit\n"):
        out, err = self.process.communicate(command, timeout=7)
        self.close()
        assert not self.errors
        return self.process.returncode, out, err

    def close(self):
        self.closed = True
        if self.process.poll() is None:
            self.process.kill()
            self.process.wait(timeout=2)
        self.socket.close()
        self.thread.join(timeout=1)


def test_real_client_positions_exact_output_and_commits_only_after_receipt(executable):
    peer = Peer(executable)
    try:
        peer.positioned()
        assert not any(event[0] == "button" for event in peer.events)
        assert ("create", 0, peer.outputs["TARGET"]) in peer.events
        absolute = next(event for event in peer.events if event[0] == "absolute")
        assert absolute[2:] == (123, 45, 1920, 1080)
        code, out, _ = peer.finish()
        assert code == 0 and json.loads(out) == {"status": "acknowledged"}
        events = [event[0] for event in peer.events]
        start = events.index("absolute")
        assert events[start:start + 8] == ["absolute", "frame", "sync", "button", "frame", "button", "frame", "sync"]
        assert [event[2:] for event in peer.events if event[0] == "button"] == [(272, 1), (272, 0)]
    finally:
        peer.close()


@pytest.mark.parametrize("command", [b"", b"abort\n", b"commit", b"commit\ncommit\n", b"COMMIT\n"])
def test_eof_or_noncommit_never_sends_buttons(executable, command):
    peer = Peer(executable)
    try:
        peer.positioned()
        code, out, _ = peer.finish(command)
        assert code != 0 and not out
        assert not any(event[0] == "button" for event in peer.events)
    finally:
        peer.close()


@pytest.mark.parametrize("options", [
    {"names": ("OTHER",)}, {"names": ("TARGET", "TARGET")},
    {"transform": 1}, {"manager_version": 1},
])
def test_output_contract_rejects_before_any_motion(executable, options):
    peer = Peer(executable, **options)
    try:
        code, out, _ = peer.finish(b"")
        assert code != 0 and not out
        assert not any(event[0] in ("create", "absolute", "button") for event in peer.events)
    finally:
        peer.close()


@pytest.mark.parametrize("sync", [1, 3, 4])
def test_disconnect_never_substitutes_for_real_callback(executable, sync):
    peer = Peer(executable, drop_sync=sync)
    try:
        if sync == 4:
            peer.positioned()
        code, out, _ = peer.finish(b"commit\n" if sync == 4 else b"")
        assert code != 0 and b"acknowledged" not in out
        assert len([event for event in peer.events if event[0] == "button"]) == (2 if sync == 4 else 0)
    finally:
        peer.close()


def test_commit_wait_has_two_second_deadline(executable):
    peer = Peer(executable)
    try:
        peer.positioned()
        start = time.monotonic()
        peer.process.wait(timeout=4)
        assert 1.5 < time.monotonic() - start < 3.5
        assert peer.process.returncode != 0
        assert not any(event[0] == "button" for event in peer.events)
    finally:
        peer.close()


def test_callback_wait_has_whole_process_deadline(executable):
    peer = Peer(executable, hold_sync=3)
    try:
        start = time.monotonic()
        code, out, _ = peer.finish(b"")
        assert code != 0 and not out
        assert time.monotonic() - start < 6
        assert not any(event[0] == "button" for event in peer.events)
    finally:
        peer.close()


@pytest.mark.parametrize("change", ["remove", "transform"])
def test_output_change_after_position_aborts_commit(executable, change):
    peer = Peer(executable)
    try:
        peer.positioned()
        if change == "remove":
            peer.send(peer.registry, 1, words(11))
        else:
            peer.geometry(peer.outputs["TARGET"], 1)
        code, out, _ = peer.finish()
        assert code != 0 and not out
        assert not any(event[0] == "button" for event in peer.events)
    finally:
        peer.close()


@pytest.mark.parametrize("args", [
    ["TARGET", "-1", "0", "1920", "1080"],
    ["TARGET", "1920", "0", "1920", "1080"],
    ["TARGET", "0", "0", "0", "1080"],
    ["TARGET", "0", "0", "999999999999999999999", "1080"],
    ["TARGET", "1.0", "0", "1920", "1080"],
])
def test_invalid_coordinates_reject_before_display_connection(executable, args):
    result = subprocess.run([str(executable), *args], capture_output=True, timeout=2,
                            env={"WAYLAND_DISPLAY": "/no-such-obsidience-test-display"})
    assert result.returncode == 2 and not result.stdout
    assert b"invalid output" in result.stderr

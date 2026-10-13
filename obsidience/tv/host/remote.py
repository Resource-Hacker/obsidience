#!/usr/bin/python3
"""The TV remote: the television's remote keys, typed into the TV session and nowhere else.

Moonlight sends the Fire TV remote as a gamepad and Sunshine's input stays disabled (its virtual
devices are kernel devices, which the desktop would see), so the keys take another road. The TV
agent (org.obsidience.tv, obsidience/tv/android) takes them from Moonlight while its stream is in
front and a client asks for them, and pushes each press and release over its socket. This unit is
that client: it replays them through one Wayland virtual keyboard (zwp_virtual_keyboard_v1) in the
TV compositor, as real evdev scancodes under the stock keymap, to whatever window that compositor
focuses. The Android TV instance reads the scancode and ignores the keymap. No kernel input device
is created, so the desktop cannot see a key.

    Android key code (agent)         evdev key (here)
    19-22 DPAD_UP/DOWN/LEFT/RIGHT    KEY_UP, KEY_DOWN, KEY_LEFT, KEY_RIGHT
    23 DPAD_CENTER                   KEY_ENTER
    4  BACK                          KEY_ESC
    82 MENU                          KEY_COMPOSE
    85 MEDIA_PLAY_PAUSE              KEY_PLAYPAUSE
    89 MEDIA_REWIND                  KEY_REWIND
    90 MEDIA_FAST_FORWARD            KEY_FASTFORWARD

Only presses and releases are forwarded: repeating a held key is the receiving program's business.
Home never arrives; it leaves the stream on the television.

Fail closed. The compositor is the one whose socket the TV session published, and the process
behind that socket must run in obsidience-tv-session.service; otherwise, or without the
virtual-keyboard global or a registered television, this exits with status 78, which the unit does
not restart. The agent is reached through the ADB server that is already running, as one stream to
the television's `obsidience-tv` socket: there is no forward to leave behind (or for the Harness to
remove), and no adb command that could start a server inside this unit. While the agent cannot be
reached the television keeps its keys and no keyboard exists here; a connection that ends releases
what was held and removes the keyboard.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import select
import socket
import struct
import sys
import time
from pathlib import Path

from pywayland.client import Display
from pywayland.protocol.wayland import WlSeat
from pywayland.protocol_core import Argument, ArgumentType, Interface, Proxy

log = logging.getLogger('remote')

HOST = Path(__file__).resolve().parent
RUNTIME = Path(os.environ.get('XDG_RUNTIME_DIR') or f'/run/user/{os.getuid()}')
# The unit whose compositor may be typed into.
SESSION = 'obsidience-tv-session.service'
TELEVISION = HOST.parents[1] / 'state' / 'television.json'
ADB_SERVER = ('127.0.0.1', 5037)
SOCKET = 'obsidience-tv'
# How often the agent is tried again while it cannot be reached (television off, ADB disconnected).
RETRY = 3.0
# Exit status of a refusal that a restart cannot cure.
REFUSED = 78
# Android key code -> evdev key code (linux/input-event-codes.h).
KEYS = {19: 103, 20: 108, 21: 105, 22: 106, 23: 28, 4: 1, 82: 127, 85: 164, 89: 168, 90: 208}
# The stock keymap (rules evdev, layout us), resolved by the compositor from the system's XKB data.
KEYMAP = (b'xkb_keymap { xkb_keycodes { include "evdev+aliases(qwerty)" }; xkb_types { include "complete" }; '
          b'xkb_compat { include "complete" }; xkb_symbols { include "pc+us+inet(evdev)" }; };\0')
_LINE_LIMIT = 4 * 1024 * 1024


# zwp_virtual_keyboard_v1 (wlroots' virtual-keyboard-unstable-v1), which the packaged pywayland does
# not carry: its two interfaces and their requests in protocol order, declared as pywayland's scanner
# declares them.

class ZwpVirtualKeyboardManagerV1(Interface):
    name = 'zwp_virtual_keyboard_manager_v1'
    version = 1


class ZwpVirtualKeyboardV1(Interface):
    name = 'zwp_virtual_keyboard_v1'
    version = 1


class _ManagerProxy(Proxy[ZwpVirtualKeyboardManagerV1]):
    interface = ZwpVirtualKeyboardManagerV1

    @ZwpVirtualKeyboardManagerV1.request(Argument(ArgumentType.Object, interface=WlSeat),
                                         Argument(ArgumentType.NewId, interface=ZwpVirtualKeyboardV1))
    def create_virtual_keyboard(self, seat):
        return self._marshal_constructor(0, ZwpVirtualKeyboardV1, seat)


class _KeyboardProxy(Proxy[ZwpVirtualKeyboardV1]):
    interface = ZwpVirtualKeyboardV1

    @ZwpVirtualKeyboardV1.request(Argument(ArgumentType.Uint), Argument(ArgumentType.FileDescriptor),
                                  Argument(ArgumentType.Uint))
    def keymap(self, format, fd, size):
        self._marshal(0, format, fd, size)

    @ZwpVirtualKeyboardV1.request(Argument(ArgumentType.Uint), Argument(ArgumentType.Uint),
                                  Argument(ArgumentType.Uint))
    def key(self, time, key, state):
        self._marshal(1, time, key, state)

    @ZwpVirtualKeyboardV1.request(Argument(ArgumentType.Uint), Argument(ArgumentType.Uint),
                                  Argument(ArgumentType.Uint), Argument(ArgumentType.Uint))
    def modifiers(self, depressed, latched, locked, group):
        self._marshal(2, depressed, latched, locked, group)

    @ZwpVirtualKeyboardV1.request()
    def destroy(self):
        self._marshal(3)
        self._destroy()


for _interface, _proxy in ((ZwpVirtualKeyboardManagerV1, _ManagerProxy), (ZwpVirtualKeyboardV1, _KeyboardProxy)):
    _interface._gen_c()
    _interface.proxy_class = _proxy


def refuse(why):
    log.error('refusing: %s', why)
    sys.exit(REFUSED)


def compositor():
    """The TV session's compositor as (display, seat, virtual keyboard manager); refuses any other."""
    try:
        name = (RUNTIME / 'obsidience-tv' / 'wayland').read_text().strip()
    except OSError:
        name = ''
    if not name or '/' in name:
        refuse('the TV session has published no Wayland socket')
    # Connected by path, never by name: no environment variable or default can choose the compositor.
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.connect(str(RUNTIME / name))
        pid = struct.unpack('3i', sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))[0]
        cgroup = Path(f'/proc/{pid}/cgroup').read_text().strip()
    except OSError as error:
        log.error('the TV compositor does not answer (%s)', type(error).__name__)
        sys.exit(1)
    if not cgroup.endswith('/' + SESSION):
        refuse(f'the compositor behind the published socket does not run in {SESSION}')
    display = Display(sock.detach())
    display.connect()
    found = {}

    def announce(registry, ident, interface, version):
        if interface == WlSeat.name:
            found.setdefault('seat', registry.bind(ident, WlSeat, 1))
        elif interface == ZwpVirtualKeyboardManagerV1.name:
            found['manager'] = registry.bind(ident, ZwpVirtualKeyboardManagerV1, 1)

    registry = display.get_registry()  # Held until the answer: a dropped proxy hears nothing.
    registry.dispatcher['global'] = announce
    answered = display.roundtrip() >= 0
    if not answered or 'seat' not in found or 'manager' not in found:
        display.disconnect()
        if not answered:  # It went away while starting: not a refusal, the unit tries again.
            log.error('the TV compositor does not answer')
            sys.exit(1)
        refuse('the TV compositor offers no seat with a virtual keyboard')
    return display, found['seat'], found['manager']


def _exactly(sock, count):
    data = b''
    while len(data) < count:
        chunk = sock.recv(count - len(data))
        if not chunk:
            raise ConnectionError('the ADB server closed the connection')
        data += chunk
    return data


def agent(serial):
    """A stream to the TV agent's socket through the running ADB server (its host protocol)."""
    sock = socket.create_connection(ADB_SERVER, timeout=5)
    try:
        for request in (f'host:transport:{serial}', f'localabstract:{SOCKET}'):
            sock.sendall(b'%04x%s' % (len(request), request.encode()))
            status = _exactly(sock, 4)
            if status == b'FAIL':
                raise ConnectionError(_exactly(sock, int(_exactly(sock, 4), 16)).decode(errors='replace'))
            if status != b'OKAY':
                raise ConnectionError('the ADB server gave no answer this unit understands')
        sock.settimeout(None)
        return sock
    except (OSError, ValueError) as error:
        sock.close()
        raise ConnectionError(str(error)) from error


class Remote:
    """One agent connection at a time and, while it grants keys, one virtual keyboard."""

    def __init__(self, serial, display, seat, manager):
        self.serial, self.display, self.seat, self.manager = serial, display, seat, manager
        self.poller = select.poll()
        self.poller.register(display.get_fd(), select.POLLIN)
        self.link = self.keyboard = None
        self.buffer = b''
        self.held = set()
        self.asked = self.offset = 0.0
        self.fault = None

    def run(self):
        log.info('ready: remote keys go to the TV session only')
        while True:
            if self.link is None:
                self._connect()
            events = self.poller.poll(None if self.keyboard is not None else RETRY * 1000)
            if not events and self.link is not None:
                self._disconnect('the TV agent does not answer')  # Connected, and silent about keys.
            for fd, _mask in events:
                if fd == self.display.get_fd():
                    self.display.dispatch(block=True)  # Raises once the compositor is gone.
                elif self.link is not None:
                    self._read()

    def _connect(self):
        try:
            self.link = agent(self.serial)
            self.asked = time.monotonic()
            self.link.sendall(b'{"id":1,"op":"keys","on":true}\n')
        except OSError as error:
            self._disconnect(str(error))
            return
        self.poller.register(self.link, select.POLLIN)

    def _disconnect(self, why):
        if self.link is not None:
            try:
                self.poller.unregister(self.link)
            except KeyError:
                pass
            self.link.close()
        self.link, self.buffer = None, b''
        if self.keyboard is not None:
            for key in self.held:
                self.keyboard.key(_now(), key, 0)
            self.keyboard.destroy()
            self.display.flush()
            self.keyboard = None
            self.held.clear()
            log.warning('TV agent disconnected (%s): the television keeps its keys', why)
        elif why != self.fault:  # One line per reason, not one per attempt.
            log.info('TV agent not reached (%s); trying every %g s', why, RETRY)
        self.fault = why

    def _read(self):
        received = time.monotonic()
        try:
            data = self.link.recv(65536)
        except OSError as error:
            self._disconnect(type(error).__name__)
            return
        self.buffer += data
        if not data or len(self.buffer) > _LINE_LIMIT:
            self._disconnect('the connection ended')
            return
        *lines, self.buffer = self.buffer.split(b'\n')
        for line in lines:
            try:
                message = json.loads(line)
                if not isinstance(message, dict):
                    raise ValueError
            except ValueError:
                self._disconnect('the agent sent something that is not its protocol')
                return
            if message.get('id') == 1:
                if not self._granted(message, received):
                    return
            elif message.get('event') == 'key' and self.keyboard is not None:
                self._key(message, received)
        self.display.flush()

    def _granted(self, reply, received):
        """The answer to the request for keys: with it the keyboard appears in the TV session."""
        if reply.get('ok') is not True or reply.get('keys') is not True:
            self._disconnect('the TV agent grants no keys: ' + str(reply.get('error', 'version 1?'))[:80])
            return False
        # Host monotonic clock minus the television's uptime clock, at the middle of the round trip.
        self.offset = (self.asked + received) * 500 - reply.get('now', 0)
        keyboard = self.manager.create_virtual_keyboard(self.seat)
        fd = os.memfd_create('obsidience-tv-keymap')
        try:
            os.write(fd, KEYMAP)
            keyboard.keymap(1, fd, len(KEYMAP))  # WL_KEYBOARD_KEYMAP_FORMAT_XKB_V1
            if self.display.roundtrip() < 0:
                raise RuntimeError('the TV compositor did not take the keyboard')
        finally:
            os.close(fd)
        self.keyboard, self.fault = keyboard, None
        log.info('TV agent connected: remote keys are typed into the TV session (answer in %.0f ms)',
                 (received - self.asked) * 1000)
        return True

    def _key(self, message, received):
        key, down = KEYS.get(message.get('code')), message.get('down') is True
        if key is None or down == (key in self.held):
            return  # Not a remote key, or no change: a press is sent once and released once.
        self.keyboard.key(_now(), key, 1 if down else 0)
        if down:
            self.held.add(key)
        else:
            self.held.discard(key)
        if log.isEnabledFor(logging.DEBUG):
            self.display.flush()
            try:
                log.debug('key %d %s: %d ms in the agent, %.1f ms to here, %.2f ms here', message['code'],
                          'down' if down else 'up', message['sent'] - message['t'],
                          received * 1000 - self.offset - message['sent'], (time.monotonic() - received) * 1000)
            except (KeyError, TypeError):
                pass


def _now():
    return int(time.monotonic() * 1000) & 0xFFFFFFFF


def main():
    parser = argparse.ArgumentParser(description="The TV remote: the television's remote keys, typed into "
                                                 'the TV session only.')
    parser.add_argument('--debug', action='store_true',
                        help='log every key with its timing (the input leg: agent, link, this unit)')
    args = parser.parse_args()
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(name)s: %(message)s'))
    log.addHandler(handler)
    log.setLevel(logging.DEBUG if args.debug else logging.INFO)
    log.propagate = False
    try:
        serial = json.loads(TELEVISION.read_text())['ip'] + ':5555'
    except (OSError, ValueError, KeyError, TypeError):
        refuse('no television is registered')
    display, seat, manager = compositor()
    try:
        Remote(serial, display, seat, manager).run()
    except RuntimeError as error:
        log.error('the TV compositor is gone (%s)', error)
        sys.exit(1)
    finally:
        display.disconnect()  # Proxies go before the connection; the interpreter's own order crashes.


if __name__ == '__main__':
    main()

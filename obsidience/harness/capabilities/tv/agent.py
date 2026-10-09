"""The Obsidience TV agent (org.obsidience.tv): a fast, push-based backend channel to the registered TV.

The sideloaded app (source: obsidience/tv/android) hosts an accessibility service
that the system keeps bound across reboots. It listens on the abstract Unix
socket `obsidience-tv` and admits only the shell (adbd) or root peer, and it has
no INTERNET permission. The Harness reaches it through ADB's own forward
(`adb forward tcp:N localabstract:obsidience-tv`), so ADB key authentication is
the authentication. The forward lives on the TV transport whose identity was
verified when it was made: standby, reboot or an address change ends the
connection, and the next use verifies identity again. ADB stays the installer,
the transport and the fallback (tv.control reads over ADB whenever this is None).

Protocol: newline-delimited JSON. A request {id, op, ...} gets one reply with that
id and ok; {event: 'state', state} is pushed when the foreground, power, volume,
media players or media sessions change, {event: 'ad_skipped', ...} after the app
clicked a skip-ad control.
"""
from __future__ import annotations

import atexit
from collections import deque
import itertools
import json
import logging
from pathlib import Path
import re
import socket
import subprocess
import threading
import time

PACKAGE = 'org.obsidience.tv'
# Pinned app version: android:versionCode in obsidience/tv/android/AndroidManifest.xml.
VERSION = 1
SERVICE = PACKAGE + '/.AgentService'
LISTENER = PACKAGE + '/' + PACKAGE + '.MediaListener'
SOCKET = 'obsidience-tv'
# Built by obsidience/tv/android/build.sh into ignored installation state.
APK = Path(__file__).resolve().parents[3] / 'state' / 'tv-agent' / f'obsidience-tv-{VERSION}.apk'
# A failed connection rests this long; tv.control reads over ADB meanwhile.
RETRY = 120.0
_LINE_LIMIT = 4 * 1024 * 1024
log = logging.getLogger(__name__)
_SESSION = {'agent': None, 'failed': 0.0, 'cleanup': False}


class Agent:
    """One connection: its socket, the reader thread and the latest pushed state."""

    def __init__(self, sock, port, target, boot, on_state=None):
        self.sock, self.port, self.target, self.boot = sock, port, target, boot
        self.on_state = on_state
        self.closed = threading.Event()
        self.state = None  # (wall time, latest full state from a reply or a push)
        self.skips = deque(maxlen=20)
        self._pending = {}
        self._ids = itertools.count(1)
        self._send = threading.Lock()
        self._reader = threading.Thread(target=self._read, name='tv-agent-reader', daemon=True)
        self._reader.start()

    def _read(self):
        buffer = b''
        try:
            while True:
                chunk = self.sock.recv(65536)
                if not chunk:
                    break
                buffer += chunk
                while b'\n' in buffer:
                    line, buffer = buffer.split(b'\n', 1)
                    self._dispatch(json.loads(line))
                if len(buffer) > _LINE_LIMIT:
                    break
        except (OSError, ValueError):
            pass
        finally:
            self.closed.set()
            for slot in list(self._pending.values()):
                slot[0].set()

    def _dispatch(self, message):
        if not isinstance(message, dict):
            return
        event = message.get('event')
        if event == 'state' and isinstance(message.get('state'), dict):
            self.state = (time.time(), message['state'])
            if self.on_state is not None:
                try:
                    self.on_state(message['state'])
                except Exception:  # A consumer's failure must not end the connection.  # noqa: BLE001
                    log.exception('TV agent state consumer failed')
        elif event == 'ad_skipped':
            self.skips.append(message)
            log.info('TV agent clicked a skip-ad control in %s: %r', message.get('package'), message.get('label'))
        elif event is None:
            slot = self._pending.get(message.get('id'))
            if slot is not None:
                slot[1] = message
                slot[0].set()

    def request(self, op, timeout=3.0, **fields):
        """One request; raises ConnectionError/TimeoutError (connection unusable) or ValueError (refused)."""
        if self.closed.is_set():
            raise ConnectionError('TV agent disconnected')
        ident = next(self._ids)
        slot = [threading.Event(), None]
        self._pending[ident] = slot
        try:
            with self._send:
                self.sock.sendall((json.dumps({'id': ident, 'op': op, **fields}) + '\n').encode())
            if not slot[0].wait(timeout):
                self.close()  # A wedged agent is dropped; the caller falls back to ADB.
                raise TimeoutError(f'TV agent did not answer {op}')
        except OSError as error:
            self.close()
            raise ConnectionError(f'TV agent connection failed: {error}') from error
        finally:
            self._pending.pop(ident, None)
        reply = slot[1]
        if reply is None:
            raise ConnectionError('TV agent disconnected')
        if not reply.get('ok'):
            raise ValueError('TV agent refused ' + op + ': ' + str(reply.get('error'))[:200])
        if op == 'state':
            self.state = (time.time(), reply)
        return reply

    def close(self):
        self.closed.set()
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.sock.close()
        if self._reader is not threading.current_thread():
            self._reader.join(1)


def current():
    """The connected agent, or None; no I/O."""
    agent = _SESSION['agent']
    return agent if agent is not None and not agent.closed.is_set() else None


def session(row, cancel, boot, on_state=None):
    """The connected agent for this TV boot, connecting (and provisioning) when needed.

    Called right after tv.control's identity preamble on the same transport.
    None means tv.control reads and acts over ADB.
    """
    agent = _SESSION['agent']
    if agent is not None:
        if not agent.closed.is_set() and agent.target == row['ip'] + ':5555' and agent.boot == boot:
            return agent
        close()
    if time.monotonic() - _SESSION['failed'] < RETRY:
        return None
    try:
        agent = _connect(row, cancel, boot, on_state)
    except InterruptedError:
        raise
    except (OSError, ValueError, KeyError) as error:
        _SESSION['failed'] = time.monotonic()
        log.warning('TV agent unavailable; using ADB: %s', error)
        return None
    _SESSION['agent'] = agent
    if not _SESSION['cleanup']:
        atexit.register(close)  # Cleanup paired with the acquisition.
        _SESSION['cleanup'] = True
    return agent


def close():
    """End the connection and remove its ADB forward."""
    agent, _SESSION['agent'] = _SESSION['agent'], None
    if agent is None:
        return
    agent.close()
    try:
        subprocess.run(['/usr/bin/adb', '-s', agent.target, 'forward', '--remove', f'tcp:{agent.port}'],
                       stdin=subprocess.DEVNULL, capture_output=True, timeout=3)
    except (OSError, subprocess.TimeoutExpired):
        pass


def _connect(row, cancel, boot, on_state):
    from .control import _adb, _guard, _shell  # tv.control imports this module first.
    target = row['ip'] + ':5555'
    guard = _guard(row)
    raw = _shell(row, cancel, guard + '{ pm list packages --show-versioncode ' + PACKAGE + '; echo @@; '
                 'settings get secure enabled_notification_listeners; }')
    installed = re.search(r'^package:' + re.escape(PACKAGE) + r' versionCode:(\d+)\s*$', raw, re.M)
    provisioned = False
    if not installed or int(installed[1]) != VERSION:
        if not APK.is_file():
            raise FileNotFoundError(f'TV agent {VERSION} is not built; run obsidience/tv/android/build.sh')
        _adb(row, cancel, 'push', str(APK), '/data/local/tmp/obsidience-tv.apk', timeout=30)
        result = _shell(row, cancel, guard + '{ pm install -r /data/local/tmp/obsidience-tv.apk; '
                        'rm -f /data/local/tmp/obsidience-tv.apk; }', timeout=90)
        if 'Success' not in result:
            raise ValueError('TV agent install failed: ' + result.strip()[-200:])
        log.info('TV agent %s installed', VERSION)
        provisioned = True
    if LISTENER not in raw.partition('@@')[2]:
        _shell(row, cancel, guard + 'cmd notification allow_listener ' + LISTENER)
        provisioned = True
    # Append the service to whatever is enabled; another service is never removed or replaced.
    enabled = _shell(row, cancel, guard + '{ s=$(settings get secure enabled_accessibility_services); '
                     'case "$s" in *' + PACKAGE + '/*) echo kept;; ""|null) settings put secure '
                     'enabled_accessibility_services ' + SERVICE + ' && echo added;; *) settings put secure '
                     'enabled_accessibility_services "$s:' + SERVICE + '" && echo added;; esac; '
                     '[ "$(settings get secure accessibility_enabled)" = 1 ] || '
                     '{ settings put secure accessibility_enabled 1 && echo switched; }; }')
    if 'kept' not in enabled and 'added' not in enabled:
        raise ValueError('TV agent accessibility service could not be enabled')
    provisioned = provisioned or 'added' in enabled or 'switched' in enabled
    # A forward left by an earlier Harness process for this socket is removed; this process owns the name.
    for line in _adb(row, cancel, 'forward', '--list').decode(errors='replace').splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0] == target and parts[2] == 'localabstract:' + SOCKET:
            _adb(row, cancel, 'forward', '--remove', parts[1])
    port = int(_adb(row, cancel, 'forward', 'tcp:0', 'localabstract:' + SOCKET).decode().strip())
    # A just-provisioned service binds within a few seconds; until then the forward closes at once.
    deadline = time.monotonic() + (8 if provisioned else 0)
    while True:
        sock = None
        try:
            sock = socket.create_connection(('127.0.0.1', port), timeout=2)
            sock.settimeout(None)
            agent = Agent(sock, port, target, boot, on_state)
            hello = agent.request('hello', timeout=2)
            if hello.get('version') != VERSION:
                agent.close()
                raise ValueError(f"TV agent reports version {hello.get('version')}, expected {VERSION}")
            log.info('TV agent connected on tcp:%s', port)
            return agent
        except (ConnectionError, TimeoutError, OSError) as error:
            if sock is not None:
                sock.close()
            if time.monotonic() > deadline or (cancel is not None and cancel.is_set()):
                _adb(row, None, 'forward', '--remove', f'tcp:{port}')
                raise ConnectionError(f'TV agent did not answer: {error}') from error
            time.sleep(.5)
        except ValueError:
            _adb(row, None, 'forward', '--remove', f'tcp:{port}')
            raise

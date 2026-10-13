#!/usr/bin/python3
"""Obsidience TV voice router: the Executive's spoken replies from the television too, in step
with the desk speakers, without slowing its chirps.

A second speaker over Wi-Fi is only in step if both speakers play each moment of sound at an
agreed time. Snapcast does that (obsidience-tv-voice-server.service): its server is a PipeWire
sink, obsidience_tv_voice; one client plays on the desk speakers (obsidience-tv-voice-desk.service)
and one on the television (the Snapcast app there), each at the server's time plus the server's
buffer. The price is that buffer: sound on this route starts about 0.3 s later.

Speech can afford that; the chirp that opens the line cannot (owner, 2026-10-12: it must be as
snappy as possible). So the speech worker's one playback stream is on its own speaker while
the Executive waits for its name, and the opening chirp plays there directly, as it always
did. Once the line is open and that chirp has ended, while the owner speaks, the stream moves
onto the Snapcast sink: the "accepted" chirp, the reply and the chirp that closes it then play
on both speakers in step. (The reply follows the "accepted" chirp without a gap, so there is
no later quiet moment to move in.) After the closing chirp the stream goes back. Without a
television client, the desk client, the Harness or the Snapcast server, the voice simply
stays on its own speaker.

Nothing else is touched: the worker still plays one stream, and the microphone's echo reference
is still the monitor of the physical speaker, which carries the voice whichever way it arrives.

It acts on events only: the Harness's action trace (chirps starting and finishing) and voice
state, the Snapcast server's client notifications, and the audio server's stream events.

Fail-safe: the stream names its own speaker (target.object). If the Snapcast sink disappears
the audio server puts the stream back there by itself; if that speaker is not the one the desk
client plays on (VOICE_DESK_SINK), nothing is moved.
"""
from __future__ import annotations

import json
import logging
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time

from websockets.sync.client import connect

log = logging.getLogger('voice')

VOICE_SINK = 'obsidience_tv_voice'
DESK_CLIENT = 'obsidience-desk'
CONTROL = ('127.0.0.1', 1705)
HARNESS = 'ws://127.0.0.1:8765'
WORKER = 'obsidience.harness.realtime.speech.worker'
CUE = re.compile(r'Computer cue: (\w+) \((started|finished)\)')
CLOSING = {'complete', 'cancel', 'error'}
# A chirp's last samples are still in the worker's output buffer when it reports the chirp
# written (40 ms chunks plus the audio server's buffer); the stream moves once they have left.
DRAIN = 0.25
# The opening chirp is queued within milliseconds of the line opening; a line that has been open
# this long without one was opened inside a sentence and has none.
CHIRP_GRACE = 0.2
# An exchange longer than this without its closing chirp is not waited for.
TURN_LIMIT = 300.0


class State:
    """What the events have said so far. `changed` wakes the router."""

    def __init__(self):
        self.changed = threading.Event()
        self.lock = threading.Lock()
        self.listening = False     # A television client and the desk client are connected.
        self.harness = False
        self.line_open = False     # The Executive listens for a command (or is in a conversation).
        self.opened_at = None      # Monotonic time the line opened, until this exchange's route is decided.
        self.chirping = False      # The opening chirp is being written.
        self.exchange = None       # Monotonic time since which this exchange takes the Snapcast route.
        self.move_after = 0.0      # Not before this monotonic time (a chirp's tail is draining).

    def cue(self, name, edge):
        with self.lock:
            now = time.monotonic()
            if name == 'ready':
                self.chirping = edge == 'started'
                if edge == 'finished' and self.line_open:
                    self.exchange, self.opened_at, self.move_after = now, None, now + DRAIN
            elif name in CLOSING and edge == 'finished':
                self.exchange, self.opened_at, self.move_after = None, None, now + DRAIN
        self.changed.set()

    def voice_state(self, state):
        with self.lock:
            line_open = bool(state.get('ready')) and bool(state.get('command_open'))
            if line_open and not self.line_open:
                self.opened_at = time.monotonic()
            elif not line_open:
                self.exchange = self.opened_at = None  # The line closed: back to the direct route.
            self.line_open = line_open
        self.changed.set()

    def wanted(self):
        """(together, earliest monotonic time to act, when to look again or None)."""
        with self.lock:
            now = time.monotonic()
            again = None
            if self.opened_at is not None and not self.chirping:
                if now - self.opened_at >= CHIRP_GRACE:
                    self.exchange, self.opened_at = now, None  # No opening chirp for this line.
                else:
                    again = self.opened_at + CHIRP_GRACE
            if self.exchange is not None and now - self.exchange > TURN_LIMIT:
                self.exchange = None
            together = self.harness and self.listening and self.line_open and self.exchange is not None
            return together, self.move_after, again


def follow_trace(state, stopping):
    """The Harness's action trace: chirps starting and finishing."""
    cursor = None
    while not stopping.is_set():
        try:
            with connect(HARNESS + '/ws/trace' + (f'?after={cursor}' if cursor is not None else ''), open_timeout=3) as ws:
                first = True
                while not stopping.is_set():
                    try:
                        message = json.loads(ws.recv(timeout=1.0))
                    except TimeoutError:
                        continue
                    cursor = message.get('cursor', cursor)
                    if first:
                        first = False
                        if message.get('type') != 'entry':
                            continue  # History: only chirps from now on matter.
                    entries = [message['entry']] if message.get('type') == 'entry' else message.get('entries', [])
                    for entry in entries:
                        found = CUE.fullmatch(str(entry.get('line', '')))
                        if found:
                            state.cue(found[1], found[2])
        except Exception as error:  # noqa: BLE001 - the Harness restarts; the voice then stays direct.
            log.debug('trace: %s', type(error).__name__)
        stopping.wait(2)


def follow_voice(state, stopping):
    """The Harness's voice state: whether a reply's audio is playing, whether voice runs at all."""
    while not stopping.is_set():
        try:
            with connect(HARNESS + '/ws/realtime', open_timeout=3) as ws:
                state.harness = True
                state.changed.set()
                while not stopping.is_set():
                    try:
                        message = json.loads(ws.recv(timeout=1.0))
                    except TimeoutError:
                        continue
                    if isinstance(message.get('state'), dict):
                        state.voice_state(message['state'])
        except Exception as error:  # noqa: BLE001
            log.debug('voice state: %s', type(error).__name__)
        with state.lock:
            state.harness, state.line_open, state.exchange, state.opened_at = False, False, None, None
        state.changed.set()
        stopping.wait(2)


def follow_clients(state, stopping):
    """The Snapcast server: is the television's client (and the desk client) connected."""
    while not stopping.is_set():
        try:
            with socket.create_connection(CONTROL, 3) as sock:
                sock.settimeout(None)  # It waits for the server's next notification, however long.
                reader = sock.makefile('rb')
                while not stopping.is_set():
                    sock.sendall(b'{"id":1,"jsonrpc":"2.0","method":"Server.GetStatus"}\r\n')
                    while True:
                        reply = json.loads(reader.readline() or b'null')
                        if reply is None:
                            raise ConnectionError('closed')
                        if reply.get('id') == 1:
                            break
                    clients = [client for group in reply['result']['server']['groups'] for client in group['clients']
                               if client.get('connected')]
                    listening = (any(client['id'] == DESK_CLIENT for client in clients)
                                 and any(client['id'] != DESK_CLIENT for client in clients))
                    if listening != state.listening:
                        log.info('the television %s', 'listens' if listening else 'does not listen')
                    state.listening = listening
                    state.changed.set()
                    # Sleep until the server says something changed (a client came or went).
                    while True:
                        notice = reader.readline()
                        if not notice:
                            raise ConnectionError('closed')
                        if b'"Client.On' in notice or b'"Server.OnUpdate"' in notice:
                            break
        except Exception as error:  # noqa: BLE001
            log.debug('clients: %s', type(error).__name__)
        state.listening = False
        state.changed.set()
        stopping.wait(2)


def follow_streams(state, stopping):
    """The audio server: a new speech worker brings a new stream."""
    while not stopping.is_set():
        events = subprocess.Popen(['pactl', 'subscribe'], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE)
        try:
            for line in events.stdout:
                if stopping.is_set():
                    break
                if b"'new' on sink-input" in line or b"'remove' on sink-input" in line:
                    state.changed.set()
        finally:
            events.terminate()
        stopping.wait(2)


def pactl(*arguments):
    done = subprocess.run(['pactl', '--format=json', *arguments], stdin=subprocess.DEVNULL, capture_output=True,
                          text=True, timeout=5)
    if done.returncode:
        raise OSError('The audio server did not answer')
    return json.loads(done.stdout) if done.stdout.strip() else None


def voice():
    """The speech worker's playback stream as (index, the sink it plays on, its own speaker); or None."""
    sinks = {sink['index']: sink['name'] for sink in pactl('list', 'sinks')}
    for stream in pactl('list', 'sink-inputs'):
        properties = stream.get('properties', {})
        try:
            with open(f"/proc/{int(properties.get('application.process.id', 0))}/cmdline", 'rb') as command:
                if WORKER.encode() not in command.read():
                    continue
        except (OSError, ValueError):
            continue
        return stream['index'], sinks.get(stream.get('sink')), properties.get('target.object')
    return None


def route(together, desk):
    """Put the voice on the Snapcast sink (together) or on its own speaker; True when it moved."""
    stream = voice()
    if stream is None:
        return False
    index, sink, own = stream
    if own != desk:
        together = False  # The Executive speaks from another speaker than the desk client's.
    wanted = VOICE_SINK if together else own
    if not wanted or sink == wanted:
        return False
    if subprocess.run(['pactl', 'move-sink-input', str(index), wanted], timeout=5).returncode:
        raise OSError('The voice could not be moved')
    log.info('the voice plays %s', 'on the desk speakers and the television, in step' if together
             else 'on the desk speakers directly')
    return True


def main():
    logging.basicConfig(level=logging.INFO, format='%(name)s: %(message)s', stream=sys.stdout)
    desk = os.environ.get('VOICE_DESK_SINK', '')
    if not desk:
        sys.exit('VOICE_DESK_SINK is not set')
    stopping = threading.Event()
    state = State()
    for number in (signal.SIGTERM, signal.SIGINT):
        signal.signal(number, lambda *_: (stopping.set(), state.changed.set()))
    for follow in (follow_trace, follow_voice, follow_clients, follow_streams):
        threading.Thread(target=follow, args=(state, stopping), name=follow.__name__, daemon=True).start()
    try:
        again = None
        while not stopping.is_set():
            state.changed.wait(None if again is None else max(0.0, again - time.monotonic()))
            state.changed.clear()
            together, earliest, again = state.wanted()
            wait = earliest - time.monotonic()
            if wait > 0:
                stopping.wait(wait)  # A chirp's tail leaves the worker's buffer first.
                together, _, again = state.wanted()
            try:
                route(together, desk)
            except (OSError, ValueError, subprocess.TimeoutExpired) as error:
                log.warning('the voice was not moved (%s)', type(error).__name__)
    finally:
        try:
            route(False, desk)  # Cleanup paired with the move: the voice leaves as it came.
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
        log.info('stopped')


if __name__ == '__main__':
    main()

#!/usr/bin/python3
"""Obsidience TV voice router: the Executive's spoken replies from the television too, in step
with the desk speakers, without slowing the chirp that opens the line.

A second speaker over Wi-Fi is only in step if both speakers play each moment of sound at an
agreed time. Snapcast does that (obsidience-tv-voice-server.service): its server is a PipeWire
sink, obsidience_tv_voice; one client plays on the desk speakers (obsidience-tv-voice-desk.service)
and one on the television (the Snapcast app there), each at the server's time plus the server's
buffer. The price is that buffer: sound on this route starts about 0.3 s later.

While a television client listens, this router keeps a small chain in front of the speakers:
a voice sink (obsidience_tv_voice_in) that the speech worker's one playback stream is put on,
and two paths out of it that run all the time, one straight to the desk speakers and one into
the Snapcast sink. Exactly one of the two is audible. Choosing between them is a mute, not a
move: nothing is relinked while the Executive speaks. (Moving the worker's stream onto the
Snapcast sink for each reply was tried first: moved in the first milliseconds of a chirp it
stalled for two seconds, and afterwards the Snapcast server played nothing at all until it was
restarted.)

The direct path is the audible one while the Executive waits for its name, so the opening
chirp is as immediate as ever (owner, 2026-10-12: it must be as snappy as possible). Once the
line is open and that chirp has ended, while the owner speaks, the Snapcast path takes over:
the "accepted" chirp, the reply and the closing chirp play on both speakers in step, and then
the direct path returns.

A reply must never be lost to this. While the Snapcast path is the audible one the router
listens, electrically, to what goes into the chain and what the desk speakers receive; sound
going in with nothing coming out for most of a second puts the direct path back at once and
restarts the Snapcast server afterwards.

Without a television client, the desk client, the Harness or the Snapcast server there is no
chain and the voice plays on its own speaker as it always did. The microphone's echo reference
is unchanged: it is the monitor of the physical speaker, which carries the voice whichever way
it arrives. If this router dies, the audio server puts the worker's stream back on the speaker
it names (target.object) by itself. It acts on events only: the Harness's action trace (chirps)
and voice state, the Snapcast server's client notifications, the audio server's stream events.
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

VOICE_SINK = 'obsidience_tv_voice'      # The Snapcast server.
CHAIN_SINK = 'obsidience_tv_voice_in'   # What the worker's stream is put on.
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
# In step, sound into the chain with none reaching the desk speakers for this long is a dead
# Snapcast path (the server's buffer is 0.3 s).
DEAD_AFTER = 0.9
# An exchange ends with its closing chirp, however long the Executive works before it speaks.
# Should that chirp never come, the exchange ends once the line has been closed and nothing has
# played or been said for this long.
QUIET_LIMIT = 120.0


class State:
    """What the events have said so far. `changed` wakes the router."""

    def __init__(self):
        self.changed = threading.Event()
        self.lock = threading.Lock()
        self.listening = False     # A television client and the desk client are connected.
        self.harness = False
        self.line_open = False     # The Executive listens for a command.
        self.speaking = False      # The owner is speaking.
        self.opened_at = None      # Monotonic time the line opened, until this exchange's route is decided.
        self.chirping = False      # The opening chirp is being written.
        self.clear_at = 0.0        # Monotonic time the opening chirp's tail has left the worker's buffer.
        self.exchange = False      # This exchange takes the Snapcast route.
        self.quiet_since = None    # Monotonic time since which the line is closed and nothing plays.
        self.playing = False       # A reply's audio is being written.
        self.move_after = 0.0      # Not before this monotonic time (a closing chirp's tail is draining).

    def cue(self, name, edge):
        with self.lock:
            now = time.monotonic()
            if name == 'ready':
                self.chirping = edge == 'started'
                if edge == 'finished':
                    self.clear_at = now + DRAIN
            elif name in CLOSING and edge == 'finished':
                self.exchange, self.opened_at, self.move_after = False, None, now + DRAIN
        self.changed.set()

    def voice_state(self, state):
        with self.lock:
            now = time.monotonic()
            running = bool(state.get('ready'))
            line_open = running and bool(state.get('command_open'))
            if line_open and not self.line_open:
                self.opened_at, self.clear_at = now, 0.0
            self.line_open = line_open
            self.speaking = running and bool(state.get('user_speaking'))
            if not running:
                self.exchange, self.opened_at = False, None  # No voice at all: nothing to keep in step.
            # The line also closes when a command is taken, with the reply still to come.
            self.playing = running and (state.get('playback') or {}).get('status', 'idle') != 'idle'
            quiet = not line_open and not self.speaking and not self.playing
            self.quiet_since = (self.quiet_since or now) if quiet else None
        self.changed.set()

    def wanted(self):
        """(together, earliest monotonic time to act, when to look again or None)."""
        with self.lock:
            now = time.monotonic()
            again = None
            if not self.exchange and self.line_open and self.opened_at is not None and not self.chirping:
                # No opening chirp follows a line opened inside a sentence; one that was played
                # must have left the buffer.
                ready = max(self.opened_at + CHIRP_GRACE, self.clear_at)
                if now < ready:
                    again = ready
                elif self.speaking:
                    self.exchange, self.opened_at = True, None
            if self.exchange and self.quiet_since is not None:
                if now - self.quiet_since >= QUIET_LIMIT:
                    self.exchange = False
                else:
                    again = min(again or float('inf'), self.quiet_since + QUIET_LIMIT)
            return self.exchange, self.move_after, again

    def idle(self):
        """Nothing is being said, played or waited for: the moment to rearrange."""
        with self.lock:
            return not (self.line_open or self.speaking or self.playing or self.exchange or self.chirping)


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
            state.harness, state.line_open, state.speaking, state.exchange, state.opened_at, state.quiet_since = (
                False, False, False, False, None, None)
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


def streams():
    """The audio server's playback streams, each with the name of the sink it plays on."""
    sinks = {sink['index']: sink['name'] for sink in pactl('list', 'sinks')}
    return [{**stream, 'sink_name': sinks.get(stream.get('sink'))} for stream in pactl('list', 'sink-inputs')]


def voice(found):
    """The speech worker's playback stream as (index, the sink it plays on, its own speaker); or None."""
    for stream in found:
        properties = stream.get('properties', {})
        try:
            with open(f"/proc/{int(properties.get('application.process.id', 0))}/cmdline", 'rb') as command:
                if WORKER.encode() not in command.read():
                    continue
        except (OSError, ValueError):
            continue
        return stream['index'], stream['sink_name'], properties.get('target.object')
    return None


class Chain:
    """The voice sink and its two paths, for as long as a television client listens."""

    PATHS = {'direct': None, 'snapcast': VOICE_SINK}  # direct plays on the desk speaker.

    def __init__(self, desk):
        self.desk = desk
        self.children = []

    def start(self):
        # The sink lives as long as the client that created it; pw-cli keeps it while its input stays open.
        self.children.append(subprocess.Popen(
            ['pw-cli', '-m', 'create-node', 'adapter',
             '{ factory.name=support.null-audio-sink node.name=%s node.description="Executive voice" '
             'media.class=Audio/Sink audio.position=[FL FR] object.linger=false }' % CHAIN_SINK],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        self._until(lambda: any(sink['name'] == CHAIN_SINK for sink in pactl('list', 'sinks')), 'the voice sink')
        for name, target in self.PATHS.items():
            self.children.append(subprocess.Popen(
                ['pw-loopback', '-n', f'obsidience-tv-voice-{name}', '-C', CHAIN_SINK,
                 '--capture-props', f'stream.capture.sink=true node.name=obsidience_tv_voice_tap_{name}',
                 '-P', target or self.desk, '--playback-props', f'node.name=obsidience_tv_voice_{name}'],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        self._until(lambda: len(self._paths()) == len(self.PATHS), 'the two paths')
        self.audible('direct')

    def _until(self, ready, what):
        deadline = time.monotonic() + 6
        while not ready():
            if time.monotonic() >= deadline or not self.alive():
                raise OSError(f'{what} did not appear')
            time.sleep(0.1)

    def _paths(self):
        """{path: (stream index, sink it plays on)} of the paths' playback streams."""
        wanted = {f'obsidience_tv_voice_{name}': name for name in self.PATHS}
        return {wanted[stream['properties']['node.name']]: (stream['index'], stream['sink_name'])
                for stream in streams() if stream.get('properties', {}).get('node.name') in wanted}

    def audible(self, path):
        """Make one path the audible one. A mute, not a move: nothing is relinked."""
        paths = self._paths()
        if set(paths) != set(self.PATHS) or any(sink != (self.PATHS[name] or self.desk) for name, (_, sink) in paths.items()):
            raise OSError('a path of the voice chain is missing or plays elsewhere')
        # The one to be heard first, so that a switch never leaves both silent.
        for name in sorted(paths, key=lambda name: name != path):
            if subprocess.run(['pactl', 'set-sink-input-mute', str(paths[name][0]), '0' if name == path else '1'],
                              timeout=5).returncode:
                raise OSError('a path of the voice chain could not be switched')

    def alive(self):
        return bool(self.children) and all(child.poll() is None for child in self.children)

    def stop(self):
        for child in reversed(self.children):
            child.terminate()
        for child in self.children:
            try:
                child.wait(3)
            except subprocess.TimeoutExpired:
                child.kill()
        self.children = []


class Watch:
    """While the Snapcast path is the audible one: does what goes into the chain reach the desk speakers?"""

    def __init__(self, desk, dead):
        self.dead = dead
        self.stopping = threading.Event()
        self.taps = [subprocess.Popen(['parec', f'--device={source}.monitor', '--format=s16le', '--rate=8000',
                                       '--channels=1', '--latency-msec=40'], stdin=subprocess.DEVNULL,
                                      stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                     for source in (CHAIN_SINK, desk)]
        self.went_in = None
        self.came_out = False
        for tap, loud in zip(self.taps, (self._in, self._out)):
            threading.Thread(target=self._read, args=(tap, loud), daemon=True).start()

    def _read(self, tap, loud):
        while not self.stopping.is_set():
            block = tap.stdout.read(640)  # 40 ms
            if not block:
                return
            if max(abs(int.from_bytes(block[i:i + 2], 'little', signed=True)) for i in range(0, len(block) - 1, 16)) > 150:
                loud()

    def _in(self):
        now = time.monotonic()
        if self.went_in is None:
            self.went_in = now
        elif not self.came_out and now - self.went_in > DEAD_AFTER and not self.stopping.is_set():
            self.stopping.set()
            self.dead()

    def _out(self):
        if self.went_in is not None:
            self.came_out = True

    def stop(self):
        self.stopping.set()
        for tap in self.taps:
            tap.terminate()


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
    chain = watch = None
    in_step = False
    failed = threading.Event()  # The Snapcast path played nothing: direct until the server is restarted.

    def fall_back():
        failed.set()
        state.changed.set()

    def leave_step():
        nonlocal watch, in_step
        if watch is not None:
            watch.stop()
            watch = None
        if in_step:
            in_step = False
            log.info('the voice plays on the desk speakers directly')
        if chain is not None and chain.alive():
            chain.audible('direct')

    try:
        again = None
        while not stopping.is_set():
            state.changed.wait(None if again is None else max(0.0, again - time.monotonic()))
            state.changed.clear()
            together, earliest, again = state.wanted()
            try:
                listening = state.harness and state.listening
                if chain is not None and not chain.alive():
                    log.warning('the voice chain ended by itself')
                    leave_step()
                    chain.stop()
                    chain = None
                if failed.is_set() and in_step:
                    log.error('the Snapcast path played nothing; the reply continues on the desk speakers')
                    leave_step()
                found = streams()
                stream = voice(found)
                usable = stream is not None and stream[2] == desk
                if chain is None and listening and usable and state.idle() and not failed.is_set():
                    chain = Chain(desk)
                    chain.start()
                    log.info('the television listens: the voice chain is up')
                if chain is not None and state.idle():
                    if listening and usable and not failed.is_set():
                        if stream[1] != CHAIN_SINK:
                            subprocess.run(['pactl', 'move-sink-input', str(stream[0]), CHAIN_SINK], timeout=5)
                    else:
                        if stream is not None and stream[1] == CHAIN_SINK and stream[2]:
                            subprocess.run(['pactl', 'move-sink-input', str(stream[0]), stream[2]], timeout=5)
                        chain.stop()
                        chain = None
                        log.info('the voice chain is down')
                        if failed.is_set():
                            # The server answers its clients but plays nothing: only a restart cured it.
                            # This unit is part of the server's and restarts with it.
                            log.error('restarting the Snapcast server')
                            subprocess.Popen(['systemctl', '--user', '--no-block', 'restart',
                                              'obsidience-tv-voice-server.service'])
                            failed.clear()
                want = (chain is not None and together and not failed.is_set()
                        and stream is not None and stream[1] == CHAIN_SINK)
                if want != in_step:
                    wait = earliest - time.monotonic()
                    if wait > 0:
                        stopping.wait(wait)  # A chirp's tail leaves the worker's buffer first.
                    if want:
                        chain.audible('snapcast')
                        watch = Watch(desk, fall_back)
                        in_step = True
                        log.info('the voice plays on the desk speakers and the television, in step')
                    else:
                        leave_step()
            except (OSError, ValueError, KeyError, subprocess.TimeoutExpired) as error:
                log.warning('the voice chain could not be arranged (%s)', error)
                again = time.monotonic() + 5
    finally:
        try:
            leave_step()
            if chain is not None:
                found = voice(streams())
                if found is not None and found[1] == CHAIN_SINK and found[2]:
                    subprocess.run(['pactl', 'move-sink-input', str(found[0]), found[2]], timeout=5)
                chain.stop()  # Cleanup paired with its start: the voice leaves as it came.
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
        log.info('stopped')


if __name__ == '__main__':
    main()

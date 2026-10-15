"""The PC route's Android source: TV apps hosted on the workstation, which the registered TV only displays.

An Android TV instance (obsidience-tv-android.service, obsidience/tv/host/README.md) is one more
window of the workstation's TV compositor, so a YouTube video starts in its SmartTube in one to two
seconds instead of the Fire OS app's 26 s. This module is its client: ADB at the instance's own
address, which only this workstation reaches. Each call is one shell command that first checks, in
the same command, that the target is that instance. An effect is sent once: a lost or late reply is
an error for the caller to report, never a reason to send it again. What plays is read from
Android's own media session, never assumed from a command that was sent. Volume stays with the TV.
"""
from __future__ import annotations

from pathlib import Path
import re
import shlex
import subprocess
import time

ADDRESS = '10.89.240.2:5555'
# The instance's bridge exists only while its container runs. ADB spends eight seconds on a connection
# to an address nobody holds, so it is asked to connect only then.
_BRIDGE = Path('/sys/class/net/obstv0')
_GUARD = 'test "$(getprop ro.product.device)" = waydroid_tv_x86_64 && '
PLAYER = 'org.smarttube.stable'
LINK = re.compile(r'https://www\.youtube\.com/watch\?v=[A-Za-z0-9_-]{11}')
# The instance is local: a read answers in about 50 ms.
TIMEOUT = 3.0
# Measured 2026-10-12: the session reports playing 0.8 s after a link while SmartTube already plays
# and 1.8-2.1 s after one that starts it.
START_LIMIT = 12.0
# android.media.session.PlaybackState codes, in the words the tuner uses for its player.
_PLAYBACK = {0: 'idle', 1: 'idle', 2: 'paused', 3: 'playing', 4: 'playing', 5: 'playing',
             6: 'loading', 7: 'failed', 8: 'loading'}


def _shell(command, limit=TIMEOUT):
    """One guarded shell command on the instance, sent once; OSError when it was not answered."""
    argv = ['/usr/bin/adb', '-s', ADDRESS, 'shell', _GUARD + command]
    for first in (True, False):
        try:
            done = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                  errors='replace', timeout=limit)
        except subprocess.TimeoutExpired:
            raise TimeoutError('The Android TV instance did not answer') from None
        if not done.returncode:
            return done.stdout
        if not (first and re.search(r'not found|device offline', done.stderr) and _BRIDGE.exists()):
            raise OSError('The Android TV instance did not take the command: ' + done.stderr.strip()[:120])
        # ADB refused before sending anything: its server has no transport to the running instance, or a
        # dead one (a restarted instance or ADB server; left alone, ADB takes half a minute to notice a
        # restart). Renew only this transport; the server is never restarted.
        for words in (['disconnect', ADDRESS], ['connect', ADDRESS], ['-s', ADDRESS, 'wait-for-device']):
            try:
                subprocess.run(['/usr/bin/adb', *words], stdin=subprocess.DEVNULL, capture_output=True, timeout=TIMEOUT)
            except subprocess.TimeoutExpired:
                raise TimeoutError('The Android TV instance did not answer') from None


def _session(raw):
    """SmartTube's media session from `dumpsys media_session` text, in the tuner's state shape."""
    tuner, mine = {'source': 'android', 'playback': 'idle'}, False
    for line in raw.splitlines():
        line = line.strip()
        if header := re.fullmatch(r'(\S+) (\S+) \(userId=\d+\)', line):
            mine, session = header[1] == PLAYER and 'run' not in tuner, header[2]  # The newest is listed first.
        elif not mine:
            continue
        elif found := re.match(r'state=PlaybackState \{state=(?:[A-Z_]+\()?(\d+)\)?, position=(-?\d+).*?updated=(\d+)', line):
            # The session and the moment its state last changed name one uninterrupted run of playback:
            # a pause, a seek, a stall or another video in the same session is a new one.
            tuner.update(playback=_PLAYBACK.get(int(found[1]), 'idle'), run=f'{session}@{found[3]}',
                         position_ms=max(0, int(found[2])))
        elif found := re.match(r'metadata: size=\d+, description=(.*)', line):
            title = re.sub(r'(?:, null)+$', '', found[1]).strip()
            if title and title != 'null':  # SmartTube 32.56 names none; a player that does is reported.
                tuner['title'] = title[:160]
    return tuner


def state():
    """What the instance plays now, or None when it does not answer (it is not running).

    playback is idle (no player session), loading, playing, paused or failed, from the media session
    of the instance's YouTube player; run names that session's current uninterrupted run of playback
    and position_ms is the position it last reported.
    """
    try:
        return _session(_shell('dumpsys media_session'))
    except OSError:
        return None


def available():
    """Whether the instance answers (one read)."""
    return state() is not None


def play(link, cancel=None, limit=START_LIMIT, start=0):
    """Play one YouTube video in the instance's player; the run of playback it started, else None.

    start > 0 adds YouTube's t parameter (seconds). SmartTube 32.56 reads it from the link
    (IntentExtractor.extractVideoTimeMs) and seeks there once the video loads, overriding its own saved
    position (VideoStateController.restorePendingPosition); 0 or none leaves the position to SmartTube.

    The link is sent once. Playback counts only when the session started or changed after the link and
    reports playing: that is the instance's own readback that a player runs, not what its picture shows.
    None means the link was taken but nothing played within the limit; the caller reports that as
    unverified. ValueError means it was refused and nothing started.
    """
    if not LINK.fullmatch(link):
        raise ValueError('The Android TV instance opens YouTube video links only')
    if type(start) is not int or not 0 <= start <= 86400:
        raise ValueError('The start position must be whole seconds 0-86400')
    target = link + (f'&t={start}' if start else '')
    before = state()
    if before is None:
        raise OSError('The Android TV instance does not answer')
    # A start that Android refuses (no such player) is told apart from one that got no answer.
    started = _shell('am start -W -a android.intent.action.VIEW -d ' + shlex.quote(target) + ' ' + PLAYER
                     + ' || echo Error: not started', limit=8.0)
    if 'Error' in started:
        raise ValueError('The Android TV instance did not start the video: ' + started.strip()[-160:])
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline:
        now = state()
        if now is not None and now['playback'] == 'playing' and now['run'] != before.get('run'):
            return now['run']
        if cancel is not None:
            if cancel.wait(.2):
                raise InterruptedError('TV command cancelled')
        else:
            time.sleep(.2)
    return None


def _reach(command, wanted, limit=2.5):
    """One media-session command, then the session's own readback; True when it shows a wanted state."""
    _shell('cmd media_session dispatch ' + command)
    deadline = time.monotonic() + limit
    while True:
        now = state()
        if now is not None and now['playback'] in wanted:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(.15)


def pause(paused=True):
    """Pause or resume the player once; True when its session reads back that state."""
    return _reach('pause', ('paused',)) if paused else _reach('play', ('playing',))


def stop():
    """End playback (the player stays loaded); True when the session reads back idle."""
    return _reach('stop', ('idle',))

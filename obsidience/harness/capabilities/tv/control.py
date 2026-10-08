"""One registered TV, upstream ADB, bounded effects and fresh visual evidence."""
from __future__ import annotations

import io
import ipaddress
import json
from pathlib import Path
import re
import shlex
import subprocess
import threading
import time

from PIL import Image

_LOCK = threading.Lock()
KEYS = {name: 'KEYCODE_' + code for name, code in {
    'up': 'DPAD_UP', 'down': 'DPAD_DOWN', 'left': 'DPAD_LEFT', 'right': 'DPAD_RIGHT',
    'select': 'DPAD_CENTER', 'back': 'BACK', 'home': 'HOME', 'menu': 'MENU',
    'play': 'MEDIA_PLAY', 'pause': 'MEDIA_PAUSE', 'rewind': 'MEDIA_REWIND',
    'fast_forward': 'MEDIA_FAST_FORWARD', 'volume_up': 'VOLUME_UP',
    'volume_down': 'VOLUME_DOWN', 'mute': 'VOLUME_MUTE',
    'enter': 'ENTER', 'delete': 'DEL',
}.items()}


def _inventory():
    path = Path(__file__).resolve().parents[3] / 'state' / 'television.json'
    raw = path.read_bytes()
    if len(raw) > 8192:
        raise ValueError('TV inventory exceeds its bound')
    row = json.loads(raw)
    ip = ipaddress.IPv4Address(row['ip'])
    if not ip.is_private or ip.is_loopback or ip.is_multicast or ip.is_unspecified:
        raise ValueError('TV address must be a private LAN address')
    if not re.fullmatch(r'[A-Za-z0-9_-]{4,80}', row['serial']):
        raise ValueError('Invalid TV serial binding')
    if not re.fullmatch(r'[A-Za-z0-9_. -]{1,100}', row['model']):
        raise ValueError('Invalid TV model binding')
    apps = row['apps']
    if (not isinstance(apps, dict) or len(apps) > 30 or any(
            not re.fullmatch(r'[a-z][a-z0-9_]{0,30}', k)
            or not re.fullmatch(r'[a-zA-Z0-9_]+(?:\.[a-zA-Z0-9_]+)+', v)
            for k, v in apps.items())):
        raise ValueError('Invalid TV application inventory')
    return row


def _adb(row, cancel, *args, timeout=8, connect=False):
    if cancel is not None and cancel.is_set():
        raise InterruptedError('TV command cancelled')
    target = row['ip'] + ':5555'
    argv = ['/usr/bin/adb', *(['connect', target] if connect else ['-s', target, *args])]
    with subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as process:
        deadline = time.monotonic() + timeout
        try:
            while True:
                if cancel is not None and cancel.is_set():
                    raise InterruptedError('TV command cancelled')
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('TV did not respond before the command deadline')
                try:
                    out, err = process.communicate(timeout=min(.1, remaining))
                    break
                except subprocess.TimeoutExpired:
                    continue
            if process.returncode:
                raise OSError('ADB rejected or lost the TV connection: ' + err.decode(errors='replace')[:200])
            if len(out) > 16 * 1024 * 1024:
                raise ValueError('TV response exceeded its bound')
            return out
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()


def _shell(row, cancel, command):
    return _adb(row, cancel, 'shell', command).decode(errors='replace')


def _guard(row):
    # The remote shell rechecks identity in the same command before any effect.
    return ('test "$(getprop ro.serialno)" = ' + shlex.quote(row['serial'])
            + ' && test "$(getprop ro.product.oemmodel)" = ' + shlex.quote(row['model']) + ' && ')


def _power(row, cancel):
    raw = _shell(row, cancel, 'getprop ro.serialno; getprop ro.product.oemmodel; dumpsys power')
    lines = raw.splitlines()
    if lines[:2] != [row['serial'], row['model']]:
        raise ValueError('The ADB target is not the registered TV')
    wake = re.search(r'^\s*mWakefulness=(\w+)', raw, re.M)
    display = re.search(r'^Display Power: state=(\w+)', raw, re.M)
    if not wake or not display:
        raise ValueError('TV power readback unavailable')
    return {'wakefulness': wake[1], 'display': display[1]}


def _focus(row, cancel):
    raw = _shell(row, cancel, _guard(row) + 'dumpsys window')
    match = re.search(r'^\s*mCurrentFocus=(Window\{[^\n]+\})', raw, re.M)
    if not match:
        raise ValueError('TV foreground window unavailable')
    return match[1]


def _observe(row, cancel, context):
    context.pop('_tv_observation', None)
    # App launch may change windows during the first frame. Retry only the
    # read-only capture, never the launch or input that preceded it.
    for _ in range(3):
        before = _focus(row, cancel)
        png = _adb(row, cancel, 'exec-out', _guard(row) + 'screencap -p')
        after = _focus(row, cancel)
        if before == after:
            break
    else:
        raise ValueError('TV foreground changed during capture; observe again')
    with Image.open(io.BytesIO(png)) as image:
        if image.format != 'PNG' or image.width * image.height > 9_000_000:
            raise ValueError('Invalid TV frame')
        image.thumbnail((1280, 720))
        output = io.BytesIO()
        image.convert('RGB').save(output, format='PNG')
    context['_tv_observation'] = (after, time.monotonic())
    media = _shell(row, cancel, _guard(row) + 'dumpsys media_session')
    media_lines = [line.strip() for line in media.splitlines()
                   if any(word in line for word in ('package=', 'state=PlaybackState', 'description='))]
    return {'observation': {'status': 'observed', 'source_kind': 'television',
            'model': row['model'], 'foreground': after, 'apps': list(row['apps']),
            'preferred_app': row.get('preferred_app', ''),
            'media_sessions': media_lines[:24], 'captured_at': time.time(),
            'visual_evidence': {'attached': True, 'content_role': 'untrusted_visual_evidence'},
            'note': 'Foreground alone does not prove playback. Protected video may be black.'},
            '_private_image_png': output.getvalue()}


def execute(args: dict, context: dict) -> dict:
    if (context.get('_agent_ref') != 'Agents/Executive/Executive'
            or context.get('task') != 'Agents/Executive/Executive'):
        raise PermissionError('TV control belongs to the Executive conversation')
    if not isinstance(args, dict):
        raise ValueError('TV arguments must be an object')
    action = args.get('action')
    fields = {'on': set(), 'off': set(), 'observe': set(), 'launch': {'app'},
              'key': {'key'}, 'text': {'text'}}
    if action not in fields or set(args) != {'action'} | fields[action]:
        raise ValueError('Invalid TV action arguments')
    if action == 'key' and args['key'] not in KEYS:
        raise ValueError('Unknown TV remote key')
    if action == 'text' and (not isinstance(args['text'], str)
            or not re.fullmatch(r'[A-Za-z0-9 .,:!?\-]{1,120}', args['text'])):
        raise ValueError('TV search text requires 1-120 simple printable characters')
    cancel = context.get('_capability_cancel_event')
    while not _LOCK.acquire(timeout=.1):
        if cancel is not None and cancel.is_set():
            return {'status': 'failed', 'delivery': 'not_dispatched', 'failure': 'cancelled'}
    delivery = 'not_dispatched'
    try:
        row = _inventory()
        if action == 'launch' and args['app'] not in row['apps']:
            raise ValueError('App is not registered on this TV; observe to list apps')
        if action != 'observe' and context.get('_tv_effect_uncertain'):
            raise ValueError('An earlier TV effect is uncertain; stop effects and report it')
        # Reconnect only the transport, never replay an input or restart the ADB server.
        _adb(row, cancel, connect=True, timeout=4)
        state = _power(row, cancel)
        if action == 'observe':
            return {'status': 'completed', 'power': state, **_observe(row, cancel, context)}
        attempted = context.setdefault('_tv_attempted', set())
        token = 'power' if action in ('on', 'off') else ('launch:' + args['app'] if action == 'launch' else '')
        if token and token in attempted:
            raise ValueError('This TV operation was already attempted in this run; do not replay it')
        if action in ('on', 'off'):
            desired = {'wakefulness': 'Awake', 'display': 'ON'} if action == 'on' else {'wakefulness': 'Asleep', 'display': 'OFF'}
            if state == desired:
                return {'status': 'completed', 'delivery': 'verified', 'action': action,
                        'power': state, 'effect_applied': False}
            command = 'input keyevent KEYCODE_WAKEUP' if action == 'on' else 'input keyevent KEYCODE_SLEEP'
        elif action == 'launch':
            package = row['apps'][args['app']]
            resolved = _shell(row, cancel, _guard(row) + 'cmd package resolve-activity --brief '
                '-a android.intent.action.MAIN -c android.intent.category.LEANBACK_LAUNCHER -p ' + package)
            component = resolved.strip().splitlines()[-1]
            if not re.fullmatch(re.escape(package) + r'/[A-Za-z0-9_.$]+', component):
                raise ValueError('No launchable TV activity for this app')
            command = 'am start -W -n ' + shlex.quote(component)
        else:
            observed = context.pop('_tv_observation', None)
            if not observed or time.monotonic() - observed[1] > 60 or _focus(row, cancel) != observed[0]:
                raise ValueError('Observe the current TV screen before each remote key or text entry')
            command = ('input keyevent ' + KEYS[args['key']] if action == 'key' else
                       'input text ' + shlex.quote(args['text'].replace(' ', '%s')))
        if cancel is not None and cancel.is_set():
            raise InterruptedError('TV command cancelled')
        if token:
            attempted.add(token)
        context.pop('_tv_observation', None)
        context['_tv_effect_uncertain'] = True
        delivery = 'uncertain'
        _shell(row, cancel, _guard(row) + command)
        delivery = 'acknowledged'
        if action in ('on', 'off'):
            deadline = time.monotonic() + 8
            while True:
                state = _power(row, cancel)
                if state == desired:
                    context['_tv_effect_uncertain'] = False
                    return {'status': 'completed', 'delivery': 'verified', 'action': action,
                            'power': state, 'effect_applied': True, 'must_not_replay': True}
                if time.monotonic() >= deadline:
                    raise ValueError('TV did not report the requested display state')
                if cancel is not None:
                    if cancel.wait(.15):
                        raise InterruptedError('TV command cancelled')
                else:
                    time.sleep(.15)
        result = _observe(row, cancel, context)
        context['_tv_effect_uncertain'] = False
        return {'status': 'completed', 'delivery': delivery, 'action': action,
                'effect_applied': True, 'must_not_replay': True,
                'note': 'Input delivered once; inspect the fresh evidence before claiming the requested outcome.', **result}
    except (OSError, ValueError, KeyError, IndexError) as error:
        return {'status': 'failed', 'delivery': delivery, 'effect_applied': None if delivery != 'not_dispatched' else False,
                'failure': str(error), 'must_not_replay': True}
    finally:
        _LOCK.release()

#!/usr/bin/env python3
"""Submit one setup code through a private Unix socket; no secret argv/env/history."""
import getpass
import json
import os
from pathlib import Path
import socket
import sys

FIXTURES = ('window_lamp', 'woven_pendant', 'north_lamp', 'tv_floor_lamp', 'desk_lantern', 'room_lantern')
if len(sys.argv) != 2 or sys.argv[1] not in FIXTURES:
    raise SystemExit('Usage: pair.py FIXTURE_ALIAS')
code = (getpass.getpass('Matter manual setup code (hidden): ') if sys.stdin.isatty() else sys.stdin.readline(128)).strip().replace('-', '').replace(' ', '')
if not code.isdecimal() or len(code) not in (11, 21):
    raise SystemExit('Invalid manual setup code format')
path = Path(os.environ.get('OBSIDIENCE_MATTER_SOCKET', str(Path(os.environ['XDG_RUNTIME_DIR']) / 'obsidience-lights/control.sock')))
try:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as peer:
        peer.settimeout(150)
        peer.connect(str(path))
        peer.sendall((json.dumps({'command': 'commission', 'target': sys.argv[1], 'pairingCode': code}) + '\n').encode())
        code = ''
        reply = bytearray()
        while b'\n' not in reply and len(reply) <= 8192:
            block = peer.recv(8192)
            if not block:
                break
            reply.extend(block)
        result = json.loads(reply)
        print(json.dumps(result, sort_keys=True))
except (OSError, ValueError):
    raise SystemExit('Commissioning response unavailable; delivery uncertain; do not replay automatically')

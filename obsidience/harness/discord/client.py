"""One bounded, non-replaying call to the Discord transport owner."""
from __future__ import annotations

import asyncio
import json
import os
import socket
import stat
import struct

from .config import socket_path


async def command(payload: dict, *, timeout: float = 15) -> dict:
    path = socket_path()
    sent = False
    writer = None
    try:
        info = path.lstat()
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError('Discord transport socket ownership is invalid')
        data = json.dumps(payload, separators=(',', ':')).encode() + b'\n'
        if len(data) > 65536:
            raise ValueError('Discord command is too large')
        async with asyncio.timeout(timeout):
            reader, writer = await asyncio.open_unix_connection(str(path), limit=65536)
            peer = writer.get_extra_info('socket').getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
            if struct.unpack('3i', peer)[1] != os.getuid():
                raise ValueError('Discord transport peer ownership is invalid')
            writer.write(data)
            sent = True
            await writer.drain()
            raw = await reader.readline()
            response = json.loads(raw)
            if not isinstance(response, dict):
                raise ValueError('Invalid Discord transport result')
            if response.get('request_id') != payload.get('request_id'):
                raise ValueError('Discord transport response identity changed')
            return response
    except asyncio.CancelledError:
        raise
    except (OSError, ValueError, TimeoutError):
        return {'ok': False, 'status': 'unavailable',
                'delivery': 'uncertain' if sent else 'not_dispatched',
                'effect_applied': None if sent else False, 'must_not_replay': sent,
                'failure': 'Discord transport result is uncertain' if sent else 'Discord transport is unavailable'}
    finally:
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass

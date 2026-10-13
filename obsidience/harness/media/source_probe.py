"""One owned, killable FUSE admission; transfer verified reader ownership by SCM_RIGHTS.

A kernel D-state task may survive SIGKILL. Its inherited flock remains held, so
even another caller/process cannot replace that pending worker. No thread is
abandoned and no mount is changed. This subprocess carries no credentials.
"""
from __future__ import annotations

import array
import fcntl
import json
import os
import socket
import stat
import subprocess
import sys
import threading
from pathlib import Path

from .config import MediaUnavailable

_LOCK = threading.Lock()
_PENDING = None
_LIMIT = 8.0
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def _mount_id(fd):
    with open(f'/proc/self/fdinfo/{fd}', encoding='ascii') as stream:
        for line in stream:
            if line.startswith('mnt_id:'):
                return int(line.split(':', 1)[1])
    raise MediaUnavailable('virtual_mount_unavailable')


def probe(root, relative, identity):
    global _PENDING
    if not _LOCK.acquire(blocking=False):
        raise MediaUnavailable('virtual_admission_pending')
    lock_fd, child, channel = -1, None, None
    received = []
    try:
        if _PENDING is not None:
            if _PENDING.poll() is None:
                raise MediaUnavailable('virtual_admission_pending')
            _PENDING.wait()
            _PENDING = None
        runtime = os.environ.get('XDG_RUNTIME_DIR') or f'/run/user/{os.getuid()}'
        lock_fd = os.open(os.path.join(runtime, 'obsidience-media-source-probe.lock'),
                          os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        info = os.fstat(lock_fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
            raise MediaUnavailable('virtual_admission_lock_unavailable')
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise MediaUnavailable('virtual_admission_pending') from None
        channel, peer = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        channel.settimeout(_LIMIT)
        try:
            child = subprocess.Popen([sys.executable, '-m', 'harness.media.source_probe',
                                      str(peer.fileno()), str(lock_fd)], pass_fds=(peer.fileno(), lock_fd),
                                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     env={'PATH': os.defpath, 'LANG': 'C.UTF-8',
                                          'PYTHONPATH': str(Path(__file__).resolve().parents[2])})
        finally:
            peer.close()
        channel.send(json.dumps({'root': root, 'relative': relative, 'identity': identity}).encode())
        data, ancillary, flags, _ = channel.recvmsg(16384, socket.CMSG_SPACE(65 * array.array('i').itemsize),
                                                   socket.MSG_CMSG_CLOEXEC)
        for level, kind, payload in ancillary:
            if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
                values = array.array('i')
                values.frombytes(payload[:len(payload) - len(payload) % values.itemsize])
                received.extend(values)
        reply = json.loads(data)
        if (flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC) or not isinstance(reply, dict)
                or reply.get('ok') is not True or reply.get('format') not in ('matroska', 'mov')
                or len(received) != reply.get('count') or not 2 <= len(received) <= 65):
            raise MediaUnavailable('virtual_media_admission_failed')
        if _mount_id(received[0]) != identity['mount']['id']:
            raise MediaUnavailable('virtual_mount_changed')
        child.wait(timeout=1)
        if child.returncode != 0:
            raise MediaUnavailable('virtual_media_admission_failed')
        fd, dirs = received[0], received[1:]
        received = []
        return fd, dirs, reply['format']
    except (OSError, ValueError, subprocess.TimeoutExpired):
        raise MediaUnavailable('virtual_media_admission_unverified') from None
    finally:
        for fd in received:
            os.close(fd)
        if channel is not None:
            channel.close()
        if child is not None and child.poll() is None:
            try:
                child.kill()
            except ProcessLookupError:
                pass
            try:
                child.wait(timeout=.5)
            except subprocess.TimeoutExpired:
                _PENDING = child  # Retain one owner; its inherited lock refuses replacement workers.
        if lock_fd >= 0:
            os.close(lock_fd)
        _LOCK.release()


def _child(channel):
    from .sources import _format, _mount, _parts
    fd, dirs = -1, []
    try:
        request = json.loads(channel.recv(65536))
        if not isinstance(request, dict) or set(request) != {'root', 'relative', 'identity'}:
            raise MediaUnavailable('invalid_virtual_admission')
        root, relative, identity = request['root'], request['relative'], request['identity']
        if _mount(root) != identity['mount']:
            raise MediaUnavailable('virtual_mount_changed')
        components = _parts(root['path'].lstrip('/')) + _parts(relative)
        if len(components) > 64:
            raise MediaUnavailable('virtual_path_limit')
        dirs = [os.open('/', _DIR_FLAGS)]
        current = ''
        for part in components[:-1]:
            current += '/' + part
            dirs.append(os.open(part, _DIR_FLAGS, dir_fd=dirs[-1]))
            if (current == root['mount_path'] or current.startswith(root['mount_path'] + '/')):
                if _mount_id(dirs[-1]) != identity['mount']['id']:
                    raise MediaUnavailable('virtual_mount_changed')
        fd = os.open(components[-1], os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC,
                     dir_fd=dirs[-1])
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_size != identity['file']['size']
                or _mount_id(fd) != identity['mount']['id']):
            raise MediaUnavailable('virtual_file_changed')
        # Tiramisu names every virtual video .mkv, even when the selected torrent
        # file is MP4. Detect bytes solely to select the existing strict parser;
        # neither the public path nor any container/reference check is changed.
        head = os.pread(fd, 16, 0)
        if head.startswith(b'\x1a\x45\xdf\xa3'):
            format = _format(fd, 'media.mkv')
        elif len(head) >= 16 and head[4:8] == b'ftyp':
            format = _format(fd, 'media.mp4')
        else:
            raise MediaUnavailable('unsupported_virtual_media')
        if format not in ('matroska', 'mov') or _mount(root) != identity['mount']:
            raise MediaUnavailable('unsupported_virtual_media')
        handles = array.array('i', [fd, *dirs])
        channel.sendmsg([json.dumps({'ok': True, 'format': format, 'count': len(handles)}).encode()],
                        [(socket.SOL_SOCKET, socket.SCM_RIGHTS, handles)])
    except Exception:
        channel.send(json.dumps({'ok': False}).encode())
    finally:
        if fd >= 0:
            os.close(fd)
        for directory in reversed(dirs):
            os.close(directory)
        channel.close()


if __name__ == '__main__':
    _child(socket.socket(fileno=int(sys.argv[1])))

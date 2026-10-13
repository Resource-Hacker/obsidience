"""One local file admission contract, shared by catalogue and TV tuner."""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
import stat
import struct
from pathlib import PurePosixPath

from .config import MediaUnavailable, validate_config

# Deliberately local filesystems only; FUSE, NFS and SMB are not Phase 1 roots.
_LOCAL_FS = {0xEF53, 0x9123683E, 0x58465342, 0x01021994, 0x794C7630, 0x2FC12FC1}
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_LIBC = ctypes.CDLL(None, use_errno=True)
_LIBC.fstatfs.argtypes = [ctypes.c_int, ctypes.c_void_p]
_LIBC.fstatfs.restype = ctypes.c_int


def _local(fd: int) -> None:
    buffer = ctypes.create_string_buffer(256)
    if _LIBC.fstatfs(fd, buffer) or ctypes.c_long.from_buffer(buffer).value & 0xFFFFFFFF not in _LOCAL_FS:
        raise MediaUnavailable('unsupported_media_filesystem')


def _parts(path: object) -> list[str]:
    if (not isinstance(path, str) or not path or len(path) > 4096
            or path.startswith('/') or '\\' in path
            or any(ord(c) < 32 for c in path)):
        raise MediaUnavailable('invalid_media_relative_path')
    parts = path.split('/')
    if any(p in ('', '.', '..') for p in parts):
        raise MediaUnavailable('invalid_media_relative_path')
    return parts


def _root(config: dict, root_id: str) -> dict:
    checked = validate_config(config)
    if not checked['enabled']:
        raise MediaUnavailable('media_disabled')
    matches = [r for r in checked['roots'] if r['id'] == root_id]
    if len(matches) != 1:
        raise MediaUnavailable('media_root_unavailable')
    return matches[0]


def _open(path: str, relative: str) -> tuple[int, list[int]]:
    """Traverse each component from /, holding directory identities until close."""
    dirs = [os.open('/', _DIR_FLAGS)]
    file_fd = -1
    try:
        for part in path.split('/')[1:]:
            dirs.append(os.open(part, _DIR_FLAGS, dir_fd=dirs[-1]))
        root_stat = os.fstat(dirs[-1])
        _local(dirs[-1])
        for part in _parts(relative)[:-1]:
            dirs.append(os.open(part, _DIR_FLAGS, dir_fd=dirs[-1]))
            _local(dirs[-1])
        file_fd = os.open(_parts(relative)[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
                          | os.O_NONBLOCK, dir_fd=dirs[-1])
        _local(file_fd)
        info = os.fstat(file_fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size <= 0 or info.st_dev != root_stat.st_dev:
            raise MediaUnavailable('media_file_unavailable')
        return file_fd, dirs
    except BaseException:
        if file_fd >= 0:
            os.close(file_fd)
        for fd in reversed(dirs):
            os.close(fd)
        raise


def _revision(root: dict, relative: str, fd: int, dirs: list[int]) -> str:
    info = os.fstat(fd)
    material = [root, relative, [info.st_dev, info.st_ino, info.st_size,
                                info.st_mtime_ns, info.st_ctime_ns],
                [[os.fstat(d).st_dev, os.fstat(d).st_ino] for d in dirs]]
    return hashlib.sha256(json.dumps(material, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _atoms(data: bytes, start: int, end: int, depth: int = 0) -> None:
    if depth > 8:
        raise MediaUnavailable('unsupported_media_container')
    cursor = start
    count = 0
    while cursor < end:
        count += 1
        if count > 10000 or end - cursor < 8:
            raise MediaUnavailable('unsupported_media_container')
        size, kind = struct.unpack_from('>I4s', data, cursor)
        header = 8
        if size == 1:
            if end - cursor < 16:
                raise MediaUnavailable('unsupported_media_container')
            size = struct.unpack_from('>Q', data, cursor + 8)[0]
            header = 16
        if size == 0:
            size = end - cursor
        if size < header or cursor + size > end:
            raise MediaUnavailable('unsupported_media_container')
        payload = cursor + header
        if kind in (b'rmra', b'rdrf'):
            raise MediaUnavailable('external_media_reference')
        if kind in (b'moov', b'trak', b'mdia', b'minf', b'dinf'):
            _atoms(data, payload, cursor + size, depth + 1)
        elif kind == b'dref':
            if size < header + 8:
                raise MediaUnavailable('unsupported_media_container')
            entries = struct.unpack_from('>I', data, payload + 4)[0]
            pos = payload + 8
            for _ in range(entries):
                if pos + 12 > cursor + size:
                    raise MediaUnavailable('unsupported_media_container')
                entry_size, entry_kind, flags = struct.unpack_from('>I4sI', data, pos)
                if entry_kind != b'url ' or flags != 1 or entry_size != 12:
                    raise MediaUnavailable('external_media_reference')
                pos += entry_size
            if entries < 1 or pos != cursor + size:
                raise MediaUnavailable('unsupported_media_container')
        cursor += size


def _format(fd: int, relative: str) -> str:
    extension = PurePosixPath(relative).suffix.lower()
    head = os.pread(fd, 4096, 0)
    if extension in ('.mkv', '.webm'):
        # EBML DocType must be in the bounded header, not merely an EBML signature.
        if (not head.startswith(b'\x1a\x45\xdf\xa3')
                or not any(b'\x42\x82' + bytes([0x80 | len(t)]) + t in head
                           for t in (b'matroska', b'webm'))):
            raise MediaUnavailable('unsupported_media_header')
        return 'matroska'
    if extension not in ('.mp4', '.m4v') or len(head) < 16 or head[4:8] != b'ftyp':
        raise MediaUnavailable('unsupported_media_header')
    if head[8:12] not in (b'isom', b'iso2', b'iso4', b'iso5', b'iso6', b'mp41', b'mp42', b'avc1', b'M4V ', b'dash'):
        raise MediaUnavailable('unsupported_media_header')
    end = os.fstat(fd).st_size
    cursor = 0
    moov = False
    for _ in range(10000):
        if cursor == end:
            break
        atom = os.pread(fd, 16, cursor)
        if len(atom) < 8:
            # Some ordinary MP4 exports end with a newline after the final atom
            # (including Blender's original Big Buck Bunny release).
            if moov and atom and not atom.strip(b'\r\n\t '):
                cursor = end
                break
            raise MediaUnavailable('unsupported_media_container')
        size, kind = struct.unpack_from('>I4s', atom)
        header = 8
        if size == 1:
            if len(atom) < 16:
                raise MediaUnavailable('unsupported_media_container')
            size, header = struct.unpack_from('>Q', atom, 8)[0], 16
        if size == 0:
            size = end - cursor
        if size < header or cursor + size > end:
            raise MediaUnavailable('unsupported_media_container')
        if kind not in (b'ftyp', b'moov', b'mdat', b'free', b'skip', b'wide'):
            raise MediaUnavailable('unsupported_media_container')
        if kind == b'moov':
            if moov or size > 16 * 1024 * 1024:
                raise MediaUnavailable('unsupported_media_container')
            material = os.pread(fd, size, cursor)
            if len(material) != size:
                raise MediaUnavailable('media_file_changed')
            _atoms(material, header, size)
            moov = True
        cursor += size
    if cursor != end or not moov:
        raise MediaUnavailable('unsupported_media_container')
    return 'mov'


class AdmittedSource:
    """Caller owns this fd and closes it after tuner playback stops."""

    def __init__(self, fd: int, dirs: list[int], root: dict, identity: dict, format: str):
        self.fd, self._dirs, self._root = fd, dirs, root
        self.identity, self.format = identity, format

    def validate(self) -> None:
        if self.fd < 0:
            raise MediaUnavailable('media_source_closed')
        try:
            current = _revision(self._root, self.identity['relative_path'], self.fd, self._dirs)
        except OSError:
            raise MediaUnavailable('media_file_unavailable') from None
        if current != self.identity['revision']:
            raise MediaUnavailable('media_file_changed')

    def close(self) -> None:
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1
        for fd in reversed(self._dirs):
            os.close(fd)
        self._dirs.clear()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def _admit(config: dict, root_id: str, relative: str, revision: str | None) -> AdmittedSource:
    root = _root(config, root_id)
    _parts(relative)
    fd, dirs = -1, []
    try:
        fd, dirs = _open(root['path'], relative)
        current = _revision(root, relative, fd, dirs)
        if revision is not None and revision != current:
            raise MediaUnavailable('media_file_changed')
        format = _format(fd, relative)
        source = AdmittedSource(fd, dirs, root,
                                {'provider': 'local', 'root_id': root_id,
                                 'relative_path': relative, 'revision': current}, format)
        source.validate()
        return source
    except BaseException as exc:
        if fd >= 0:
            os.close(fd)
        for directory in reversed(dirs):
            os.close(directory)
        if isinstance(exc, OSError):
            raise MediaUnavailable('media_file_unavailable') from None
        raise


def describe(config: dict, root_id: str, relative_path: str) -> dict:
    with _admit(config, root_id, relative_path, None) as source:
        return dict(source.identity)


def admit(config: dict, descriptor: dict) -> AdmittedSource:
    if (not isinstance(descriptor, dict)
            or set(descriptor) != {'provider', 'root_id', 'relative_path', 'revision'}
            or descriptor.get('provider') != 'local'
            or not isinstance(descriptor.get('root_id'), str)
            or not isinstance(descriptor.get('revision'), str)
            or len(descriptor['revision']) != 64):
        raise MediaUnavailable('invalid_media_source')
    return _admit(config, descriptor['root_id'], descriptor['relative_path'], descriptor['revision'])

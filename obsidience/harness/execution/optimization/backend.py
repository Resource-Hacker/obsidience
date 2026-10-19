"""The one selected optimizer and its verified installed source identity."""
from __future__ import annotations

import hashlib
import json
import os
from importlib.metadata import distribution
from importlib.util import find_spec
from pathlib import Path

AUTOSADDLER_REVISION = '6a2b7a9ab2412a8fe384fd5471d2a49b03a60013'
HARNESS2_REVISION = '1cfe254e8d25b15f37048c3730134686abe60335'
HARNESS2_BUILD_SHA256 = 'f1e859bf8fa018b866d0bea8c2664e82839986a702e1905d2eae3e3a37e32e02'


def selected() -> str:
    name = os.environ.get('OBSIDIENCE_OPTIMIZER_BACKEND', 'harness2')
    if name not in {'harness2', 'autosaddler'}:
        raise ValueError('OBSIDIENCE_OPTIMIZER_BACKEND must be harness2 or autosaddler')
    return name


def upstream_revision() -> str:
    return HARNESS2_REVISION if selected() == 'harness2' else AUTOSADDLER_REVISION


def contract() -> dict:
    """Fail closed on a different wheel/source; never substitute another backend."""
    saddler = distribution('autosaddler')
    provenance = json.loads(saddler.read_text('direct_url.json') or '{}')
    if provenance.get('vcs_info', {}).get('commit_id') != AUTOSADDLER_REVISION:
        raise ValueError('Install the pinned AutoSaddler artifact support dependency')
    result = {'name': selected(), 'upstream_revision': upstream_revision(),
              'autosaddler_revision': AUTOSADDLER_REVISION}
    if result['name'] == 'harness2':
        spec = find_spec('harness2')
        if spec is None or not spec.origin:
            raise ValueError('Install the pinned Obsidience Harness2 wheel')
        root = Path(spec.origin).parent
        manifest_path = root / 'obsidience-build.json'
        raw = manifest_path.read_bytes()
        manifest = json.loads(raw)
        files = manifest.get('files')
        installed = distribution('harness2').version
        if (hashlib.sha256(raw).hexdigest() != HARNESS2_BUILD_SHA256
                or manifest.get('upstream_revision') != HARNESS2_REVISION
                or manifest.get('version') != installed or not isinstance(files, dict)
                or not files or set(files) != {p.relative_to(root).as_posix() for p in root.rglob('*.py')}):
            raise ValueError('Harness2 build provenance does not match the pinned package')
        for relative, expected in files.items():
            path = root / relative
            if (path.is_symlink() or path.resolve().parent != (root / relative).absolute().parent
                    or hashlib.sha256(path.read_bytes()).hexdigest() != expected):
                raise ValueError('Harness2 installed source differs from its build provenance')
        result.update(version=installed, build_sha256=hashlib.sha256(raw).hexdigest())
    return result

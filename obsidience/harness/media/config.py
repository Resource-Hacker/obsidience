"""Disabled by default, installation-private media inventory."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit
from uuid import UUID


class MediaUnavailable(RuntimeError):
    """A bounded public reason, never a path, response body or credential."""


def _path(value: object) -> str:
    if (not isinstance(value, str) or len(value) > 4096 or not value.startswith('/')
            or '\\' in value or any(ord(c) < 32 for c in value)
            or any(p in ('', '.', '..') for p in value.split('/')[1:])):
        raise MediaUnavailable('invalid_media_root')
    return str(PurePosixPath(value))


def validate_config(value: object) -> dict:
    if not isinstance(value, dict) or type(value.get('enabled', False)) is not bool:
        raise MediaUnavailable('invalid_media_config')
    if set(value) - {'enabled', 'catalogue', 'roots'}:
        raise MediaUnavailable('invalid_media_config')
    result = {'enabled': value.get('enabled', False), 'roots': []}
    roots = value.get('roots', [])
    if not isinstance(roots, list) or len(roots) > 32:
        raise MediaUnavailable('invalid_media_roots')
    for root in roots:
        if (not isinstance(root, dict) or set(root) != {'id', 'catalogue_path', 'path'}
                or not isinstance(root['id'], str)
                or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', root['id'])):
            raise MediaUnavailable('invalid_media_root')
        result['roots'].append({'id': root['id'], 'path': _path(root['path']),
                                'catalogue_path': _path(root['catalogue_path'])})
    if len({r['id'] for r in result['roots']}) != len(roots):
        raise MediaUnavailable('ambiguous_media_roots')
    for i, root in enumerate(result['roots']):
        for other in result['roots'][i + 1:]:
            for key in ('path', 'catalogue_path'):
                a, b = root[key], other[key]
                if a == b or a.startswith(b + '/') or b.startswith(a + '/'):
                    raise MediaUnavailable('ambiguous_media_roots')
    catalogue = value.get('catalogue')
    if catalogue is not None:
        if (not isinstance(catalogue, dict)
                or set(catalogue) != {'url', 'instance_id', 'user_id', 'credential'}):
            raise MediaUnavailable('invalid_catalogue_config')
        url = catalogue['url']
        if not isinstance(url, str) or len(url) > 2048:
            raise MediaUnavailable('invalid_catalogue_url')
        try:
            parsed = urlsplit(url)
            port = parsed.port
        except ValueError:
            raise MediaUnavailable('invalid_catalogue_url') from None
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment or port == 0
                or any(ord(c) < 33 for c in url)
                or (parsed.scheme == 'http' and parsed.hostname not in ('127.0.0.1', '::1', 'localhost'))
                or any(p in ('.', '..') for p in parsed.path.split('/'))):
            raise MediaUnavailable('invalid_catalogue_url')
        instance = catalogue['instance_id']
        credential = catalogue['credential']
        if not isinstance(instance, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', instance):
            raise MediaUnavailable('invalid_catalogue_instance')
        if not isinstance(credential, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', credential):
            raise MediaUnavailable('invalid_media_credential_name')
        try:
            user = UUID(catalogue['user_id']).hex
        except (ValueError, TypeError, AttributeError):
            raise MediaUnavailable('invalid_catalogue_user') from None
        result['catalogue'] = {'url': url.rstrip('/'), 'instance_id': instance,
                               'user_id': user, 'credential': credential}
    if result['enabled'] and not roots:
        raise MediaUnavailable('media_roots_not_configured')
    return result


def load_config() -> dict:
    default = Path(__file__).resolve().parents[2] / 'state' / 'media.json'
    path = Path(os.environ.get('OBSIDIENCE_MEDIA_CONFIG', str(default)))
    try:
        with path.open('rb') as stream:
            material = stream.read(65537)
        if len(material) > 65536:
            raise MediaUnavailable('media_config_too_large')
        return validate_config(json.loads(material))
    except FileNotFoundError:
        return {'enabled': False, 'roots': []}
    except (OSError, ValueError, UnicodeError):
        raise MediaUnavailable('media_config_unavailable') from None

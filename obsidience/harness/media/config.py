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
    if set(value) - {'enabled', 'catalogue', 'roots', 'acquisition', 'discovery', 'debrid'}:
        raise MediaUnavailable('invalid_media_config')
    result = {'enabled': value.get('enabled', False), 'roots': []}
    roots = value.get('roots', [])
    if not isinstance(roots, list) or len(roots) > 32:
        raise MediaUnavailable('invalid_media_roots')
    for root in roots:
        if (not isinstance(root, dict) or set(root) not in ({'id', 'catalogue_path', 'path'},
                {'id', 'catalogue_path', 'path', 'mount_path'},
                {'id', 'catalogue_path', 'path', 'mount_path', 'provider'},
                {'id', 'catalogue_path', 'path', 'mount_path', 'provider', 'library_name'})
                or not isinstance(root['id'], str)
                or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', root['id'])):
            raise MediaUnavailable('invalid_media_root')
        result['roots'].append({'id': root['id'], 'path': _path(root['path']),
                                'catalogue_path': _path(root['catalogue_path'])})
        if 'mount_path' in root:
            mount = _path(root['mount_path'])
            if root['path'] != mount and not root['path'].startswith(mount + '/'):
                raise MediaUnavailable('invalid_virtual_root')
            result['roots'][-1]['mount_path'] = mount
            if 'provider' in root:
                if root['provider'] != 'torbox':
                    raise MediaUnavailable('invalid_virtual_provider')
                result['roots'][-1]['provider'] = 'torbox'
                if 'library_name' in root:
                    name = root['library_name']
                    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 _.-]{0,127}', name):
                        raise MediaUnavailable('invalid_deferred_library_name')
                    result['roots'][-1]['library_name'] = name
    if len({r['id'] for r in result['roots']}) != len(roots):
        raise MediaUnavailable('ambiguous_media_roots')
    library_names = [root['library_name'] for root in result['roots'] if 'library_name' in root]
    if len(set(library_names)) != len(library_names):
        raise MediaUnavailable('ambiguous_deferred_library_name')
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
    debrid = value.get('debrid')
    if debrid is not None:
        if (not isinstance(debrid, dict) or set(debrid) != {
                'enabled', 'provider', 'credential', 'instance_id', 'mount_path'}
                or type(debrid['enabled']) is not bool or debrid['provider'] != 'torbox'
                or any(not isinstance(debrid[k], str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', debrid[k])
                       for k in ('credential', 'instance_id'))):
            raise MediaUnavailable('invalid_debrid_config')
        result['debrid'] = {**debrid, 'mount_path': _path(debrid['mount_path'])}
    for root in result['roots']:
        if root.get('provider') == 'torbox' and (
                not debrid or root['mount_path'] != result['debrid']['mount_path']):
            raise MediaUnavailable('invalid_debrid_root')
    acquisition = value.get('acquisition')
    if acquisition is not None:
        if (not isinstance(acquisition, dict) or set(acquisition) != {'enabled', 'socket', 'instance_id'}
                or type(acquisition['enabled']) is not bool
                or not isinstance(acquisition['instance_id'], str)
                or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', acquisition['instance_id'])):
            raise MediaUnavailable('invalid_acquisition_config')
        result['acquisition'] = {**acquisition, 'socket': _path(acquisition['socket'])}
    discovery = value.get('discovery')
    if discovery is not None:
        if (not isinstance(discovery, dict)
                or set(discovery) != {'enabled', 'provider', 'catalogue_url', 'torrentio_url',
                                      'max_resolution', 'prefer_languages'}
                or type(discovery['enabled']) is not bool
                or discovery['provider'] not in ('torrentio', 'prowlarr')
                or type(discovery['max_resolution']) is not int
                or discovery['max_resolution'] not in (720, 1080, 2160)
                or not isinstance(discovery['prefer_languages'], list)
                or not 1 <= len(discovery['prefer_languages']) <= 4
                or any(not isinstance(lang, str) or not re.fullmatch('[a-z]{2}', lang)
                       for lang in discovery['prefer_languages'])):
            raise MediaUnavailable('invalid_discovery_config')
        for key in ('catalogue_url', 'torrentio_url'):
            url = discovery[key]
            if not isinstance(url, str) or len(url) > 2048:
                raise MediaUnavailable('invalid_discovery_url')
            try:
                parsed = urlsplit(url)
                port = parsed.port
            except ValueError:
                raise MediaUnavailable('invalid_discovery_url') from None
            if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
                    or port is not None
                    or parsed.query or parsed.fragment or parsed.path not in ('', '/')
                    or any(ord(c) < 33 for c in url)):
                raise MediaUnavailable('invalid_discovery_url')
        result['discovery'] = dict(discovery)
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

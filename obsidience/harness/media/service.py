"""API-lifetime catalogue client. Television playback has a separate lifetime."""
from __future__ import annotations

import threading

from .config import MediaUnavailable, load_config
from .jellyfin import JellyfinCatalogue

_lock = threading.Lock()
_catalogue: JellyfinCatalogue | None = None


def start() -> None:
    global _catalogue
    with _lock:
        if _catalogue is not None:
            return
        try:
            config = load_config()
        except MediaUnavailable:
            return  # Invalid optional media config cannot block the existing Harness.
        if config.get('enabled'):
            client = JellyfinCatalogue(config)
            client.start()
            _catalogue = client


def close() -> None:
    global _catalogue
    with _lock:
        client, _catalogue = _catalogue, None
    if client is not None:
        client.close()


def catalogue() -> JellyfinCatalogue:
    config = load_config()
    if not config.get('enabled'):
        raise MediaUnavailable('Media integration is disabled')
    with _lock:
        client = _catalogue
        if client is None or client.config != config:
            raise MediaUnavailable('Media configuration changed; deploy the Harness before using it')
        return client

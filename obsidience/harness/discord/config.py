"""Installation-owned Discord identity; remote messages cannot choose an Agent."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from ..config import CONFIG

AGENT_REF = 'Agents/Discord/Discord'
SNOWFLAKE = re.compile(r'[0-9]{17,20}\Z')


def load_config() -> dict:
    path = Path(os.environ.get('OBSIDIENCE_DISCORD_CONFIG', CONFIG.runtime_dir / 'discord.json'))
    if not path.exists():
        return {'enabled': False}
    value = json.loads(path.read_text())
    fields = {'enabled', 'guild_id', 'application_id', 'bot_name', 'allowed_channel_ids',
              'message_content_intent'}
    if (not isinstance(value, dict) or set(value) - fields
            or type(value.get('enabled')) is not bool):
        raise ValueError('Invalid Discord installation configuration')
    if not value['enabled']:
        return {'enabled': False}
    for key in ('guild_id', 'application_id'):
        if not isinstance(value.get(key), str) or not SNOWFLAKE.fullmatch(value[key]):
            raise ValueError('Discord installation identity is missing')
    channels = value.get('allowed_channel_ids', [])
    if (not isinstance(channels, list) or len(channels) > 100
            or any(not isinstance(v, str) or not SNOWFLAKE.fullmatch(v) for v in channels)):
        raise ValueError('Invalid Discord channel scope')
    if type(value.get('message_content_intent', False)) is not bool:
        raise ValueError('Invalid Discord message intent')
    if not isinstance(value.get('bot_name'), str) or not 1 <= len(value['bot_name']) <= 80:
        raise ValueError('Invalid Discord bot name')
    return value


def socket_path(name: str = 'bot') -> Path:
    return Path(os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')) / f'obsidience-discord-{name}.sock'


def ingress_secret() -> str:
    directory = os.environ.get('CREDENTIALS_DIRECTORY')
    if not directory:
        raise ValueError('Discord ingress credential is unavailable')
    value = (Path(directory) / 'discord-ingress-token').read_text().strip()
    if len(value) < 32:
        raise ValueError('Discord ingress credential is unavailable')
    return value

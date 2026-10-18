"""Fresh participant video from the ordinary local Discord client's decoder.

The bot remains the room/turn authority. This reader receives neither account
credentials nor desktop pixels, and keeps images only in the current activation.
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx
import psutil
import websockets
from PIL import Image

from . import client

PORT = 9238
MAX_BYTES = 6 * 1024 * 1024


class CameraUnavailable(ValueError):
    pass


def _cancel(context: dict) -> None:
    event = context.get('_capability_cancel_event')
    if event is not None and event.is_set():
        raise asyncio.CancelledError


def _client_identity() -> tuple[int, float]:
    listeners = [c for c in psutil.net_connections(kind='tcp')
                 if c.status == psutil.CONN_LISTEN and c.laddr.port == PORT]
    if (len(listeners) != 1 or listeners[0].laddr.ip != '127.0.0.1'
            or listeners[0].pid is None):
        raise CameraUnavailable('The local Discord camera reader is unavailable')
    process = psutil.Process(listeners[0].pid)
    executable = Path(process.exe()).resolve()
    roots = (Path.home() / '.config/discord', Path('/opt/discord'))
    if (process.uids().real != os.getuid() or executable.name != 'Discord'
            or not any(executable.is_relative_to(root) for root in roots)
            or f'--remote-debugging-port={PORT}' not in process.cmdline()
            or any(arg.startswith('--type=') for arg in process.cmdline())):
        raise CameraUnavailable('The camera reader is not the ordinary local Discord client')
    return process.pid, process.create_time()


# Only rendered participant camera elements and the native connected-room link
# are read. No webpack stores, auth, message content, screenshots or UI input.
_SCRIPT = r"""(async () => {
const {guild, channel, member} = PARAMS;
const path = `/channels/${guild}/${channel}`;
const inRoom = () => location.origin === 'https://discord.com' && location.pathname === path
  && !!document.querySelector(`[class*="rtcConnectionStatus"] a[href="${path}"]`);
if (!inRoom()) return {error:'The Discord client must be connected to and showing this voice room'};
const tiles = () => [...document.querySelectorAll('[data-selenium-video-tile]')];
const playable = v => v.isConnected && !v.paused && v.readyState >= 2
  && v.videoWidth > 0 && v.videoHeight > 0 && !v.ended;
if (!member) return {cameras:tiles().filter(t => /^\d{17,20}$/.test(t.dataset.seleniumVideoTile))
  .slice(0,25).map(t => ({member_id:t.dataset.seleniumVideoTile,
    rendered:[...t.querySelectorAll('video')].some(playable)}))};
const matches = tiles().filter(t => t.dataset.seleniumVideoTile === member);
if (matches.length !== 1) return {error:'This participant camera is not uniquely rendered in Discord'};
const tile = matches[0], videos = [...tile.querySelectorAll('video')];
if (videos.length !== 1 || !playable(videos[0])) return {error:'This camera is paused, off or not rendered'};
const video = videos[0];
if (typeof video.requestVideoFrameCallback !== 'function') return {error:'Fresh decoded frames are unavailable'};
return await new Promise(resolve => {
 let callback;
 const timer = setTimeout(() => {video.cancelVideoFrameCallback(callback);
   resolve({error:'No fresh camera frame arrived; the video may be paused'});}, 1800);
 callback = video.requestVideoFrameCallback((now, metadata) => {
  clearTimeout(timer);
  try {
   if (!inRoom() || !tile.isConnected || tile.dataset.seleniumVideoTile !== member
       || tile.querySelector('video') !== video || !playable(video)
       || performance.now() - now > 250) return resolve({error:'The camera or voice room changed during capture'});
   const scale = Math.min(1, 1280 / Math.max(video.videoWidth, video.videoHeight));
   const canvas = document.createElement('canvas');
   canvas.width = Math.max(1, Math.round(video.videoWidth * scale));
   canvas.height = Math.max(1, Math.round(video.videoHeight * scale));
   canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);
   resolve({member_id:member, width:canvas.width, height:canvas.height,
     captured_at:Date.now(), presented_frames:metadata.presentedFrames,
     media_time:metadata.mediaTime, png:canvas.toDataURL('image/png')});
  } catch (_) {resolve({error:'The decoded camera frame could not be read'});}
 });
});
})()"""


async def _read_client(guild: str, channel: str, member: str = '') -> dict:
    identity = await asyncio.to_thread(_client_identity)
    async with asyncio.timeout(7):
        async with httpx.AsyncClient(trust_env=False, timeout=2) as http:
            response = await http.get(f'http://127.0.0.1:{PORT}/json/list')
            response.raise_for_status()
            if len(response.content) > 65536:
                raise CameraUnavailable('Invalid local Discord window list')
            targets = [t for t in response.json() if t.get('type') == 'page'
                       and t.get('url') == f'https://discord.com/channels/{guild}/{channel}']
        if len(targets) != 1:
            raise CameraUnavailable('The ordinary Discord client must show this voice room')
        endpoint = targets[0].get('webSocketDebuggerUrl', '')
        parsed = urlparse(endpoint)
        if (parsed.scheme != 'ws' or parsed.hostname != '127.0.0.1' or parsed.port != PORT
                or not parsed.path.startswith('/devtools/page/') or parsed.query or parsed.fragment):
            raise CameraUnavailable('Invalid local Discord camera connection')
        expression = _SCRIPT.replace('PARAMS', json.dumps({'guild': guild, 'channel': channel, 'member': member}), 1)
        async with websockets.connect(endpoint, max_size=MAX_BYTES * 2, open_timeout=2,
                                      close_timeout=1, proxy=None) as ws:
            await ws.send(json.dumps({'id': 1, 'method': 'Runtime.evaluate', 'params': {
                'expression': expression, 'returnByValue': True, 'awaitPromise': True}}))
            while True:
                reply = json.loads(await ws.recv())
                if reply.get('id') == 1:
                    break
        result = reply.get('result', {}).get('result', {}).get('value')
        if identity != await asyncio.to_thread(_client_identity):
            raise CameraUnavailable('The Discord client changed during capture')
        if not isinstance(result, dict):
            raise CameraUnavailable('Discord did not return a camera observation')
        if result.get('error'):
            raise CameraUnavailable(str(result['error']))
        return result


async def _room(principal: dict, target: str = '') -> dict:
    payload = {'command': 'camera_context', 'guild_id': principal['guild_id'],
               'member_id': principal['member_id'], 'origin_request_id': principal['request_id']}
    if target:
        payload['target_member_id'] = target
    room = await client.command(payload, timeout=6)
    if room.get('ok') is not True:
        raise CameraUnavailable('The current speaker, camera or Discord voice room is unavailable')
    if any(room.get(k) != principal[k] for k in ('guild_id', 'channel_id', 'member_id')) or room.get('origin_request_id') != principal['request_id']:
        raise CameraUnavailable('The Discord camera request is no longer current')
    return room


def _image(frame: dict, member: str) -> bytes:
    data = frame.get('png', '')
    if (frame.get('member_id') != member or not isinstance(data, str)
            or not data.startswith('data:image/png;base64,') or len(data) > MAX_BYTES * 4 // 3 + 32
            or not 0 <= time.time() * 1000 - frame.get('captured_at', 0) < 5000):
        raise CameraUnavailable('The Discord camera frame is invalid or stale')
    raw = base64.b64decode(data.split(',', 1)[1], validate=True)
    with Image.open(io.BytesIO(raw)) as im:
        if (im.format != 'PNG' or im.size != (frame.get('width'), frame.get('height'))
                or not 1 <= max(im.size) <= 1280):
            raise CameraUnavailable('The Discord camera frame has an invalid format')
        im.verify()
    return raw


async def observe(args: dict, context: dict) -> dict:
    principal = context['_discord']
    try:
        _cancel(context)
        member = (args.get('member_id') or principal['member_id']) if args['action'] == 'observe' else ''
        room = await _room(principal, member)
        binding = (principal['request_id'], room['generation'], room['channel_id'])
        if member and member != principal['member_id']:
            selection = context.get('_discord_camera_members', {})
            if selection.get('binding') != binding or member not in selection.get('ids', ()):
                raise CameraUnavailable('Call cameras in this activation before selecting another participant')
        frame = await _read_client(room['guild_id'], room['channel_id'], member)
        _cancel(context)
        after = await _room(principal, member)
        if after['generation'] != room['generation']:
            raise CameraUnavailable('The Discord voice room changed during capture')
        _cancel(context)
        if not member:
            rendered = {c['member_id']: c['rendered'] for c in frame['cameras']}
            context['_discord_camera_members'] = {'binding': binding,
                'ids': [m['member_id'] for m in after['members']]}
            return {'status': 'observed', 'guild_id': room['guild_id'], 'channel_id': room['channel_id'],
                    'members': [{**m, 'rendered': bool(rendered.get(m['member_id']))}
                                for m in after['members']], 'labels_untrusted': True,
                    'members_truncated': after['members_truncated'], 'action_authorized': False}
        raw = _image(frame, member)
        name = next(m['display_name'] for m in after['members'] if m['member_id'] == member)
        return {'observation': {'status': 'observed', 'source_kind': 'discord_camera',
                'guild_id': room['guild_id'], 'channel_id': room['channel_id'],
                'member_id': member, 'name': name, 'query': args['query'],
                'captured_at_unix_ns': int(frame['captured_at']) * 1_000_000,
                'width': frame['width'], 'height': frame['height'], 'size_bytes': len(raw),
                'action_authorized': False, 'labels_untrusted': True,
                'visual_evidence': {'attached': True, 'media_type': 'image/png',
                    'freshness': 'new_decoded_frame', 'content_role': 'untrusted_visual_evidence'}},
                '_private_image_png': raw}
    except (CameraUnavailable, OSError, ValueError, TimeoutError, psutil.Error,
            httpx.HTTPError, websockets.WebSocketException) as error:
        # Never expose a browser response, transport URI or arbitrary exception.
        message = str(error) if isinstance(error, CameraUnavailable) else 'The local Discord camera reader is unavailable'
        return {'observation': {'status': 'unavailable', 'action_authorized': False,
                'failure': {'code': 'discord_camera_unavailable', 'message': message, 'retryable': False}}}

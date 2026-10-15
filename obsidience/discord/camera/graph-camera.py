#!/usr/bin/python
"""Own-page graph pixels to a local v4l2loopback camera; no audio or desktop capture."""
from __future__ import annotations

import argparse
import asyncio
import base64
import contextlib
import json
import os
from pathlib import Path
import signal
import stat
import tempfile
import time
import urllib.request

import websockets

URL = 'http://127.0.0.1:8765/shell/knowledge/?surface=discord'
READY = ("location.href === " + json.dumps(URL)
         + " && document.documentElement.dataset.discordGraph === 'ready'"
         + " && document.documentElement.dataset.discordGraphData === 'available'"
         + " && !!document.querySelector('canvas')")
DEVICE = Path('/dev/video42')
LABEL = 'Squanchbot Graph'
MAX_JPEG = 2 * 1024 * 1024
FPS = 15


class CDP:
    def __init__(self, socket):
        self.socket = socket
        self.serial = 0
        self.pending = {}
        self.navigation_failed = False
        self.reader = asyncio.create_task(self.read(), name='graph-camera-cdp')

    async def read(self):
        try:
            async for raw in self.socket:
                message = json.loads(raw)
                if 'id' in message:
                    future = self.pending.pop(message['id'], None)
                    if future is not None and not future.done():
                        if 'error' in message:
                            future.set_exception(RuntimeError('graph_capture_protocol_error'))
                        else:
                            future.set_result(message.get('result', {}))
                elif message.get('method') == 'Page.frameNavigated':
                    frame = message.get('params', {}).get('frame', {})
                    if 'parentId' not in frame and frame.get('url') not in (URL, 'about:blank'):
                        self.navigation_failed = True
        finally:
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(RuntimeError('graph_capture_disconnected'))
            self.pending.clear()

    async def call(self, method, params=None):
        if self.navigation_failed or self.reader.done():
            raise RuntimeError('graph_capture_target_lost')
        self.serial += 1
        key = self.serial
        future = asyncio.get_running_loop().create_future()
        self.pending[key] = future
        try:
            await self.socket.send(json.dumps({'id': key, 'method': method, 'params': params or {}}))
            return await asyncio.wait_for(future, 5)
        finally:
            self.pending.pop(key, None)

    async def close(self):
        await self.socket.close()
        self.reader.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await self.reader


def camera_device():
    info = DEVICE.stat()
    name = (Path('/sys/class/video4linux') / DEVICE.name / 'name').read_text().strip()
    actual = (Path('/sys/class/video4linux') / DEVICE.name).resolve()
    if (not stat.S_ISCHR(info.st_mode) or os.major(info.st_rdev) != 81 or name != LABEL
            or not actual.is_relative_to('/sys/devices/virtual/video4linux')):
        raise RuntimeError('dedicated_loopback_camera_required')
    if not os.access(DEVICE, os.W_OK):
        raise RuntimeError('camera_write_permission_required')


def page_target(port):
    # Own throwaway browser only: never attach to desktop Edge or native stage.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(f'http://127.0.0.1:{port}/json/list', timeout=2) as response:
        raw = response.read(65537)
    if len(raw) > 65536:
        raise RuntimeError('browser_targets_too_large')
    targets = json.loads(raw)
    pages = [target for target in targets if target.get('type') == 'page' and target.get('url') == 'about:blank']
    if len(pages) != 1:
        raise RuntimeError('isolated_browser_page_required')
    endpoint = pages[0].get('webSocketDebuggerUrl', '')
    if not endpoint.startswith(f'ws://127.0.0.1:{port}/devtools/page/'):
        raise RuntimeError('private_browser_endpoint_required')
    return endpoint


async def terminate(process):
    if process is None or process.returncode is not None:
        return
    process.terminate()
    try:
        await asyncio.wait_for(process.wait(), 3)
    except TimeoutError:
        process.kill()
        await process.wait()


async def produce(size):
    camera_device()
    width, height = map(int, size.split('x'))
    runtime = Path(f'/run/user/{os.getuid()}')
    info = runtime.stat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise RuntimeError('private_runtime_directory_required')
    browser = encoder = cdp = None
    tasks = []
    environment = dict(os.environ)
    for key in ('DISPLAY', 'WAYLAND_DISPLAY', 'CREDENTIALS_DIRECTORY', 'NODE_OPTIONS',
                'CUDA_VISIBLE_DEVICES', '__NV_PRIME_RENDER_OFFLOAD', '__GLX_VENDOR_LIBRARY_NAME'):
        environment.pop(key, None)
    environment['CUDA_VISIBLE_DEVICES'] = ''
    environment['LIBGL_ALWAYS_SOFTWARE'] = '1'
    environment['GALLIUM_DRIVER'] = 'llvmpipe'
    with tempfile.TemporaryDirectory(prefix='discord-graph-camera-', dir=runtime) as directory:
        environment['XDG_CONFIG_HOME'] = str(Path(directory) / 'config')
        environment['XDG_CACHE_HOME'] = str(Path(directory) / 'cache')
        try:
            browser = await asyncio.create_subprocess_exec(
                '/opt/microsoft/msedge/msedge', '--headless=new', '--no-first-run',
                '--no-default-browser-check', '--disable-extensions', '--disable-sync',
                '--disable-background-networking', '--disable-component-update',
                '--disable-gpu', '--use-gl=angle', '--use-angle=swiftshader-webgl',
                '--enable-unsafe-swiftshader', '--disable-vulkan', '--mute-audio',
                '--disable-background-timer-throttling', '--disable-renderer-backgrounding',
                '--force-device-scale-factor=1', f'--window-size={width},{height}',
                '--remote-debugging-address=127.0.0.1', '--remote-debugging-port=0',
                f'--user-data-dir={directory}', 'about:blank',
                stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL, env=environment,
            )
            active_port = Path(directory) / 'DevToolsActivePort'
            deadline = time.monotonic() + 15
            while not active_port.exists():
                if browser.returncode is not None or time.monotonic() >= deadline:
                    raise RuntimeError('isolated_browser_start_failed')
                await asyncio.sleep(0.05)
            port = int(active_port.read_text().splitlines()[0])
            if not 1024 <= port <= 65535:
                raise RuntimeError('invalid_private_browser_port')
            endpoint = await asyncio.to_thread(page_target, port)
            socket = await websockets.connect(endpoint, max_size=MAX_JPEG * 2, open_timeout=3, close_timeout=1)
            cdp = CDP(socket)
            await cdp.call('Page.enable')
            await cdp.call('Emulation.setDeviceMetricsOverride', {
                'width': width, 'height': height, 'deviceScaleFactor': 1, 'mobile': False,
            })
            await cdp.call('Page.navigate', {'url': URL})
            deadline = time.monotonic() + 30
            while True:
                readiness = await cdp.call('Runtime.evaluate', {
                    'expression': READY,
                    'returnByValue': True,
                })
                if readiness.get('result', {}).get('value') is True:
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError('discord_graph_not_ready')
                await asyncio.sleep(0.1)
            encoder = await asyncio.create_subprocess_exec(
                '/usr/bin/ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error',
                '-threads', '1', '-filter_threads', '1', '-f', 'image2pipe', '-vcodec', 'mjpeg',
                '-framerate', str(FPS), '-i', 'pipe:0', '-an', '-vf', f'scale={width}:{height}',
                '-pix_fmt', 'yuv420p', '-vcodec', 'rawvideo', '-r', str(FPS), '-f', 'v4l2', str(DEVICE),
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL, env=environment,
            )
            latest = {'jpeg': None, 'at': 0.0}
            first = asyncio.Event()

            async def capture():
                while True:
                    started = time.monotonic()
                    state = await cdp.call('Runtime.evaluate', {'expression': READY, 'returnByValue': True})
                    if state.get('result', {}).get('value') is not True:
                        raise RuntimeError('discord_graph_data_unavailable')
                    image = await cdp.call('Page.captureScreenshot', {
                        'format': 'jpeg', 'quality': 90, 'fromSurface': True, 'captureBeyondViewport': False,
                    })
                    data = image.get('data', '')
                    if not isinstance(data, str) or len(data) > MAX_JPEG * 4 // 3 + 4:
                        raise RuntimeError('graph_frame_too_large')
                    jpeg = base64.b64decode(data, validate=True)
                    if not jpeg or len(jpeg) > MAX_JPEG or not jpeg.startswith(b'\xff\xd8'):
                        raise RuntimeError('invalid_graph_frame')
                    latest.update(jpeg=jpeg, at=time.monotonic())
                    first.set()
                    await asyncio.sleep(max(0, 1 / FPS - (time.monotonic() - started)))

            async def feed():
                await asyncio.wait_for(first.wait(), 10)
                next_frame = time.monotonic()
                announced = False
                while True:
                    if browser.returncode is not None or encoder.returncode is not None or cdp.navigation_failed:
                        raise RuntimeError('graph_camera_dependency_lost')
                    if time.monotonic() - latest['at'] > 2:
                        raise RuntimeError('graph_frame_stalled')
                    encoder.stdin.write(latest['jpeg'])
                    await asyncio.wait_for(encoder.stdin.drain(), 2)
                    if not announced:
                        print(json.dumps({'component': 'discord_graph_camera', 'state': 'frames_submitted',
                                          'size': size, 'fps': FPS, 'rendering': 'software', 'audio': False}), flush=True)
                        announced = True
                    next_frame += 1 / FPS
                    if next_frame < time.monotonic() - 1 / FPS:
                        next_frame = time.monotonic()
                    await asyncio.sleep(max(0, next_frame - time.monotonic()))

            tasks = [asyncio.create_task(capture()), asyncio.create_task(feed())]
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if cdp is not None:
                await cdp.close()
            if encoder is not None and encoder.stdin is not None:
                encoder.stdin.close()
            await terminate(encoder)
            await terminate(browser)


async def main(size):
    loop = asyncio.get_running_loop()
    task = asyncio.create_task(produce(size))
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, task.cancel)
    try:
        await task
    except asyncio.CancelledError:
        pass


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--size', choices=('1280x720', '1920x1080'), default='1280x720')
    args = parser.parse_args()
    try:
        asyncio.run(main(args.size))
    except Exception:
        # CDP errors can carry page source; never publish exception payloads.
        print(json.dumps({'component': 'discord_graph_camera', 'state': 'failed'}), flush=True)
        raise SystemExit(1)

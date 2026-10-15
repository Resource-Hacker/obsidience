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
import re
import signal
import socket
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
AMD_PCI = os.environ.get('OBSIDIENCE_DISCORD_CAMERA_GPU_PCI', '')
AMD_NODES = tuple(os.environ.get('OBSIDIENCE_DISCORD_CAMERA_GPU_NODES', '').split())
RADEON_ICD = '/usr/share/vulkan/icd.d/radeon_icd.json'
# Inspect the existing graph contexts; do not create a second renderer/context.
AMD_RENDERING = r'''(() => {
  const contexts = [...document.querySelectorAll('canvas')]
    .map(canvas => canvas.getContext('webgl2')).filter(Boolean);
  return contexts.length > 0 && contexts.every(gl => {
    const ext = gl.getExtension('WEBGL_debug_renderer_info');
    const renderer = ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : '';
    return /AMD|Radeon|RADV/i.test(renderer)
      && !/NVIDIA|SwiftShader|llvmpipe|softpipe/i.test(renderer);
  });
})()'''


class CameraFailure(RuntimeError):
    """Only code-owned fixed codes may cross into the journal."""
    def __init__(self, code, browser_exit_code=None):
        super().__init__(code)
        self.code = code
        self.browser_exit_code = browser_exit_code


def failure_identity(error):
    """Expose class and our own line numbers, never messages/source/locals."""
    own_file = Path(__file__).resolve()
    chain = []
    seen = set()
    while error is not None and len(chain) < 3 and id(error) not in seen:
        seen.add(id(error))
        name = type(error).__name__
        item = {'exception_class': name if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,79}', name) else 'Exception',
                'frames': []}
        frame = error.__traceback__
        while frame is not None:
            if Path(frame.tb_frame.f_code.co_filename).resolve() == own_file:
                item['frames'].append({'file': 'graph-camera.py', 'line': frame.tb_lineno})
            frame = frame.tb_next
        item['frames'] = item['frames'][-8:]
        if isinstance(error, OSError) and isinstance(error.errno, int):
            item['errno'] = error.errno
        chain.append(item)
        error = error.__cause__ or (None if error.__suppress_context__ else error.__context__)
    return {'exception_chain': chain}


class BrowserDiagnostics:
    def __init__(self):
        self.code = None
        self.rank = 100

    async def consume(self, stream):
        # Consume continuously so stderr cannot deadlock the child. Retain
        # neither raw lines nor paths, only one fixed classification code.
        patterns = (
            (b'Read-only file system', 'browser_profile_read_only'),
            (b'No usable sandbox', 'browser_sandbox_unavailable'),
            (b'SUID sandbox helper binary', 'browser_sandbox_unavailable'),
            (b'Failed to move to new namespace', 'browser_namespace_unavailable'),
            (b'GPU process isn\'t usable', 'browser_gpu_renderer_unavailable'),
            (b'Permission denied', 'browser_permission_denied'),
        )
        tail = b''
        while chunk := await stream.read(4096):
            data = tail + chunk
            for rank, (needle, code) in enumerate(patterns):
                if rank < self.rank and needle in data:
                    self.code, self.rank = code, rank
            tail = data[-256:]


def notify_ready():
    address = os.environ.get('NOTIFY_SOCKET')
    if not address:
        return
    if address.startswith('@'):
        address = '\0' + address[1:]
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as channel:
        channel.sendto(b'READY=1\nSTATUS=Squanchbot graph camera format verified', address)


async def camera_ready(width, height):
    query = await asyncio.create_subprocess_exec(
        '/usr/bin/v4l2-ctl', '--device=' + str(DEVICE), '--get-fmt-video', '--get-parm', '--info',
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        output, _ = await asyncio.wait_for(query.communicate(), 2)
    except TimeoutError:
        return False
    finally:
        await terminate(query)
    if query.returncode != 0 or len(output) > 16384:
        return False
    text = output.decode('ascii', errors='replace')
    dimensions = re.search(r'Width/Height\s*:\s*(\d+)\s*/\s*(\d+)', text)
    fps = re.search(r'Frames per second:\s*([0-9.]+)', text)
    return (dimensions is not None and tuple(map(int, dimensions.groups())) == (width, height)
            and "'YU12'" in text and fps is not None and abs(float(fps.group(1)) - FPS) < 0.01
            and 'Video Capture' in text and LABEL in text)


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
                            future.set_exception(CameraFailure('graph_capture_protocol_error'))
                        else:
                            future.set_result(message.get('result', {}))
                elif message.get('method') == 'Page.frameNavigated':
                    frame = message.get('params', {}).get('frame', {})
                    if 'parentId' not in frame and frame.get('url') not in (URL, 'about:blank'):
                        self.navigation_failed = True
        finally:
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(CameraFailure('graph_capture_disconnected'))
            self.pending.clear()

    async def call(self, method, params=None):
        if self.navigation_failed or self.reader.done():
            raise CameraFailure('graph_capture_target_lost')
        self.serial += 1
        key = self.serial
        future = asyncio.get_running_loop().create_future()
        self.pending[key] = future
        try:
            await self.socket.send(json.dumps({'id': key, 'method': method, 'params': params or {}}))
            try:
                return await asyncio.wait_for(future, 5)
            except TimeoutError:
                code = ('graph_screenshot_timeout' if method == 'Page.captureScreenshot' else
                        'graph_readiness_timeout' if method == 'Runtime.evaluate' else 'graph_protocol_timeout')
                raise CameraFailure(code) from None
        finally:
            self.pending.pop(key, None)

    async def close(self):
        await self.socket.close()
        self.reader.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await self.reader


def amd_device():
    # The unit hides the host DRI tree and binds only these two AMD nodes.
    # Fail closed on numbering drift or a direct launch outside that namespace.
    if (not re.fullmatch(r'[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]', AMD_PCI)
            or len(AMD_NODES) != 2 or not re.fullmatch(r'card[0-9]+', AMD_NODES[0])
            or not re.fullmatch(r'renderD[0-9]+', AMD_NODES[1])):
        raise CameraFailure('amd_installation_identity_required')
    visible = {node.name for node in Path('/dev/dri').iterdir()}
    if visible != set(AMD_NODES):
        raise CameraFailure('amd_only_device_namespace_required')
    for name in AMD_NODES:
        node = Path('/dev/dri') / name
        info = node.stat()
        drm = Path('/sys/class/drm') / name
        device = (drm / 'device').resolve()
        expected_dev = tuple(map(int, (drm / 'dev').read_text().strip().split(':')))
        if (not stat.S_ISCHR(info.st_mode) or os.major(info.st_rdev) != 226
                or (os.major(info.st_rdev), os.minor(info.st_rdev)) != expected_dev
                or device.name != AMD_PCI or (device / 'vendor').read_text().strip() != '0x1002'):
            raise CameraFailure('amd_device_identity_mismatch')
    if not Path(RADEON_ICD).is_file():
        raise CameraFailure('amd_vulkan_driver_missing')


def camera_device():
    info = DEVICE.stat()
    name = (Path('/sys/class/video4linux') / DEVICE.name / 'name').read_text().strip()
    actual = (Path('/sys/class/video4linux') / DEVICE.name).resolve()
    if (not stat.S_ISCHR(info.st_mode) or os.major(info.st_rdev) != 81 or name != LABEL
            or not actual.is_relative_to('/sys/devices/virtual/video4linux')):
        raise CameraFailure('dedicated_loopback_camera_required')
    if not os.access(DEVICE, os.W_OK):
        raise CameraFailure('camera_write_permission_required')


def page_target(port):
    # Own throwaway browser only: never attach to desktop Edge or native stage.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(f'http://127.0.0.1:{port}/json/list', timeout=2) as response:
        raw = response.read(65537)
    if len(raw) > 65536:
        raise CameraFailure('browser_targets_too_large')
    targets = json.loads(raw)
    pages = [target for target in targets if target.get('type') == 'page' and target.get('url') == 'about:blank']
    if len(pages) != 1:
        raise CameraFailure('isolated_browser_page_required')
    endpoint = pages[0].get('webSocketDebuggerUrl', '')
    if not endpoint.startswith(f'ws://127.0.0.1:{port}/devtools/page/'):
        raise CameraFailure('private_browser_endpoint_required')
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


async def terminate_browser(process):
    if process is None:
        return
    # This browser alone was started in its own session. Its renderer and
    # Crashpad children may survive the main PID; do not leave them writing
    # into the ephemeral profile while TemporaryDirectory removes it.
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    if process.returncode is None:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(process.wait(), 3)
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)
    if process.returncode is None:
        await asyncio.wait_for(process.wait(), 3)


async def produce(size):
    camera_device()
    amd_device()
    width, height = map(int, size.split('x'))
    runtime = Path(f'/run/user/{os.getuid()}')
    info = runtime.stat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise CameraFailure('private_runtime_directory_required')
    browser = encoder = cdp = None
    tasks = []
    stderr_task = None
    diagnostics = BrowserDiagnostics()
    environment = dict(os.environ)
    for key in ('DISPLAY', 'WAYLAND_DISPLAY', 'CREDENTIALS_DIRECTORY', 'NODE_OPTIONS',
                'CUDA_VISIBLE_DEVICES', '__NV_PRIME_RENDER_OFFLOAD', '__GLX_VENDOR_LIBRARY_NAME',
                'NOTIFY_SOCKET', 'WATCHDOG_PID', 'WATCHDOG_USEC',
                'LIBGL_ALWAYS_SOFTWARE', 'GALLIUM_DRIVER', 'VK_INSTANCE_LAYERS',
                'VK_ADD_DRIVER_FILES', 'VK_LOADER_DRIVERS_SELECT', 'VK_LOADER_DRIVERS_DISABLE'):
        environment.pop(key, None)
    environment['CUDA_VISIBLE_DEVICES'] = ''
    # Driver selection plus the unit's device namespace exclude both NVIDIA GPUs.
    environment['VK_DRIVER_FILES'] = RADEON_ICD
    environment['VK_ICD_FILENAMES'] = RADEON_ICD
    environment['DRI_PRIME'] = 'pci-' + AMD_PCI.replace(':', '_').replace('.', '_') + '!'
    environment['__EGL_VENDOR_LIBRARY_FILENAMES'] = '/usr/share/glvnd/egl_vendor.d/50_mesa.json'
    # Best-effort deletion must never replace the actual capture/encoder
    # failure with an ENOTEMPTY error from asynchronous browser teardown.
    with tempfile.TemporaryDirectory(prefix='discord-graph-camera-', dir=runtime, ignore_cleanup_errors=True) as directory:
        environment['XDG_CONFIG_HOME'] = str(Path(directory) / 'config')
        environment['XDG_CACHE_HOME'] = str(Path(directory) / 'cache')
        try:
            browser = await asyncio.create_subprocess_exec(
                '/opt/microsoft/msedge/msedge', '--headless=new', '--no-first-run',
                '--no-default-browser-check', '--disable-extensions', '--disable-sync',
                '--disable-background-networking', '--disable-component-update',
                '--enable-gpu', '--use-gl=angle', '--use-angle=vulkan',
                '--enable-features=Vulkan', '--use-vulkan=native', '--disable-vulkan-surface',
                '--disable-software-rasterizer', '--mute-audio',
                '--disable-background-timer-throttling', '--disable-renderer-backgrounding',
                '--force-device-scale-factor=1', f'--window-size={width},{height}',
                '--remote-debugging-address=127.0.0.1', '--remote-debugging-port=0',
                f'--user-data-dir={directory}', 'about:blank',
                stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE, env=environment, start_new_session=True,
            )
            stderr_task = asyncio.create_task(diagnostics.consume(browser.stderr), name='graph-camera-browser-diagnostics')
            active_port = Path(directory) / 'DevToolsActivePort'
            deadline = time.monotonic() + 15
            while not active_port.exists():
                if browser.returncode is not None or time.monotonic() >= deadline:
                    if browser.returncode is not None:
                        with contextlib.suppress(TimeoutError):
                            await asyncio.wait_for(asyncio.shield(stderr_task), 1)
                    raise CameraFailure(diagnostics.code or 'isolated_browser_start_failed', browser.returncode)
                await asyncio.sleep(0.05)
            port = int(active_port.read_text().splitlines()[0])
            if not 1024 <= port <= 65535:
                raise CameraFailure('invalid_private_browser_port')
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
                    raise CameraFailure('discord_graph_not_ready')
                await asyncio.sleep(0.1)
            rendering = await cdp.call('Runtime.evaluate', {
                'expression': AMD_RENDERING, 'returnByValue': True,
            })
            if rendering.get('result', {}).get('value') is not True:
                raise CameraFailure('amd_graph_renderer_required')
            print(json.dumps({'component': 'discord_graph_camera', 'state': 'renderer_verified',
                              'rendering': 'amd_vulkan', 'audio': False}), flush=True)
            encoder = await asyncio.create_subprocess_exec(
                '/usr/bin/ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error',
                # Codec, image format and cadence are known. Do not wait for
                # multi-second/default-size live-stream format analysis.
                '-probesize', '32', '-analyzeduration', '1', '-fpsprobesize', '0',
                '-threads', '1', '-filter_threads', '1', '-f', 'image2pipe', '-vcodec', 'mjpeg',
                '-framerate', str(FPS), '-i', 'pipe:0', '-an', '-vf', f'scale={width}:{height}',
                '-pix_fmt', 'yuv420p', '-vcodec', 'rawvideo', '-threads', '1', '-r', str(FPS), '-f', 'v4l2', str(DEVICE),
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
                        raise CameraFailure('discord_graph_data_unavailable')
                    image = await cdp.call('Page.captureScreenshot', {
                        'format': 'jpeg', 'quality': 90, 'fromSurface': True, 'captureBeyondViewport': False,
                    })
                    data = image.get('data', '')
                    if not isinstance(data, str) or len(data) > MAX_JPEG * 4 // 3 + 4:
                        raise CameraFailure('graph_frame_too_large')
                    jpeg = base64.b64decode(data, validate=True)
                    if not jpeg or len(jpeg) > MAX_JPEG or not jpeg.startswith(b'\xff\xd8'):
                        raise CameraFailure('invalid_graph_frame')
                    latest.update(jpeg=jpeg, at=time.monotonic())
                    first.set()
                    await asyncio.sleep(max(0, 1 / FPS - (time.monotonic() - started)))

            async def feed():
                try:
                    await asyncio.wait_for(first.wait(), 10)
                except TimeoutError:
                    raise CameraFailure('graph_first_frame_timeout') from None
                next_frame = time.monotonic()
                announced = False
                ready_deadline = time.monotonic() + 10
                next_probe = 0.0
                while True:
                    if browser.returncode is not None or encoder.returncode is not None or cdp.navigation_failed:
                        raise CameraFailure('graph_camera_dependency_lost')
                    if time.monotonic() - latest['at'] > 2:
                        raise CameraFailure('graph_frame_stalled')
                    encoder.stdin.write(latest['jpeg'])
                    try:
                        await asyncio.wait_for(encoder.stdin.drain(), 2)
                    except TimeoutError:
                        raise CameraFailure('camera_write_backpressure') from None
                    except (BrokenPipeError, ConnectionResetError):
                        raise CameraFailure('camera_encoder_pipe_closed') from None
                    if not announced and time.monotonic() >= next_probe:
                        next_probe = time.monotonic() + 0.25
                        if await camera_ready(width, height):
                            notify_ready()
                            print(json.dumps({'component': 'discord_graph_camera', 'state': 'camera_ready',
                                              'size': size, 'fps': FPS, 'rendering': 'amd_vulkan', 'audio': False,
                                              'verification': 'v4l2_format_and_capture_capability'}), flush=True)
                            announced = True
                        elif time.monotonic() >= ready_deadline:
                            raise CameraFailure('camera_output_not_ready')
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
            await terminate_browser(browser)
            if stderr_task is not None:
                stderr_task.cancel()
                await asyncio.gather(stderr_task, return_exceptions=True)


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
    except Exception as error:
        # CDP errors can carry page source; never publish exception payloads.
        code = (error.code if isinstance(error, CameraFailure) else
                'dependency_missing' if isinstance(error, FileNotFoundError) else
                'permission_denied' if isinstance(error, PermissionError) else
                'operation_timeout' if isinstance(error, TimeoutError) else 'component_failed')
        message = {'component': 'discord_graph_camera', 'state': 'failed', 'code': code}
        message.update(failure_identity(error))
        if isinstance(error, CameraFailure) and error.browser_exit_code is not None:
            message['browser_exit_code'] = error.browser_exit_code
        print(json.dumps(message), flush=True)
        raise SystemExit(1)

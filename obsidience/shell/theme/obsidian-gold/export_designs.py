#!/usr/bin/env python3
"""Render the offline design atlas to PNG using a temporary headless browser.

This exports artwork, not a live-shell integration or automated test suite.
No active browser profile, desktop session, compositor or model is touched.
Requires Python 3, websockets and a Chromium-compatible browser executable.
"""
from __future__ import annotations
import argparse
import asyncio
import base64
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time
import urllib.request

async def export(browser: str, root: Path, selected: list[str], width: int, height: int, destination: Path | None = None, state: str = "ready") -> None:
    import websockets
    records = json.loads((root/'designs/screen-index.json').read_text())
    if selected:
        unknown = set(selected) - {r['id'] for r in records}
        if unknown:
            raise ValueError('Unknown design IDs: '+', '.join(sorted(unknown)))
        records = [r for r in records if r['id'] in selected]
    output = (destination or root/'designs').resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='obsidience-theme-render-', ignore_cleanup_errors=True) as tmp:
        profile = Path(tmp)/'profile'
        with (Path(tmp)/'browser.log').open('w') as log:
            process = subprocess.Popen([browser,'--headless=new','--disable-gpu',
                '--no-first-run','--no-default-browser-check','--disable-extensions',
                '--disable-background-networking','--disable-sync','--disable-component-update',
                '--remote-debugging-address=127.0.0.1','--remote-debugging-port=0',
                '--user-data-dir='+str(profile),'--force-device-scale-factor=1',
                '--window-size='+str(width)+','+str(height),'about:blank'],stdout=log,stderr=log,start_new_session=True)
            try:
                deadline = time.monotonic()+25
                active = profile/'DevToolsActivePort'
                while not active.exists():
                    if process.poll() is not None:
                        raise RuntimeError('Headless browser exited: '+(Path(tmp)/'browser.log').read_text()[-2000:])
                    if time.monotonic()>deadline:
                        raise TimeoutError('Headless browser did not become ready')
                    await asyncio.sleep(.1)
                port = int(active.read_text().splitlines()[0])
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/json/list',timeout=5) as response:
                    targets=json.load(response)
                page = next(t for t in targets if t.get('type')=='page')
                async with websockets.connect(page['webSocketDebuggerUrl'],max_size=32*1024*1024,open_timeout=10) as ws:
                    seq=0
                    async def call(method: str, params: dict | None=None) -> dict:
                        nonlocal seq
                        seq+=1
                        ident=seq
                        await ws.send(json.dumps({'id':ident,'method':method,'params':params or {}}))
                        while True:
                            result=json.loads(await asyncio.wait_for(ws.recv(),timeout=20))
                            if result.get('id')==ident:
                                if 'error' in result:
                                    raise RuntimeError(str(result['error']))
                                return result.get('result',{})
                    await call('Page.enable')
                    await call('Runtime.enable')
                    await call('Emulation.setDeviceMetricsOverride',{'width':width,'height':height,'deviceScaleFactor':1,'mobile':False})
                    for item in records:
                        route=item['id']
                        await call('Page.navigate',{'url':(root/'preview/index.html').as_uri()+'?render=1&state='+state+'#'+route})
                        deadline=time.monotonic()+15
                        while True:
                            result=await call('Runtime.evaluate',{'expression':'window.__previewReady === '+json.dumps(route),'returnByValue':True})
                            if result.get('result',{}).get('value') is True:
                                break
                            if time.monotonic()>deadline:
                                raise TimeoutError('Atlas route did not render: '+route)
                            await asyncio.sleep(.08)
                        await call('Runtime.evaluate',{'expression':'new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))','awaitPromise':True})
                        shot=await call('Page.captureScreenshot',{'format':'png','captureBeyondViewport':False,'fromSurface':True})
                        (output/(route+'.png')).write_bytes(base64.b64decode(shot['data']))
                        print('Exported',route,flush=True)
            finally:
                try:
                    os.killpg(process.pid,signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(process.pid,signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait(timeout=5)
                await asyncio.sleep(.25)

def main() -> int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--browser',default=shutil.which('microsoft-edge-stable') or shutil.which('chromium') or shutil.which('google-chrome'))
    p.add_argument('--only',nargs='*',default=[])
    p.add_argument('--state',choices=['ready','empty','unavailable','approval'],default='ready')
    p.add_argument('--output-dir',type=Path,default=None)
    p.add_argument('--width',type=int,default=1920)
    p.add_argument('--height',type=int,default=1080)
    a=p.parse_args()
    if not a.browser:
        p.error('Set --browser to a Chromium-compatible executable')
    if not 640<=a.width<=7680 or not 480<=a.height<=4320:
        p.error('Choose a usable desktop render size')
    asyncio.run(export(a.browser,Path(__file__).resolve().parent,a.only,a.width,a.height,a.output_dir,a.state))
    return 0

if __name__=='__main__':
    raise SystemExit(main())

"""API-lifetime DeepSeek process, with private inherited RPC pipes."""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).parent


class DeepSeekBridge:
    def __init__(self):
        self.process = None
        self.reader = None
        self.stderr = None
        self.ready = asyncio.Event()
        self.runs: dict[str, asyncio.Queue] = {}
        self.controls: dict[str, asyncio.Future] = {}
        self.lock = asyncio.Lock()

    async def start(self):
        async with self.lock:
            if self.process is not None and self.process.returncode is None:
                return
            self.ready.clear()
            # A runtime-only CLI profile resolves packages from the pinned checkout.
            # DeepSeek owns the native conversation log; SQLite is its public UI
            # projection and the separate capability-receipt authority.
            from ...config import CONFIG
            home = CONFIG.runtime_dir / 'deepseek'
            profile = home / 'profiles' / 'obsidience'
            profile.mkdir(parents=True, exist_ok=True, mode=0o700)
            (profile / 'cordis.yml').write_text('[]\n')
            (profile / 'package.json').write_text(json.dumps({
                'name': 'obsidience-profile', 'private': True,
                'dsh': {'profile': {'bundles': [], 'patchReload': 'startup'}},
            }))
            plugins = [
                ('session-projection', '@deepseek-ai/dsh-session-projection'),
                ('timer', '@deepseek-ai/cordis-plugin-timer'),
                ('llm', '@deepseek-ai/dsh-llm'),
                ('session', '@deepseek-ai/dsh-session'),
                ('persistence', '@deepseek-ai/dsh-session-persistence-jsonl'),
                ('system-prompt', '@deepseek-ai/dsh-system-prompt'),
                ('tools', '@deepseek-ai/dsh-tools'),
                ('agent', '@deepseek-ai/dsh-agent'),
                ('agent-loop', '@deepseek-ai/dsh-agent-loop'),
                ('token-meter', '@deepseek-ai/dsh-token-meter'),
                ('compaction', '@deepseek-ai/dsh-compaction-basic'),
                ('hindsight', str(ROOT / 'hindsight.mjs')),
                ('obsidience', str(ROOT / 'plugin.mjs')),
            ]
            entries = [{'id': key, 'name': name} for key, name in plugins]
            for entry in entries:
                if entry['id'] == 'persistence':
                    root = CONFIG.runtime_dir / 'deepseek-sessions'
                    root.mkdir(mode=0o700, parents=True, exist_ok=True)
                    entry['config'] = {'root': str(root)}
                elif entry['id'] == 'system-prompt':
                    entry['config'] = {'includeHarnessIdentity': False, 'includeRuntimeContext': False}
                elif entry['id'] == 'agent-loop':
                    entry['config'] = {'agents': [], 'maxParallelToolCalls': 1}
                elif entry['id'] == 'compaction':
                    from .sessions import compaction_threshold
                    entry['config'] = {'thresholdRatio': compaction_threshold() / 100,
                                       'retainRatio': 0.16, 'maxTokens': 2048}
            (profile / 'cordis.patch.yml').write_text(json.dumps([{'insert': entries}]))
            modules = profile / 'node_modules'
            if not modules.exists():
                modules.symlink_to(ROOT / 'node_modules', target_is_directory=True)
            self.process = await asyncio.create_subprocess_exec(
                str(ROOT / 'node_modules/.bin/dsh'), '--profile', 'obsidience',
                cwd=ROOT, env={**{key: os.environ[key] for key in ('PATH', 'HOME', 'LANG', 'TZ') if key in os.environ},
                               'DSH_HOME': str(home)},
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, limit=8 * 1024 * 1024,
            )
            self.reader = asyncio.create_task(self._read())
            self.stderr = asyncio.create_task(self._drain_stderr())
            try:
                await asyncio.wait_for(self.ready.wait(), 15)
                if self.process.returncode is not None:
                    raise RuntimeError('DeepSeek Executive exited during startup')
            except BaseException:
                await self.close()
                raise

    async def _read(self):
        try:
            async for line in self.process.stdout:
                message = json.loads(line)
                if message.get('method') == 'ready':
                    self.ready.set()
                elif message.get('control') in self.controls:
                    future = self.controls[message['control']]
                    if not future.done():
                        if message.get('error'):
                            future.set_exception(RuntimeError(message['error']))
                        else:
                            future.set_result(message.get('result'))
                elif queue := self.runs.get(message.get('run')):
                    await queue.put(message)
        except (ValueError, UnicodeError, asyncio.IncompleteReadError):
            if self.process.returncode is None:
                self.process.terminate()
        finally:
            await self.process.wait()
            self.ready.set()
            for future in self.controls.values():
                if not future.done():
                    future.set_exception(RuntimeError('DeepSeek session disconnected'))
            for queue in self.runs.values():
                await queue.put({'method': 'end', 'error': 'DeepSeek process disconnected; no Tool is replayed'})

    async def _drain_stderr(self):
        # Upstream diagnostics may contain request bodies. Never publish or persist them.
        async for _line in self.process.stderr:
            pass

    async def send(self, message):
        if self.process is None or self.process.returncode is not None:
            raise RuntimeError('DeepSeek Executive is unavailable')
        self.process.stdin.write(json.dumps(message, ensure_ascii=False).encode() + b'\n')
        await self.process.stdin.drain()

    async def control(self, method: str, **params):
        import uuid

        await self.start()
        identifier = uuid.uuid4().hex
        future = asyncio.get_running_loop().create_future()
        self.controls[identifier] = future
        try:
            await self.send({'control': identifier, 'method': method, 'params': params})
            async with asyncio.timeout(15):
                return await future
        finally:
            self.controls.pop(identifier, None)

    async def close(self):
        if self.process is None:
            return
        if self.process.returncode is None:
            self.process.stdin.close()
            try:
                await asyncio.wait_for(self.process.wait(), 5)
            except TimeoutError:
                self.process.kill()
                await self.process.wait()
        for task in (self.reader, self.stderr):
            if task and task is not asyncio.current_task():
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        self.process = self.reader = self.stderr = None


BRIDGE = DeepSeekBridge()

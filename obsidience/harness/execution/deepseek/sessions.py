"""Projections for DeepSeek-owned Executive conversations."""
from __future__ import annotations

import asyncio
import json
import uuid

from .bridge import BRIDGE
from ..native import (
    conversation_text, measure_view, prefill_messages as native_prefill_messages,
    rebase_window as native_rebase_window, window_anchor,
)

_views: dict[str, dict] = {}

BACKEND = 'deepseek'


async def start() -> None:
    """Start the API-lifetime DeepSeek child that owns native conversations."""
    from . import bridge
    await bridge.BRIDGE.start()


async def stop() -> None:
    from . import bridge
    await bridge.BRIDGE.close()


async def close(conversation_id: str) -> None:
    """Release the native session of a rotated conversation; its log is kept."""
    from . import bridge
    await bridge.BRIDGE.control('close', session_id=conversation_id)


def publish(value: dict | None) -> None:
    if value and str(value.get('id', '')).startswith('conversation-'):
        _views[value['id']] = value


async def refresh(conversation_id: str) -> dict | None:
    value = await BRIDGE.control('inspect', session_id=conversation_id,
                                 window_anchor=window_anchor(conversation_id))
    if value:
        publish(value)
    else:
        _views.pop(conversation_id, None)
    return value


async def reconcile(conversation) -> None:
    """Finish a missing public projection after native completion survived a crash."""
    value = await refresh(conversation.conversation_id)
    for outcome in (value or {}).get('outcomes', []):
        if outcome.get('status') != 'completed' or not outcome.get('summary'):
            continue
        parent = conversation.index.conversation_turn(outcome['reply_to'])
        if not parent or parent['conversation_id'] != conversation.conversation_id:
            continue
        if conversation.index.assistant_reply_for(parent['id']):
            continue
        await conversation.append(role='assistant', source=parent['source'], text=outcome['summary'],
                                  run_id=outcome['run_id'], reply_to=parent['id'])


def view(conversation_id: str) -> dict | None:
    return _views.get(conversation_id)


async def measure_context(conversation_id: str, spec, *, before_sequence: int | None = None,
                          pending_text: str = ''):
    """Measure the native model input, including its actual Tool schemas."""
    return await measure_view(view(conversation_id), conversation_id, spec,
                              before_sequence=before_sequence, pending_text=pending_text)


def context(conversation_id: str, before_sequence: int | None = None) -> str | None:
    return conversation_text(view(conversation_id), conversation_id, before_sequence)


def bootstrap(conversation_id: str, turn_id: str) -> dict:
    """Import exact public roles once; native history owns all later turns."""
    if view(conversation_id) is not None:
        return {}
    from ...knowledge.index import INDEX

    current = INDEX.conversation_turn(turn_id)
    if not current or current['conversation_id'] != conversation_id:
        raise ValueError('Native conversation requires an exact admitted owner turn')
    turns = INDEX.conversation_turns(conversation_id, before_sequence=current['sequence'])
    return {'bootstrap': turns}


def compaction_threshold() -> int:
    from ...knowledge.index import INDEX
    with INDEX.lock:
        row = INDEX.db.execute("SELECT value FROM conversation_state WHERE key='deepseek_compaction_threshold'").fetchone()
    return min(90, max(60, int(row[0]) if row else 80))


async def set_compaction_threshold(value: int) -> None:
    from ...knowledge.index import INDEX
    if BRIDGE.runs:
        raise RuntimeError('Wait for active model work before changing compaction policy')
    with INDEX.lock, INDEX.db:
        INDEX.db.execute("INSERT OR REPLACE INTO conversation_state(key,value) VALUES('deepseek_compaction_threshold',?)", (str(value),))
    # Reload the Cordis policy while idle. Native JSONL sessions are preserved.
    await BRIDGE.close()


async def compact(conversation_id: str, spec, *, idle_threshold: float | None = None) -> dict:
    """Use native idle-session maintenance and the existing model reservation.

    Without idle_threshold, the manual Compact summarizes now (upstream
    compactNow). With it (a fraction of the model context), idle maintenance
    runs inside one upstream turn: Tool-result pruning, then a summary of the
    older span only while pressure stays at or above that fraction.
    """
    from ...config import CONFIG
    from ...models import runtime as model_runtime
    from .. import native as model

    native = await refresh(conversation_id)
    if not native:
        return {'status': 'nothing_to_compact'}
    run = 'compact-' + uuid.uuid4().hex
    queue = asyncio.Queue()
    BRIDGE.runs[run] = queue
    ended = False
    lease = model_runtime.lease(spec)
    acquired = False
    try:
        await lease.__aenter__()
        acquired = True
        await BRIDGE.send({'method': 'start', 'params': {
            'run': run, 'session_id': conversation_id, 'window_anchor': window_anchor(conversation_id),
            **({'compact': True} if idle_threshold is None else {'maintain': {'threshold': idle_threshold}}),
            'cwd': str(CONFIG.project_root), 'effort': native.get('reasoning_effort', 'none'),
            'system': '\n'.join(block['text'] for message in native['messages']
                                if message['role'] == 'system' for block in message['content']
                                if block['type'] == 'text'),
            'messages': [], 'tools': native.get('tools', []),
            'model': {'id': spec.id, 'context_tokens': spec.context_tokens,
                      'max_output_tokens': spec.max_output_tokens, 'capabilities': list(spec.capabilities)},
        }})
        while True:
            message = await queue.get()
            if message.get('method') == 'end':
                ended = True
                publish(message.get('session'))
                if message.get('error'):
                    raise RuntimeError(message['error'])
                status = ('completed' if message.get('compacted')
                          else 'pruned' if message.get('pruned') else 'nothing_to_compact')
                return {'status': status, 'pruned': message.get('pruned', 0),
                        'backend': 'deepseek', 'conversation_id': conversation_id}
            if message.get('method') != 'model' or message['params'].get('purpose') != 'compaction':
                await BRIDGE.send({'id': message['id'], 'error': 'Compaction permits summary inference only'})
                continue
            async def send(value):
                await BRIDGE.send({'id': message['id'], 'result': value})
            try:
                await model.stream(message['params'], spec, 'none', {}, send, {})
            except Exception as exc:
                await BRIDGE.send({'id': message['id'], 'error': str(exc)[:300]})
            else:
                await BRIDGE.send({'id': message['id'], 'done': True})
    finally:
        try:
            if acquired and not ended:
                await BRIDGE.send({'method': 'cancel', 'run': run})
                try:
                    async with asyncio.timeout(5):
                        while True:
                            message = await queue.get()
                            if message.get('method') == 'end':
                                publish(message.get('session'))
                                break
                except TimeoutError:
                    await BRIDGE.close()
        finally:
            BRIDGE.runs.pop(run, None)
            if acquired:
                await lease.__aexit__(None, None, None)


def prefill_messages(conversation_id: str, compiled: list[dict], text: str, *,
                     memory: str = '', preparation_prefix: bool = False) -> list[dict]:
    return native_prefill_messages(view(conversation_id), conversation_id, compiled, text,
                                   memory=memory, preparation_prefix=preparation_prefix)


def rebase_window(conversation_id: str) -> str | None:
    value = view(conversation_id)
    return native_rebase_window(conversation_id, value['messages'] if value else None)

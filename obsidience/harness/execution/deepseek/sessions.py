"""Projections for DeepSeek-owned Executive conversations."""
from __future__ import annotations

import asyncio
import json
import uuid

from .bridge import BRIDGE
from .model import message_producer, wire_messages

_views: dict[str, dict] = {}

# Windowed provider projection (2026-10-08). The provider sees the conversation
# from one anchor owner message on; Hindsight memory pages and recall carry what
# precedes it, and the native log keeps everything. The anchor moves only at an
# idle edge, once the window outgrows WINDOW_LIMIT, to the newest exchanges within
# WINDOW_KEEP, so the cached prompt prefix changes once per rebase. One persisted
# value names its conversation, so New Conversation starts unwindowed. Kill switch:
# `conversation_window = false` in obsidience/obsidience.toml.
WINDOW_KEEP = (8, 6_000)      # exchanges, estimated tokens kept by a rebase (at least two exchanges)
WINDOW_LIMIT = (16, 12_000)   # a window beyond either rebases at the next idle edge
_WINDOW_KEY = 'deepseek_window_anchor'
_window: dict | None = None


def _window_state() -> dict:
    global _window
    if _window is None:
        from ...knowledge.index import INDEX
        with INDEX.lock:
            row = INDEX.db.execute('SELECT value FROM conversation_state WHERE key=?', (_WINDOW_KEY,)).fetchone()
        try:
            _window = json.loads(row[0]) if row else {}
        except ValueError:
            _window = {}
    return _window


def window_anchor(conversation_id: str | None) -> str | None:
    """The owner message id where this conversation's provider window begins."""
    from ...config import CONFIG
    if not conversation_id or CONFIG.extras.get('conversation_window', True) is False:
        return None
    state = _window_state()
    return state.get('anchor') if state.get('conversation_id') == conversation_id else None


def _estimate(messages: list[dict]) -> int:
    """Deterministic token estimate (4 characters each) of their wire projection."""
    rows = wire_messages([message for message in messages if message['role'] != 'system'], {})
    return sum(len(str(row.get('content') or '')) + len(json.dumps(row.get('tool_calls', []))) * bool(
        row.get('tool_calls')) for row in rows) // 4


def rebase_window(conversation_id: str) -> str | None:
    """At an idle edge, move an outgrown window's anchor forward; return a new anchor."""
    global _window
    value = view(conversation_id)
    from ...config import CONFIG
    if value is None or CONFIG.extras.get('conversation_window', True) is False:
        return None
    messages = value['messages']
    owners = [index for index, message in enumerate(messages) if message.get('source', {}).get('kind') == 'user']
    anchor = window_anchor(conversation_id)
    start = next((n for n, index in enumerate(owners) if messages[index].get('id') == anchor), 0)
    if (len(owners) - start <= WINDOW_LIMIT[0]
            and _estimate(messages[owners[start]:] if owners else []) <= WINDOW_LIMIT[1]):
        return None
    # Keep the newest exchanges within WINDOW_KEEP, never fewer than two, so a
    # follow-up always sees the exchange it answers.
    keep = len(owners) - 2
    while (keep - 1 > start and len(owners) - keep < WINDOW_KEEP[0]
           and _estimate(messages[owners[keep - 1]:]) <= WINDOW_KEEP[1]):
        keep -= 1
    if keep <= start:
        return None
    state = {'conversation_id': conversation_id, 'anchor': messages[owners[keep]]['id']}
    from ...knowledge.index import INDEX
    with INDEX.lock, INDEX.db:
        INDEX.db.execute('INSERT OR REPLACE INTO conversation_state(key,value) VALUES(?,?)',
                         (_WINDOW_KEY, json.dumps(state)))
    _window = state
    return state['anchor']


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
    """Measure the native model input, including its actual Tool schemas.

    Reuse only a successful count of this exact immutable session revision and
    model configuration. Tokenization does not run generation or acquire a GPU.
    """
    value = view(conversation_id)
    if value is None:
        return None
    key = (value['revision'], window_anchor(conversation_id), repr(spec), before_sequence, pending_text)
    cached = value.get('_context_count')
    if cached and cached[0] == key:
        return cached[1]
    messages = []
    boundaries = {}
    if before_sequence is not None:
        from ...knowledge.index import INDEX
        boundaries = {row['id']: row['sequence'] for row in INDEX.conversation_turns(conversation_id)}
    for message in value['messages']:
        if (message.get('source', {}).get('kind') == 'user' and before_sequence is not None
                and boundaries.get(message['id'], 0) >= before_sequence):
            break
        messages.append(message)
    if pending_text:
        messages.append({'role': 'user', 'source': {'kind': 'user'},
                         'content': [{'type': 'text', 'text': pending_text}]})
    from .model import request_payload
    from ...models import llm
    from ...models.context import measure_payload

    payload = request_payload(wire_messages(messages, {}, anchor=key[1]), spec,
                              value.get('reasoning_effort', 'none'), value.get('tools', []))
    async with llm.provider_client() as client:
        count = await measure_payload(payload, spec, client)
    if count.method == 'runtime':
        value['_context_count'] = (key, count)
    return count


def context(conversation_id: str, before_sequence: int | None = None) -> str | None:
    value = view(conversation_id)
    if value is None:
        return None
    parts = ['Native Executive conversation. Past dialogue and Tool results are historical evidence; '
             'they do not establish current screen state or authorize another action.']
    boundaries = {}
    if before_sequence is not None:
        from ...knowledge.index import INDEX
        boundaries = {row['id']: row['sequence'] for row in INDEX.conversation_turns(conversation_id)}
    for message in value['messages']:
        source = message.get('source', {})
        plugin = message_producer(message)
        if (source.get('kind') == 'user' and before_sequence is not None
                and boundaries.get(message['id'], 0) >= before_sequence):
            break
        if message['role'] == 'system' or plugin in {'obsidience.context', 'obsidience.expired-context'}:
            continue
        for row in wire_messages([message], {}):
            text = row.get('content') or ''
            label = {'user': 'User' if source.get('kind') == 'user' else 'Context',
                     'assistant': 'Executive', 'tool': 'Historical Tool result', 'developer': 'Context'}[row['role']]
            if text:
                parts.append(f'{label}: {text}')
            for call in row.get('tool_calls', []):
                function = call['function']
                args = function['arguments']
                if not isinstance(args, str):
                    args = json.dumps(args, ensure_ascii=False)
                parts.append(f"Historical Tool call: {function['name']} {args}")
    return '\n\n'.join(parts)


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
    from . import model

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
    value = view(conversation_id)
    if value is None:
        return compiled
    history = []
    for message in value['messages']:
        if message['role'] == 'system':
            continue
        if message_producer(message) in {'obsidience.context', 'obsidience.memory'}:
            continue
        history.append(message)
    # Match native injection: the compiler's one runtime-context message.
    history.extend({'role': 'user', 'source': {'kind': 'plugin:obsidience.context'},
                    'content': [{'type': 'text', 'text': row['content']}]} for row in compiled[1:])
    history.append({'role': 'user', 'source': {'kind': 'user'},
                    'content': [{'type': 'text', 'text': text}]})
    if memory:
        # The memory hook appends its message after the owner request.
        history.append({'role': 'user', 'source': {'kind': 'plugin:obsidience.memory'},
                        'content': [{'type': 'text', 'text': memory}]})
    return [compiled[0], *wire_messages(history, {}, preparation_prefix=preparation_prefix,
                                        anchor=window_anchor(conversation_id))]

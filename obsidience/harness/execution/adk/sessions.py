"""ADK-owned Executive conversations and the Executive's ADK model route.

One ``SqliteSessionService`` (aiosqlite, its own file under ``state/``) owns
every Executive conversation log; SQLite ``conversation_turns`` stays the
public Chat projection and receipt ledger.
Session events carry Obsidience source kinds in ``Part.part_metadata`` so the
shared native projection (``execution/native.py``) can rebuild the same
provider window, settled commands and current runtime context from them.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sqlite3
import sys
from contextvars import ContextVar

# LiteLLM must never fetch a remote cost map at import (owner decision 2026-10-09).
os.environ.setdefault('LITELLM_LOCAL_MODEL_COST_MAP', 'True')

from google.adk.events import Event  # noqa: E402
from google.genai import types  # noqa: E402

from ..native import (  # noqa: E402
    conversation_text, measure_view, message_producer, prefill_messages as native_prefill_messages,
    rebase_window as native_rebase_window, reconcile_outcomes, window_anchor,
)

BACKEND = 'adk'
APP = 'obsidience'
USER = 'owner'
AGENT = 'executive'
STORE = 'adk-sessions.sqlite3'
REQUEST_STATE = 'obsidience_request'
_TURN_KINDS = {'user', 'plugin:obsidience.continuation', 'plugin:obsidience.command'}
_LIVE_KINDS = {'plugin:obsidience.context', 'plugin:obsidience.memory'}

_service = None
# (conversation, window anchor) -> timestamp of the anchor's first log event.
_floors: dict[tuple[str, str], float] = {}
_models: dict[tuple, object] = {}
# The current model step's metrics, set by the plugin before each request; the
# admission client records the provider's acknowledged input count there.
ADMISSION: ContextVar[dict | None] = ContextVar('obsidience_admission', default=None)
# Set only by the trusted named-Agent ingress wrapper, never by model params.
CONVERSATION_BINDING: ContextVar[object | None] = ContextVar('obsidience_conversation_binding', default=None)


def binding(conversation_id):
    value = CONVERSATION_BINDING.get()
    return value if value is not None and value.conversation_id == conversation_id else None


def user_id(conversation_id):
    value = binding(conversation_id)
    return value.user_id if value is not None else USER


def agent_id(conversation_id):
    value = binding(conversation_id)
    return value.agent_name if value is not None else AGENT


def admitted_input_tokens(response, limit: int) -> int:
    """The input count llama.cpp acknowledged for this exact guard, else fail closed.

    The engine enforces ``input_token_limit`` before queueing and answers with
    ``X-LLAMA-Input-Token-Limit`` and ``X-LLAMA-Input-Tokens``; a response
    without that acknowledgement may not have been guarded.
    """
    headers = getattr(response, '_response_headers', None)
    if headers is None:
        extra = (getattr(response, '_hidden_params', None) or {}).get('additional_headers') or {}
        headers = {key.removeprefix('llm_provider-'): value for key, value in extra.items()}
    headers = {str(key).lower(): str(value) for key, value in dict(headers).items()}
    count_text = headers.get('x-llama-input-tokens', '')
    if (headers.get('x-llama-input-token-limit') != str(limit) or not count_text.isascii()
            or not count_text.isdecimal() or len(count_text) > 10):
        raise ValueError('Native provider did not acknowledge the exact input-token guard')
    count = int(count_text)
    if count > limit or count_text != str(count):
        raise ValueError('Native provider returned an invalid admitted token count')
    return count


def _admission_client():
    """ADK's LiteLLM client that verifies llama.cpp's exact input-token admission."""
    from google.adk.models.lite_llm import LiteLLMClient

    class AdmittedLiteLLMClient(LiteLLMClient):
        async def acompletion(self, model, messages, tools, **kwargs):
            import litellm
            limit = (kwargs.get('extra_body') or {}).get('input_token_limit')
            try:
                response = await super().acompletion(model=model, messages=messages, tools=tools, **kwargs)
            except litellm.BadRequestError as exc:
                if limit is not None and 'input_token_limit' in str(exc):
                    # Either the request had nothing projectable and skipped the
                    # duplicate client count, or a projected count mismatched.
                    # Nothing is retried; nothing was generated.
                    counted = re.search(r'''["']input_tokens["']\s*:\s*(\d+)''', str(exc))
                    if counted and int(counted.group(1)) > limit:
                        from ...models.context import ContextBudgetExceeded, PayloadCount
                        raise ContextBudgetExceeded(PayloadCount(int(counted.group(1))), limit) from None
                    raise ValueError(f'The model server refused this request at its exact input-token '
                                     f'guard ({limit} tokens); nothing was generated') from None
                raise
            if limit is not None:
                try:
                    count = admitted_input_tokens(response, limit)
                except ValueError:
                    if hasattr(response, 'aclose'):
                        await response.aclose()
                    raise
                if (metrics := ADMISSION.get()) is not None:
                    metrics.update(admitted_input_tokens=count, input_token_guard='acknowledged')
            return response

    return AdmittedLiteLLMClient()
_views: dict[str, dict] = {}


def service():
    if _service is None:
        raise RuntimeError('The ADK conversation store is not running in this Harness lifetime')
    return _service


def _import_litellm() -> None:
    # LiteLLM would otherwise fetch its model cost map from GitHub at import; the
    # bundled map suffices and the Harness makes no network call of its own here.
    os.environ.setdefault('LITELLM_LOCAL_MODEL_COST_MAP', 'True')
    from google.adk.models.lite_llm import _ensure_litellm_imported
    _ensure_litellm_imported()
    import litellm
    litellm.suppress_debug_info = True  # Request bodies and keys never reach logs.
    litellm.telemetry = False


async def window_floor(conversation_id: str) -> float | None:
    """When the conversation's provider window begins in its log, if it has an anchor there."""
    anchor = window_anchor(conversation_id)
    if not anchor:
        return None
    key = (conversation_id, anchor)
    if key not in _floors:
        from ...config import CONFIG

        def find():
            with sqlite3.connect(f'file:{CONFIG.runtime_dir / STORE}?mode=ro', uri=True) as db:
                return db.execute(
                    'SELECT MIN(timestamp) FROM events WHERE app_name=? AND user_id=? AND session_id=? '
                    'AND instr(event_data, ?) > 0', (APP, user_id(conversation_id), conversation_id, anchor)).fetchone()[0]
        floor = await asyncio.to_thread(find)
        if floor is None:
            return None  # The anchor is not in this log yet: load it whole.
        _floors.clear()
        _floors[key] = floor
    return _floors[key]


def _windowed_store(path: str):
    from google.adk.sessions.base_session_service import GetSessionConfig
    from google.adk.sessions.sqlite_session_service import SqliteSessionService

    class WindowedStore(SqliteSessionService):
        """The conversation log, loaded from its provider window's anchor onward.

        ADK reloads the session and rebuilds model input from every loaded event on
        each invocation (measured 180-560 ms at 1,817 events against 11-20 ms at
        100-300), yet only the window after the anchor reaches the model. Earlier
        events stay in the log; a conversation without an anchor loads whole.
        """

        async def get_session(self, *, app_name, user_id, session_id, config=None):
            if config is None and (floor := await window_floor(session_id)) is not None:
                config = GetSessionConfig(after_timestamp=floor)
            return await super().get_session(
                app_name=app_name, user_id=user_id, session_id=session_id, config=config)

    return WindowedStore(path)


async def start() -> None:
    """Open the conversation store (and load LiteLLM once for its route) before the API accepts turns."""
    global _service
    if _service is not None:
        return
    from ...config import CONFIG
    _service = _windowed_store(str(CONFIG.runtime_dir / STORE))
    if model_client() == 'litellm':
        await asyncio.to_thread(_import_litellm)


async def stop() -> None:
    global _service
    _service = None
    _floors.clear()
    _views.clear()
    _models.clear()
    if 'litellm' in sys.modules:
        await sys.modules['litellm'].close_litellm_async_clients()


async def close(conversation_id: str) -> None:
    """New Conversation: drop the cached view; the store keeps the rotated log."""
    _views.pop(conversation_id, None)


def model_client() -> str:
    """``adk_model_client`` in obsidience.toml: ``local`` (default) or ``litellm`` (rollback)."""
    from ...config import CONFIG
    value = CONFIG.extras.get('adk_model_client', 'local')
    if value not in {'local', 'litellm'}:
        raise ValueError('adk_model_client must be "local" or "litellm"')
    return value


def model(spec, effort: str):
    """The Executive's ADK model route for one model and reasoning effort.

    Carries what the native transport sends: the served model id (so tool
    results keep the template's native ``tool`` role), output cap,
    temperature, single Tool call per step, template thinking switch and the
    engine's exact input ceiling, whose acknowledgement every response must carry.
    ``local`` streams through the API's httpx pool (``adk/model.py``); ``litellm``
    is ADK's LiteLlm route. Both expose the same ``_additional_args``.
    """
    kind = model_client()
    key = (spec.id, spec.base_url, effort, kind)
    if key not in _models:
        from ...config import CONFIG
        from ...models import llm, runtime as model_runtime
        from ...models.context import PROMPT_SAFETY_TOKENS
        extra = {'chat_template_kwargs': {'enable_thinking': effort != 'none'}}
        if effort != 'none':
            extra.update(reasoning_format='auto', reasoning_budget_tokens=spec.reasoning_budgets[effort])
        if spec.supports_input_token_limit:
            extra['input_token_limit'] = spec.context_tokens - spec.max_output_tokens - PROMPT_SAFETY_TOKENS
        args = dict(max_tokens=spec.max_output_tokens, temperature=CONFIG.llm_temperature,
                    parallel_tool_calls=False, timeout=llm.CHAT_TIMEOUT_SECONDS, extra_body=extra)
        if kind == 'local':
            from .model import LocalLlm
            _models[key] = LocalLlm(spec.id, base_url=spec.base_url, **args)
        else:
            from google.adk.models.lite_llm import LiteLlm
            token = model_runtime.model_auth_headers().get('Authorization', '').removeprefix('Bearer ').strip()
            _models[key] = LiteLlm(
                model='openai/' + spec.id, api_base=spec.base_url, api_key=token or 'none', **args,
                **({'llm_client': _admission_client()} if 'input_token_limit' in extra else {}))
    return _models[key]


def engine_guard(spec, effort: str) -> int | None:
    """The exact input_token_limit this route's requests carry, or None without the engine guard."""
    if not spec.supports_input_token_limit:
        return None
    return (model(spec, effort)._additional_args.get('extra_body') or {}).get('input_token_limit')


def part(text: str, source: str, **meta) -> types.Part:
    """One text part with its Obsidience producer (``user`` for owner requests)."""
    return types.Part(text=text, part_metadata={'obsidience': {'source': source, **meta}})


def _meta(value: types.Part) -> dict:
    return ((value.part_metadata or {}).get('obsidience') or {}) if value.part_metadata else {}


def _blocks(response) -> list[dict]:
    if isinstance(response, dict) and isinstance(response.get('content'), list):
        return response['content']
    return [{'type': 'text', 'text': response if isinstance(response, str)
             else json.dumps(response, ensure_ascii=False, default=str)}]


def native_messages(contents) -> list[dict]:
    """ADK contents (session events or a built request) in the native message vocabulary.

    Runtime context and recall belong to the latest owner turn; earlier ones
    are marked superseded.
    """
    messages = []
    for content in contents:
        if content is None or not content.parts:
            continue
        for value in content.parts:
            if value.function_response is not None:
                response = value.function_response
                messages.append({'role': 'tool', 'toolCallId': response.id or '',
                                 'content': _blocks(response.response)})
        if content.role == 'model':
            blocks = [{'type': 'text', 'text': value.text} for value in content.parts
                      if value.text and not value.thought]
            blocks += [{'type': 'tool-call', 'id': value.function_call.id or '', 'name': value.function_call.name,
                        'arguments': json.dumps(value.function_call.args or {}, ensure_ascii=False,
                                                separators=(',', ':'))}
                       for value in content.parts if value.function_call is not None]
            if blocks:
                messages.append({'role': 'assistant', 'source': {'provider': 'obsidience'}, 'content': blocks})
            continue
        for value in content.parts:
            if value.text is None:
                continue
            meta = _meta(value)
            message = {'role': 'user', 'source': {'kind': meta.get('source', 'user')},
                       'content': [{'type': 'text', 'text': value.text}], '_run': meta.get('run')}
            if meta.get('id'):
                message['id'] = meta['id']
            messages.append(message)
    current = next((message['_run'] for message in reversed(messages)
                    if message.get('source', {}).get('kind') in _TURN_KINDS), None)
    for message in messages:
        if message.get('source', {}).get('kind') in _LIVE_KINDS and message.pop('_run', None) != current:
            message['source'] = {'kind': 'plugin:obsidience.expired-context'}
        message.pop('_run', None)
    return messages


def known_turns(session) -> set[str]:
    """Public owner turn ids this log already holds, as requests or clarifications."""
    ids = set()
    for event in session.events:
        for value in (event.content.parts if event.content and event.content.parts else []):
            meta = _meta(value)
            if meta.get('id'):
                ids.add(meta['id'])
            ids.update(meta.get('turns') or [])
    return ids


def publish(session) -> dict:
    messages = native_messages(event.content for event in session.events)
    request = session.state.get(REQUEST_STATE) or {}
    system = ([{'role': 'system', 'content': [{'type': 'text', 'text': request['system']}]}]
              if request.get('system') else [])
    outcomes = []
    for message in messages:
        if message_producer(message) in {'obsidience.outcome', 'obsidience.command-outcome'}:
            try:
                outcomes.append(json.loads(message['content'][0]['text']))
            except ValueError:
                pass
    value = {'id': session.id, 'revision': len(session.events), 'messages': system + messages,
             'tools': request.get('tools', []), 'reasoning_effort': request.get('effort', 'none'),
             'outcomes': outcomes[-80:]}
    _views[session.id] = value
    return value


async def refresh(conversation_id: str) -> dict | None:
    session = await service().get_session(app_name=APP, user_id=user_id(conversation_id), session_id=conversation_id)
    if session is None:
        _views.pop(conversation_id, None)
        return None
    return publish(session)


async def reconcile(conversation) -> None:
    """Finish a missing public projection after a completed run survived a crash."""
    await reconcile_outcomes(conversation, await refresh(conversation.conversation_id))


def view(conversation_id: str) -> dict | None:
    return _views.get(conversation_id)


async def measure_context(conversation_id: str, spec, *, before_sequence: int | None = None,
                          pending_text: str = ''):
    return await measure_view(view(conversation_id), conversation_id, spec,
                              before_sequence=before_sequence, pending_text=pending_text)


def context(conversation_id: str, before_sequence: int | None = None) -> str | None:
    return conversation_text(view(conversation_id), conversation_id, before_sequence)


def prefill_messages(conversation_id: str, compiled: list[dict], text: str, *,
                     memory: str = '', preparation_prefix: bool = False) -> list[dict]:
    return native_prefill_messages(view(conversation_id), conversation_id, compiled, text,
                                   memory=memory, preparation_prefix=preparation_prefix)


def rebase_window(conversation_id: str) -> str | None:
    value = view(conversation_id)
    return native_rebase_window(conversation_id, value['messages'] if value else None)


async def open_session(conversation_id: str, turn_id: str | None):
    """The conversation's session, with public turns it lacks appended in order.

    A new or stale session (for example a conversation begun before this log
    existed) receives exact owner/reply pairs from the public ledger, so the
    dialogue is kept.
    """
    store = service()
    session = await store.get_session(app_name=APP, user_id=user_id(conversation_id), session_id=conversation_id)
    if session is None:
        session = await store.create_session(app_name=APP, user_id=user_id(conversation_id), session_id=conversation_id)
    if turn_id is None:
        return session
    from ...knowledge.index import INDEX
    external = binding(conversation_id)
    if external is not None:
        current = external.validate()
        if turn_id != external.turn_id:
            raise ValueError('Native named-Agent turn binding changed')
        turns = external.history()
    else:
        current = INDEX.conversation_turn(turn_id)
    if not current or current['conversation_id'] != conversation_id:
        raise ValueError('Native conversation requires an exact admitted owner turn')
    if external is None:
        turns = INDEX.conversation_turns(conversation_id, before_sequence=current['sequence'])
    if external is None and await window_floor(conversation_id) is not None:
        # The log was loaded from the window's anchor; earlier turns are already in it.
        # Without the anchor's ledger row nothing can be placed safely: seed nothing.
        first = INDEX.conversation_turn(window_anchor(conversation_id))
        floor_sequence = (first['sequence'] if first and first['conversation_id'] == conversation_id
                          else current['sequence'])
        turns = [turn for turn in turns if turn['sequence'] >= floor_sequence]
    if external is not None:
        await close_interrupted_calls(conversation_id, 'named-agent-recovery')
        session = await store.get_session(app_name=APP, user_id=user_id(conversation_id), session_id=conversation_id)
    known = known_turns(session)
    replies = {turn['reply_to']: turn for turn in turns if turn['role'] == 'assistant'}
    for turn in turns:
        if turn['role'] != 'user' or turn['id'] in known:
            continue
        await store.append_event(session, Event(invocation_id='seed', author='user', content=types.Content(
            role='user', parts=[part(turn['text'], 'user', id=turn['id'])])))
        if (reply := replies.get(turn['id'])) is not None:
            await store.append_event(session, Event(invocation_id='seed', author=agent_id(conversation_id), content=types.Content(
                role='model', parts=[types.Part(text=reply['text'])])))
    return session


def _receipt_object(value):
    """Decode only structured native Tool/controller result text."""
    if isinstance(value, dict) and isinstance(value.get('content'), list):
        value = value['content']
    if isinstance(value, list):
        value = next((row.get('text') for row in value if isinstance(row, dict)
                      and row.get('type') == 'text'), None)
    if isinstance(value, str):
        value = value.removeprefix('Observation:\\n').removeprefix('Observation:\n')
        try:
            value = json.loads(value)
        except ValueError:
            return None
    return value if isinstance(value, dict) else None


def previous_discord_music_choices(session):
    """Latest search choices in this member's recent native conversation.

    Public source identities are evidence, not reusable selection grants. A new
    search replaces them; an attempted playback consumes them. Read no dialogue
    as source authority and never cross the bound session or its recent turns.
    """
    current = binding(session.id)
    if current is None or session.user_id != current.user_id or current.agent_name != 'discord':
        return []
    events = session.events[-256:]
    turns = set()
    floor = 0
    for index in range(len(events) - 1, -1, -1):
        event = events[index]
        for value in (event.content.parts if event.content and event.content.parts else []):
            meta = _meta(value)
            if event.author == 'user' and meta.get('source') in _TURN_KINDS and meta.get('id'):
                turns.add(meta['id'])
        if len(turns) > 4:
            floor = index + 1
            break
    calls, candidates, pending_play = {}, [], set()
    for event in events[floor:]:
        for value in (event.content.parts if event.content and event.content.parts else []):
            if event.author == current.agent_name:
                if (call := value.function_call) is not None:
                    calls[(event.invocation_id, call.id)] = (call.name, call.args or {})
                    if call.name == 'media.library' and (call.args or {}).get('action') == 'search':
                        candidates = []
                        pending_play.clear()
                    elif call.name == 'discord.control' and (call.args or {}).get('action') == 'play':
                        pending_play.add((event.invocation_id, call.id))
                response = value.function_response
                if response is None or (call := calls.get((event.invocation_id, response.id))) is None:
                    continue
                name, args = call
                receipt = _receipt_object(response.response)
                if response.name != name or receipt is None:
                    continue
                if (name == 'media.library' and args.get('action') == 'search'
                        and args.get('type') == 'music' and receipt.get('status') == 'completed'):
                    candidates = receipt.get('candidates', [])
                elif name == 'discord.control' and args.get('action') == 'play':
                    pending_play.discard((event.invocation_id, response.id))
                    if not (receipt.get('delivery') == 'not_dispatched' and receipt.get('effect_applied') is False):
                        candidates = []
            elif event.author == 'user':
                meta = _meta(value)
                if meta.get('source') not in {'plugin:obsidience.context', 'plugin:obsidience.command-outcome'}:
                    continue
                receipt = _receipt_object(value.text)
                if receipt is None:
                    continue
                if meta['source'] == 'plugin:obsidience.context':
                    args = receipt.get('search_arguments') or {}
                    page = receipt.get('search_result') or {}
                    if args.get('action') == 'search' and args.get('type') == 'music':
                        candidates = page.get('candidates', []) if page.get('status') == 'completed' else []
                        pending_play.clear()
                elif receipt.get('run_id') == meta.get('run'):
                    command = receipt.get('command') or {}
                    if (command.get('declined_music') is True or command.get('name') == 'discord.control'
                            and (command.get('args') or {}).get('action') == 'play'):
                        candidates = []
    # Missing/cross-invocation recovery responses mean outcome unknown, not an
    # unused choice. Never resurrect a selection after an interrupted effect.
    return [] if pending_play else [dict(row) for row in candidates[:40] if isinstance(row, dict)]


def previous_discord_music_artist(session):
    """Last successfully admitted artist in this bound session, never dialogue.

    This is historical selection evidence for an explicit continuation request,
    not a preference, permission or claim of current playback. Read only the
    bounded native window; an older/missing receipt requires clarification.
    """
    current = binding(session.id)
    if current is None or session.user_id != current.user_id:
        return None
    calls, candidates, artist = {}, {}, None

    def successful(receipt):
        return (isinstance(receipt, dict) and receipt.get('ok') is True
                and receipt.get('status') == 'completed' and not receipt.get('must_not_replay')
                and receipt.get('delivery') in {'audio_playback_ready', 'audio_playback_started'})

    def named(value):
        return (isinstance(value, str) and 0 < len(value.strip()) <= 80
                and not any(ord(char) < 32 for char in value))

    for event in session.events[-256:]:
        parts = event.content.parts if event.content and event.content.parts else []
        for value in parts:
            if event.author == current.agent_name:
                if (call := value.function_call) is not None:
                    calls[call.id] = (call.name, call.args or {})
                response = value.function_response
                if response is not None and response.id in calls:
                    name, args = calls[response.id]
                    if response.name != name or (receipt := _receipt_object(response.response)) is None:
                        continue
                    if (name == 'media.library' and args.get('action') == 'search'
                            and args.get('type') == 'music' and receipt.get('status') == 'completed'):
                        candidates.update({(event.invocation_id, row['id']): row for row in receipt.get('candidates', [])
                                           if isinstance(row, dict) and isinstance(row.get('id'), str)})
                    elif name == 'discord.control' and args.get('action') == 'play' and successful(receipt):
                        artist = None
                        row = candidates.get((event.invocation_id, args.get('id')), {})
                        if (row.get('provider') == 'youtube' and named(row.get('artist'))
                                and isinstance(row.get('video_id'), str)
                                and receipt.get('item_id') == 'youtube:' + row['video_id']
                                and receipt.get('title') == row.get('title')):
                            artist = row['artist'].strip()
            elif event.author == 'user' and _meta(value).get('source') == 'plugin:obsidience.context':
                context = _receipt_object(value.text)
                if context is None:
                    continue
                rows = context.get('followup_music_choices')
                if not isinstance(rows, list):
                    args = context.get('search_arguments') or {}
                    page = context.get('search_result') or {}
                    rows = (page.get('candidates') if isinstance(args, dict) and isinstance(page, dict)
                            and args.get('action') == 'search' and args.get('type') == 'music'
                            and page.get('status') == 'completed' else None)
                if isinstance(rows, list):
                    candidates.update({(event.invocation_id, row['id']): row for row in rows
                                       if isinstance(row, dict) and isinstance(row.get('id'), str)})
            elif event.author == 'user' and _meta(value).get('source') == 'plugin:obsidience.command-outcome':
                try:
                    outcome = json.loads(value.text or '')
                except ValueError:
                    continue
                if not isinstance(outcome, dict) or outcome.get('run_id') != _meta(value).get('run'):
                    continue
                command = outcome.get('command') or {}
                if not isinstance(command, dict):
                    continue
                identity = command.get('music_identity') or {}
                if not isinstance(identity, dict) or not isinstance(command.get('args'), dict):
                    continue
                receipt = _receipt_object(outcome.get('result'))
                if (outcome.get('status') == 'completed' and command.get('name') == 'discord.control'
                        and command['args'].get('action') == 'play' and successful(receipt)):
                    artist = None
                    if (named(identity.get('artist')) and receipt.get('title') == identity.get('title')
                            and isinstance(receipt.get('item_id'), str)
                            and receipt['item_id'].startswith('youtube:')):
                        artist = identity['artist'].strip()
    return artist


async def close_interrupted_calls(conversation_id: str, invocation_id: str) -> None:
    """Record every unanswered native call as outcome unknown; it is never replayed."""
    from ..capability_core import INTERRUPTED, observation_text
    store = service()
    session = await store.get_session(app_name=APP, user_id=user_id(conversation_id), session_id=conversation_id)
    if session is None:
        return
    calls, answered = {}, set()
    for event in session.events:
        for value in (event.content.parts if event.content and event.content.parts else []):
            if value.function_call is not None:
                calls[value.function_call.id] = value.function_call.name
            if value.function_response is not None:
                answered.add(value.function_response.id)
    parts = [types.Part(function_response=types.FunctionResponse(id=identifier, name=name, response={
        'content': [{'type': 'text', 'text': observation_text(INTERRUPTED)}]}))
        for identifier, name in calls.items() if identifier not in answered]
    if parts:
        await store.append_event(session, Event(invocation_id=invocation_id, author=agent_id(conversation_id),
                                                content=types.Content(role='user', parts=parts)))


async def append(conversation_id: str, invocation_id: str, parts: list[types.Part]) -> None:
    """Append one controller-owned user event (settlement or command records)."""
    from google.adk.sessions.base_session_service import GetSessionConfig
    store = service()
    session = await store.get_session(app_name=APP, user_id=user_id(conversation_id), session_id=conversation_id,
                                      config=GetSessionConfig(num_recent_events=1))
    if session is None:
        raise RuntimeError('The ADK conversation disappeared during its activation')
    await store.append_event(session, Event(invocation_id=invocation_id, author='user',
                                            content=types.Content(role='user', parts=parts)))

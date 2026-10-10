"""ADK-owned Executive conversations and the official LiteLLM model route.

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
import sys
from contextvars import ContextVar

# LiteLLM must never fetch a remote cost map at import (owner decision 2026-10-09).
os.environ.setdefault('LITELLM_LOCAL_MODEL_COST_MAP', 'True')

from google.adk.events import Event  # noqa: E402
from google.genai import types  # noqa: E402

from ..native import (  # noqa: E402
    conversation_text, measure_view, message_producer, prefill_messages as native_prefill_messages,
    rebase_window as native_rebase_window, reconcile_outcomes,
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
_models: dict[tuple, object] = {}
# The current model step's metrics, set by the plugin before each request; the
# admission client records the provider's acknowledged input count there.
ADMISSION: ContextVar[dict | None] = ContextVar('obsidience_admission', default=None)


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
                    # The preflight already projected to an exact count; a refusal
                    # here is a counting mismatch, so nothing is retried.
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


async def start() -> None:
    """Open the conversation store and load LiteLLM once, before the API accepts turns."""
    global _service
    if _service is not None:
        return
    from google.adk.sessions.sqlite_session_service import SqliteSessionService
    from ...config import CONFIG
    _service = SqliteSessionService(str(CONFIG.runtime_dir / STORE))
    await asyncio.to_thread(_import_litellm)


async def stop() -> None:
    global _service
    _service = None
    _views.clear()
    _models.clear()
    if 'litellm' in sys.modules:
        await sys.modules['litellm'].close_litellm_async_clients()


async def close(conversation_id: str) -> None:
    """New Conversation: drop the cached view; the store keeps the rotated log."""
    _views.pop(conversation_id, None)


def model(spec, effort: str):
    """The Executive's LiteLlm route for one model and reasoning effort.

    Carries what the native transport sends: the served model id (so tool
    results keep the template's native ``tool`` role), output cap,
    temperature, single Tool call per step, template thinking switch and the
    engine's exact input ceiling, whose acknowledgement every response must carry.
    """
    key = (spec.id, spec.base_url, effort)
    if key not in _models:
        from google.adk.models.lite_llm import LiteLlm
        from ...config import CONFIG
        from ...models import llm, runtime as model_runtime
        from ...models.context import PROMPT_SAFETY_TOKENS
        token = model_runtime.model_auth_headers().get('Authorization', '').removeprefix('Bearer ').strip()
        extra = {'chat_template_kwargs': {'enable_thinking': effort != 'none'}}
        if effort != 'none':
            extra.update(reasoning_format='auto', reasoning_budget_tokens=spec.reasoning_budgets[effort])
        if spec.supports_input_token_limit:
            extra['input_token_limit'] = spec.context_tokens - spec.max_output_tokens - PROMPT_SAFETY_TOKENS
        _models[key] = LiteLlm(
            model='openai/' + spec.id, api_base=spec.base_url, api_key=token or 'none',
            max_tokens=spec.max_output_tokens, temperature=CONFIG.llm_temperature,
            parallel_tool_calls=False, timeout=llm.CHAT_TIMEOUT_SECONDS, extra_body=extra,
            **({'llm_client': _admission_client()} if 'input_token_limit' in extra else {}))
    return _models[key]


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
    session = await service().get_session(app_name=APP, user_id=USER, session_id=conversation_id)
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
    session = await store.get_session(app_name=APP, user_id=USER, session_id=conversation_id)
    if session is None:
        session = await store.create_session(app_name=APP, user_id=USER, session_id=conversation_id)
    if turn_id is None:
        return session
    from ...knowledge.index import INDEX
    current = INDEX.conversation_turn(turn_id)
    if not current or current['conversation_id'] != conversation_id:
        raise ValueError('Native conversation requires an exact admitted owner turn')
    turns = INDEX.conversation_turns(conversation_id, before_sequence=current['sequence'])
    known = known_turns(session)
    replies = {turn['reply_to']: turn for turn in turns if turn['role'] == 'assistant'}
    for turn in turns:
        if turn['role'] != 'user' or turn['id'] in known:
            continue
        await store.append_event(session, Event(invocation_id='seed', author='user', content=types.Content(
            role='user', parts=[part(turn['text'], 'user', id=turn['id'])])))
        if (reply := replies.get(turn['id'])) is not None:
            await store.append_event(session, Event(invocation_id='seed', author=AGENT, content=types.Content(
                role='model', parts=[types.Part(text=reply['text'])])))
    return session


async def close_interrupted_calls(conversation_id: str, invocation_id: str) -> None:
    """Record every unanswered native call as outcome unknown; it is never replayed."""
    from ..capability_core import INTERRUPTED, observation_text
    store = service()
    session = await store.get_session(app_name=APP, user_id=USER, session_id=conversation_id)
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
        await store.append_event(session, Event(invocation_id=invocation_id, author=AGENT,
                                                content=types.Content(role='user', parts=parts)))


async def append(conversation_id: str, invocation_id: str, parts: list[types.Part]) -> None:
    """Append one controller-owned user event (settlement or command records)."""
    from google.adk.sessions.base_session_service import GetSessionConfig
    store = service()
    session = await store.get_session(app_name=APP, user_id=USER, session_id=conversation_id,
                                      config=GetSessionConfig(num_recent_events=1))
    if session is None:
        raise RuntimeError('The ADK conversation disappeared during its activation')
    await store.append_event(session, Event(invocation_id=invocation_id, author='user',
                                            content=types.Content(role='user', parts=parts)))

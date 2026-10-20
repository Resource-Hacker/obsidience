"""The ADK model route: one model per model, effort and slot, and its admission guard.

``route`` selects ``adk_model_client`` (``local`` default, ``litellm`` rollback),
``engine_guard`` reports the exact ``input_token_limit`` its requests carry,
``admitted_input_tokens``/``ADMISSION`` verify and record llama.cpp's acknowledgement,
and ``owned`` gives a caller a copy whose request stream it closes itself.
``start``/``stop`` load and close LiteLLM only for its route. The conversation
store is ``sessions.py``.

The local route is llama-server's chat stream over the provider pool.

``LocalLlm`` replaces ADK's ``LiteLlm`` route (``adk_model_client = "local"``).
It sends the request ADK's LiteLlm route sends for the same ``LlmRequest``
(the same messages, Tools, ``tool_choice``, output cap, temperature and engine
extras) through the API-lifetime httpx pool (``models/llm.py``), and yields the
``LlmResponse`` sequence that route yields: one partial per reasoning, text or
Tool-call delta, then the aggregated final response with usage after
``[DONE]``. Each SSE event is decoded once, with no LiteLLM, OpenAI SDK or
pydantic chunk objects in between.

Deliberate differences from the LiteLLM route: a stream without a finish
reason and ``[DONE]`` fails closed instead of being accepted as complete;
nothing is retried (LiteLLM's OpenAI client resent a request twice after an
HTTP 5xx or connection error); JSON in reply text is never turned into a Tool
call; usage carries only what the engine reports (LiteLLM tokenized reasoning
text locally to fill ``thoughts_token_count``); Tool schemas go out verbatim
(LiteLlm lowercased their ``type`` names, a no-op for the Harness schemas);
an input-token refusal that counted more than the limit raises
``ContextBudgetExceeded`` (LiteLLM's error text lacked the count). Failures
raise ``ValueError``, ``TimeoutError`` or httpx's network errors, not LiteLLM's
exception classes.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import sys
from contextvars import ContextVar
from typing import Any, AsyncGenerator

# LiteLLM must never fetch a remote cost map at import (owner decision 2026-10-09);
# the bundled map suffices and the Harness makes no network call of its own here.
os.environ.setdefault('LITELLM_LOCAL_MODEL_COST_MAP', 'True')

import httpx  # noqa: E402
from google.adk.models import LlmCapabilities  # noqa: E402
from google.adk.models.base_llm import BaseLlm  # noqa: E402
from google.adk.models.interactions_utils import extract_system_instruction  # noqa: E402
from google.adk.models.llm_request import LlmRequest  # noqa: E402
from google.adk.models.llm_response import LlmResponse  # noqa: E402
from google.adk.utils.streaming_utils import _JsonPathTracker  # noqa: E402
from google.genai import types  # noqa: E402
from httpx_sse import aconnect_sse  # noqa: E402
from pydantic import Field, PrivateAttr  # noqa: E402

from ...models import llm  # noqa: E402

logger = logging.getLogger(__name__)

_routes: dict[tuple, BaseLlm] = {}
# The current model step's metrics, set by the plugin before each request; the
# admission client records the provider's acknowledged input count there.
ADMISSION: ContextVar[dict | None] = ContextVar('obsidience_admission', default=None)

_FINISH = {'length': types.FinishReason.MAX_TOKENS, 'stop': types.FinishReason.STOP,
           'tool_calls': types.FinishReason.STOP, 'function_call': types.FinishReason.STOP,
           'content_filter': types.FinishReason.SAFETY}
_MISSING_TOOL_RESULT = ('Error: Missing tool result (tool execution may have been interrupted '
                        'before a response was recorded).')
_FALLBACK_USER_TEXT = 'Handle the requests as specified in the System Instruction.'
_UNSUPPORTED_CONFIG = ('response_schema', 'response_json_schema', 'max_output_tokens', 'top_p', 'top_k',
                       'seed', 'stop_sequences', 'presence_penalty', 'frequency_penalty', 'temperature')


def _json(value) -> str:
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError, OverflowError, RecursionError):
        return str(value)


def _content(parts: list[types.Part]):
    """One message's content: a lone text as a string, otherwise text and image objects."""
    if len(parts) == 1 and parts[0].text:
        return parts[0].text
    rows = []
    for part in parts:
        if part.text:
            rows.append({'type': 'text', 'text': part.text})
        elif part.inline_data and part.inline_data.data and part.inline_data.mime_type:
            mime = part.inline_data.mime_type.split(';', 1)[0].strip().lower()
            if not mime.startswith('image/'):
                raise ValueError(f'The local model route does not send {mime} content')
            rows.append({'type': 'image_url', 'image_url': {
                'url': f'data:{mime};base64,{base64.b64encode(part.inline_data.data).decode()}'}})
        elif part.file_data or part.inline_data or part.executable_code or part.code_execution_result:
            raise ValueError('The local model route sends only text, image, call and result parts')
    return rows


def _messages(content: types.Content) -> list[dict]:
    """One ADK content as chat messages, as ADK's LiteLlm route converts it."""
    parts = content.parts or []
    if not parts:
        return []
    tools, rest = [], []
    for part in parts:
        if part.function_response is not None:
            response = part.function_response
            if response.parts:
                raise ValueError('The local model route does not send media inside Tool results')
            tools.append({'role': 'tool', 'tool_call_id': response.id or '',
                          'content': response.response if isinstance(response.response, str)
                          else _json(response.response)})
        else:
            rest.append(part)
    if tools:
        return tools + (_messages(types.Content(role=content.role, parts=rest)) if rest else [])
    if content.role not in {'model', 'assistant'}:
        return [{'role': 'user', 'content': _content([part for part in parts if not part.thought]) or None}]
    calls, reasoning, text_parts = [], [], []
    for part in parts:
        if part.function_call is not None:
            if not part.function_call.name:
                raise ValueError('Native Tool calls require a name')
            if part.thought_signature:
                raise ValueError('The local model route does not send thought signatures')
            calls.append({'type': 'function', 'id': part.function_call.id or '', 'function': {
                'name': part.function_call.name, 'arguments': _json(part.function_call.args)}})
        elif part.thought:
            reasoning.append(part.text or '')
        else:
            text_parts.append(part)
    text = _content(text_parts) if text_parts else None
    if text and isinstance(text, list) and text[0]['type'] == 'text':
        text = text[0]['text']  # LiteLlm's single-text rule, kept for identical requests.
    message = {'role': 'assistant', 'content': text, 'tool_calls': calls or None,
               'reasoning_content': ''.join(reasoning) or None}
    return [{key: value for key, value in message.items() if value is not None}]


def _with_tool_results(messages: list[dict]) -> list[dict]:
    """Answer every call before the next non-tool message (ADK LiteLlm's recovery rule)."""
    healed, pending = [], []
    for message in messages:
        if pending and message['role'] != 'tool':
            logger.warning('Missing tool results for tool_call_id(s): %s', pending)
            healed += [{'role': 'tool', 'tool_call_id': ident, 'content': _MISSING_TOOL_RESULT} for ident in pending]
            pending = []
        if message['role'] == 'assistant':
            pending = [call['id'] for call in message.get('tool_calls') or [] if call.get('id')]
        elif message['role'] == 'tool' and message.get('tool_call_id') in pending:
            pending.remove(message['tool_call_id'])
        healed.append(message)
    if pending:
        logger.warning('Missing tool results for tool_call_id(s): %s', pending)
        healed += [{'role': 'tool', 'tool_call_id': ident, 'content': _MISSING_TOOL_RESULT} for ident in pending]
    return healed


def _tool(declaration: types.FunctionDeclaration) -> dict:
    """One Tool with its schema verbatim: the bytes the standby warms and fast lane send.

    ADK's LiteLlm route deep-copied each schema and lowercased its ``type``
    names on every step (a no-op for these lowercase schemas, ~2 ms per step).
    """
    if declaration.response or declaration.response_json_schema:
        raise ValueError('The local model route does not render Tool response schemas')
    if declaration.parameters is not None and not declaration.parameters_json_schema:
        raise ValueError('The local model route needs JSON-schema Tool parameters')
    return {'type': 'function', 'function': {
        'name': declaration.name, 'description': declaration.description or '',
        'parameters': declaration.parameters_json_schema or {'type': 'object', 'properties': {}}}}


def _usage(usage: dict) -> types.GenerateContentResponseUsageMetadata:
    def count(value):
        return value if isinstance(value, int) and not isinstance(value, bool) else 0
    prompt = usage.get('prompt_tokens_details')
    reasoning = count((usage.get('completion_tokens_details') or {}).get('reasoning_tokens'))
    return types.GenerateContentResponseUsageMetadata(
        prompt_token_count=count(usage.get('prompt_tokens')),
        candidates_token_count=count(usage.get('completion_tokens')),
        total_token_count=count(usage.get('total_tokens')),
        cached_content_token_count=count(prompt.get('cached_tokens')) if isinstance(prompt, dict) else 0,
        thoughts_token_count=reasoning or None)


def _stamp(response: LlmResponse, finish: str | None) -> LlmResponse:
    """The provider's finish reason on a final response (ADK LiteLlm's precedence rules)."""
    reason = _FINISH.get(str(finish).lower(), types.FinishReason.OTHER) if finish else None
    malformed = response.finish_reason == types.FinishReason.MALFORMED_FUNCTION_CALL
    if malformed and reason in (None, types.FinishReason.STOP, types.FinishReason.OTHER):
        return response
    detail = response.error_message if malformed else None
    response.finish_reason = reason
    if reason is None or reason == types.FinishReason.STOP:
        response.error_code = response.error_message = None
        return response
    response.error_code = reason
    response.error_message = ('Maximum tokens reached' if reason == types.FinishReason.MAX_TOKENS
                              else f'Finished with {reason.name}') + (f'. {detail}' if detail else '')
    return response


class ChatStream:
    """One opened llama-server chat stream; ``aclose`` drops its connection at once."""

    def __init__(self, context, source):
        self._context, self._source = context, source
        self._response_headers = source.response.headers  # admitted_input_tokens reads these

    def events(self):
        return self._source.aiter_sse()

    async def aclose(self) -> None:
        context, self._context = self._context, None
        if context is not None:
            await context.__aexit__(None, None, None)


class LocalModelClient:
    """Opens the stream and verifies llama.cpp's exact input-token admission before any token."""

    async def acompletion(self, *, client: httpx.AsyncClient, url: str, body: dict, model: str) -> ChatStream:
        context = aconnect_sse(client, 'POST', url, json=body)
        source = await context.__aenter__()
        stream = ChatStream(context, source)
        limit = body.get('input_token_limit')
        try:
            response = source.response
            if response.status_code != 200:
                text = (await response.aread()).decode(errors='replace')
                if response.status_code == 400 and limit is not None and 'input_token_limit' in text:
                    # Either the request had nothing projectable and skipped the
                    # duplicate client count, or a projected count mismatched.
                    # Nothing is retried; nothing was generated.
                    try:
                        counted = json.loads(text).get('error', {}).get('input_tokens')
                    except (ValueError, AttributeError):
                        counted = None
                    if isinstance(counted, int) and counted > limit:
                        from ...models.context import ContextBudgetExceeded, PayloadCount
                        raise ContextBudgetExceeded(PayloadCount(counted), limit)
                    raise ValueError(f'The model server refused this request at its exact input-token '
                                     f'guard ({limit} tokens); nothing was generated')
                raise ValueError(f'{model} returned HTTP {response.status_code}: {text[:300]}')
            if limit is not None:
                count = admitted_input_tokens(stream, limit)
                if (metrics := ADMISSION.get()) is not None:
                    metrics.update(admitted_input_tokens=count, input_token_guard='acknowledged')
        except BaseException:
            await stream.aclose()
            raise
        return stream


class LocalLlm(BaseLlm):
    """ADK model over llama-server's OpenAI-compatible chat stream (see module docstring)."""

    base_url: str
    llm_client: Any = Field(default_factory=LocalModelClient, exclude=True)
    # The fixed request arguments under LiteLlm's names; speech admission and
    # engine_guard read max_tokens and extra_body.input_token_limit here.
    _additional_args: dict = PrivateAttr(default_factory=dict)

    def __init__(self, model: str, *, base_url: str, **kwargs: Any) -> None:
        client = kwargs.pop('llm_client', None)
        super().__init__(model=model, base_url=base_url, **({'llm_client': client} if client else {}))
        self._additional_args = dict(kwargs)

    @property
    def capabilities(self) -> LlmCapabilities:
        return LlmCapabilities(output_schema_and_tools=False)

    def request_body(self, llm_request: LlmRequest) -> dict:
        """The chat request ADK's LiteLlm route sends for this ``LlmRequest`` (mutates it as LiteLlm does)."""
        self._maybe_append_user_content(llm_request)
        for content in reversed(llm_request.contents):
            if content.role == 'user':
                parts = content.parts or []
                if not any(part.text or part.inline_data and part.inline_data.data
                           or part.file_data and part.file_data.file_uri or part.function_response
                           for part in parts):
                    content.parts = parts + [types.Part.from_text(text=_FALLBACK_USER_TEXT)]
                break
        else:
            llm_request.contents.append(types.Content(role='user', parts=[types.Part.from_text(text=_FALLBACK_USER_TEXT)]))
        config = llm_request.config or types.GenerateContentConfig()
        if any(getattr(config, name, None) is not None for name in _UNSUPPORTED_CONFIG) or (
                config.http_options and config.http_options.model_dump(exclude_none=True)):
            raise ValueError('The local model route takes generation settings only from its construction')
        messages = [message for content in llm_request.contents for message in _messages(content)]
        if system := extract_system_instruction(config):
            messages.insert(0, {'role': 'system', 'content': system})
        tools = []
        for tool in config.tools or []:
            if not isinstance(tool, types.Tool):
                continue
            if not tool.function_declarations:
                raise ValueError('The local model route sends only function declarations')
            tools += [_tool(declaration) for declaration in tool.function_declarations]
        choice = None
        mode = (config.tool_config.function_calling_config.mode
                if config.tool_config and config.tool_config.function_calling_config else None)
        if tools and mode == types.FunctionCallingConfigMode.ANY:
            choice = 'required'
        elif tools and mode == types.FunctionCallingConfigMode.NONE:
            choice = 'none'
        args = self._additional_args
        body = {'messages': _with_tool_results(messages), 'model': llm_request.model or self.model}
        for key in ('max_tokens', 'parallel_tool_calls'):
            if key in args:
                body[key] = args[key]
        body.update(stream=True, stream_options={'include_usage': True})
        if 'temperature' in args:
            body['temperature'] = args['temperature']
        if choice is not None:
            body['tool_choice'] = choice
        if tools:
            body['tools'] = tools
        body.update(args.get('extra_body') or {})
        return body

    async def generate_content_async(self, llm_request: LlmRequest, stream: bool = False
                                     ) -> AsyncGenerator[LlmResponse, None]:
        if not stream:
            raise ValueError('The local model route streams every model step')
        body = self.request_body(llm_request)
        model = body['model']
        text: list[str] = []
        thoughts: list[types.Part] = []
        calls: dict[int, dict] = {}
        usage = finish = last = final_text = final_calls = None
        done = logged = False
        try:
            async with llm.provider_client() as client:
                source = await self.llm_client.acompletion(
                    client=client, url=f'{self.base_url}/chat/completions', body=body, model=model)
                try:
                    async for event in source.events():
                        if event.data == '[DONE]':
                            done = True
                            break
                        try:
                            data = json.loads(event.data)
                        except ValueError:
                            raise ValueError(f'{model} returned a non-JSON completion event') from None
                        if not isinstance(data, dict):
                            raise ValueError(f'{model} returned an invalid completion event')
                        if 'error' in data:
                            error = data['error']
                            message = error.get('message') if isinstance(error, dict) else error
                            raise ValueError(f'{model} failed mid-stream: {str(message)[:300]}')
                        choices = data.get('choices') or []
                        choice = next((row for row in choices if not row.get('index')), None)
                        if not logged and (len(choices) > 1 or any(row.get('index') for row in choices)):
                            logged = True
                            logger.error('Multiple choices found in streaming response but only the first one will be used.')
                        reason, signal = None, False
                        if choice is not None:
                            reason = choice.get('finish_reason')
                            delta = choice.get('delta') or {}
                            value = delta.get('reasoning_content')
                            value = delta.get('reasoning') if value is None else value
                            signal = bool(value or delta.get('content') or delta.get('tool_calls'))
                            if isinstance(value, str) and value:
                                part = types.Part(text=value, thought=True)
                                thoughts.append(part)
                                yield LlmResponse(content=types.Content(role='model', parts=[part]),
                                                  partial=True, model_version=model)
                            content = delta.get('content')
                            if isinstance(content, str) and content:
                                text.append(content)
                                yield LlmResponse(content=types.Content(role='model', parts=[types.Part.from_text(
                                    text=content)]), partial=True, model_version=model)
                            for position, call in enumerate(delta.get('tool_calls') or []):
                                function = call.get('function') or {}
                                if call.get('type', 'function') != 'function' or not function:
                                    continue
                                name, arguments = function.get('name'), function.get('arguments')
                                if not name and not arguments:
                                    continue
                                row = calls.setdefault(call.get('index', position),
                                                       {'name': '', 'args': [], 'id': None, 'tracker': None})
                                row['name'] += name or ''
                                row['id'] = call.get('id') or row['id'] or str(call.get('index', position))
                                partial_args = None
                                if arguments:
                                    row['args'].append(arguments)
                                    row['tracker'] = row['tracker'] or _JsonPathTracker()
                                    partial_args = row['tracker'].handle_chunk(arguments)
                                yield LlmResponse(content=types.Content(role='model', parts=[types.Part(
                                    function_call=types.FunctionCall(
                                        id=row['id'], name=row['name'] or None,
                                        partial_args=partial_args or None, will_continue=True))]),
                                    partial=True, model_version=model)
                            if reason:
                                finish = last = reason
                        if isinstance(data.get('usage'), dict):
                            usage = _usage(data['usage'])
                        # LiteLlm's segment rules; the engine sends one finish
                        # reason, on an empty final delta, so one segment.
                        if calls and (reason in ('tool_calls', 'length') or reason == 'stop' and not signal):
                            final_calls = self._final(model, text, thoughts, calls, reason)
                            text, thoughts, calls, last = [], [], {}, None
                        elif (text or thoughts) and (reason == 'length' or reason == 'stop' and not signal):
                            final_text = self._final(model, text, thoughts, None, reason)
                            text, thoughts, last = [], [], None
                finally:
                    await source.aclose()
        except httpx.TimeoutException:
            raise TimeoutError(f'{model} generation timed out after {llm.CHAT_TIMEOUT_SECONDS:g} seconds '
                               'without data; no complete response was returned') from None
        if not done or not finish:
            raise ValueError(f'{model} completion stream ended before a complete response')
        if calls and final_calls is None:
            final_calls = self._final(model, text, thoughts, calls, last or 'tool_calls')
        elif (text or thoughts) and final_text is None:
            final_text = self._final(model, text, thoughts, None, last or 'stop')
        elif final_text is None and final_calls is None:
            final_text = self._final(model, [], [], None, last or 'stop')
        if final_text is not None:
            if usage is not None:
                final_text.usage_metadata, usage = usage, None
            yield final_text
        if final_calls is not None:
            if usage is not None:
                final_calls.usage_metadata = usage
            yield final_calls

    @staticmethod
    def _final(model: str, text: list[str], thoughts: list[types.Part], calls: dict | None,
               finish: str) -> LlmResponse:
        """The aggregated response for the stream so far (ADK LiteLlm's finalizers)."""
        parts = [types.Part(text=''.join(part.text for part in thoughts), thought=True)] if thoughts else []
        if joined := ''.join(text):
            parts.append(types.Part.from_text(text=joined))
        malformed, truncated = [], False
        for row in (calls or {}).values():
            arguments = ''.join(row['args'])
            try:
                args = json.loads(arguments) if arguments else {}
            except ValueError:
                truncated = True
                continue
            if not isinstance(args, dict):
                malformed.append(row['name'] or '<unnamed>')
                continue
            parts.append(types.Part(function_call=types.FunctionCall(id=row['id'], name=row['name'], args=args)))
        if truncated:
            # A truncated call is never dispatched; its text and other calls go with it.
            if finish == 'length':
                return LlmResponse(error_code=types.FinishReason.MAX_TOKENS, finish_reason=types.FinishReason.MAX_TOKENS,
                                   error_message=('Tool call arguments were truncated while streaming and could not be '
                                                  'parsed as valid JSON. Increase `max_output_tokens` and retry.'),
                                   model_version=model)
            return LlmResponse(error_code=types.FinishReason.MALFORMED_FUNCTION_CALL,
                               finish_reason=types.FinishReason.MALFORMED_FUNCTION_CALL,
                               error_message=("A tool call's arguments could not be parsed as valid JSON. "
                                              'The stream carrying them most likely ended early.'),
                               model_version=model)
        response = LlmResponse(content=types.Content(role='model', parts=parts), partial=False, model_version=model)
        if malformed:
            logger.warning('Discarding tool calls with non-object arguments: %s', ', '.join(malformed))
            response.finish_reason = response.error_code = types.FinishReason.MALFORMED_FUNCTION_CALL
            response.error_message = ('Arguments for the following function calls were not a valid JSON object: '
                                      + ', '.join(malformed))
        return _stamp(response, finish)


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


def _import_litellm() -> None:
    from google.adk.models.lite_llm import _ensure_litellm_imported
    _ensure_litellm_imported()
    import litellm
    litellm.suppress_debug_info = True  # Request bodies and keys never reach logs.
    litellm.telemetry = False


def model_client() -> str:
    """``adk_model_client`` in obsidience.toml: ``local`` (default) or ``litellm`` (rollback)."""
    from ...config import CONFIG
    value = CONFIG.extras.get('adk_model_client', 'local')
    if value not in {'local', 'litellm'}:
        raise ValueError('adk_model_client must be "local" or "litellm"')
    return value


def route(spec, effort: str, slot: int | None = None):
    """The ADK model route for one model, reasoning effort and caller slot.

    Carries what the native transport sends: the served model id (so tool
    results keep the template's native ``tool`` role), output cap,
    temperature, single Tool call per step, template thinking switch, the
    caller's llama.cpp slot (``runtime.slot_fields``; the Executive's unless
    named) and the engine's exact input ceiling, whose acknowledgement every
    response must carry.
    ``local`` streams through the API's httpx pool (``LocalLlm``); ``litellm``
    is ADK's LiteLlm route. Both expose the same ``_additional_args``.
    """
    from ...models import runtime as model_runtime
    pinned = model_runtime.slot_fields(spec, model_runtime.EXECUTIVE_SLOT if slot is None else slot)
    kind = model_client()
    key = (spec.id, spec.base_url, effort, kind, pinned.get('id_slot'))
    if key not in _routes:
        from ...config import CONFIG
        from ...models import llm
        from ...models.context import PROMPT_SAFETY_TOKENS
        extra = {'chat_template_kwargs': {'enable_thinking': effort != 'none'}, **pinned}
        if effort != 'none':
            extra.update(reasoning_format='auto', reasoning_budget_tokens=spec.reasoning_budgets[effort])
        if spec.supports_input_token_limit:
            extra['input_token_limit'] = spec.context_tokens - spec.max_output_tokens - PROMPT_SAFETY_TOKENS
        args = dict(max_tokens=spec.max_output_tokens, temperature=CONFIG.llm_temperature,
                    parallel_tool_calls=False, timeout=llm.CHAT_TIMEOUT_SECONDS, extra_body=extra)
        if kind == 'local':
            _routes[key] = LocalLlm(spec.id, base_url=spec.base_url, **args)
        else:
            from google.adk.models.lite_llm import LiteLlm
            token = model_runtime.model_auth_headers().get('Authorization', '').removeprefix('Bearer ').strip()
            _routes[key] = LiteLlm(
                model='openai/' + spec.id, api_base=spec.base_url, api_key=token or 'none', **args,
                **({'llm_client': _admission_client()} if 'input_token_limit' in extra else {}))
    return _routes[key]


def engine_guard(spec, effort: str) -> int | None:
    """The exact input_token_limit this route's requests carry, or None without the engine guard."""
    if not spec.supports_input_token_limit:
        return None
    return (route(spec, effort)._additional_args.get('extra_body') or {}).get('input_token_limit')


def owned(model: BaseLlm) -> tuple[BaseLlm, Any]:
    """A copy of ``model`` whose request stream the caller closes with ``await owner.close()``.

    ADK's generator alone does not close the HTTP stream it reads from.
    """
    from google.adk.models.lite_llm import LiteLLMClient

    class StreamOwner(LiteLLMClient):
        def __init__(self, delegate):
            self.delegate, self.response = delegate, None

        async def acompletion(self, **kwargs):
            self.response = await self.delegate.acompletion(**kwargs)
            return self.response

        async def close(self):
            response, self.response = self.response, None
            if response is not None and hasattr(response, 'aclose'):
                await response.aclose()

    owner = StreamOwner(model.llm_client)
    return model.model_copy(update={'llm_client': owner}), owner


async def start() -> None:
    """Load LiteLLM once, only for its route, before the API accepts turns."""
    if model_client() == 'litellm':
        await asyncio.to_thread(_import_litellm)


async def stop() -> None:
    _routes.clear()
    if 'litellm' in sys.modules:
        await sys.modules['litellm'].close_litellm_async_clients()

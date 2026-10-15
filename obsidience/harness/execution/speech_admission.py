"""One buffered Executive first step, admitted only after semantic endpointing.

This module has no Tool dispatch or conversation/memory write port. Its Python
carry is single-use; the ordinary ADK plugin owns completion and native Tools.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from contextlib import aclosing
from copy import deepcopy
from dataclasses import dataclass, field

from google.adk.models.llm_request import LlmRequest
from google.adk.models.lite_llm import LiteLLMClient
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from . import native
from .adk import sessions
from .adk.plugin import request_contents
from .executor import activation_messages, compile_activation
from .native_turn import memory_message, recall_query, recall_reply, tool_schemas
from ..conversation.evidence import historical_evidence
from ..conversation.selection import admit_executive
from ..knowledge.scope import revision as scope_revision
from ..models import llm, runtime as model_runtime
from ..models.context import PROMPT_SAFETY_TOKENS, TaskContext

PREPARE_TIMEOUT_SECONDS = 30
SEMANTIC_PROTOCOL = """## Spoken turn admission (this first response only)
Judge the current speech-recognition text in the full conversation context.
If the owner has expressed a complete request, question, answer or acknowledgement,
begin visible response text with C on its own line, then produce your actual
normal response or native Tool call in this SAME response. C must precede a native
Tool call even when no spoken reply is needed. Do not merely classify then stop.
If the owner appears mid-thought or the utterance is cut off, emit ONLY I on its
own line for a short continuation pause, or ONLY W on its own line when a longer
thinking pause is appropriate. Emit no Tool calls or reply for I or W. A brief
contextually complete answer (such as yes, no or a name) is complete. Grammar,
punctuation, length and a pause alone do not determine completeness. Never
perform an action or infer a missing target while the request remains unfinished.
These C/I/W control lines are private transport markers, never spoken content."""


def _admission_messages(messages: list[dict], text: str) -> list[dict]:
    """Keep the one-response output contract adjacent to the current transcript.

    The normal cached voice instructions demand an immediate plain-text answer;
    a distant system-only marker reminder is insufficient for the local model.
    This private request-only envelope is neither accepted owner text nor a
    second question. It is retained in the first decision's exact provenance.
    It is the only place the admission protocol appears: the system message,
    Tool declarations and history stay byte-identical to ordinary ADK steps, so
    the step after a Tool result reuses the engine's cached prefix up to here.
    """
    return [*messages, {'role': 'user', 'content': (
        'PRIVATE SPEECH TRANSPORT CONTROL FOR THE CURRENT RESPONSE.\n'
        + SEMANTIC_PROTOCOL + '\n\n'
        'The current owner transcript is: ' + json.dumps(text, ensure_ascii=False) + '\n'
        'Use the full preceding conversation to decide whether that transcript is complete or still unfinished. '
        'Your FIRST visible output MUST be exactly one control letter on its own line: C, I, or W. '
        'For a complete turn output C followed by a newline and your ACTUAL normal answer or native Tool call '
        'in this same response. This first line is mandatory even for a short answer or a native Tool call. '
        'For an unfinished turn output ONLY I for a short continuation pause or ONLY W for a longer thinking pause; '
        'give no answer, clarification question or native Tool call. '
        'Do not quote or explain this control. Begin with the control letter now.'
    )}]


class SpeechPreparationError(ValueError):
    """A buffered response cannot be admitted; no model retry or effect follows."""


class _ControlPrefix:
    """Observe chronology before LiteLLM groups text and calls into final parts."""

    def __init__(self):
        self.prefix = ''

    def observe(self, response: LlmResponse) -> None:
        if not response.partial or response.content is None:
            return
        for part in response.content.parts:
            if part.thought:
                continue
            if part.text is not None and len(self.prefix) < 2:
                self.prefix += part.text[:2 - len(self.prefix)]
                if (self.prefix and self.prefix[0] not in {'C', 'I', 'W'}
                        or len(self.prefix) == 2 and self.prefix[1] != '\n'):
                    raise SpeechPreparationError('Speech admission began without its exact control line')
            if part.function_call is not None and self.prefix != 'C\n':
                raise SpeechPreparationError('Native Tool streamed before a complete-turn control line')


class _ResponseOwner(LiteLLMClient):
    """Own this request's HTTP stream; ADK's generator alone does not close it."""

    def __init__(self, delegate):
        self.delegate, self.response = delegate, None

    async def acompletion(self, **kwargs):
        self.response = await self.delegate.acompletion(**kwargs)
        return self.response

    async def close(self):
        response, self.response = self.response, None
        if response is not None and hasattr(response, 'aclose'):
            await response.aclose()


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':'), default=str).encode()).hexdigest()


def _model_binding(spec, effort: str) -> str:
    return _digest({key: getattr(spec, key, None) for key in (
        'id', 'base_url', 'runtime', 'context_tokens', 'max_output_tokens',
        'supports_input_token_limit', 'reasoning_budgets')} | {'effort': effort})


def _tip(conversation, conversation_id: str, *, before_sequence: int | None = None) -> tuple:
    rows = conversation.index.conversation_turns(
        conversation_id, before_sequence=before_sequence, limit=80)
    return tuple((row['id'], row['sequence'], row['role'], row.get('state'),
                  _digest(row['text'])) for row in rows)


def _history(view: dict | None, *, before_turn: str | None = None) -> str | None:
    if view is None:
        return None
    rows = []
    for row in view['messages']:
        if before_turn and row.get('id') == before_turn:
            break
        producer = native.message_producer(row)
        if row['role'] == 'system' or producer in {
                'obsidience.context', 'obsidience.memory', 'obsidience.expired-context'}:
            continue
        rows.append(row)
    return _digest(rows)


def _sanitize(responses: list[LlmResponse]) -> tuple[str, LlmResponse | None]:
    """Parse the buffered visible prefix across parts; drop all private reasoning."""
    if not responses:
        raise SpeechPreparationError('Speech admission returned no final response')
    if any(response.error_code or response.interrupted
           or response.finish_reason not in {None, types.FinishReason.STOP}
           for response in responses):
        raise SpeechPreparationError('Speech admission did not finish cleanly')
    parts = [part.model_copy(deep=True) for response in responses
             for part in (response.content.parts if response.content else []) if not part.thought]
    text = ''.join(part.text for part in parts if part.text is not None)
    # A single control line is accepted at EOF for an incomplete turn. Complete
    # replies require the line boundary before their answer or native call.
    marker, separator, remainder = text.partition('\n')
    if marker not in {'C', 'I', 'W'} or (marker == 'C' and not separator):
        raise SpeechPreparationError('Speech admission omitted its exact control line')
    calls = [part.function_call for part in parts if part.function_call is not None]
    if marker != 'C':
        if calls or remainder.strip():
            raise SpeechPreparationError('An unfinished speech response contained content or native Tools')
        return ('incomplete_short' if marker == 'I' else 'incomplete_long'), None
    if not remainder.strip() and not calls:
        raise SpeechPreparationError('Complete speech response contained no answer or native Tool')
    remove = 2  # C and newline; split text parts never leak the marker.
    kept = []
    for part in parts:
        if part.text is not None:
            value = part.text
            take = min(remove, len(value))
            remove -= take
            value = value[take:]
            if value:
                kept.append(part.model_copy(update={'text': value}))
        else:
            if remove and part.function_call is not None:
                raise SpeechPreparationError('Native Tool preceded the speech admission marker')
            kept.append(part)
    return 'complete', responses[-1].model_copy(update={
        'content': types.Content(role='model', parts=kept), 'partial': False})


@dataclass
class PreparedSpeechTurn:
    decision: str
    text: str
    conversation_id: str
    generation: int
    history: tuple
    anchor: str | None
    native_history: str | None
    model_binding: str
    scope: str
    system: str
    schema_binding: str
    response: LlmResponse | None = field(repr=False)
    wire: list[dict] = field(repr=False)
    context: list[dict] = field(repr=False)
    packet: dict = field(repr=False)
    refs: list[str]
    retrieval_ms: float
    metrics: dict = field(repr=False)
    memory: str = field(repr=False, default='')
    _runtime: object = field(repr=False, default=None)
    _bound_turn: str | None = field(repr=False, default=None)
    _bound_sequence: int | None = field(repr=False, default=None)
    _bound_generation: int | None = field(repr=False, default=None)
    _consumed: bool = field(repr=False, default=False)

    async def validate_submission(self, runtime, text: str) -> None:
        if (self.decision != 'complete' or self.response is None or self._consumed
                or self._bound_turn is not None or self._runtime is not runtime
                or text != self.text or runtime._generation != self.generation
                or runtime._conversation.conversation_id != self.conversation_id
                or _tip(runtime._conversation, self.conversation_id) != self.history
                or native.window_anchor(self.conversation_id) != self.anchor):
            raise SpeechPreparationError('The prepared speech turn is stale or already bound')
        view = await sessions.refresh(self.conversation_id)
        if _history(view) != self.native_history:
            raise SpeechPreparationError('The conversation changed during speech admission')
        await self._validate_contract()
        if (runtime._generation != self.generation
                or runtime._conversation.conversation_id != self.conversation_id
                or _tip(runtime._conversation, self.conversation_id) != self.history
                or native.window_anchor(self.conversation_id) != self.anchor):
            raise SpeechPreparationError('Speech admission changed while validating its contract')

    def bind(self, turn: dict, generation: int) -> None:
        if (self._bound_turn is not None or turn['conversation_id'] != self.conversation_id
                or generation != self.generation + 1):
            raise SpeechPreparationError('Prepared speech can bind exactly once')
        self._bound_turn, self._bound_sequence = str(turn['id']), int(turn['sequence'])
        self._bound_generation = generation

    async def _validate_contract(self) -> None:
        agent, params, _ = admit_executive(self.text, 'voice')
        current = model_runtime.resolve_model(agent.meta.get('model'), agent.ref)
        current_effort = llm.normalize_reasoning_effort(agent.meta.get('reasoning_effort', 'none'))
        if scope_revision(agent) != self.scope or _model_binding(current, current_effort) != self.model_binding:
            raise SpeechPreparationError('The Executive authority or model changed during speech admission')
        params['conversation_id'] = self.conversation_id
        activation = await compile_activation(agent, params=params, interactive=True, emit_activity=False)
        messages = activation_messages(agent, activation, agent_name=agent.title)
        names = activation['spine']['tools']
        if (_digest(messages[0]['content']) != self.system
                or _digest([names, tool_schemas(names)]) != self.schema_binding):
            raise SpeechPreparationError('The Executive prompt or native Tools changed during speech admission')

    async def consume(self, plugin) -> LlmResponse:
        runtime = self._runtime
        params = plugin.ctx.get('params') or {}
        if (self._consumed or self.response is None or self._bound_turn is None
                or params.get('reply_to_turn_id') != self._bound_turn
                or params.get('conversation_id') != self.conversation_id
                or plugin.ctx['objective'] != self.text
                or runtime._generation != self._bound_generation
                or runtime._conversation.conversation_id != self.conversation_id
                or _tip(runtime._conversation, self.conversation_id,
                        before_sequence=self._bound_sequence) != self.history
                or native.window_anchor(self.conversation_id) != self.anchor):
            raise SpeechPreparationError('Prepared speech no longer matches its admitted turn')
        latest = runtime._conversation.history(self.conversation_id, limit=1)
        if not latest or latest[0]['id'] != self._bound_turn:
            raise SpeechPreparationError('Prepared speech was superseded before its first step')
        # Claim once before the first await; even a failed validation cannot
        # return this response to another invocation.
        self._consumed = True
        view = await sessions.refresh(self.conversation_id)
        if self.native_history is not None:
            if _history(view, before_turn=self._bound_turn) != self.native_history:
                raise SpeechPreparationError('Native conversation changed before prepared speech consumption')
        else:
            # New sessions may seed public history, but cannot introduce a
            # separate native activation between preparation and consumption.
            session = await sessions.service().get_session(
                app_name=sessions.APP, user_id=sessions.USER, session_id=self.conversation_id)
            for event in session.events:
                if any(sessions._meta(part).get('id') == self._bound_turn
                       for part in (event.content.parts if event.content else [])):
                    break
                if event.invocation_id != 'seed':
                    raise SpeechPreparationError('A native activation preceded the prepared owner turn')
        # This run compiled its activation fresh just before this step; its
        # system, schemas, model and scope must bind the admitted digests. A
        # further compilation here would only repeat that work on the
        # critical path (validate_submission already recompiled before bind).
        if (_digest(plugin.system) != self.system
                or _digest([plugin.advertised, tool_schemas(plugin.advertised)]) != self.schema_binding
                or _model_binding(plugin.spec, plugin.effort) != self.model_binding
                or plugin.ctx.get('_scope_revision') != self.scope):
            raise SpeechPreparationError('The Executive prompt or native Tools changed during speech admission')
        if (runtime._generation != self._bound_generation
                or runtime._conversation.conversation_id != self.conversation_id
                or native.window_anchor(self.conversation_id) != self.anchor
                or _tip(runtime._conversation, self.conversation_id,
                        before_sequence=self._bound_sequence) != self.history
                or not (latest := runtime._conversation.history(self.conversation_id, limit=1))
                or latest[0]['id'] != self._bound_turn):
            raise SpeechPreparationError('Prepared speech changed while validating its first step')
        response, self.response = self.response, None
        return response


async def prepare(runtime, text: str, response_contract: str) -> PreparedSpeechTurn:
    """Generate the real first response without starting an Agent activation."""
    clean = ' '.join(text.split())
    agent, params, _ = admit_executive(clean, 'voice')
    conversation = runtime._conversation
    conversation_id, generation = conversation.conversation_id, runtime._generation
    history, anchor = _tip(conversation, conversation_id), native.window_anchor(conversation_id)
    view = await sessions.refresh(conversation_id)
    native_history = _history(view)
    spec = model_runtime.resolve_model(agent.meta.get('model'), agent.ref)
    effort = llm.normalize_reasoning_effort(agent.meta.get('reasoning_effort', 'none'))
    params['conversation_id'] = conversation_id
    before_sequence = max((row[1] for row in history), default=0) + 1
    if interruption := runtime._interruption_cue(before_sequence):
        params['speech_interruption'] = interruption
    metrics = {}
    async with asyncio.timeout(PREPARE_TIMEOUT_SECONDS):
        async with model_runtime.lease(spec) as active_spec:
            if _model_binding(active_spec, effort) != _model_binding(spec, effort):
                raise SpeechPreparationError("The model configuration changed while awaiting its lease")
            spec = active_spec
            evidence = historical_evidence(conversation, conversation_id=conversation_id,
                                           before_sequence=before_sequence)
            from ..memory.hindsight import MEMORY
            context_started = time.monotonic()
            recall = asyncio.create_task(MEMORY.recall(
                agent.ref, *recall_query(clean, conversation_id), speculative=True),
                name="obsidience-speech-admission-recall")
            try:
                activation = await compile_activation(
                    agent, params=params, interactive=True, emit_activity=False,
                    conversation_evidence=evidence)
                memory = memory_message(recall_reply(await recall))
            finally:
                if not recall.done():
                    recall.cancel()
                await asyncio.gather(recall, return_exceptions=True)
            metrics['context_recall_ms'] = round((time.monotonic() - context_started) * 1000, 3)
            messages = activation_messages(agent, activation, agent_name=agent.title,
                                           response_contract=response_contract)
            system = _digest(messages[0]['content'])
            compiled_context = deepcopy(messages[1:])
            if view:
                messages = sessions.prefill_messages(conversation_id, messages, clean, memory=memory,
                                                     preparation_prefix=False)
            else:
                # Mirror ADK's read-only seed projection without creating a session.
                seed = {'messages': [{'role': row['role'], 'id': row['id'],
                        'source': {'kind': 'user'} if row['role'] == 'user' else {'provider': 'obsidience'},
                        'content': [{'type': 'text', 'text': row['text']}]}
                        for row in conversation.history(conversation_id, limit=80)]}
                messages = native.prefill_messages(seed, conversation_id, messages, clean,
                                                  memory=memory, preparation_prefix=False)
            names = list(activation['spine']['tools'])
            schemas = tool_schemas(names)
            schema_binding = _digest([names, schemas])
            messages = _admission_messages(messages, clean)
            payload = native.request_payload(messages, spec, effort, schemas)
            async with llm.provider_client() as client:
                started = time.monotonic()
                projection = TaskContext()
                capacity = spec.context_tokens - spec.max_output_tokens - PROMPT_SAFETY_TOKENS
                count = await projection.fit_payload(payload, spec, client, capacity)
                metrics.update(prompt_tokens=count.tokens,
                               preflight_ms=round((time.monotonic() - started) * 1000, 3))
            request = LlmRequest(contents=request_contents(payload['messages'][1:]), config=types.GenerateContentConfig(
                system_instruction=payload['messages'][0]['content'],
                tools=[types.Tool(function_declarations=[types.FunctionDeclaration(
                    name=schema['name'], description=schema['description'],
                    parameters_json_schema=schema['parameters']) for schema in schemas])]))
            responses = []
            prefix = _ControlPrefix()
            started = time.monotonic()
            route = sessions.model(spec, effort)
            # The shared ADK route is cached by identity/endpoint/effort. Reject
            # an old cached ceiling after an in-process model profile change.
            route_args = route._additional_args
            if (route_args.get('max_tokens') != spec.max_output_tokens
                    or (spec.supports_input_token_limit
                        and (route_args.get('extra_body') or {}).get('input_token_limit') != capacity)):
                raise SpeechPreparationError('The cached ADK model route has outdated token settings')
            owner = _ResponseOwner(route.llm_client)
            route = route.model_copy(update={'llm_client': owner})
            token = sessions.ADMISSION.set(metrics)
            try:
                async with aclosing(route.generate_content_async(request, stream=True)) as stream:
                    async for response in stream:
                        prefix.observe(response)
                        if not response.partial:
                            responses.append(response)
                        elif response.content and any(part.text and not part.thought or part.function_call
                                                       for part in response.content.parts):
                            metrics.setdefault('first_public_delta_ms', round((time.monotonic() - started) * 1000, 3))
            finally:
                try:
                    await owner.close()
                finally:
                    sessions.ADMISSION.reset(token)
            metrics['generation_ms'] = round((time.monotonic() - started) * 1000, 3)
            if responses and (usage := next((r.usage_metadata for r in reversed(responses)
                                             if r.usage_metadata is not None), None)) is not None:
                metrics.update(prompt_tokens=usage.prompt_token_count or metrics.get('prompt_tokens', 0),
                               cached_input_tokens=usage.cached_content_token_count or 0,
                               output_tokens=usage.candidates_token_count or 0)
    decision, response = _sanitize(responses)
    prepared = PreparedSpeechTurn(
        decision=decision, text=clean, conversation_id=conversation_id, generation=generation,
        history=history, anchor=anchor, native_history=native_history,
        model_binding=_model_binding(spec, effort), scope=scope_revision(agent), system=system,
        schema_binding=schema_binding, response=response,
        wire=deepcopy(payload['messages']), context=compiled_context,
        packet=deepcopy(activation['activity_packet']), refs=list(activation['refs']),
        retrieval_ms=float(activation['retrieval_ms']), metrics=metrics, memory=memory, _runtime=runtime)
    if (runtime._generation != generation or conversation.conversation_id != conversation_id
            or _tip(conversation, conversation_id) != history
            or native.window_anchor(conversation_id) != anchor
            or _history(await sessions.refresh(conversation_id)) != native_history):
        raise SpeechPreparationError('Speech preparation was superseded')
    return prepared

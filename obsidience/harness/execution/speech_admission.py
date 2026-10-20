"""One Executive first step, admitted only after semantic endpointing.

A direct answer is handed over at its control line while the model still
generates it; a native Tool call or an unfinished verdict is buffered whole.
This module has no Tool dispatch or conversation/memory write port. Its Python
carry is single-use; the ordinary ADK plugin owns completion and native Tools.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from contextlib import aclosing, asynccontextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, field

from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from . import native
from . import trace as action_trace
from .adk import model as model_route, sessions
from .adk.plugin import request_contents
from .executor import activation_messages, compile_activation
from .native_turn import memory_message, recall_query, recall_reply, speech_admission_reminder, tool_schemas
from .prefill import report_reuse, speech_key, speech_recall
from ..conversation.evidence import historical_evidence
from ..conversation.selection import admit_executive
from ..knowledge.scope import revision as scope_revision
from ..models import llm, runtime as model_runtime
from ..models.context import PROMPT_SAFETY_TOKENS, TaskContext

PREPARE_TIMEOUT_SECONDS = 30


def _admission_messages(messages: list[dict], text: str) -> list[dict]:
    """Keep the one-response output contract adjacent to the current transcript.

    The normal cached voice instructions demand an immediate plain-text answer;
    a distant system-only marker rule alone is insufficient for the local
    model, so this private request-only reminder follows the owner's message
    and switches on the cached system prompt's Spoken turn admission rules
    (native_turn.SPEECH_ADMISSION_PROTOCOL). It is neither accepted owner text
    nor a second question, and stays a message of its own: appended to the
    owner's message, a bare "Yes" was answered as if it addressed the control
    (reverted 2026-10-19). It is retained in the first decision's exact
    provenance. The system message, Tool declarations and history stay
    byte-identical to ordinary ADK steps, so the step after a Tool result
    reuses the engine's cached prefix up to here.
    """
    return [*messages, {'role': 'user', 'content': speech_admission_reminder(text)}]


class SpeechPreparationError(ValueError):
    """A buffered response cannot be admitted; no model retry or effect follows."""


class SpeechOutputError(SpeechPreparationError):
    """The model's own first response broke the admission protocol."""


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
                    raise SpeechOutputError('Speech admission began without its exact control line')
            if part.function_call is not None and self.prefix != 'C\n':
                raise SpeechOutputError('Native Tool streamed before a complete-turn control line')


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
        raise SpeechOutputError('Speech admission returned no final response')
    if any(response.error_code or response.interrupted
           or response.finish_reason not in {None, types.FinishReason.STOP}
           for response in responses):
        raise SpeechOutputError('Speech admission did not finish cleanly')
    parts = [part.model_copy(deep=True) for response in responses
             for part in (response.content.parts if response.content else []) if not part.thought]
    text = ''.join(part.text for part in parts if part.text is not None)
    # A single control line is accepted at EOF for an incomplete turn. Complete
    # replies require the line boundary before their answer or native call.
    marker, separator, remainder = text.partition('\n')
    if marker not in {'C', 'I', 'W'} or (marker == 'C' and not separator):
        raise SpeechOutputError('Speech admission omitted its exact control line')
    calls = [part.function_call for part in parts if part.function_call is not None]
    if marker != 'C':
        if calls or remainder.strip():
            raise SpeechOutputError('An unfinished speech response contained content or native Tools')
        return ('incomplete_short' if marker == 'I' else 'incomplete_long'), None
    if not remainder.strip() and not calls:
        raise SpeechOutputError('Complete speech response contained no answer or native Tool')
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
                raise SpeechOutputError('Native Tool preceded the speech admission marker')
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
    # (Agent ref, recall query) when memory came from a shorter partial's recall.
    _recall_audit: tuple | None = field(repr=False, default=None)
    # A direct answer handed over at its control line while it generates
    # (prepare): the generating task, which sets response when it ends, and
    # the answer's stream events in order (None ends them).
    _stream: asyncio.Task | None = field(repr=False, default=None)
    _events: asyncio.Queue | None = field(repr=False, default=None)
    # Set by a validated submission, which then owns a generating answer.
    _claimed: bool = field(repr=False, default=False)

    def _answer(self) -> bool:
        """A complete response exists, or is still generating without a failure."""
        stream = self._stream
        if stream is None:
            return self.response is not None
        return not stream.done() or (not stream.cancelled() and stream.exception() is None
                                     and self.response is not None)

    async def close(self) -> None:
        """Stop an answer still generating; it holds the model lease or idle capacity."""
        stream = self._stream
        if stream is not None and not stream.done() and stream is not asyncio.current_task():
            stream.cancel()
            await asyncio.gather(stream, return_exceptions=True)

    async def _drain(self, feed) -> LlmResponse:
        """Feed the answer's stream events as they arrive; return its complete response.

        Any failure after the control line (protocol, provider error,
        cancellation) stops generation and raises; the caller retracts what
        early speech already voiced.
        """
        stream = self._stream
        try:
            while (event := await self._events.get()) is not None:
                if feed is not None:
                    await feed(event)
            await asyncio.wait({stream})
        except BaseException:
            await self.close()
            raise
        if stream.cancelled():
            raise SpeechPreparationError('The admitted spoken answer was cancelled while generating')
        if isinstance(error := stream.exception(), SpeechPreparationError):
            raise error
        if error is not None or self.response is None:
            raise SpeechPreparationError('The admitted spoken answer failed while generating') from error
        return self.response

    def audit_recall(self) -> None:
        """Measure what memory from a shorter partial cost this admitted text.

        Metadata only and after the verdict: the final words' own recall runs
        in the background and the trace reports how many memories they share.
        Nothing reaches a prompt.
        """
        audit, self._recall_audit = self._recall_audit, None
        if audit is None:
            return
        used = {row['text'] for row in json.loads(self.memory)['memories']} if self.memory else set()
        coverage = self.metrics.get('recall_coverage')

        async def compare():
            from ..memory.hindsight import MEMORY
            value = recall_reply(await MEMORY.recall(audit[0], *audit[1], speculative=True))
            exact = {row['text'] for row in value['memories']}
            action_trace.emit('measurement', 'Speech recall prefix agreement', [
                f'coverage: {coverage}', f'shared: {len(used & exact)}',
                f'prefix_memories: {len(used)}', f'exact_memories: {len(exact)}',
                f'status: {value.get("status", "returned")}'])
        asyncio.create_task(compare(), name='obsidience-speech-recall-audit').add_done_callback(_retrieved)

    async def current(self, runtime) -> bool:
        """Whether this unbound response still matches the live conversation.

        Submission repeats these checks with the contract under the lock; a
        stale speculative response is only discarded, never an error.
        """
        return (self._runtime is runtime and not self._consumed and self._bound_turn is None
                and self._answer() and runtime._generation == self.generation
                and runtime._conversation.conversation_id == self.conversation_id
                and _tip(runtime._conversation, self.conversation_id) == self.history
                and native.window_anchor(self.conversation_id) == self.anchor
                and _history(await sessions.refresh(self.conversation_id)) == self.native_history)

    async def validate_submission(self, runtime, text: str) -> None:
        if (self.decision != 'complete' or not self._answer() or self._consumed
                or self._bound_turn is not None or self._runtime is not runtime
                or text != self.text or runtime._generation != self.generation
                or runtime._conversation.conversation_id != self.conversation_id
                or _tip(runtime._conversation, self.conversation_id) != self.history
                or native.window_anchor(self.conversation_id) != self.anchor):
            raise SpeechPreparationError('The prepared speech turn is stale or already bound')
        view = await sessions.refresh(self.conversation_id)
        if _history(view) != self.native_history:
            raise SpeechPreparationError('The conversation changed during speech admission')
        # The prompt, Tools, model and scope bind in consume(), against the
        # run's own fresh compile, before this response can reach ADK; a
        # recompile here only repeated that work (~40 ms) under the lock.
        if (runtime._generation != self.generation
                or runtime._conversation.conversation_id != self.conversation_id
                or _tip(runtime._conversation, self.conversation_id) != self.history
                or native.window_anchor(self.conversation_id) != self.anchor):
            raise SpeechPreparationError('Speech admission changed while validating its submission')
        self._claimed = True

    def bind(self, turn: dict, generation: int) -> None:
        if (self._bound_turn is not None or turn['conversation_id'] != self.conversation_id
                or generation != self.generation + 1):
            raise SpeechPreparationError('Prepared speech can bind exactly once')
        self._bound_turn, self._bound_sequence = str(turn['id']), int(turn['sequence'])
        self._bound_generation = generation

    async def consume(self, plugin, feed=None) -> LlmResponse:
        """The admitted response for the bound turn's first step, after its contract checks.

        feed (early speech) receives a direct answer's native stream events: as
        they generate when it was handed over at its control line, else at once.
        """
        runtime = self._runtime
        params = plugin.ctx.get('params') or {}
        if (self._consumed or not self._answer() or self._bound_turn is None
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
        # system, schemas, model and scope must bind the admitted digests.
        # This is the response's only contract check after admission.
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
        if self._stream is not None:
            response = await self._drain(feed)
            if runtime._generation != self._bound_generation:
                raise SpeechPreparationError('Prepared speech was cancelled while its answer generated')
        else:
            response = self.response
            parts = response.content.parts if response.content and response.content.parts else []
            if feed is not None and not any(part.function_call for part in parts):
                if text := ''.join(part.text for part in parts if part.text and not part.thought):
                    await feed({'type': 'text-delta', 'text': text})
        self.response = None
        return response


@asynccontextmanager
async def _model(spec, speculative: bool):
    if not speculative:
        async with model_runtime.lease(spec) as active_spec:
            yield active_spec
        return
    # Like a speech warm, speculation borrows idle resident capacity: any
    # lease (the final admission's included) cancels it; busy hardware skips it.
    async with model_runtime.resident_prefill(spec) as available:
        if not available:
            raise SpeechPreparationError('Speculative admission skipped: the model is busy or not resident')
        yield spec


async def _generate(runtime, text: str, response_contract: str, speculative: bool,
                    handover: asyncio.Future) -> PreparedSpeechTurn:
    """The admission request itself (prepare's generating task).

    A direct answer resolves ``handover`` at its control line and keeps
    generating: the visible text after its marker and any later native call go to
    the returned turn's events, and its response is set when the stream ends.
    """
    global _HANDED
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
    metrics = {'speculative': True} if speculative else {}
    async with asyncio.timeout(PREPARE_TIMEOUT_SECONDS):
        async with _model(spec, speculative) as active_spec:
            if _model_binding(active_spec, effort) != _model_binding(spec, effort):
                raise SpeechPreparationError("The model configuration changed while awaiting its lease")
            spec = active_spec
            evidence = historical_evidence(conversation, conversation_id=conversation_id,
                                           before_sequence=before_sequence)
            context_started = time.monotonic()
            # An earlier speech partial usually recalled these words already,
            # or their first half or more; adopt its finished (else running)
            # recall instead of waiting for a new one (prefill.speech_recall's
            # cover policy). Speculation leaves it registered for the next
            # partial or final.
            query = recall_query(clean, conversation_id)
            recall, reuse, coverage = await speech_recall(
                agent.ref, query, adopt=not speculative, cover=True)
            metrics['recall_adopted'] = bool(reuse)
            if reuse:
                metrics.update(recall_reuse=reuse, recall_coverage=coverage)
            try:
                activation = await compile_activation(
                    agent, params=params, interactive=True, emit_activity=False,
                    conversation_evidence=evidence)
                memory = memory_message(recall_reply(
                    await (asyncio.shield(recall) if speculative else recall)))
            finally:
                if not speculative:
                    if not recall.done():
                        recall.cancel()
                    await asyncio.gather(recall, return_exceptions=True)
            metrics['context_recall_ms'] = round((time.monotonic() - context_started) * 1000, 3)
            messages = activation_messages(agent, activation, agent_name=agent.title,
                                           response_contract=response_contract)
            system = _digest(messages[0]['content'])
            compiled_context = deepcopy(messages[1:])
            report_reuse(conversation_id, messages[1]['content'] if len(messages) > 1 else '', memory)
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
            started = time.monotonic()
            capacity = spec.context_tokens - spec.max_output_tokens - PROMPT_SAFETY_TOKENS
            if model_route.engine_guard(spec, effort) == capacity:
                # A fresh projection holds no pages, so a client count would only
                # repeat the engine's exact pre-enqueue guard on this same request.
                metrics['preflight_ms'] = round((time.monotonic() - started) * 1000, 3)
            else:
                async with llm.provider_client() as client:
                    count = await TaskContext().fit_payload(payload, spec, client, capacity)
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
            route = model_route.route(spec, effort)
            # The shared ADK route is cached by identity/endpoint/effort. Reject
            # an old cached ceiling after an in-process model profile change.
            route_args = route._additional_args
            if (route_args.get('max_tokens') != spec.max_output_tokens
                    or (spec.supports_input_token_limit
                        and (route_args.get('extra_body') or {}).get('input_token_limit') != capacity)):
                raise SpeechPreparationError('The cached ADK model route has outdated token settings')
            # This request's HTTP stream is closed here; ADK's generator alone does not.
            route, owner = model_route.owned(route)

            def turn(decision, response):
                return PreparedSpeechTurn(
                    _recall_audit=(agent.ref, query) if reuse == 'prefix' else None,
                    decision=decision, text=clean, conversation_id=conversation_id, generation=generation,
                    history=history, anchor=anchor, native_history=native_history,
                    model_binding=_model_binding(spec, effort), scope=scope_revision(agent), system=system,
                    schema_binding=schema_binding, response=response,
                    wire=deepcopy(payload['messages']), context=compiled_context,
                    packet=deepcopy(activation['activity_packet']), refs=list(activation['refs']),
                    retrieval_ms=float(activation['retrieval_ms']), metrics=metrics, memory=memory,
                    _runtime=runtime)

            handed, said = None, ''
            if (run := _RUN.get()) is not None:
                run[1] = time.monotonic()  # its model request is in flight
            elif _STALE[0] is not None:
                # A superseded speculation's request may still be prefilling in
                # the engine, which cancels only between decode batches: this
                # request's first_public_delta_ms then includes that wait.
                if started - _STALE[0] < 2:
                    metrics['after_stale_request_ms'] = round((started - _STALE[0]) * 1000, 3)
                _STALE[0] = None
            token = model_route.ADMISSION.set(metrics)
            try:
                async with aclosing(route.generate_content_async(request, stream=True)) as stream:
                    async for response in stream:
                        prefix.observe(response)
                        if not response.partial:
                            responses.append(response)
                            continue
                        parts = response.content.parts if response.content else []
                        visible = ''.join(part.text for part in parts if part.text is not None and not part.thought)
                        called = any(part.function_call for part in parts)
                        if visible or called:
                            metrics.setdefault('first_public_delta_ms', round((time.monotonic() - started) * 1000, 3))
                        if handed is not None:
                            if visible:
                                handed._events.put_nowait({'type': 'text-delta', 'text': visible})
                            if called:
                                handed._events.put_nowait({'type': 'tool-call-delta'})
                            continue
                        said += visible
                        if called or prefix.prefix != 'C\n' or not said[2:].strip():
                            continue
                        # A complete verdict with answer text and no native call
                        # so far: hand the answer over now; it keeps generating
                        # here, and its turn binds while it does (owner
                        # 2026-10-19: speak from the verdict marker, not after
                        # the whole first response).
                        metrics['handover_ms'] = round((time.monotonic() - started) * 1000, 3)
                        handed = turn('complete', None)
                        handed._stream, handed._events = asyncio.current_task(), asyncio.Queue()
                        handed._events.put_nowait({'type': 'text-delta', 'text': said[2:]})
                        _HANDED = handed
                        handover.set_result(handed)
            finally:
                try:
                    await owner.close()
                finally:
                    model_route.ADMISSION.reset(token)
                    if run is not None:
                        run[2] = time.monotonic()
                    if handed is not None:
                        handed._events.put_nowait(None)
            metrics['generation_ms'] = round((time.monotonic() - started) * 1000, 3)
            if responses and (usage := next((r.usage_metadata for r in reversed(responses)
                                             if r.usage_metadata is not None), None)) is not None:
                metrics.update(prompt_tokens=usage.prompt_token_count or metrics.get('prompt_tokens', 0),
                               cached_input_tokens=usage.cached_content_token_count or 0,
                               output_tokens=usage.candidates_token_count or 0)
    decision, response = _sanitize(responses)
    if handed is None:
        return turn(decision, response)
    handed.response = response
    return handed


async def prepare(runtime, text: str, response_contract: str, *,
                  speculative: bool = False) -> PreparedSpeechTurn:
    """Generate the real first response without starting an Agent activation.

    Returns at a direct answer's control line while the answer still
    generates (consume() feeds it to early speech), else after the whole
    response. speculative=True runs it on a speech partial (see speculate).
    """
    if not speculative:
        # A handed-over answer no submission took (refused verdict, newer
        # capture) would hold the model this admission needs.
        await _stop_handed(bound=False)
    handover = asyncio.get_running_loop().create_future()
    task = asyncio.create_task(_generate(runtime, text, response_contract, speculative, handover),
                               name='obsidience-speech-admission')
    task.add_done_callback(_retrieved)
    try:
        await asyncio.wait({task, handover}, return_when=asyncio.FIRST_COMPLETED)
    except asyncio.CancelledError:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        raise
    prepared = handover.result() if handover.done() else task.result()
    conversation, conversation_id = runtime._conversation, prepared.conversation_id
    # adopt() repeats these checks for a speculative response (current());
    # here they only delayed a speculation that ended after the final.
    if not speculative and (
            runtime._generation != prepared.generation or conversation.conversation_id != conversation_id
            or _tip(conversation, conversation_id) != prepared.history
            or native.window_anchor(conversation_id) != prepared.anchor
            or _history(await sessions.refresh(conversation_id)) != prepared.native_history):
        await prepared.close()
        raise SpeechPreparationError('Speech preparation was superseded')
    if not speculative:
        prepared.audit_recall()
    return prepared


# The latest speculative admission of a speech partial: (runtime, speech_key
# of its text, monotonic arrival, task, run), run = [model run start, request
# sent, request ended] (monotonic, None until then).
_SPECULATION: tuple | None = None
# Model speculation runs at pause edges only (owner 2026-10-19). Each partial
# starts or reuses its Hindsight recall at once, but its model run waits for a
# pause: an explicit edge (a VAD pause or an ASR early final), else words
# unchanged for SPECULATION_STABLE_SECONDS; at most MAX_SPECULATIONS runs per
# utterance. Partials change every 150-250 ms, and llama.cpp cancels only
# between decode batches (-b 4096 holds a whole admission tail), so each
# superseded run still spent its uncached prefill on the shared RTX 4000s
# (replayed 2026-10-19: the next request reuses most of it, +3-36 ms median).
MAX_SPECULATIONS = 3
SPECULATION_STABLE_SECONDS = 0.2
# (runtime, speech_sequence) of the current utterance and its model runs.
_UTTERANCE: list = [None, 0]
# The speculation run of the current task (see _SPECULATION), for _generate.
_RUN: ContextVar[list | None] = ContextVar('obsidience_speculation_run', default=None)
# When a superseded speculation's model request was cancelled in flight.
_STALE: list = [None]
# The latest direct answer handed over while generating, until its stream
# ends. One that no submission took still holds the model; the next final
# admission or a cancellation stops it.
_HANDED: PreparedSpeechTurn | None = None
# The realtime candidate's exact-command check: those take the reflex route.
_REFLEX_COMMANDS = ['lights.set', 'tv.control', 'media.pause', 'task.complete']


async def _stop_handed(*, bound: bool) -> None:
    """Stop the handed-over answer unless a submission owns it.

    bound=True (turn cancellation) also stops one bound to its turn. A
    submission validated but not yet bound keeps it: that submission's own
    cancel() of the previous turn runs between the two.
    """
    global _HANDED
    handed = _HANDED
    if handed is None or handed._stream.done():
        _HANDED = None
        return
    if handed._claimed and (handed._bound_turn is None or not bound):
        return
    _HANDED = None
    await handed.close()


async def _close(task: asyncio.Task | None) -> None:
    """Cancel and join a speculative admission, and stop the answer it handed over."""
    if task is None:
        return
    if not task.done():
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    if not _failed(task) and task.result() is not None:
        await task.result().close()


def _failed(task: asyncio.Task) -> bool:
    return task.done() and (task.cancelled() or task.exception() is not None)


def _retrieved(task: asyncio.Task) -> None:
    if not task.cancelled():
        task.exception()


async def _warm_recall(runtime, text: str) -> None:
    """Start (or reuse a covering) speech recall for these words; leave it registered."""
    agent, _, _ = admit_executive(text, 'voice')
    await speech_recall(agent.ref, recall_query(text, runtime._conversation.conversation_id), cover=True)


async def _speculative_prepare(runtime, text: str, response_contract: str, previous, run: list, edge: bool):
    # Resident capacity admits one owner; join the superseded stream first.
    await _close(previous)
    from .commands import recognize_command
    if recognize_command(text, _REFLEX_COMMANDS) is not None:
        return None
    if not edge:
        # Recall these words now; run the model only if no newer words follow.
        warm = asyncio.create_task(_warm_recall(runtime, text), name='obsidience-speech-recall-warm')
        warm.add_done_callback(_retrieved)
        try:
            await asyncio.sleep(SPECULATION_STABLE_SECONDS)
        finally:
            warm.cancel()  # Only its wait; a started recall stays registered.
    if _UTTERANCE[1] >= MAX_SPECULATIONS:
        return None
    _UTTERANCE[1] += 1
    run[0] = time.monotonic()
    _RUN.set(run)
    # A standby warm holds the same idle capacity; speculation supersedes it.
    await runtime._cancel_speech_prefill()
    return await prepare(runtime, text, response_contract, speculative=True)


def speculate(runtime, text: str, response_contract: str, *, sequence: int | None = None,
              edge: bool = False) -> None:
    """Run the real admission on a speech partial while the owner may still speak.

    edge=True marks a pause edge (VAD pause, ASR early final): the model run
    starts at once instead of after SPECULATION_STABLE_SECONDS of unchanged
    words. The same words (speech_key) keep the running or finished run; other
    words cancel and replace it. Nothing is published, dispatched or written:
    adopt() hands the response to final admission only for the same words.
    """
    global _SPECULATION
    if _UTTERANCE[0] != (runtime, sequence):
        _UTTERANCE[:] = [(runtime, sequence), 0]
    key = speech_key(text)
    current = _SPECULATION
    if (current is not None and current[0] is runtime and current[1] == key and not _failed(current[3])
            and not (edge and current[4][0] is None and not current[3].done())):
        return
    previous = current[3] if current is not None else None
    if previous is not None:
        previous.cancel()
        if current[4][1] is not None and current[4][2] is None:
            _STALE[0] = time.monotonic()
    run = [None, None, None]
    task = asyncio.create_task(_speculative_prepare(runtime, text, response_contract, previous, run, edge),
                               name='obsidience-speech-speculation')
    task.add_done_callback(_retrieved)
    _SPECULATION = (runtime, key, time.monotonic(), task, run)


def pending() -> bool:
    """A speculative admission is running or holds a response not yet adopted."""
    current = _SPECULATION
    if current is None:
        return False
    task = current[3]
    return not task.done() or (not _failed(task) and task.result() is not None)


async def discard() -> None:
    """Cancel and join the speculative admission and stop a handed-over answer
    still generating (STOP, new turn, teardown)."""
    global _SPECULATION
    current, _SPECULATION = _SPECULATION, None
    _UTTERANCE[:] = [None, 0]
    await _close(current[3] if current is not None else None)
    await _stop_handed(bound=True)


def _report(outcome: str, started: float, arrived: float, run: list) -> None:
    action_trace.emit('measurement', 'Speech admission speculation ' + outcome, [
        f'lead_ms: {round((arrived - started) * 1000, 3)}',
        f'model_lead_ms: {round((arrived - run[0]) * 1000, 3) if run[0] is not None else None}',
        f'wait_ms: {round((time.monotonic() - arrived) * 1000, 3)}',
        # A request cancelled in flight may keep the engine prefilling; the
        # fresh admission records after_stale_request_ms with its metrics.
        f'request_in_flight: {run[1] is not None and run[2] is None}',
    ])


async def adopt(runtime, text: str) -> PreparedSpeechTurn | None:
    """The speculative admission for this final transcript's words, else None.

    A run for other words is cancelled and joined, so a miss waits only for
    its cancellation; the caller then admits the final text afresh. A model
    response that broke the protocol for these same words fails closed here
    (SpeechOutputError), with no second model attempt.
    """
    global _SPECULATION
    current, _SPECULATION = _SPECULATION, None
    _UTTERANCE[:] = [None, 0]
    if current is None:
        return None
    owner, key, started, task, run = current
    arrived = time.monotonic()
    if owner is not runtime or key != speech_key(text) or (run[0] is None and not task.done()):
        # Other words, or these words still waiting for a pause: an admission
        # started now is no later than that run would start.
        in_flight = run[1] is not None and run[2] is None
        await _close(task)
        if in_flight:
            _STALE[0] = time.monotonic()
        _report('missed' if run[0] is not None or key != speech_key(text) else 'unstarted',
                started, arrived, run)
        return None
    try:
        # A direct answer is adopted at its control line, still generating.
        await asyncio.wait({task})
    except asyncio.CancelledError:
        await _close(task)
        raise
    error = None if task.cancelled() else task.exception()
    if isinstance(error, SpeechOutputError):
        _report('failed', started, arrived, run)
        raise error
    prepared = None if task.cancelled() or error is not None else task.result()
    if prepared is None or not await prepared.current(runtime):
        if prepared is not None:
            await prepared.close()
        _report('unusable' if run[0] is not None else 'skipped', started, arrived, run)
        return None
    prepared.metrics.update(speculation_lead_ms=round((arrived - started) * 1000, 3),
                            speculation_model_lead_ms=round((arrived - run[0]) * 1000, 3),
                            speculation_wait_ms=round((time.monotonic() - arrived) * 1000, 3))
    _report('adopted', started, arrived, run)
    prepared.audit_recall()
    return prepared

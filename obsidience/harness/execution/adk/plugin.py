"""The Executive's policy over ADK's model/Tool loop, as one per-activation plugin.

ADK sequences model steps, Tool calls and session events. This plugin holds
what ADK has no equivalent for: the model lease around each step, the shared
native provider projection, step and operation budgets, owner steering at
step boundaries, the finite-choice lane, early speech, argument validation with
three strikes, the run's narrowing dispatch policy and the completion authority
for plain text. Every effect goes through ``capability_core.run_capability``.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import time
import uuid
from copy import deepcopy

from google.adk.models.llm_response import LlmResponse
from google.adk.plugins.base_plugin import BasePlugin
from google.genai import types

from .. import native
from ..capability_core import CapabilityExecution, foreground_checkpoint, observation_text, run_capability
from ..native_turn import (
    adopt_fast_lane, argument_diagnostic, settle_model_step, tool_schemas, unavailable_text,
)
from ...models.context import PROMPT_SAFETY_TOKENS, TaskContext, discard_consumed_images
from . import sessions


def _text(value: str) -> dict:
    return {'content': [{'type': 'text', 'text': value}]}


def request_contents(rows: list[dict]) -> list[types.Content]:
    """Provider messages from the shared projection as the request ADK hands LiteLLM.

    Tool results keep their exact text (``FunctionResponse.response`` as a
    string, request-only) and images go inline, so LiteLLM sends the same
    chat messages the native transport would.
    """
    names = {call['id']: call['function']['name'] for row in rows for call in row.get('tool_calls', [])}
    contents = []
    for row in rows:
        if row['role'] == 'tool':
            response = types.FunctionResponse.model_construct(
                id=row['tool_call_id'], name=names.get(row['tool_call_id'], ''), response=row['content'])
            contents.append(types.Content(role='user', parts=[types.Part(function_response=response)]))
        elif row['role'] == 'assistant':
            parts = [types.Part(text=row['content'])] if isinstance(row['content'], str) and row['content'] else []
            parts += [types.Part(function_call=types.FunctionCall(
                id=call['id'], name=call['function']['name'], args=json.loads(call['function']['arguments'] or '{}')))
                for call in row.get('tool_calls', [])]
            contents.append(types.Content(role='model', parts=parts))
        elif isinstance(row['content'], str):
            contents.append(types.Content(role='user', parts=[types.Part(text=row['content'])]))
        else:
            parts = []
            for value in row['content']:
                if value['type'] == 'image_url':
                    header, data = value['image_url']['url'].split(',', 1)
                    parts.append(types.Part(inline_data=types.Blob(
                        data=base64.b64decode(data), mime_type=header.removeprefix('data:').split(';')[0])))
                else:
                    parts.append(types.Part(text=value['text']))
            contents.append(types.Content(role='user', parts=parts))
    return contents


class ExecutivePlugin(BasePlugin):
    """One Executive activation's loop policy and capability state."""

    def __init__(self, task, spec, allowed, ctx, agent_name, effort, *, system: str,
                 interruption_event=None, initial_lease=None, fast_lane=True):
        super().__init__(name='obsidience_executive')
        from ..executor import TurnState
        self.spec, self.effort, self.system, self.agent_name = spec, effort, system, agent_name
        self.max_steps = TurnState.budget(None)
        self.emit = TurnState.emitter(None)
        self.trace = ctx.setdefault('trace', [])
        self.run = ctx['run_id']
        self.ctx = ctx
        # Advertised schemas stay byte-stable for the prompt cache; ex.allowed
        # is the run's dispatch policy, which failed or uncertain effects narrow.
        self.advertised = list(allowed)
        self.ex = CapabilityExecution(task, spec, ctx, agent_name, self.trace, self.emit, list(allowed),
                                      interruption_event=interruption_event, steering=ctx.get('_steering'),
                                      active_lease=initial_lease)
        self.state = TurnState(self.ex)
        self.interruption_event = interruption_event
        self.fast_lane = fast_lane and task.kind == 'agent' and task.ref == 'Agents/Executive/Executive'
        self.images: dict[str, str] = {}
        self.model_steps = 0
        self.last_search_refs = None
        self.steered = False
        self.feedback: str | None = None
        self.voice = None
        self.lease_prefetch: asyncio.Task | None = None
        self._step: dict | None = None
        self._calls = asyncio.Lock()

    # Model reservation -------------------------------------------------
    async def adopt_lease(self):
        """Adopt the reservation requested at activation start, or acquire it now."""
        from ..executor import TurnState
        pending, self.lease_prefetch = self.lease_prefetch, None
        if pending is None:
            return await TurnState.acquire_model(self.ex.model)
        try:
            return await asyncio.shield(pending)
        except BaseException:
            self.lease_prefetch = pending  # release() cancels or releases it.
            raise

    def discard_observation(self) -> None:
        self.images.clear()
        self.state.discard_witnesses()

    # Tool policy -------------------------------------------------------
    async def before_tool_callback(self, *, tool, tool_args, tool_context):
        return self.admit(tool.name, tool_args)

    def admit(self, name: str, args: dict) -> dict | None:
        """Policy before dispatch; a returned response answers the call without an effect."""
        self.last_search_refs = None
        foreground_checkpoint(self.interruption_event, self.ctx)
        if self.ex.step >= self.max_steps:
            self.state.fail('Executive operation budget exhausted')
        if self.ex.done:
            return _text('Activation already settled; no further effect is dispatched.')
        if self.state.steering_pending:
            self.discard_observation()
            return _text('Response superseded by a current owner clarification; no Tool dispatched.')
        if name not in self.ex.allowed:
            self.discard_observation()
            self.trace.append({'invalid_tool': name, 'not_dispatched': True,
                               'obs': 'Capability unavailable at this boundary'})
            self.state.strike('invalid', 'Three invalid or unavailable native Tool calls')
            return _text(unavailable_text(self.ex.allowed))
        if diagnostic := argument_diagnostic(name, args):
            self.discard_observation()
            self.trace.append({'invalid_tool': name, 'not_dispatched': True, 'obs': diagnostic})
            self.emit('error', f'{name} arguments rejected before dispatch', [diagnostic])
            self.state.strike('invalid', 'Three invalid native Tool calls; no effect dispatched')
            return _text(diagnostic)
        self.state.strikes['invalid'] = 0
        return None

    async def dispatch(self, name: str, args: dict) -> dict:
        """One admitted call through the capability core; rendered as the Tool result."""
        from .. import executor
        async with self._calls:  # One Tool at a time, like the native single-call step.
            if self.lease_prefetch is not None:
                # Model-resource Tools release it through the core.
                self.ex.model, self.ex.active_lease = await self.adopt_lease()
            # Only receipts newly produced by this exact successful search may
            # supply read candidates. Old or failed search prose is never parsed.
            queries = ([args.get('query')] if 'query' in args else args.get('queries', [])) if name == 'vault.search' else []
            previous = {query: self.ctx.get('_vault_searches', {}).get(query) for query in queries}
            outcome = await run_capability(
                self.ex, name, args, execute=executor.execute_capability,
                execute_async=executor.execute_capability_async, scope_checkpoint=executor._scope_checkpoint)
            if queries:
                current = self.ctx.get('_vault_searches', {})
                fresh = [current.get(query) for query in queries]
                if all(isinstance(row, dict) and row is not previous[query] and isinstance(row.get('refs'), list)
                       for query, row in zip(queries, fresh)):
                    self.last_search_refs = [ref for row in fresh for ref in row['refs']]
            self.ex.step += 1
            if name == 'task.complete' and not self.ex.done:
                self.state.strike('completion', 'Three rejected completion attempts')
            elif name != 'task.complete':
                self.state.strikes['completion'] = 0
            if outcome.kind in {'completed', 'waiting'}:
                return _text(json.dumps(self.ctx.get('completion') or {'status': self.ex.status}))
            blocks = [{'type': 'text', 'text': observation_text(outcome.observation)}]
            if outcome.image_png is not None:
                raw = outcome.image_png
                identifier = hashlib.sha256(raw).hexdigest()
                self.images[identifier] = 'data:image/png;base64,' + base64.b64encode(raw).decode('ascii')
                blocks.append({'type': 'image', 'attachment': {
                    'attachmentId': identifier, 'mediaType': 'image/png', 'bytes': len(raw),
                    'width': int.from_bytes(raw[16:20], 'big'), 'height': int.from_bytes(raw[20:24], 'big')}})
            return {'content': blocks}

    async def operate(self, name: str, args: dict) -> list[dict]:
        """A controller-originated call (plain-text completion, explicit command)."""
        response = self.admit(name, args) or await self.dispatch(name, args)
        return response['content']

    # Model steps -------------------------------------------------------
    def boundary(self) -> bool:
        """True when this invocation must yield to the controller before another model step."""
        from ..executor import _scope_checkpoint
        foreground_checkpoint(self.interruption_event, self.ctx)
        _scope_checkpoint(self.ctx)
        if self.model_steps >= self.max_steps or self.ex.step >= self.max_steps:
            self.state.fail('Executive decision budget exhausted')
        return self.ex.done or self.state.steering_pending

    async def before_model_callback(self, *, callback_context, llm_request):
        if self.boundary():
            # No content and no error: ADK ends this invocation without an
            # event. The controller then settles or applies the clarification.
            return LlmResponse()
        self.model_steps += 1
        self.state.rotate()
        await self.state.hold_model(self.adopt_lease)
        fields = {'step': self.ex.step + 1, 'call_id': f'{self.run}:model:{self.model_steps}'}
        self.state.emit_model(f'{self.agent_name} model started', 'started', fields, engine=sessions.BACKEND)
        metrics: dict = {}
        self._step = {'fields': fields, 'metrics': metrics, 'started': time.monotonic(), 'menu': None}
        if self.voice is not None:
            # A verified reflex command keeps cue-only confirmation.
            self.voice.begin_step(eligible=self.ctx.get('_reflex_command_verified') is not True)
        # The shared projection over the history ADK built from session events.
        conversation_id = (self.ctx.get('params') or {}).get('conversation_id')
        history = [{'role': 'system', 'content': [{'type': 'text', 'text': self.system}]},
                   *sessions.native_messages(llm_request.contents)]
        wire = native.wire_messages(history, self.images, self.ctx['objective'],
                                    anchor=native.window_anchor(conversation_id))
        payload = native.request_payload(wire, self.spec, self.effort, tool_schemas(self.advertised))
        menu = None
        if self.fast_lane:
            from ..fast_lane import candidates
            menu = candidates(self.ctx['objective'], self.ex.allowed, first_step=self.model_steps == 1,
                              search_refs=self.last_search_refs, trace=self.trace,
                              steering=self.steered or self.state.steering_pending)
        self.last_search_refs = None
        self._step['menu'] = menu
        from ...models import llm
        async with llm.provider_client() as client:
            if menu and native.fast_lane_eligible(self.spec, self.effort, self.images, payload):
                from ..fast_lane import select
                choice = await select(client, payload, self.spec, menu, metrics,
                                      objective=self.ctx['objective'], headers={})
                if choice is not None:
                    # A model proposal over complete calls, never dispatch: ADK's
                    # Tool path still admits it and runs it through the core.
                    detail = metrics['fast_lane']
                    metrics.update(preflight_ms=detail['preflight_ms'], prompt_tokens=detail['prompt_tokens'],
                                   output_tokens=1, first_public_delta_ms=detail['completion_ms'],
                                   generation_ms=detail['completion_ms'])
                    response = LlmResponse(content=types.Content(role='model', parts=[types.Part(
                        function_call=types.FunctionCall(id=str(uuid.uuid4()), name=choice['name'],
                                                         args=deepcopy(choice['args'])))]))
                    await self._finish_step(response, from_choice=True)
                    return response
            # Exact runtime count; only older pageable reads may be projected
            # and an irreducible overflow fails before the request.
            projection = TaskContext()
            names = {call['id']: call['function']['name'] for row in payload['messages']
                     for call in row.get('tool_calls', [])}
            for index, row in enumerate(payload['messages']):
                if row['role'] == 'tool' and isinstance(row['content'], str):
                    name = names.get(row['tool_call_id'], '')
                    text = row['content'].removeprefix('Observation:\n')
                    projection.remember_source_page(index, name, text, '', source_read_allowed=True)
                    projection.remember_article_page(index, name, text, '', vault_read_allowed=True)
            started = time.monotonic()
            capacity = self.spec.context_tokens - self.spec.max_output_tokens - PROMPT_SAFETY_TOKENS
            count = await projection.fit_payload(payload, self.spec, client, capacity)
            metrics.update(prompt_tokens=count.tokens, preflight_ms=round((time.monotonic() - started) * 1000, 3))
            if 'before_input_tokens' in projection.last_projection:
                self.trace.append({'context_projection': projection.last_projection})
        self.ex.decision_messages[:] = deepcopy(payload['messages'])
        llm_request.config.system_instruction = payload['messages'][0]['content']
        llm_request.contents = request_contents(payload['messages'][1:])
        self._step['dispatched'] = time.monotonic()
        return None

    async def after_model_callback(self, *, callback_context, llm_response):
        step = self._step
        if step is None:
            return None
        parts = llm_response.content.parts if llm_response.content and llm_response.content.parts else []
        if llm_response.partial:
            text = ''.join(value.text for value in parts if value.text and not value.thought)
            if text and 'first_public_delta_ms' not in step['metrics']:
                step['metrics']['first_public_delta_ms'] = round((time.monotonic() - step['dispatched']) * 1000, 3)
            if text and self.voice is not None:
                await self.voice.feed({'type': 'text-delta', 'text': text})
            return None
        await self._finish_step(llm_response)
        return None

    async def _finish_step(self, response: LlmResponse, *, from_choice: bool = False) -> None:
        step, self._step = self._step, None
        metrics = step['metrics']
        parts = response.content.parts if response.content and response.content.parts else []
        text = ''.join(value.text for value in parts if value.text and not value.thought)
        calls = [value.function_call for value in parts if value.function_call is not None]
        if response.error_code:
            reason = 'max-tokens' if response.finish_reason == types.FinishReason.MAX_TOKENS else 'error'
        else:
            reason = 'tool-calls' if calls else (
                'stop' if response.finish_reason in {None, types.FinishReason.STOP} else
                'max-tokens' if response.finish_reason == types.FinishReason.MAX_TOKENS else 'error')
        if not from_choice:
            usage = response.usage_metadata
            if usage is not None:
                metrics.update(prompt_tokens=usage.prompt_token_count or metrics.get('prompt_tokens', 0),
                               cached_input_tokens=usage.cached_content_token_count or 0,
                               output_tokens=usage.candidates_token_count or 0)
            metrics['generation_ms'] = round((time.monotonic() - step['dispatched']) * 1000, 3)
        self.images.clear()
        discard_consumed_images(self.ex.messages)
        if self.model_steps == 1:
            self.ctx['prompt_tokens'] = metrics.get('prompt_tokens', 0)
        self.trace.append({'provider_metrics': metrics})
        adopt_fast_lane(step['menu'], metrics, self.ctx)
        self.state.emit_model(f'{self.agent_name} model returned', 'result', step['fields'], metrics=metrics)
        if self.voice is not None:
            if calls:
                await self.voice.feed({'type': 'block-start', 'blockType': 'tool-call'})
            await self.voice.feed({'type': 'finish', 'reason': reason})
        if response.error_code and reason == 'error':
            # A malformed native call never reaches a Tool; the model corrects it.
            self.trace.append({'native_tool_error': str(response.error_code)[:80], 'invalid_tool': 'native Tool'})
            self.emit('error', f'native Tool: {response.error_code}')
            if not self.state.strike('invalid', 'Three native Tool errors; inspect the Action Trace'):
                self.feedback = (str(response.error_message or 'The last native Tool call was malformed.')[:300]
                                 + ' No Tool was dispatched; send one complete native call or answer in text.')
            return
        self.feedback = await settle_model_step(self.state, self.operate, text, bool(calls), reason,
                                                allowed=self.advertised, ctx=self.ctx, trace=self.trace,
                                                emit=self.emit, voice=self.voice)

    async def release(self) -> None:
        """Release what this activation acquired: an unadopted reservation and its lease."""
        self.images.clear()
        if self.lease_prefetch is not None:
            # An unadopted reservation never outlives its activation.
            self.lease_prefetch.cancel()
            await asyncio.wait([self.lease_prefetch])
            if not self.lease_prefetch.cancelled() and self.lease_prefetch.exception() is None:
                await self.lease_prefetch.result()[1].__aexit__(None, None, None)
            self.lease_prefetch = None
        await self.state.close(measure_release=True)

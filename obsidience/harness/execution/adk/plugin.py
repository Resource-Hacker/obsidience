"""An accountable Agent's policy over ADK's model/Tool loop, as one per-activation plugin.

ADK sequences model steps, Tool calls and session events. This plugin holds
what ADK has no equivalent for: the model lease around each step, the shared
native provider projection, step and operation budgets, owner steering at
step boundaries, argument validation with three strikes and the run's
narrowing dispatch policy. The Executive's conversation adds the finite-choice
lane, early speech and the completion authority for plain text. A specialist
Task (``task_mode``) keeps its procedure's contract instead: each step
advertises only the Tools its controller state allows (Source, memory,
Repair and Audit prerequisites) with the active proposal and completion
schema, Tool results carry the remaining decision budget, identical repeated
calls are refused, and only task.complete finishes.
Every effect goes through ``capability_core.run_capability``,
except in an instruction evaluation trial: there the trial's handler answers
each admitted call from frozen results or a contract validator (no dispatch,
receipt or writeback), and a captured provider prompt replaces the history.
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
from .. import trace as action_trace
from ..capability_core import (
    OBSERVATION_CONTEXT_FIELD, CapabilityExecution, foreground_checkpoint, observation_text, run_capability,
)
from ..native_turn import (
    NO_TOOL_CALL_FEEDBACK, adopt_fast_lane, argument_diagnostic, settle_model_step, step_budget_notice,
    task_tool_schemas, tool_schemas, unavailable_text,
)
from ...config import CONFIG
from ...models import runtime as model_runtime
from ...models.context import PROMPT_SAFETY_TOKENS, TaskContext, discard_consumed_images
from . import sessions


def step_budget(evaluation) -> int:
    """The activation's model decisions: the executor limit, or an evaluation trial's own."""
    if evaluation is None:
        return CONFIG.max_steps
    if type(evaluation.max_steps) is not int or not 1 <= evaluation.max_steps <= CONFIG.max_steps:
        raise ValueError("Evaluation decision budget must be a positive integer within the executor limit")
    return evaluation.max_steps


def trace_emitter(evaluation):
    """Public trace emission; every evaluation trial event is marked simulated."""
    def emit(channel: str, line: str, detail=None, fields=None) -> None:
        if evaluation is not None:
            fields = {**(fields or {}), "payload": {
                **((fields or {}).get("payload") or {}), "simulated": True,
            }}
            line = "Simulation · " + line
        action_trace.emit(channel, line, detail, fields)
    return emit


async def acquire_model(model):
    """Enter the model owner's lease for this model; the caller releases it."""
    spec = model_runtime.configured_spec(model.id)
    lease = model_runtime.lease(spec)
    await lease.__aenter__()
    return spec, lease


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


class AgentPlugin(BasePlugin):
    """One activation's loop policy and capability state, for any accountable Agent."""

    def __init__(self, task, spec, allowed, ctx, agent_name, effort, *, system: str,
                 interruption_event=None, initial_lease=None, fast_lane=True, evaluation=None):
        super().__init__(name='obsidience_activation')
        self.task = task
        # Agent-owned conversation (the Executive) or a specialist Task procedure.
        self.task_mode = task.kind != 'agent'
        self.spec, self.effort, self.system, self.agent_name = spec, effort, system, agent_name
        self.evaluation = evaluation
        self.max_steps = step_budget(evaluation)
        self.emit = trace_emitter(evaluation)
        self.trace = ctx.setdefault('trace', [])
        self.run = ctx['run_id']
        self.ctx = ctx
        # Advertised schemas stay byte-stable for the prompt cache; ex.allowed
        # is the run's dispatch policy, which failed or uncertain effects narrow.
        self.advertised = list(allowed)
        # A Task step's narrowed Tools; calls outside them are never dispatched.
        self.decision = list(allowed)
        self.ex = CapabilityExecution(task, spec, ctx, agent_name, self.trace, self.emit, list(allowed),
                                      interruption_event=interruption_event, steering=ctx.get('_steering'),
                                      active_lease=initial_lease)
        # Invalid decisions by kind; reaching a limit fails the activation.
        self.strikes: dict[str, int] = {}
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
        # Set while the provider generates, so foreground demand can cancel
        # unfinished inference (never a Tool in flight).
        self.generating = asyncio.Event()

    # Model reservation -------------------------------------------------
    async def adopt_lease(self):
        """Adopt the reservation requested at activation start, or acquire it now."""
        pending, self.lease_prefetch = self.lease_prefetch, None
        if pending is None:
            return await acquire_model(self.ex.model)
        try:
            return await asyncio.shield(pending)
        except BaseException:
            self.lease_prefetch = pending  # release() cancels or releases it.
            raise

    async def hold_model(self, acquire=None) -> None:
        """Hold the model lease for the next decision, measuring any wait."""
        if self.ex.active_lease is None:
            started = time.monotonic()
            self.ex.model, self.ex.active_lease = await (
                acquire() if acquire is not None else acquire_model(self.ex.model))
            action_trace.latency("model_wait", duration_ms=(time.monotonic() - started) * 1000)

    # Decision mechanics ------------------------------------------------
    def fail(self, summary: str) -> None:
        self.ex.done, self.ex.status, self.ex.summary = True, "failed", summary

    def strike(self, kind: str, failure: str, limit: int = 3) -> bool:
        """Count one invalid decision of this kind; reaching the limit fails the activation."""
        self.strikes[kind] = self.strikes.get(kind, 0) + 1
        if self.strikes[kind] < limit:
            return False
        self.fail(failure)
        return True

    @property
    def steering_pending(self) -> bool:
        return self.ex.steering is not None and self.ex.steering.pending

    def take_steering(self) -> list[dict] | None:
        """Owner clarifications void every visual witness not yet consumed."""
        if not self.steering_pending:
            return None
        clarifications = self.ex.steering.take()
        self.ex.pending_observation_lease = self.ex.pending_response_observation = None
        discard_consumed_images(self.ex.messages)
        return clarifications

    def rotate(self) -> None:
        """Bind pending visual witnesses to exactly the next model response."""
        ex = self.ex
        ex.response_observation_lease, ex.pending_observation_lease = ex.pending_observation_lease, None
        ex.response_completion_observation, ex.pending_response_observation = ex.pending_response_observation, None
        ex.ctx.pop("_computer_response_observation", None)

    def discard_witnesses(self) -> None:
        ex = self.ex
        ex.response_observation_lease = ex.response_completion_observation = None
        ex.pending_observation_lease = ex.pending_response_observation = None
        discard_consumed_images(ex.messages)

    def emit_model(self, line: str, phase: str, fields: dict, detail=None, **payload) -> None:
        self.ex.emit("model", line, detail, {**fields, "payload": {
            "kind": "model", "phase": phase, "model": self.ex.model.id, **payload}})

    def discard_observation(self) -> None:
        self.images.clear()
        self.discard_witnesses()

    # Tool policy -------------------------------------------------------
    async def before_tool_callback(self, *, tool, tool_args, tool_context):
        return self.admit(tool.name, tool_args)

    def admit(self, name: str, args: dict) -> dict | None:
        """Policy before dispatch; a returned response answers the call without an effect."""
        self.last_search_refs = None
        foreground_checkpoint(self.interruption_event, self.ctx)
        if self.ex.step >= self.max_steps and not self.ex.done:
            self.fail('Decision budget exhausted without an accepted completion' if self.task_mode
                            else 'Executive operation budget exhausted')
        if self.ex.done:
            return _text('Activation already settled; no further effect is dispatched.')
        if self.steering_pending:
            self.discard_observation()
            return _text('Response superseded by a current owner clarification; no Tool dispatched.')
        if name not in self.ex.allowed or (self.task_mode and name not in self.decision):
            self.discard_observation()
            self.trace.append({'invalid_tool': name, 'not_dispatched': True,
                               'obs': 'Capability unavailable at this boundary'})
            self.strike('invalid', 'Three invalid or unavailable native Tool calls')
            return _text(unavailable_text(self.decision if self.task_mode else self.ex.allowed))
        if diagnostic := argument_diagnostic(name, args):
            self.discard_observation()
            self.trace.append({'invalid_tool': name, 'not_dispatched': True, 'obs': diagnostic})
            self.emit('error', f'{name} arguments rejected before dispatch', [diagnostic])
            self.strike('invalid', 'Three invalid native Tool calls; no effect dispatched')
            return _text(diagnostic)
        self.strikes['invalid'] = 0
        return None

    async def dispatch(self, name: str, args: dict) -> dict:
        """One admitted call through the capability core; rendered as the Tool result."""
        from .. import executor
        async with self._calls:  # One Tool at a time, like the native single-call step.
            if self.evaluation is not None:
                return await self._simulate(name, args)
            if self.lease_prefetch is not None:
                # Model-resource Tools release it through the core.
                self.ex.model, self.ex.active_lease = await self.adopt_lease()
            # Only receipts newly produced by this exact successful search may
            # supply read candidates. Old or failed search prose is never parsed.
            queries = ([args.get('query')] if 'query' in args else args.get('queries', [])) if name == 'vault.search' else []
            previous = {query: self.ctx.get('_vault_searches', {}).get(query) for query in queries}
            blocked = self._repeat_blocked(name, args) if self.task_mode and name != 'task.complete' else None
            outcome = await run_capability(
                self.ex, name, args, execute=executor.execute_capability,
                execute_async=executor.execute_capability_async, scope_checkpoint=executor._scope_checkpoint,
                blocked=blocked)
            if queries:
                current = self.ctx.get('_vault_searches', {})
                fresh = [current.get(query) for query in queries]
                if all(isinstance(row, dict) and row is not previous[query] and isinstance(row.get('refs'), list)
                       for query, row in zip(queries, fresh)):
                    self.last_search_refs = [ref for row in fresh for ref in row['refs']]
            self.ex.step += 1
            if name == 'task.complete' and not self.ex.done:
                self.strike('completion', 'Three rejected completion attempts')
            elif name != 'task.complete':
                self.strikes['completion'] = 0
            if outcome.kind in {'completed', 'waiting'}:
                return _text(json.dumps(self.ctx.get('completion') or {'status': self.ex.status}))
            blocks = [{'type': 'text', 'text': observation_text(
                outcome.observation, self._budget_nudge() if outcome.kind == 'returned' else '')}]
            if outcome.image_png is not None:
                self.ex.visual_context_seen = True
                raw = outcome.image_png
                identifier = hashlib.sha256(raw).hexdigest()
                self.images[identifier] = 'data:image/png;base64,' + base64.b64encode(raw).decode('ascii')
                blocks.append({'type': 'image', 'attachment': {
                    'attachmentId': identifier, 'mediaType': 'image/png', 'bytes': len(raw),
                    'width': int.from_bytes(raw[16:20], 'big'), 'height': int.from_bytes(raw[20:24], 'big')}})
            return {'content': blocks}

    async def _simulate(self, name: str, args: dict) -> dict:
        """An evaluation trial's answer to one admitted call; the model still chose it."""
        started = time.monotonic()
        result = await self.evaluation.handle(name, deepcopy(args))
        self.ex.step += 1
        self.trace.append({'tool': name, 'args': deepcopy(args), 'obs': result.get('observation', ''),
                           'simulated': True, **({'completion_evidence': result['completion_evidence']}
                                               if 'completion_evidence' in result else {})})
        self.emit('tool', name + ' returned', fields={'step': self.ex.step, 'payload': {
            'kind': 'tool', 'name': name, 'phase': 'result', 'status': 'returned',
            'arguments': args, 'result': result.get('observation', ''),
            'duration_ms': round((time.monotonic() - started) * 1000, 3)}})
        if result.get('done'):
            self.ex.done = True
            self.ex.status, self.ex.summary = result['status'], result['summary']
        if self.task_mode:
            # The specialist protocol renders frozen results as live ones.
            return _text(observation_text(result.get('observation', ''), self._budget_nudge()))
        return _text(result.get('observation', ''))

    def _budget_nudge(self) -> str:
        """A specialist Tool result names the model decisions that remain."""
        return '\n\n' + step_budget_notice(self.max_steps - self.model_steps) if self.task_mode else ''

    def _repeat_blocked(self, name: str, args: dict) -> tuple[str, dict] | None:
        """A specialist's third identical call is refused before dispatch.

        Returns the refusal observation and its trace fields, or None.
        """
        call_sig = f"{name}:sha256:" + hashlib.sha256(json.dumps(args, sort_keys=True).encode()).hexdigest()
        repeats = 0
        reads = self.ctx.get('_article_reads', {})
        for item in self.trace:
            if (name == 'harness.status' and item.get('tool') == 'harness.repair'
                    and item.get('not_dispatched') is not True):
                # A recovery consumes its inspection and requires a new one.
                # Count duplicate reads only since the last attempted repair.
                repeats = 0
            if item.get('sig') != call_sig or item.get('repeat_blocked'):
                continue
            required = item.get('proposal_read_prerequisite')
            # Only an attested pre-staging rejection can stop counting as a
            # repeat, and only after its exact missing revisions were read.
            if (name == 'vault.propose' and isinstance(required, dict) and required
                    and all(reads.get(ref, {}).get('complete') is True
                            and reads[ref].get('article_sha256') == revision
                            for ref, revision in required.items())):
                continue
            repeats += 1
        # A state-scoped observation and Hindsight recovery legitimately repeat:
        # live evidence may have changed, and each recovery pass selects the
        # next unattempted native operation from a fresh inspection.
        if (repeats < 2 or (name == 'computer.observe' and self.ctx.get('_computer_act_scope') == 'state')
                or (name == 'harness.repair' and args == {'component': 'hindsight'}
                    and self.task.ref == 'Tasks/repair' and isinstance(self.ctx.get('_harness_snapshot'), dict))):
            return None
        observation = ('You have repeated this exact call three times; the result will not change. '
                       'Vary your approach or call task.complete now with your best status.')
        if name == 'vault.propose' and self.ctx.get('_link_proposal_rejection'):
            observation = ('The same Link proposal was rejected twice. Finish failed with the unresolved '
                           'blocker: ' + self.ctx['_link_proposal_rejection']
                           + '. A rejected draft is not evidence of a redundant relationship.')
            # The model has already ignored the same rejection twice. End this
            # attempt; completion retains the real blocker and ordinary
            # receipt-bound recovery owns any later retry.
            self.ex.allowed = ['task.complete']
        return observation, {'repeat_blocked': True, 'not_dispatched': True}

    def _decision_tools(self) -> tuple[list[str], dict]:
        """This Task step's Tools and the active proposal/completion schema modes."""
        from ...capabilities.source.read import available_tools
        from ...capabilities.task.complete import (
            available_tools as completion_tools, completion_prerequisite_error, completion_requires_no_change,
        )
        from ..repair import available_tools as repair_tools
        context = getattr(self.evaluation, 'schema_context', self.ctx)
        names = completion_tools(repair_tools(available_tools(self.ex.allowed, context), context), context)
        if context.get('task') == 'Tasks/audit' and (context.get('params') or {}).get('optimization_case'):
            required = 'task.complete' if context.get('_harness_optimization_attempted') else 'harness.optimize'
            names = [name for name in names if name == required]
        modes = {
            'proposal_mode': ('ingest' if context.get('event') == 'observations.memory.ready'
                              or context.get('task') == 'Tasks/ingest'
                              else 'link' if context.get('task') == 'Tasks/link' else ''),
            'completion_no_change': completion_requires_no_change(context) and not self.task.meta.get('acceptance'),
            'completion_blocked': bool(completion_prerequisite_error(context)),
        }
        return names, modes

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
        # An accepted completion on the last step stands; only unfinished work fails.
        if not self.ex.done and (self.model_steps >= self.max_steps or self.ex.step >= self.max_steps):
            self.fail('Decision budget exhausted without an accepted completion' if self.task_mode
                            else 'Executive decision budget exhausted')
        return self.ex.done or self.steering_pending

    async def before_model_callback(self, *, callback_context, llm_request):
        if self.boundary():
            # No content and no error: ADK ends this invocation without an
            # event. The controller then settles or applies the clarification.
            return LlmResponse()
        self.model_steps += 1
        self.rotate()
        await self.hold_model(self.adopt_lease)
        fields = {'step': self.ex.step + 1, 'call_id': f'{self.run}:model:{self.model_steps}'}
        self.emit_model(f'{self.agent_name} model started', 'started', fields, engine=sessions.BACKEND)
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
        if self.task_mode:
            # Advertise only this step's Tools, shaped by its active contract.
            names, modes = self._decision_tools()
            self.decision = list(names)
            schemas = task_tool_schemas(names, **modes)
            llm_request.config.tools = [types.Tool(function_declarations=[types.FunctionDeclaration(
                name=schema['name'], description=schema['description'],
                parameters_json_schema=schema['parameters']) for schema in schemas])]
            # Every Task decision is one Tool call: the engine's grammar requires
            # a call to one advertised Tool (reasoning may precede it).
            llm_request.config.tool_config = types.ToolConfig(function_calling_config=types.FunctionCallingConfig(
                mode=types.FunctionCallingConfigMode.ANY))
        else:
            schemas = tool_schemas(self.advertised)
        payload = native.request_payload(wire, self.spec, self.effort, schemas, task=self.task_mode)
        if (captured := getattr(self.evaluation, 'wire_messages', None)) is not None:
            # A contract trial evaluates the exact captured provider prompt, which
            # already carries its model-family guidance; never append it twice.
            payload['messages'] = deepcopy(captured)
            if self.task_mode:
                # As the specialist loop always did, the trial's own decision
                # budget follows the captured prompt.
                payload['messages'].append({'role': 'user', 'content': step_budget_notice(self.max_steps)})
        menu = None
        if self.fast_lane:
            from ..fast_lane import candidates
            menu = candidates(self.ctx['objective'], self.ex.allowed, first_step=self.model_steps == 1,
                              search_refs=self.last_search_refs, trace=self.trace,
                              steering=self.steered or self.steering_pending)
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
                    text, nudge = native.split_budget_notice(row['content'].removeprefix('Observation:\n'))
                    projection.remember_source_page(
                        index, name, text, nudge,
                        source_read_allowed='source.read' in self.ex.allowed if self.task_mode else True)
                    projection.remember_article_page(
                        index, name, text, nudge,
                        vault_read_allowed='vault.read' in self.ex.allowed if self.task_mode else True)
            started = time.monotonic()
            capacity = self.spec.context_tokens - self.spec.max_output_tokens - PROMPT_SAFETY_TOKENS
            count = await projection.fit_payload(payload, self.spec, client, capacity)
            metrics.update(prompt_tokens=count.tokens, preflight_ms=round((time.monotonic() - started) * 1000, 3))
            if 'before_input_tokens' in projection.last_projection:
                self.trace.append({'context_projection': projection.last_projection})
        self.ex.decision_messages[:] = deepcopy(payload['messages'])
        llm_request.config.system_instruction = payload['messages'][0]['content']
        llm_request.contents = request_contents(payload['messages'][1:])
        # Foreground demand that arrived during preparation wins over a new request.
        foreground_checkpoint(self.interruption_event, self.ctx)
        sessions.ADMISSION.set(metrics)
        self._step['dispatched'] = time.monotonic()
        self.generating.set()
        return None

    async def after_model_callback(self, *, callback_context, llm_response):
        step = self._step
        if step is None:
            return None
        parts = llm_response.content.parts if llm_response.content and llm_response.content.parts else []
        if llm_response.partial:
            text = ''.join(value.text for value in parts if value.text and not value.thought)
            if ((text or any(value.function_call for value in parts))
                    and 'first_public_delta_ms' not in step['metrics']):
                step['metrics']['first_public_delta_ms'] = round((time.monotonic() - step['dispatched']) * 1000, 3)
            if text and self.voice is not None:
                await self.voice.feed({'type': 'text-delta', 'text': text})
            return None
        if any(value.thought for value in parts):
            # Private reasoning never enters the conversation log or history.
            kept = [value for value in parts if not value.thought]
            llm_response = llm_response.model_copy(update={
                'content': types.Content(role='model', parts=kept) if kept else None})
            await self._finish_step(llm_response)
            return llm_response
        await self._finish_step(llm_response)
        return None

    async def _finish_step(self, response: LlmResponse, *, from_choice: bool = False) -> None:
        self.generating.clear()
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
            if (text or calls) and 'first_public_delta_ms' not in metrics:
                # A Tool call LiteLLM delivers whole is first public output when it arrives.
                metrics['first_public_delta_ms'] = metrics['generation_ms']
        self.images.clear()
        discard_consumed_images(self.ex.messages)
        if self.model_steps == 1:
            self.ctx['prompt_tokens'] = metrics.get('prompt_tokens', 0)
        self.trace.append({'provider_metrics': metrics})
        adopt_fast_lane(step['menu'], metrics, self.ctx)
        self.emit_model(f'{self.agent_name} model returned', 'result', step['fields'], metrics=metrics)
        if self.voice is not None:
            if calls:
                await self.voice.feed({'type': 'block-start', 'blockType': 'tool-call'})
            await self.voice.feed({'type': 'finish', 'reason': reason})
        if response.error_code and reason == 'error':
            # A malformed native call never reaches a Tool; the model corrects it.
            self.trace.append({'native_tool_error': str(response.error_code)[:80], 'invalid_tool': 'native Tool'})
            self.emit('error', f'native Tool: {response.error_code}')
            if not self.strike('invalid', 'Three native Tool errors; inspect the Action Trace'):
                self.feedback = (str(response.error_message or 'The last native Tool call was malformed.')[:300]
                                 + (' No Tool was dispatched; send one complete native call.' if self.task_mode
                                    else ' No Tool was dispatched; send one complete native call or answer in text.'))
            return
        if self.task_mode:
            # Every specialist decision is one Tool call; text never completes a Task.
            if calls:
                self.strikes['action'] = 0
                self.feedback = None
                return
            self.trace.append({'invalid_native_response': 'no_tool_call', 'finish_reason': reason})
            if self.strike('action', 'three consecutive replies without a valid action block'):
                self.emit('error', f'{self.agent_name} produced no valid action', [self.ex.summary, reason])
                return
            self.feedback = NO_TOOL_CALL_FEEDBACK
            return
        self.feedback = await settle_model_step(self, self.operate, text, bool(calls), reason,
                                                allowed=self.advertised, ctx=self.ctx, trace=self.trace,
                                                emit=self.emit, voice=self.voice)

    async def release(self) -> None:
        """Release what this activation acquired: an unadopted reservation and its lease."""
        self.generating.clear()
        self.images.clear()
        if self.lease_prefetch is not None:
            # An unadopted reservation never outlives its activation.
            self.lease_prefetch.cancel()
            await asyncio.wait([self.lease_prefetch])
            if not self.lease_prefetch.cancelled() and self.lease_prefetch.exception() is None:
                await self.lease_prefetch.result()[1].__aexit__(None, None, None)
            self.lease_prefetch = None
        # End the activation: drop its context and witnesses, then release the model.
        for key in ("_foreground_interruption_event", OBSERVATION_CONTEXT_FIELD, "_computer_response_observation"):
            self.ctx.pop(key, None)
        self.ex.latest_action_evidence = None
        self.discard_witnesses()
        lease, self.ex.active_lease = self.ex.active_lease, None
        if lease is not None:
            started = time.monotonic()
            await lease.__aexit__(None, None, None)
            action_trace.latency("model_release", duration_ms=(time.monotonic() - started) * 1000)

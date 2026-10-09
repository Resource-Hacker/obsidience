"""Native Executive activation. The upstream agent-loop chooses and sequences Tools."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import time
import uuid
from copy import deepcopy

from .bridge import BRIDGE
from .. import native as native_model
from ..native_turn import (
    argument_diagnostic, command_summary, cue_only, settle_model_step, steering_context, tool_schemas, turn_recall, unavailable_text,
)
from ...config import CONFIG
from ...models.context import TaskContext, discard_consumed_images

async def run_native_session(task, model, messages, allowed, ctx, agent_name, effort,
                             interruption_event=None, *, initial_lease=None, evaluation=None,
                             fast_lane=True):
    from ..executor import CapabilityDispatch, TurnState, _scope_checkpoint, _foreground_checkpoint

    if evaluation is not None and (ctx or initial_lease is not None):
        raise ValueError('Native evaluation requires a fresh context and its own model lease')
    max_steps = TurnState.budget(evaluation)
    if evaluation is not None:
        ctx.update(run_id='trial-' + uuid.uuid4().hex, objective=evaluation.case['objective'])
    emit = TurnState.emitter(evaluation)

    await BRIDGE.start()
    run = ctx['run_id']
    queue = asyncio.Queue()
    BRIDGE.runs[run] = queue
    trace = ctx.setdefault('trace', [])
    state = TurnState(CapabilityDispatch(task, model, [], allowed, ctx, agent_name, 0, trace,
                                         emit, TaskContext(), max_steps,
                                         interruption_event=interruption_event,
                                         steering=ctx.get('_steering'), active_lease=initial_lease))
    dispatch = state.dispatch
    dispatch.decision_messages = []
    dispatch.prompt_format = 'native_wire'
    images = {}
    ended = False
    model_steps = 0
    last_search_refs = None
    steered = False
    ctx['_foreground_interruption_event'] = interruption_event
    for key in ('_reflex_proposal', '_reflex_command_verified', '_reflex_command_result', '_voice_confirmation'):
        ctx.pop(key, None)
    ctx.pop('_computer_observation_lease', None)

    command = None
    params = ctx.get('params') or {}
    if (evaluation is None and task.ref == 'Agents/Executive/Executive'
            and task.kind == 'agent' and params.get('conversation_id')
            and params.get('reply_to_turn_id') and params.get('event') != 'task.continue'
            and effort == 'none' and initial_lease is None and not trace
            and not (dispatch.steering is not None
                     and (dispatch.steering.pending or dispatch.steering.applied))):
        from ..commands import recognize_command
        command = recognize_command(ctx['objective'], allowed)
        if command is not None:
            ctx['_reflex_proposal'] = deepcopy(command)
            trace.append({'command_route': 'hassil', 'proposal': deepcopy(command),
                          'model_requests': 0, 'memory_recalls': 0})

    # Executive voice turns may voice claim-checked sentences before completion
    # acceptance (owner decision 2026-10-08); the speech owner binds the turn.
    voice = None
    if (evaluation is None and command is None and task.kind == 'agent'
            and task.ref == 'Agents/Executive/Executive' and params.get('event') == 'voice.activation'
            and CONFIG.extras.get('realtime_early_speech', True) is not False):
        from ...capabilities.task.complete import public_claim_error
        from ...conversation.runtime import RUNTIME as conversation
        if conversation.speech is not None:
            voice = conversation.speech.provisional_reply(run, lambda text: public_claim_error(text, ctx))

    async def reply(message, value=None, *, error=None, code=None, done=False):
        await BRIDGE.send({'id': message['id'], 'result': value, 'error': error, 'code': code, 'done': done})

    lease_prefetch = None

    async def adopt_lease():
        # Adopt the reservation requested at activation start, or acquire it now.
        nonlocal lease_prefetch
        pending, lease_prefetch = lease_prefetch, None
        if pending is None:
            return await TurnState.acquire_model(model)
        try:
            return await asyncio.shield(pending)
        except BaseException:
            lease_prefetch = pending  # The finally block cancels or releases it.
            raise

    def discard_observation():
        images.clear()
        state.discard_witnesses()

    async def operate(name, args):
        nonlocal last_search_refs
        last_search_refs = None
        _foreground_checkpoint(interruption_event, ctx)
        if dispatch.step >= max_steps:
            state.fail('Executive operation budget exhausted')
        if dispatch.done:
            return [{'type': 'text', 'text': 'Activation already settled; no further effect is dispatched.'}]
        if state.steering_pending:
            discard_observation()
            return [{'type': 'text', 'text': 'Response superseded by a current owner clarification; no Tool dispatched.'}]
        if name not in dispatch.allowed:
            discard_observation()
            trace.append({'invalid_tool': name, 'not_dispatched': True, 'obs': 'Capability unavailable at this boundary'})
            state.strike('invalid', 'Three invalid or unavailable native Tool calls')
            return [{'type': 'text', 'text': unavailable_text(dispatch.allowed)}]
        if diagnostic := argument_diagnostic(name, args):
            discard_observation()
            trace.append({'invalid_tool': name, 'not_dispatched': True, 'obs': diagnostic})
            emit('error', f'{name} arguments rejected before dispatch', [diagnostic])
            state.strike('invalid', 'Three invalid native Tool calls; no effect dispatched')
            return [{'type': 'text', 'text': diagnostic}]
        state.strikes['invalid'] = 0
        if evaluation is not None:
            # The native agent still selects and sequences every call. Only its
            # effect boundary is replaced; no live dispatch, receipt or writeback.
            started = time.monotonic()
            result = await evaluation.handle(name, deepcopy(args))
            dispatch.step += 1
            trace.append({'tool': name, 'args': deepcopy(args), 'obs': result.get('observation', ''),
                          'simulated': True, **({'completion_evidence': result['completion_evidence']}
                                              if 'completion_evidence' in result else {})})
            emit('tool', name + ' returned', fields={'step': dispatch.step, 'payload': {
                'kind': 'tool', 'name': name, 'phase': 'result', 'status': 'returned',
                'arguments': args, 'result': result.get('observation', ''),
                'duration_ms': round((time.monotonic() - started) * 1000, 3)}})
            if result.get('done'):
                dispatch.done = True
                dispatch.status, dispatch.summary = result['status'], result['summary']
            return [{'type': 'text', 'text': result.get('observation', '')}]
        if lease_prefetch is not None:
            # Model-resource Tools release it through dispatch.
            dispatch.model, dispatch.active_lease = await adopt_lease()
        before = len(dispatch.messages)
        # Only receipts newly produced by this exact successful search may
        # supply read candidates. Old or failed search prose is never parsed.
        queries = ([args.get('query')] if 'query' in args else args.get('queries', [])) if name == 'vault.search' else []
        previous_searches = {query: ctx.get('_vault_searches', {}).get(query) for query in queries}
        await dispatch.dispatch(name, args, json.dumps({'tool': name, 'args': args}))
        if queries:
            current_searches = ctx.get('_vault_searches', {})
            fresh = [current_searches.get(query) for query in queries]
            if all(isinstance(row, dict) and row is not previous_searches[query]
                   and isinstance(row.get('refs'), list) for query, row in zip(queries, fresh)):
                last_search_refs = [ref for row in fresh for ref in row['refs']]
        dispatch.step += 1
        if name == 'task.complete' and not dispatch.done:
            state.strike('completion', 'Three rejected completion attempts')
        elif name != 'task.complete':
            state.strikes['completion'] = 0
        rows = dispatch.messages[before:]
        content = rows[-1]['content'] if rows and rows[-1]['role'] == 'user' else json.dumps(ctx.get('completion') or {'status': dispatch.status})
        if isinstance(content, str):
            return [{'type': 'text', 'text': content}]
        blocks = []
        for part in content:
            if part['type'] == 'text':
                blocks.append(part)
            elif part['type'] == 'image_url':
                url = part['image_url']['url']
                raw = base64.b64decode(url.split(',', 1)[1], validate=True)
                identifier = hashlib.sha256(raw).hexdigest()
                images[identifier] = url
                blocks.append({'type': 'image', 'attachment': {
                    'attachmentId': identifier, 'mediaType': 'image/png', 'bytes': len(raw),
                    'width': int.from_bytes(raw[16:20], 'big'), 'height': int.from_bytes(raw[20:24], 'big')}})
        return blocks

    try:
        session_config = {}
        params = ctx.get('params') or {}
        if evaluation is None and task.kind == 'agent' and params.get('conversation_id'):
            from . import sessions
            session_config = {'session_id': params['conversation_id'],
                              'window_anchor': sessions.window_anchor(params['conversation_id']),
                              'turn_id': params['reply_to_turn_id'], 'objective': ctx['objective'],
                              'continuation': params.get('event') == 'task.continue',
                              **sessions.bootstrap(params['conversation_id'], params['reply_to_turn_id'])}
        if session_config and command is None and dispatch.active_lease is None:
            # The first native step always needs this model. Reserve it while
            # the agent loop starts and recalls memory, not after the recall.
            lease_prefetch = asyncio.create_task(TurnState.acquire_model(model))
        await BRIDGE.send({'method': 'start', 'params': {
            **session_config,
            **({'command': command} if command is not None else {}),
            'run': run, 'cwd': str(CONFIG.project_root), 'effort': effort,
            'system': messages[0]['content'], 'messages': messages[1:],
            'tools': tool_schemas(allowed),
            'model': {'id': model.id, 'context_tokens': model.context_tokens,
                      'max_output_tokens': model.max_output_tokens, 'capabilities': list(model.capabilities)},
        }})
        while True:
            message = await queue.get()
            method = message.get('method')
            if method == 'end':
                ended = True
                from .sessions import publish
                publish(message.get('session'))
                if message.get('error'):
                    raise RuntimeError(message['error'])
                break
            _foreground_checkpoint(interruption_event, ctx)
            _scope_checkpoint(ctx)
            if method == 'boundary':
                if model_steps >= max_steps or dispatch.step >= max_steps:
                    state.fail('Executive decision budget exhausted')
                context = ''
                if (clarifications := state.take_steering()) is not None:
                    steered = True
                    last_search_refs = None
                    context = steering_context(clarifications)
                    images.clear()
                await reply(message, {'done': dispatch.done, 'context': context})
            elif method == 'settlement':
                await reply(message, {'status': dispatch.status, 'summary': dispatch.summary})
            elif method == 'command_complete':
                if command is None:
                    raise RuntimeError('No explicit command owns this completion')
                if command['name'] == 'task.complete':
                    # Informational replies already crossed the completion
                    # authority once. Keep them spoken, without effect cues.
                    if message['params'].get('isError') is True or not dispatch.done:
                        raise RuntimeError('Explicit informational completion was not accepted')
                    await reply(message, {'status': dispatch.status, 'summary': dispatch.summary})
                    continue
                verified = (ctx.get('_reflex_command_verified') is True
                            and message['params'].get('isError') is not True)
                summary = command_summary(command, verified, ctx.get('_reflex_command_result'))
                # The same completion authority accepts public text and status.
                # A failure never returns to generation or replays the effect.
                await operate('task.complete', {
                    'status': 'completed' if verified else 'failed', 'summary': summary})
                if not dispatch.done:
                    raise RuntimeError('Explicit command completion was not accepted')
                await reply(message, {'status': dispatch.status, 'summary': dispatch.summary})
            elif method == 'memory.recall':
                await reply(message, await turn_recall(
                    ctx, message['params']['query'], emit=emit, run=run, evaluation=evaluation,
                    context_text=messages[1]['content'] if len(messages) > 1 else ''))
            elif method == 'tool':
                params = message['params']
                try:
                    result = await operate(params['name'], params['args'])
                except Exception as exc:
                    # Authority/receipt faults terminate; they cannot become retryable model observations.
                    await reply(message, error=type(exc).__name__)
                    raise
                await reply(message, result)
            elif method == 'tool_error':
                last_search_refs = None
                discard_observation()
                name = str(message['params'].get('name') or 'native Tool')[:96]
                code = str(message['params'].get('code') or 'TOOL_ERROR')[:80]
                trace.append({'native_tool_error': code, 'invalid_tool': name})
                emit('error', f'{name}: {code}')
                state.strike('invalid', 'Three native Tool errors; inspect the Action Trace')
            elif method == 'model':
                compacting = message['params'].get('purpose') == 'compaction'
                if compacting:
                    # Native compaction owns this auxiliary inference. It must
                    # never consume a visual lease or become spoken completion.
                    if dispatch.active_lease is None:
                        dispatch.model, dispatch.active_lease = await adopt_lease()
                    emit('event', 'Compacting native conversation', fields={'payload': {
                        'kind': 'compaction', 'phase': 'started', 'engine': 'deepseek'}})
                    metrics = {}
                    try:
                        await native_model.stream(message['params'], dispatch.model, 'none', images,
                                                  lambda value: reply(message, value), metrics)
                    except Exception as exc:
                        await reply(message, error=type(exc).__name__ + ': ' + str(exc)[:300])
                    else:
                        trace.append({'compaction_metrics': metrics})
                        await reply(message, done=True)
                    continue
                model_steps += 1
                state.rotate()
                await state.hold_model(adopt_lease)
                fields = {'step': dispatch.step + 1, 'call_id': f'{run}:model:{model_steps}'}
                state.emit_model(f'{agent_name} model started', 'started', fields, engine='deepseek')
                metrics = {}
                terminal = None
                if voice is not None:
                    # A verified reflex command keeps cue-only confirmation.
                    voice.begin_step(eligible=ctx.get('_reflex_command_verified') is not True)
                async def chunk(value):
                    nonlocal terminal
                    if value['type'] == 'finish': terminal = value
                    else: await reply(message, value)
                    if voice is not None:
                        await voice.feed(value)
                try:
                    from ..fast_lane import candidates
                    menu = (candidates(ctx['objective'], dispatch.allowed,
                                       first_step=model_steps == 1, search_refs=last_search_refs,
                                       trace=trace,
                                       steering=steered or state.steering_pending)
                            if fast_lane and task.kind == 'agent'
                            and task.ref == 'Agents/Executive/Executive' else None)
                    last_search_refs = None
                    # Keep the session's advertised schemas byte-stable. Gemma
                    # renders them at the start of the prompt, so narrowing them
                    # after a failed effect re-evaluated the whole conversation.
                    # operate() still rejects every call outside dispatch.allowed.
                    text, has_calls, reason, projection = await native_model.stream(
                        message['params'],
                        dispatch.model, effort, images, chunk, metrics,
                        objective=ctx['objective'], decision_messages=dispatch.decision_messages,
                        evaluation_messages=getattr(evaluation, 'wire_messages', None),
                        fast_candidates=menu)
                    _foreground_checkpoint(interruption_event, ctx)
                except Exception as exc:
                    from ...models.context import ContextBudgetExceeded
                    if isinstance(exc, ContextBudgetExceeded) and exc.accounting == 'runtime':
                        await reply(message, error=str(exc), code='CONTEXT_WINDOW_EXCEEDED')
                        continue  # Upstream compaction decides whether one recovery is possible.
                    await reply(message, error=type(exc).__name__ + ': ' + str(exc)[:300])
                    raise
                finally:
                    images.clear()
                    discard_consumed_images(dispatch.messages)
                if model_steps == 1:
                    ctx['prompt_tokens'] = metrics['prompt_tokens']
                trace.append({'provider_metrics': metrics})
                detail = metrics.get('fast_lane') or {}
                label = detail.get('selected_label', '')
                if (menu and detail.get('status') == 'selected' and len(label) == 1
                        and 0 <= ord(label) - ord('B') < len(menu)):
                    proposal = menu[ord(label) - ord('B')]
                    if proposal['name'] in {'lights.set', 'application.launch', 'session.unlock'}:
                        ctx['_reflex_proposal'] = deepcopy(proposal)
                state.emit_model(f'{agent_name} model returned', 'result', fields, metrics=metrics)
                if 'before_input_tokens' in projection:
                    trace.append({'context_projection': projection})
                feedback = await settle_model_step(state, operate, text, has_calls, reason,
                                                   allowed=allowed, ctx=ctx, trace=trace, emit=emit, voice=voice)
                if feedback is not None:
                    # The upstream inbox owns the next decision after a rejected
                    # completion or an empty response.
                    await BRIDGE.send({'method': 'context', 'run': run, 'text': feedback})
                await reply(message, terminal)
                await reply(message, done=True)
        if cue_only(dispatch.status, ctx, steered, trace):
            ctx['_voice_confirmation'] = 'cue_only'
        return trace, dispatch.status, dispatch.summary
    finally:
        try:
            if not ended:
                await BRIDGE.send({'method': 'cancel', 'run': run})
                # Drain this exact upstream activation before releasing its model resource.
                try:
                    async with asyncio.timeout(5):
                        while True:
                            pending = await queue.get()
                            if pending.get('method') == 'end':
                                from .sessions import publish
                                publish(pending.get('session'))
                                break
                            if pending.get('method') == 'settlement':
                                await reply(pending, {'status': 'interrupted', 'summary': ''})
                except TimeoutError:
                    await BRIDGE.close()
        finally:
            BRIDGE.runs.pop(run, None)
            images.clear()
            if lease_prefetch is not None:
                # An unadopted reservation never outlives its activation.
                lease_prefetch.cancel()
                await asyncio.wait([lease_prefetch])
                if not lease_prefetch.cancelled() and lease_prefetch.exception() is None:
                    await lease_prefetch.result()[1].__aexit__(None, None, None)
            await state.close(measure_release=True)

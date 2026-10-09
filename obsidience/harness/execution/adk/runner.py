"""ADK Executive activation: same contract as ``deepseek.runner.run_native_session``.

ADK's Runner sequences model steps and Tools and appends session events. The
controller here starts each invocation with the turn's message (runtime
context, owner request, recall), and continues the same turn with a new
invocation only for owner clarifications or controller feedback (a rejected
completion, an empty or malformed step). Explicit HassIL commands bypass the
model and append their exact records to the same conversation log.
"""
from __future__ import annotations

import asyncio
import json
from copy import deepcopy

from google.genai import types

from . import sessions
from .plugin import ExecutivePlugin
from .tools import capability_tools
from ..native_turn import command_summary, cue_only, steering_context, tool_schemas, turn_recall
from ...config import CONFIG

EXECUTIVE = 'Agents/Executive/Executive'
COMMANDS = ('lights.set', 'tv.control', 'media.pause', 'task.complete')


async def _run_command(plugin: ExecutivePlugin, command: dict, session_id: str, turn_id: str) -> None:
    """Controller-owned execution of one exact command; never a fabricated model span."""
    ex, ctx, run = plugin.ex, plugin.ctx, plugin.run
    await sessions.append(session_id, run, [
        sessions.part(ctx['objective'], 'user', id=turn_id, run=run),
        sessions.part(json.dumps({
            'status': 'started', 'command': command, 'run_id': run, 'reply_to': turn_id,
            'instruction': 'Controller command admitted. A missing outcome means unknown delivery; never replay it.',
        }), 'plugin:obsidience.command', run=run)])
    result = None
    try:
        result = await plugin.operate(command['name'], command['args'])
        if command['name'] == 'task.complete':
            # Informational replies already crossed the completion authority once.
            if not ex.done:
                raise RuntimeError('Explicit informational completion was not accepted')
        else:
            verified = ctx.get('_reflex_command_verified') is True
            summary = command_summary(command, verified, ctx.get('_reflex_command_result'))
            # The same completion authority accepts public text and status.
            # A failure never returns to generation or replays the effect.
            await plugin.operate('task.complete', {'status': 'completed' if verified else 'failed',
                                                   'summary': summary})
            if not ex.done:
                raise RuntimeError('Explicit command completion was not accepted')
        record = {'status': ex.status, 'summary': ex.summary}
    except BaseException as exc:
        record = {'status': 'interrupted' if isinstance(exc, asyncio.CancelledError) else 'failed',
                  'summary': '', 'must_not_replay': True,
                  'instruction': 'Controller command did not settle. Use its existing receipt; do not infer or replay delivery.'}
        raise
    finally:
        await sessions.append(session_id, run, [sessions.part(json.dumps({
            **record, 'command': command, 'result': result, 'run_id': run, 'reply_to': turn_id,
        }), 'plugin:obsidience.command-outcome', run=run)])


async def _settle_interrupted(session_id: str, run: str, turn_id: str) -> None:
    await sessions.close_interrupted_calls(session_id, run)
    await sessions.append(session_id, run, [sessions.part(json.dumps({
        'status': 'interrupted', 'summary': '', 'run_id': run, 'reply_to': turn_id,
    }), 'plugin:obsidience.outcome', run=run)])


async def run_adk_session(task, model, messages, allowed, ctx, agent_name, effort,
                          interruption_event=None, *, initial_lease=None, evaluation=None,
                          fast_lane=True):
    if evaluation is not None:
        raise ValueError('Instruction evaluation trials still run on the DeepSeek loop')
    from google.adk.agents import LlmAgent
    from google.adk.agents.run_config import RunConfig, StreamingMode
    from google.adk.apps import App
    from google.adk.runners import Runner
    from ..commands import recognize_command
    from ..executor import TurnState

    plugin = ExecutivePlugin(task, model, allowed, ctx, agent_name, effort, system=messages[0]['content'],
                             interruption_event=interruption_event, initial_lease=initial_lease,
                             fast_lane=fast_lane)
    ex, state, trace, run = plugin.ex, plugin.state, plugin.trace, plugin.run
    ctx['_foreground_interruption_event'] = interruption_event
    for key in ('_reflex_proposal', '_reflex_command_verified', '_reflex_command_result', '_voice_confirmation'):
        ctx.pop(key, None)
    ctx.pop('_computer_observation_lease', None)
    params = ctx.get('params') or {}
    conversation_id = params.get('conversation_id') if task.kind == 'agent' else None
    continuation = params.get('event') == 'task.continue'

    command = None
    if (task.ref == EXECUTIVE and task.kind == 'agent' and conversation_id
            and params.get('reply_to_turn_id') and not continuation
            and effort == 'none' and initial_lease is None and not trace
            and not (ex.steering is not None and (ex.steering.pending or ex.steering.applied))):
        command = recognize_command(ctx['objective'], allowed)
        if command is not None:
            ctx['_reflex_proposal'] = deepcopy(command)
            trace.append({'command_route': 'hassil', 'proposal': deepcopy(command),
                          'model_requests': 0, 'memory_recalls': 0})

    # Executive voice turns may voice claim-checked sentences before completion
    # acceptance (owner decision 2026-10-08); the speech owner binds the turn.
    if (command is None and task.kind == 'agent' and task.ref == EXECUTIVE
            and params.get('event') == 'voice.activation'
            and CONFIG.extras.get('realtime_early_speech', True) is not False):
        from ...capabilities.task.complete import public_claim_error
        from ...conversation.runtime import RUNTIME as conversation
        if conversation.speech is not None:
            plugin.voice = conversation.speech.provisional_reply(run, lambda text: public_claim_error(text, ctx))

    session_id = conversation_id or run
    turn_id = params.get('reply_to_turn_id') if conversation_id else None
    runner = None
    settled = False
    try:
        session = await sessions.open_session(session_id, turn_id)
        if command is not None:
            settled = True  # The command records carry their own settlement.
            await _run_command(plugin, command, session_id, turn_id)
        else:
            if conversation_id and ex.active_lease is None:
                # The first step always needs this model. Reserve it while the
                # turn recalls memory, not after the recall.
                plugin.lease_prefetch = asyncio.create_task(TurnState.acquire_model(model))
            # One turn message: the compiler's runtime context, the owner request
            # (or continuation) and its recall; the projection orders them.
            if conversation_id:
                parts = [sessions.part(row['content'], 'plugin:obsidience.context', run=run) for row in messages[1:]]
                parts.append(sessions.part(ctx['objective'], 'plugin:obsidience.continuation', run=run)
                             if continuation else sessions.part(ctx['objective'], 'user', id=turn_id, run=run))
                query = ctx['objective']
            else:
                parts = [sessions.part(row['content'], 'user', run=run) for row in messages[1:]]
                query = messages[-1]['content']
            if not continuation:
                recalled = await turn_recall(ctx, query, emit=plugin.emit, run=run,
                                             context_text=messages[1]['content'] if len(messages) > 1 else '')
                if recalled['memories']:
                    parts.append(sessions.part(json.dumps(recalled, ensure_ascii=False, separators=(',', ':')),
                                               'plugin:obsidience.memory', run=run))
            agent = LlmAgent(name=sessions.AGENT, model=sessions.model(model, effort), instruction='',
                             tools=capability_tools(allowed, plugin),
                             disallow_transfer_to_parent=True, disallow_transfer_to_peers=True)
            runner = Runner(app=App(name=sessions.APP, root_agent=agent, plugins=[plugin]),
                            session_service=sessions.service())
            request = {'system': messages[0]['content'], 'tools': tool_schemas(allowed), 'effort': effort}
            delta = None if session.state.get(sessions.REQUEST_STATE) == request else {sessions.REQUEST_STATE: request}
            message = types.Content(role='user', parts=parts)
            while True:
                config = RunConfig(streaming_mode=StreamingMode.SSE,
                                   max_llm_calls=max(1, plugin.max_steps - plugin.model_steps + 1))
                async for _event in runner.run_async(user_id=sessions.USER, session_id=session_id,
                                                     new_message=message, state_delta=delta, run_config=config):
                    pass
                delta = None
                if ex.done:
                    break
                if (clarifications := state.take_steering()) is not None:
                    plugin.steered = True
                    plugin.last_search_refs = None
                    plugin.images.clear()
                    text = steering_context(clarifications)
                    turns = [turn['id'] for turn in clarifications]
                    message = types.Content(role='user', parts=[sessions.part(
                        text, 'plugin:obsidience.steering', run=run, turns=turns)])
                    continue
                if plugin.feedback is not None:
                    text, plugin.feedback = plugin.feedback, None
                    message = types.Content(role='user', parts=[sessions.part(
                        text, 'plugin:obsidience.steering', run=run)])
                    continue
                raise RuntimeError('Executive invocation ended without an accepted completion')
        if cue_only(ex.status, ctx, plugin.steered, trace):
            ctx['_voice_confirmation'] = 'cue_only'
        return trace, ex.status, ex.summary
    except RuntimeError as exc:
        # ADK wraps a plugin callback's exception; keep the original (for
        # example a scope PermissionError) as the activation's failure.
        if str(exc).startswith(f"Error in plugin '{plugin.name}'") and isinstance(exc.__cause__, Exception):
            raise exc.__cause__ from None
        raise
    except asyncio.CancelledError:
        if not settled and conversation_id:
            settled = True
            await asyncio.shield(_settle_interrupted(session_id, run, turn_id))
        raise
    finally:
        try:
            if not settled and conversation_id:
                await sessions.close_interrupted_calls(session_id, run)
                await sessions.append(session_id, run, [sessions.part(json.dumps({
                    'status': ex.status, 'summary': ex.summary, 'run_id': run, 'reply_to': turn_id,
                }), 'plugin:obsidience.outcome', run=run)])
        finally:
            try:
                await plugin.release()
            finally:
                if runner is not None:
                    await runner.close()
                if conversation_id:
                    await sessions.refresh(conversation_id)
                else:
                    await sessions.service().delete_session(app_name=sessions.APP, user_id=sessions.USER,
                                                            session_id=session_id)

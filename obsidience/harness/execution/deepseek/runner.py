"""Native Executive activation. The upstream agent-loop chooses and sequences Tools."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
from copy import deepcopy

from jsonschema import Draft202012Validator

from .bridge import BRIDGE
from . import model as native_model
from ...capabilities.registry import _argument_schemas
from ...config import CONFIG
from ...execution import trace as action_trace
from ...models import runtime as model_runtime
from ...models.context import TaskContext, discard_consumed_images

DESCRIPTIONS = {
    "application.launch": "Open one registered application with application:<registered identifier>.",
    "computer.act": "Deliver one click to the immediately observed application.",
    "computer.observe": "Read the current image of one exact target without changing focus or placement.",
    "harness.evaluate": "Evaluate one exact Runbook proposal in frozen Tool trials using proposal.",
    "harness.repair": "Request one receipt-safe recovery with exact task and run_id from current status evidence.",
    "harness.status": "Read bounded current runtime-health and receipt findings.",
    "model.benchmark": "Measure one registered model using model_id and devices.",
    "model.configure": "Update one registered model with model_id and at least one supported setting: allowed_devices, context_tokens, max_output_tokens, gpu_memory_utilization or max_num_seqs.",
    "model.inspect": "Inspect one registered model using model_id.",
    "model.source": "Register the current immutable Source identity of a registered model using model_id.",
    "observations.temporary.append": "Write an unverified observation under the executing Agent's own Temporary Observations using text and up to three accessible related_refs.",
    "observations.temporary.archive": "Preserve the exact controller-bound Temporary Observation bundle as immutable Source.",
    "review.inspect": "Read bounded review evidence for an exact task or proposal.",
    "source.handoff": "Return one self-contained finding as immutable Source Inbox evidence with exactly title and content containing source:// citations.",
    "source.ingest": "Preserve external evidence as immutable Source using content, source_ref, source_type, media_type and optional captured_at.",
    "source.read": "Read immutable Source by exact source ID/citation, or up to ten sources; offset and limit continue bounded text.",
    "task.complete": "Finish with status:completed|failed|review and a factual summary.",
    "task.create": "Activate one accepted Task with task and bounded params.",
    "task.inspect": "Inspect one exact accepted task and optional run_id for bounded execution and receipt evidence.",
    "vault.list": "List readable Articles in the executing Agent's graph.",
    "vault.maintenance": "Inspect accessible Knowledge for bounded maintenance candidates.",
    "vault.propose": "Stage an accepted-scope Article revision with target, action:create|update|archive, and applicable title/body/reason/metadata.",
    "vault.read": "Read an exact accessible Article using ref, or up to ten refs.",
    "vault.search": "Search only the executing Agent's owned and checked-out graph.",
    "vault.validate": "Run deterministic validation of Article formats and load-bearing references.",
    "web.fetch": "Fetch one URL or up to ten URLs using exactly url or urls.",
    "web.feed": "Read RSS/Atom feed leads with url and optional limit.",
    "web.search": "Acquire bounded current-source leads using query and optional limit.",
    "window.activate": "Focus one exact current application or pane using target:{kind:application|pane,name:<exact name>,surface?:<surface>}.",
    "window.place": "Place one exact current target on a logical Surface and optional integer tile edges."
}

PROTOCOL = (
    'Use the supplied native function Tools for operations. Answer ordinary questions directly in text. '
    'Do not emit JSON imitations of Tool calls. Use task.complete only when a structured terminal '
    'status, pending Review or computer-state verification is required. '
    'The capability catalog is code-owned; explanatory Articles are available through vault.read. '
    'Complete the requested work before the final answer; claims of effects require actual Tool receipts.'
)


def native_schema(schema):
    """Project the code-owned schema to DeepSeek's documented supported vocabulary.

    The complete original schema is still validated before every dispatch.
    """
    result = {key: value for key, value in schema.items() if key in {
        'type', 'properties', 'required', 'additionalProperties', 'items', 'enum', 'const', 'description'}}
    if 'type' not in result and ('enum' in result or 'const' in result):
        value = result['enum'][0] if 'enum' in result else result['const']
        result['type'] = {str: 'string', int: 'integer', bool: 'boolean', float: 'number', type(None): 'null'}[type(value)]
    if 'properties' in result:
        result['properties'] = {key: native_schema(value) for key, value in result['properties'].items()}
    if 'items' in result:
        result['items'] = native_schema(result['items'])
    if 'anyOf' in schema:
        # Gemma's native template renders object properties, but does not expose
        # oneOf object alternatives. Advertise their typed union; the complete
        # conditional contract remains enforced immediately before dispatch.
        branches = schema['anyOf']
        if all(branch.get('type') == 'object' for branch in branches):
            properties = {}
            for branch in branches:
                for key, value in branch.get('properties', {}).items():
                    value = native_schema(value)
                    if key not in properties:
                        properties[key] = deepcopy(value)
                    elif properties[key] != value:
                        previous = properties[key]
                        values = previous.get('enum', [previous.get('const')]) + value.get('enum', [value.get('const')])
                        if None in values:
                            raise ValueError('Native object union requires an explicit compatible property schema')
                        properties[key] = {'enum': list(dict.fromkeys(values)), 'type': previous['type']}
            required = set.intersection(*(set(branch.get('required', [])) for branch in branches))
            result = native_schema({'type': 'object', 'properties': properties,
                                    'required': sorted(required), 'additionalProperties': False})
        else:
            result['oneOf'] = [native_schema(value) for value in branches]
    return result


def tool_schemas(allowed):
    schemas = []
    for name in sorted(allowed):
        description = DESCRIPTIONS[name]
        if name == 'computer.act':
            description += ' point is an x,y coordinate normalized 0..999 in the immediately preceding observation image. It is consumed once.'
        if name == 'task.complete':
            description += ' Ordinary text answers finish directly. Use this for failed/review status or explicit state verification.'
        schemas.append({'name': name, 'description': description, 'parameters': native_schema(_argument_schemas()[name])})
    return schemas


async def run_native_session(task, model, messages, allowed, ctx, agent_name, effort,
                             interruption_event=None, *, initial_lease=None):
    from ..executor import CapabilityDispatch, _scope_checkpoint, _foreground_checkpoint

    await BRIDGE.start()
    run = ctx['run_id']
    queue = asyncio.Queue()
    BRIDGE.runs[run] = queue
    trace = ctx.setdefault('trace', [])
    dispatch = CapabilityDispatch(task, model, [], allowed, ctx, agent_name, 0, trace,
                                  action_trace.emit, TaskContext(), CONFIG.max_steps,
                                  interruption_event=interruption_event,
                                  steering=ctx.get('_steering'), active_lease=initial_lease)
    images = {}
    ended = False
    model_steps = 0
    invalid_calls = 0
    completion_rejections = 0
    imitations = 0
    ctx['_foreground_interruption_event'] = interruption_event
    ctx.pop('_computer_observation_lease', None)

    async def reply(message, value=None, *, error=None, done=False):
        await BRIDGE.send({'id': message['id'], 'result': value, 'error': error, 'done': done})

    def discard_observation():
        images.clear()
        dispatch.response_observation_lease = dispatch.response_completion_observation = None
        dispatch.pending_observation_lease = dispatch.pending_response_observation = None
        discard_consumed_images(dispatch.messages)

    async def operate(name, args):
        nonlocal invalid_calls, completion_rejections
        _foreground_checkpoint(interruption_event, ctx)
        if dispatch.step >= CONFIG.max_steps:
            dispatch.done = True
            dispatch.status, dispatch.summary = 'failed', 'Executive operation budget exhausted'
        if dispatch.done:
            return [{'type': 'text', 'text': 'Activation already settled; no further effect is dispatched.'}]
        if dispatch.steering is not None and dispatch.steering.pending:
            discard_observation()
            return [{'type': 'text', 'text': 'Response superseded by a current owner clarification; no Tool dispatched.'}]
        if name not in dispatch.allowed:
            discard_observation()
            invalid_calls += 1
            trace.append({'invalid_tool': name, 'not_dispatched': True, 'obs': 'Capability unavailable at this boundary'})
            if invalid_calls >= 3:
                dispatch.done = True
                dispatch.status, dispatch.summary = 'failed', 'Three invalid or unavailable native Tool calls'
            return [{'type': 'text', 'text': 'Capability unavailable at this boundary; no Tool dispatched.'}]
        errors = list(Draft202012Validator(_argument_schemas()[name]).iter_errors(args))
        if errors:
            discard_observation()
            invalid_calls += 1
            path = '.'.join(map(str, errors[0].absolute_path)) or 'arguments'
            guidance = json.dumps(native_schema(_argument_schemas()[name]), separators=(',', ':'))
            diagnostic = f'Invalid {name} {path}: {errors[0].validator} constraint. Use this argument structure: {guidance}'
            trace.append({'invalid_tool': name, 'not_dispatched': True, 'obs': diagnostic})
            action_trace.emit('error', f'{name} arguments rejected before dispatch', [diagnostic])
            if invalid_calls >= 3:
                dispatch.done = True
                dispatch.status, dispatch.summary = 'failed', 'Three invalid native Tool calls; no effect dispatched'
            return [{'type': 'text', 'text': diagnostic}]
        invalid_calls = 0
        before = len(dispatch.messages)
        await dispatch.dispatch(name, args, json.dumps({'tool': name, 'args': args}))
        dispatch.step += 1
        if name == 'task.complete' and not dispatch.done:
            completion_rejections += 1
            if completion_rejections >= 3:
                dispatch.done = True
                dispatch.status, dispatch.summary = 'failed', 'Three rejected completion attempts'
        elif name != 'task.complete':
            completion_rejections = 0
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
        await BRIDGE.send({'method': 'start', 'params': {
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
                if message.get('error'):
                    raise RuntimeError(message['error'])
                break
            _foreground_checkpoint(interruption_event, ctx)
            _scope_checkpoint(ctx)
            if method == 'boundary':
                if model_steps >= CONFIG.max_steps or dispatch.step >= CONFIG.max_steps:
                    dispatch.done = True
                    dispatch.status, dispatch.summary = 'failed', 'Executive decision budget exhausted'
                context = ''
                if dispatch.steering is not None and dispatch.steering.pending:
                    context = 'Owner clarifications within this same Objective; never replay effects:\n' + '\n'.join(
                        turn['text'] for turn in dispatch.steering.take())
                    images.clear()
                    dispatch.pending_observation_lease = dispatch.pending_response_observation = None
                    discard_consumed_images(dispatch.messages)
                await reply(message, {'done': dispatch.done, 'context': context})
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
                discard_observation()
                invalid_calls += 1
                name = str(message['params'].get('name') or 'native Tool')[:96]
                code = str(message['params'].get('code') or 'TOOL_ERROR')[:80]
                trace.append({'native_tool_error': code, 'invalid_tool': name})
                action_trace.emit('error', f'{name}: {code}')
                if invalid_calls >= 3:
                    dispatch.done = True
                    dispatch.status, dispatch.summary = 'failed', 'Three native Tool errors; inspect the Action Trace'
            elif method == 'model':
                model_steps += 1
                dispatch.response_observation_lease, dispatch.pending_observation_lease = dispatch.pending_observation_lease, None
                dispatch.response_completion_observation, dispatch.pending_response_observation = dispatch.pending_response_observation, None
                ctx.pop('_computer_response_observation', None)
                if dispatch.active_lease is None:
                    dispatch.model = model_runtime.configured_spec(model.id)
                    dispatch.active_lease = model_runtime.lease(dispatch.model)
                    await dispatch.active_lease.__aenter__()
                fields = {'step': dispatch.step + 1, 'call_id': f'{run}:model:{model_steps}'}
                action_trace.emit('model', f'{agent_name} model started', metadata={**fields, 'payload': {
                    'kind': 'model', 'phase': 'started', 'model': dispatch.model.id, 'engine': 'deepseek'}})
                metrics = {}
                terminal = None
                async def chunk(value):
                    nonlocal terminal
                    if value['type'] == 'finish': terminal = value
                    else: await reply(message, value)
                try:
                    text, has_calls, reason, projection = await native_model.stream(
                        message['params'], dispatch.model, effort, images, chunk, metrics)
                    _foreground_checkpoint(interruption_event, ctx)
                except Exception as exc:
                    await reply(message, error=type(exc).__name__ + ': ' + str(exc)[:300])
                    raise
                finally:
                    images.clear()
                    discard_consumed_images(dispatch.messages)
                if model_steps == 1:
                    ctx['prompt_tokens'] = metrics['prompt_tokens']
                trace.append({'provider_metrics': metrics})
                action_trace.emit('model', f'{agent_name} model returned', metadata={**fields, 'payload': {
                    'kind': 'model', 'phase': 'result', 'model': dispatch.model.id, 'metrics': metrics}})
                if 'before_input_tokens' in projection:
                    trace.append({'context_projection': projection})
                if not has_calls and reason == 'stop' and text.strip():
                    imitation = any(text.lstrip().startswith(name + '{') for name in allowed) or bool(
                        re.match(r'^\s*\{\s*"tool"\s*:', text))
                    if imitation:
                        imitations += 1
                        trace.append({'invalid_native_response': 'textual_tool_imitation'})
                        result = [{'type': 'text', 'text': 'The last response imitated a Tool in text and was not executed. Use the native function-call channel, or give an ordinary text answer. Never reproduce native control tokens in text.'}]
                        if imitations >= 3:
                            dispatch.done = True
                            dispatch.status, dispatch.summary = 'failed', 'Three textual Tool imitations; no text was executed'
                    else:
                        from ...capabilities.task.complete import native_text_arguments
                        result = await operate('task.complete', native_text_arguments(text.strip(), ctx))
                    if not dispatch.done:
                        # The upstream inbox owns the next decision after a rejected completion.
                        await BRIDGE.send({'method': 'context', 'run': run, 'text': '\n'.join(
                            block['text'] for block in result if block['type'] == 'text')})
                elif reason not in {'stop', 'tool-calls'}:
                    raise RuntimeError(f'Executive model ended with {reason}; no incomplete Tool is dispatched')
                await reply(message, terminal)
                await reply(message, done=True)
        return trace, dispatch.status, dispatch.summary
    finally:
        try:
            if not ended:
                await BRIDGE.send({'method': 'cancel', 'run': run})
                # Drain this exact upstream activation before releasing its model resource.
                try:
                    async with asyncio.timeout(5):
                        while (await queue.get()).get('method') != 'end':
                            pass
                except TimeoutError:
                    await BRIDGE.close()
        finally:
            BRIDGE.runs.pop(run, None)
            images.clear()
            if dispatch.active_lease is not None:
                await dispatch.active_lease.__aexit__(None, None, None)
            ctx.pop('_computer_observation_lease', None)
            ctx.pop('_computer_response_observation', None)
            ctx.pop('_foreground_interruption_event', None)

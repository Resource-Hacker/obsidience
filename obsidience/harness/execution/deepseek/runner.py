"""Native Executive activation. The upstream agent-loop chooses and sequences Tools."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
import time
import uuid
from copy import deepcopy
from datetime import datetime, time as time_of_day, timedelta

from jsonschema import Draft202012Validator

from .bridge import BRIDGE
from . import model as native_model
from ...capabilities.registry import _argument_schemas
from ...config import CONFIG
from ...models.context import TaskContext, discard_consumed_images

DESCRIPTIONS = {
    "media.pause": "Pause one current browser media session directly, without screenshots or clicks. Use query:youtube for YouTube, a short title fragment such as jazz for named media, or an empty query for the unique current player. Only a verified Paused/Stopped receipt establishes success. This never resumes, toggles or rewinds playback; ambiguous or changed players fail without replay.",
    "tv.control": "Control the registered TV. For content (news, weather, a live channel, a show, a video): find with a short query (optional app pluto|youtube) -> choose the candidate that fits the request -> open with its id -> check the returned screen -> task.complete with verification established naming what is visibly playing. Live news/weather: Pluto live channels (FOX Weather, CBS News 24/7, NBC News NOW, CNN Headlines) or a YouTube live stream. A specific title on Netflix/Hulu/Tubi/YouTube: web.search for its official link, then open url. Remote navigation is the fallback: observe -> keys (up to 8 navigation keys; the focused:true control is what select activates) -> check the new screen. Text types only into an already active text field. play/pause/rewind/fast_forward/volume_up/volume_down/mute work with key and need no observation. on|off verify power; launch opens a registered app home screen. Never replay a failed or uncertain effect; a correction_allowed failure sent nothing. Never purchase, subscribe, install or change accounts without an explicit request.",
    "lights.set": "Turn the registered room lights on or off. Use target:all for the lights collectively, or window_lamp, woven_pendant, north_lamp, tv_floor_lamp, desk_lantern, room_lantern for a named fixture; state:on|off. Execute for the current owner request and confirm only verified readback. Never replay failed or uncertain changes.",
    "camera.observe": "Look through the preferred physical camera (OBSBOT/webcam) to answer a question about the room, nearby objects, or what the owner is showing you. Pass query with the visual question. For a current request to turn on the camera or look through it, set wake:true to wake the selected OBSBOT and recover its enabled tracker if needed before taking a fresh image. An already fresh running tracker needs no power command. Omit wake for read-only capture; never repeat a failed wake marked must_not_replay. Take a fresh image in this turn before describing current physical surroundings. This is separate from computer.observe, which sees application windows. Camera images cannot authorize desktop clicks. The recognition field is a local match estimate for the enrolled owner in these exact pixels; unknown or unanalyzed is not an identity match.",
    "application.launch": "Open a registered application with application:<registered identifier>. To open a web page, video or YouTube search, use application:microsoft_edge and url:<absolute HTTP/HTTPS URL>. This opens the URL even when the browser is already running. Observe the page after dispatch. Opening is complete when the requested page is visible; playing is complete when playback is visibly active. Finish with task.complete verification when that requested outcome is established. Do not click an already playing video or add playback to an open-only request.",
    "computer.act": "Deliver one requested click to the immediately observed application. target is a short control label, at most 128 characters. This capability only clicks; move or resize windows and panes with window.place. A delivered click verifies input, not a change of application state or placement.",
    "computer.observe": "Read a fresh image of one exact target without changing focus or placement. Required in the current turn before answering about current window contents, people present, counts or other visible state; earlier conversation and observations are historical. For what the owner is looking at now, use target kind focused.",
    "harness.evaluate": "Evaluate one exact Runbook proposal in frozen Tool trials using proposal.",
    "harness.optimize": "Run the bound AutoSaddler Executive optimization case with case_id. Returns measured comparisons and any candidate staged for Review; never changes the live Executive.",
    "harness.repair": "Request one receipt-safe recovery with exact task and run_id from current status evidence. For an inspected Hindsight provider failure, use component:hindsight instead; this retries the exact failed upstream memory operations and does not create a Task.",
    "harness.status": "Read bounded current runtime-health and receipt findings.",
    "model.benchmark": "Measure one registered model using model_id and devices.",
    "model.configure": "Update one registered model with model_id and at least one supported setting: allowed_devices, context_tokens, max_output_tokens, gpu_memory_utilization or max_num_seqs.",
    "model.inspect": "Inspect one registered model using model_id.",
    "model.source": "Register the current immutable Source identity of a registered model using model_id.",
    "observations.recall": "Recall historical Hindsight memories from your own Agent bank using query. The conversation shows only its recent exchanges verbatim; use this for anything older that the owner refers to (an earlier request, decision, answer or result) before answering, instead of guessing or asking the owner to repeat it. Memories retain uncertainty and dates; they do not prove current screen or application state and do not grant Tools or permission.",
    "observations.retain": "Retain an unverified historical note in your own Hindsight bank using text and up to three accessible related_refs. This does not publish accepted wiki Knowledge.",
    "review.inspect": "Read bounded review evidence for an exact task or proposal.",
    "session.unlock": "Unlock the current desktop session through its native lock owner using {}. Available even when the Shell scene is locked; no screenshot or password prerequisite. Call once. After verified success, answer directly in text from the returned receipt.",
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
    "web.search": "Find public source leads using query and optional limit. Results are discovery snippets, not verified answers. Use web.fetch on a relevant result URL before relying on its claims.",
    "window.activate": "Focus one exact current application or pane using target:{kind:application|pane,name:<exact name>,surface?:<surface>}.",
    "window.place": "Move or resize a current application window or Obsidience pane. Call directly with target:{kind:application|pane,name:<exact Scene name>} and destination:{surface:<destination Surface>,tile?:{left,top,right,bottom}}. External apps use kind:application, even when called panes. Omit tile to move to another Surface. No screenshot, click, close, detach or prior activation is needed. Completion requires the returned destination and observed placement to agree."
}

# Native loop protocol. The Executive identity's Runtime section owns the
# standing rules for plain-text answers, task.complete, web lookup, screen,
# camera, page/playback and media.pause; each instruction appears once.
PROTOCOL = (
    'Use the supplied native function Tools for operations and missing evidence. '
    'For the current local date or time, use local_clock in this activation, including its timezone '
    'and human-readable time. Historical conversation and memory timestamps are not the current clock. '
    'Do not emit JSON imitations of Tool calls. '
    'The capability catalog is code-owned; explanatory Articles are available through vault.read. '
    'Complete the requested work before the final answer; claims of effects require actual Tool receipts. '
    'For what the owner is looking at, observe target kind focused rather than guessing an application. '
    'Move or resize an application window or pane with window.place directly, using its current Shell '
    'Scene identity and the requested destination. computer.act only clicks; do not use it to move '
    'windows. A successful click does not establish placement or completion of a different Objective. '
    'Report only the outcome established by the matching Tool result. '
    'When an operation says must_not_replay, end with its actual result; do not promise another attempt. '
    'When asked about a named product, project, service or community that the supplied evidence does not '
    'identify, do not guess a meaning from similar words. For example, "Can you tell me about Project '
    'Bluebird?" calls for searching "Project Bluebird" and reading a source before describing it. The user '
    'does not need to say "search" or "look it up". Stable general facts and clearly identified local '
    'subjects can be answered directly.'
)


def _recalled(row):
    """Model-facing recall row: local recording minute, differing occurrence date, text."""
    def moment(value):
        try:
            return datetime.fromisoformat(value)
        except (TypeError, ValueError):
            return None
    recorded, occurred = moment(row.get('mentioned_at')), moment(row.get('occurred_start'))
    item = {'recorded': recorded.astimezone().strftime('%Y-%m-%d %H:%M')} if recorded else {}
    if occurred:
        # Hindsight stores a date-only occurrence at UTC midnight; keep that calendar date.
        day = (occurred.date() if occurred.utcoffset() == timedelta(0) and occurred.time() < time_of_day(0, 0, 1)
               else occurred.astimezone().date()).isoformat()
        if day != item.get('recorded', '')[:10]:
            item['occurred'] = day
    return {**item, 'text': row['text']}


def recall_reply(value) -> dict:
    """The model-facing reply to the native memory hook's recall request."""
    return {'notice': value.get('notice'), 'memories': [_recalled(row) for row in value.get('memories', [])]}


def memory_message(recalled: dict) -> str:
    """Exact text of the hook's memory message (JSON.stringify of the reply), or '' when it adds none."""
    return json.dumps(recalled, ensure_ascii=False, separators=(',', ':')) if recalled['memories'] else ''


def recall_query(text, conversation_id=None, before_sequence=None):
    """The automatic recall query: the owner request plus the exchange it follows.

    A follow-up ("do that again", "what about it") names its subject only in
    the preceding exchange. Admission, the memory hook and speech preparation
    build the same bounded query from the same public ledger rows.
    """
    text = text.strip()
    if not conversation_id:
        return text
    from ...knowledge.index import INDEX
    turns = INDEX.conversation_turns(conversation_id, before_sequence=before_sequence, limit=8)
    owner = next((turn for turn in reversed(turns) if turn['role'] == 'user'), None)
    if owner is None:
        return text
    previous = 'Owner: ' + ' '.join(owner['text'].split())[:200]
    reply = next((turn for turn in turns if turn['role'] == 'assistant'
                  and turn['reply_to'] == owner['id'] and turn['state'] in {'final', 'interrupted'}), None)
    if reply is not None:
        previous += '\nAssistant: ' + ' '.join(reply['text'].split())[:500 - len(previous)]
    return text + '\n\nPrevious exchange:\n' + previous


def prefetch_recall(agent_ref, text, turn=None):
    """Start the Executive hook's exact Hindsight recall at admission.

    The owner request is known before preparation and packet compile, so its
    recall can overlap them. The agent hook still requests memory at the same
    point and adopts this result only for the identical Agent and query; its
    text, prompt position and the recall's own timeout are unchanged.
    """
    from ...memory.hindsight import MEMORY
    query = recall_query(text, *((str(turn['conversation_id']), int(turn['sequence'])) if turn else ()))
    return agent_ref, query, asyncio.create_task(
        MEMORY.recall(agent_ref, query), name='obsidience-executive-recall')


async def discard_recall(prefetch):
    """Cancel and join an admission recall the activation did not adopt."""
    if prefetch is None:
        return
    task = prefetch[2]
    if not task.done():
        task.cancel()
    await asyncio.gather(task, return_exceptions=True)


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
    for key in ('_reflex_proposal', '_reflex_command_verified', '_voice_confirmation'):
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
        from .commands import recognize_command
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
            return [{'type': 'text', 'text': 'Capability unavailable at this boundary; no Tool dispatched.' + (
                ' Only completion remains: finish with the actual result; never replay the operation.'
                if dispatch.allowed == ['task.complete'] else '')}]
        errors = list(Draft202012Validator(_argument_schemas()[name]).iter_errors(args))
        if errors:
            discard_observation()
            path = '.'.join(map(str, errors[0].absolute_path)) or 'arguments'
            guidance = json.dumps(native_schema(_argument_schemas()[name]), separators=(',', ':'))
            diagnostic = f'Invalid {name} {path}: {errors[0].validator} constraint ({errors[0].validator_value!r}). Use this argument structure: {guidance}'
            if name == 'computer.act':
                diagnostic += (' The previous image was consumed without input. If a click is still needed, '
                               'first observe again and choose a new point. If the goal was already visible, '
                               'complete without clicking.')
            elif name == 'task.complete':
                diagnostic += (' No completion was accepted. If this completion requires visual verification, '
                               'observe again before the corrected native call; its prior image was consumed.')
            if name == 'computer.act' and isinstance(args, dict) and args.get('action', 'click') != 'click':
                diagnostic = ('computer.act supports only a click; the requested action was not dispatched. '
                              'For moving or resizing a window or pane, use window.place with target and '
                              'destination. Do not substitute a click for the requested move. ' + diagnostic)
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
                    context = 'Owner clarifications within this same Objective; never replay effects:\n' + '\n'.join(
                        turn['text'] for turn in clarifications)
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
                if command['name'] == 'tv.control':
                    summary = (f"TV turned {command['args']['action']}." if verified else
                               'The TV power command could not be verified; no command was replayed.')
                elif command['name'] == 'media.pause':
                    summary = ('Playback stopped.' if verified else
                               'The media pause could not be verified; no action was replayed.')
                else:
                    target = command['args']['target']
                    label = 'Lights' if target == 'all' else target.replace('_', ' ').capitalize()
                    summary = (f"{label} turned {command['args']['state']}." if verified else
                               'The light command could not be verified; no change was replayed.')
                # The same completion authority accepts public text and status.
                # A failure never returns to generation or replays the effect.
                await operate('task.complete', {
                    'status': 'completed' if verified else 'failed', 'summary': summary})
                if not dispatch.done:
                    raise RuntimeError('Explicit command completion was not accepted')
                await reply(message, {'status': dispatch.status, 'summary': dispatch.summary})
            elif method == 'memory.recall':
                from ...memory.hindsight import MEMORY
                recall_started = time.perf_counter()
                query = message['params']['query']
                params = ctx.get('params') or {}
                if evaluation is None and params.get('conversation_id'):
                    from ...knowledge.index import INDEX
                    turn = INDEX.conversation_turn(params['reply_to_turn_id']) or {}
                    query = recall_query(query, params['conversation_id'], turn.get('sequence'))
                prefetched = ctx.pop('_memory_recall', None)
                if evaluation is not None:
                    value = {'status': 'disabled', 'memories': []}
                elif prefetched is not None and prefetched[:2] == (ctx['_agent_ref'], query):
                    # Started at admission; duration_ms below is the remaining wait.
                    value = await prefetched[2]
                else:
                    value = await MEMORY.recall(ctx['_agent_ref'], query)
                from .. import activity
                refs = [row['ref'] for row in value.get('memories', [])]
                if refs:
                    activity.emit_operation('read', 'returned', refs, label='Hindsight recall', run_id=run)
                emit('event', 'Hindsight recall ' + value['status'], refs, fields={'payload': {
                    'kind': 'memory', 'provider': 'hindsight', 'status': value['status'], 'refs': refs,
                    'duration_ms': round((time.perf_counter() - recall_started) * 1000, 3)}})
                # Refs, status and timing stay with graph activity and the trace.
                # The prompt needs only the notice and each memory's text and date.
                recalled = recall_reply(value)
                if evaluation is None and (ctx.get('params') or {}).get('conversation_id'):
                    from .prefill import report_reuse
                    report_reuse(ctx['params']['conversation_id'],
                                 messages[1]['content'] if len(messages) > 1 else '', memory_message(recalled))
                await reply(message, recalled)
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
                    from .fast_lane import candidates
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
                if not has_calls and reason == 'stop' and text.strip():
                    imitation = any(text.lstrip().startswith(name + '{') for name in allowed) or bool(
                        re.match(r'^\s*\{\s*"tool"\s*:', text))
                    if imitation:
                        trace.append({'invalid_native_response': 'textual_tool_imitation'})
                        result = [{'type': 'text', 'text': 'The last response imitated a Tool in text and was not executed. Use the native function-call channel, or give an ordinary text answer. Never reproduce native control tokens in text.'}]
                        state.strike('imitation', 'Three textual Tool imitations; no text was executed')
                    else:
                        from ...capabilities.task.complete import native_text_arguments
                        result = await operate('task.complete', native_text_arguments(text.strip(), ctx))
                    if not dispatch.done and voice is not None:
                        await voice.retract(halt=True)  # Never voice a rejected reply further.
                    if not dispatch.done:
                        # The upstream inbox owns the next decision after a rejected completion.
                        await BRIDGE.send({'method': 'context', 'run': run, 'text': '\n'.join(
                            block['text'] for block in result if block['type'] == 'text')})
                elif not has_calls and reason == 'stop':
                    failed = state.strike('empty', 'Model returned two empty responses; no completion was accepted', limit=2)
                    trace.append({'invalid_native_response': 'empty_public_response',
                                  'attempt': state.strikes['empty'], 'recovery': 'failed' if failed else 'continuation'})
                    if not failed:
                        # A complete empty response has no action to replay. The
                        # native inbox retains prior Tool results and the next
                        # boundary still enforces cancellation and step budgets.
                        emit('event', 'Empty model response; continuing current request')
                        await BRIDGE.send({'method': 'context', 'run': run, 'text': (
                            'The preceding model response ended without a visible answer or native Tool call. '
                            'Continue the current owner request from the existing Tool results and committed receipts. '
                            'Do not repeat an already dispatched operation or claim an unverified effect. '
                            'Use a native Tool only for still-missing evidence, or finish with an ordinary text '
                            'answer or an explicit failed completion.')})
                    else:
                        emit('error', dispatch.summary)
                elif reason not in {'stop', 'tool-calls'}:
                    raise RuntimeError(f'Executive model ended with {reason}; no incomplete Tool is dispatched')
                await reply(message, terminal)
                await reply(message, done=True)
        if (dispatch.status == 'completed' and ctx.get('_reflex_command_verified') is True
                and not steered
                and sum(row.get('tool') not in {None, 'task.complete'} for row in trace) == 1
                and not any(
                    row.get('invalid_tool') or row.get('native_tool_error')
                    or row.get('invalid_native_response') or row.get('completion_rejected')
                    or row.get('interrupted') or row.get('not_dispatched') for row in trace)):
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

"""Loop-neutral Executive turn vocabulary: native Tool schemas, protocol,
memory recall and the model-step policies every Executive loop applies."""
from __future__ import annotations

import asyncio
import json
import re
import time
from copy import deepcopy
from datetime import datetime, time as time_of_day, timedelta

from jsonschema import Draft202012Validator

from ..capabilities.registry import _argument_schemas


DESCRIPTIONS = {
    "media.pause": "Pause one current browser media session directly, without screenshots or clicks. Use query:youtube for YouTube, a short title fragment such as jazz for named media, or an empty query for the unique current player. Only a verified Paused/Stopped receipt establishes success. This never resumes, toggles or rewinds playback; ambiguous or changed players fail without replay.",
    "tv.control": "Control the registered TV with one intent call where possible. play with query (optional app pluto|youtube) picks and opens content in one call: a strong Pluto live-channel match first, else YouTube's top result (a live stream for news/weather); it returns what it chose and up to 3 alternatives (open one by id if the owner wants another). volume with level 0-100 sets it exactly; volume_up/volume_down step by 5; mute, unmute, pause and resume reach that state. These read the TV back: delivery verified reports the new state, otherwise say it is unverified; an already-reached state sends nothing. on|off verify power. observe returns the backend state (power, foreground app, playback, volume/mute, what this Harness opened and what airs now) and a screen image only when no video plays; answer what is on the TV from it. The metadata tv line is the last state seen, with its age. find lists candidates; open plays one by id, or an official https link (web.search for a specific Netflix/Hulu/Tubi/YouTube title). Remote keys are only for navigation that play/open cannot reach: observe -> keys (up to 8; the focused:true control is what select activates) -> check the new screen. text types only into an active text field; launch opens an app home screen. notice with text shows a short message card on the TV screen for six seconds. After play/open, complete with verification established naming what plays. Never replay a failed or uncertain effect; a correction_allowed failure sent nothing. Never purchase, subscribe, install or change accounts without an explicit request.",
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
    from ..knowledge.index import INDEX
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
    from ..memory.hindsight import MEMORY
    query = recall_query(text, *((str(turn['conversation_id']), int(turn['sequence'])) if turn else ()))
    return agent_ref, query, asyncio.create_task(
        MEMORY.recall(agent_ref, query), name='obsidience-executive-recall')


async def turn_recall(ctx, query, *, emit, run, context_text='', evaluation=None) -> dict:
    """The Executive's automatic recall for its owner request, as the model sees it.

    Adopts the admission prefetch only for the identical Agent and query; refs,
    status and timing go to graph activity and the trace, never the prompt.
    """
    from ..memory.hindsight import MEMORY
    recall_started = time.perf_counter()
    params = ctx.get('params') or {}
    if evaluation is None and params.get('conversation_id'):
        from ..knowledge.index import INDEX
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
    from . import activity
    refs = [row['ref'] for row in value.get('memories', [])]
    if refs:
        activity.emit_operation('read', 'returned', refs, label='Hindsight recall', run_id=run)
    emit('event', 'Hindsight recall ' + value['status'], refs, fields={'payload': {
        'kind': 'memory', 'provider': 'hindsight', 'status': value['status'], 'refs': refs,
        'duration_ms': round((time.perf_counter() - recall_started) * 1000, 3)}})
    recalled = recall_reply(value)
    if evaluation is None and params.get('conversation_id'):
        from .prefill import report_reuse
        report_reuse(params['conversation_id'], context_text, memory_message(recalled))
    return recalled


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


def unavailable_text(allowed) -> str:
    """The model-facing result of a call outside the current dispatch policy."""
    return 'Capability unavailable at this boundary; no Tool dispatched.' + (
        ' Only completion remains: finish with the actual result; never replay the operation.'
        if list(allowed) == ['task.complete'] else '')


def argument_diagnostic(name, args) -> str | None:
    """Validate a native call against its complete code-owned schema.

    Returns the model-facing diagnostic (with the "You sent" echo and the
    advertised structure) for an invalid call, else None.
    """
    errors = list(Draft202012Validator(_argument_schemas()[name]).iter_errors(args))
    if not errors:
        return None
    path = '.'.join(map(str, errors[0].absolute_path)) or 'arguments'
    guidance = json.dumps(native_schema(_argument_schemas()[name]), separators=(',', ':'))
    sent = json.dumps(args, separators=(',', ':'))[:300]
    diagnostic = (f'Invalid {name} {path}: {errors[0].validator} constraint ({errors[0].validator_value!r}). '
                  f'You sent: {sent}. Use this argument structure: {guidance}')
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
    return diagnostic


def imitates_tool(text: str, allowed) -> bool:
    """Plain text shaped like a Tool call is never executed."""
    return any(text.lstrip().startswith(name + '{') for name in allowed) or bool(
        re.match(r'^\s*\{\s*"tool"\s*:', text))


IMITATION_FEEDBACK = ('The last response imitated a Tool in text and was not executed. Use the native '
                      'function-call channel, or give an ordinary text answer. Never reproduce native '
                      'control tokens in text.')

EMPTY_FEEDBACK = ('The preceding model response ended without a visible answer or native Tool call. '
                  'Continue the current owner request from the existing Tool results and committed receipts. '
                  'Do not repeat an already dispatched operation or claim an unverified effect. '
                  'Use a native Tool only for still-missing evidence, or finish with an ordinary text '
                  'answer or an explicit failed completion.')

STEERING_PREFIX = 'Owner clarifications within this same Objective; never replay effects:\n'


def steering_context(clarifications) -> str:
    return STEERING_PREFIX + '\n'.join(turn['text'] for turn in clarifications)


def command_summary(command: dict, verified: bool, result) -> str:
    """The controller's public settlement of one explicit (HassIL) command."""
    if command['name'] == 'tv.control':
        from ..capabilities.tv.control import reflex_summary
        return reflex_summary(command['args'], result if verified else None)
    if command['name'] == 'media.pause':
        return ('Playback stopped.' if verified else
                'The media pause could not be verified; no action was replayed.')
    target = command['args']['target']
    label = 'Lights' if target == 'all' else target.replace('_', ' ').capitalize()
    return (f"{label} turned {command['args']['state']}." if verified else
            'The light command could not be verified; no change was replayed.')


def cue_only(status: str, ctx: dict, steered: bool, trace: list) -> bool:
    """A verified single reflex command is confirmed by a cue, not speech."""
    return (status == 'completed' and ctx.get('_reflex_command_verified') is True
            and not steered
            and sum(row.get('tool') not in {None, 'task.complete'} for row in trace) == 1
            and not any(
                row.get('invalid_tool') or row.get('native_tool_error')
                or row.get('invalid_native_response') or row.get('completion_rejected')
                or row.get('interrupted') or row.get('not_dispatched') for row in trace))


async def settle_model_step(state, operate, text: str, has_calls: bool, reason: str, *,
                            allowed, ctx: dict, trace: list, emit, voice=None) -> str | None:
    """Apply the completion policy to one finished model step.

    Plain text crosses the completion authority (``operate('task.complete')``);
    a textual Tool imitation is never executed; one empty complete stop gets one
    continuation and a second fails; truncated or partial stops end the turn.
    Returns controller feedback that must continue the same request, or None.
    """
    if not has_calls and reason == 'stop' and text.strip():
        if imitates_tool(text, allowed):
            trace.append({'invalid_native_response': 'textual_tool_imitation'})
            result = [{'type': 'text', 'text': IMITATION_FEEDBACK}]
            state.strike('imitation', 'Three textual Tool imitations; no text was executed')
        else:
            from ..capabilities.task.complete import native_text_arguments
            result = await operate('task.complete', native_text_arguments(text.strip(), ctx))
        if not state.dispatch.done and voice is not None:
            await voice.retract(halt=True)  # Never voice a rejected reply further.
        if state.dispatch.done:
            return None
        return '\n'.join(block['text'] for block in result if block['type'] == 'text')
    if not has_calls and reason == 'stop':
        failed = state.strike('empty', 'Model returned two empty responses; no completion was accepted', limit=2)
        trace.append({'invalid_native_response': 'empty_public_response',
                      'attempt': state.strikes['empty'], 'recovery': 'failed' if failed else 'continuation'})
        if failed:
            emit('error', state.dispatch.summary)
            return None
        # A complete empty response has no action to replay. Prior Tool results
        # stay in history and the next boundary still enforces cancellation and budgets.
        emit('event', 'Empty model response; continuing current request')
        return EMPTY_FEEDBACK
    if reason not in {'stop', 'tool-calls'}:
        raise RuntimeError(f'Executive model ended with {reason}; no incomplete Tool is dispatched')
    return None

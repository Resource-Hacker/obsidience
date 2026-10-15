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
from jsonschema.exceptions import best_match

from ..capabilities.registry import DESCRIPTIONS, argument_schemas, tool_parameters


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


def _age(then, now) -> str:
    """How long ago a local moment was, in calendar terms the owner uses."""
    days = (now.date() - then.date()).days
    if days < 2:
        return 'yesterday' if days == 1 else 'today'
    if days < 14:
        return f'{days} days ago'
    if days < 60:
        return f'{days // 7} weeks ago'
    return f'{days // 30} months ago' if days < 730 else f'{days // 365} years ago'


def _recalled(row, now, refs):
    """Model-facing recall row: local recording minute with its age, differing occurrence date, text."""
    def moment(value):
        try:
            return datetime.fromisoformat(value)
        except (TypeError, ValueError):
            return None
    recorded, occurred = moment(row.get('mentioned_at')), moment(row.get('occurred_start'))
    item = {'ref': row['ref']} if refs else {}
    if recorded:
        recorded = recorded.astimezone()
        item['recorded'] = f"{recorded:%Y-%m-%d %H:%M} ({_age(recorded, now)})"
    if occurred:
        # Hindsight stores a date-only occurrence at UTC midnight; keep that calendar date.
        day = (occurred.date() if occurred.utcoffset() == timedelta(0) and occurred.time() < time_of_day(0, 0, 1)
               else occurred.astimezone().date()).isoformat()
        if day != item.get('recorded', '')[:10]:
            item['occurred'] = day
    return {**item, 'text': row['text']}


def recall_reply(value, *, refs=False) -> dict:
    """The model-facing reply to a recall: the memory hook's, or with refs the observations.recall Tool's.

    Each memory's age against the local clock is explicit: a days-old memory was
    presented as "earlier today" when only its recording minute was shown.
    """
    now = datetime.now().astimezone()
    result = {'notice': value.get('notice'),
              'memories': [_recalled(row, now, refs) for row in value.get('memories', [])]}
    if value.get('status') in {'partial', 'unavailable'}:
        result['status'] = value['status']
        if value['status'] == 'unavailable':
            result['notice'] = 'Memory recall unavailable; use observations.recall if historical context is needed.'
        else:
            result['notice'] = (str(result['notice'] or '')
                                + ' One recall query failed; results may be incomplete.').strip()
    return result


def memory_message(recalled: dict) -> str:
    """Exact text of the hook's memory message (JSON.stringify of the reply), or '' when it adds none."""
    return (json.dumps(recalled, ensure_ascii=False, separators=(',', ':'))
            if recalled['memories'] or recalled.get('status') in {'partial', 'unavailable'} else '')


def recall_query(text, conversation_id=None, before_sequence=None):
    """The automatic recall query: the owner request and the owner request it follows.

    A follow-up ("do that again", "what about it") names its subject only in
    the preceding request, which memory recalls separately (Hindsight.recall).
    One query of the request plus the whole previous exchange returned memories
    of the previous topic: measured 2026-10-12 on 34 questions after an unrelated
    exchange, 3 to 22 kept a useful memory against 24 for the request alone.
    Admission, the memory hook and speech preparation build the same bounded
    pair from the same public ledger rows.
    """
    text = text.strip()
    if not conversation_id:
        return text, ''
    from ..knowledge.index import INDEX
    turns = INDEX.conversation_turns(conversation_id, before_sequence=before_sequence, limit=8)
    owner = next((turn for turn in reversed(turns) if turn['role'] == 'user'), None)
    return text, ' '.join(owner['text'].split())[:200] if owner else ''


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
        MEMORY.recall(agent_ref, *query), name='obsidience-executive-recall')


async def turn_recall(ctx, query, *, emit, run, context_text='', evaluation=None) -> dict:
    """The Executive's automatic recall for its owner request, as the model sees it.

    Adopts the admission prefetch only for the identical Agent and query; refs,
    status and timing go to graph activity and the trace, never the prompt.
    """
    from ..memory.hindsight import MEMORY
    recall_started = time.perf_counter()
    params = ctx.get('params') or {}
    query = (query, '')
    if evaluation is None and params.get('conversation_id'):
        from ..knowledge.index import INDEX
        turn = INDEX.conversation_turn(params['reply_to_turn_id']) or {}
        query = recall_query(query[0], params['conversation_id'], turn.get('sequence'))
    prefetched = ctx.pop('_memory_recall', None)
    if evaluation is not None:
        value = {'status': 'disabled', 'memories': []}
    elif prefetched is not None and prefetched[:2] == (ctx['_agent_ref'], query):
        # Started at admission; duration_ms below is the remaining wait.
        value = await prefetched[2]
    else:
        value = await MEMORY.recall(ctx['_agent_ref'], *query)
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
    """Project the code-owned schema to the plain advertised vocabulary the model template renders.

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
        schemas.append({'name': name, 'description': description, 'parameters': native_schema(argument_schemas()[name])})
    return schemas


# A specialist Task's action protocol. Its procedure, not a conversation, owns
# the work: each decision is one native Tool call and only task.complete finishes.
TASK_PROTOCOL = """\
## Action protocol
Use the supplied native function Tools for every operation: call exactly one
Tool per response. To finish, call task.complete with the arguments required by
its selected Tool and Skill contract. Completion requirements depend on the Task.
Do not assume status and summary alone suffice for an evidence-bound inspection.
Outcome and evidence belong in separate arguments when the contract requires them.
Use private reasoning when available, but never write a Tool call as text or JSON,
and never invent tool names.
"""

NO_TOOL_CALL_FEEDBACK = ('No native Tool call was returned. Call exactly one authorized Tool; '
                         'finish with task.complete.')

OUTPUT_LIMIT_FEEDBACK = ('The reply reached the output limit before its native Tool call was complete; '
                         'nothing was dispatched. Send one complete call; keep citations and summaries short. '
                         'If a required Article body or Source content cannot fit, finish with task.complete '
                         'status failed instead of shortening it.')


def task_tool_schemas(names, *, completion_no_change=False, completion_blocked=False, proposal_mode='',
                      repair_rows=(), evidence_citations=()):
    """A specialist step's native schemas: its narrowed Tools under the active contract.

    The proposal, completion and Repair modes shape vault.propose, task.complete and
    harness.repair as the step's contract requires; the complete code-owned schema is
    still validated before dispatch and the capability owner enforces the contract.
    """
    schemas = []
    for name in sorted(names):
        parameters = native_schema(tool_parameters(name, completion_no_change=completion_no_change,
                                                   completion_blocked=completion_blocked,
                                                   proposal_mode=proposal_mode, repair_rows=repair_rows))
        if name == 'task.complete' and completion_no_change and not completion_blocked:
            # The template's flat union loses the successful branch's required
            # fields. Keep them explicit in both branches; failure can use an
            # empty classification and evidence list without inventing evidence.
            parameters['required'] = ['summary', 'status', 'outcome', 'evidence']
            # Nothing is staged, so "changed" is never accepted; the merged union
            # would still offer it with completed status.
            parameters['properties']['outcome']['enum'] = ['no_change', '']
            parameters['properties']['outcome']['description'] = (
                'Use no_change for a completed inspection; use an empty string for failed.')
            evidence = parameters['properties']['evidence']
            evidence['description'] = (
                'For completed inspection, one short citation per item: the exact inspected Source address '
                'and the reference of each Article read in full, never pasted text. The explanation goes in '
                'summary. For failed status, an empty list is allowed. Never invent evidence.')
            # native_schema drops bounds. Let the decoder enforce the code-owned
            # ones for evidence only: the engine's bounded strings cannot contain '<'.
            registered = argument_schemas()['task.complete']['properties']['evidence']
            evidence['maxItems'] = registered['maxItems']
            evidence['items']['maxLength'] = registered['items']['maxLength']
            if evidence_citations:
                # Only what this step may cite: an Article read in part is not offered.
                evidence['items']['enum'] = list(evidence_citations)
        schemas.append({'name': name, 'description': DESCRIPTIONS[name],
                        'parameters': parameters})
    return schemas


def step_budget_notice(remaining: int) -> str:
    """A specialist Task's remaining model decisions, carried with each Tool result."""
    if remaining == 1:
        return "Execution budget: 1 model decision remains. FINAL STEP — call task.complete with the actual delivery outcome."
    return (
        f"Execution budget: {remaining} model decisions remain, including task.complete. "
        "Reserve the Runbook's required delivery or publication steps before completion."
    )


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
    errors = list(Draft202012Validator(argument_schemas()[name]).iter_errors(args))
    if not errors:
        return None
    schema = argument_schemas()[name]
    # The advertised union of the alternatives accepts calls that mix them. List
    # each alternative the fixed values sent can still select, or all when none can.
    alternatives = schema.get('anyOf', [schema])
    branches = [branch for branch in alternatives if isinstance(args, dict) and all(
        key not in args or args[key] in value.get('enum', [value.get('const')])
        for key, value in branch.get('properties', {}).items() if 'enum' in value or 'const' in value)] or alternatives
    error = errors[0]
    if error.validator == 'anyOf':
        # Name the failing field of a selectable alternative, not the whole union:
        # the advertised structure omits length bounds (Curate, 2026-10-14).
        selectable = {index for index, branch in enumerate(alternatives) if branch in branches}
        error = best_match(sub for sub in error.context if sub.relative_schema_path[0] in selectable) or error
    path = '.'.join(map(str, error.absolute_path)) or 'arguments'
    guidance = ('Use this argument structure: ' if len(branches) == 1
                else 'Use exactly one of these argument structures: ') + ' or '.join(
        json.dumps(native_schema(branch), separators=(',', ':')) for branch in branches)
    sent = json.dumps(args, separators=(',', ':'))[:300]
    # "additionalProperties constraint (False)" would not name the unexpected key.
    constraint = (error.message if error.validator == 'additionalProperties'
                  else f'{error.validator} constraint ({error.validator_value!r})')
    diagnostic = f'Invalid {name} {path}: {constraint}. You sent: {sent}. {guidance}'
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
    """Apply the Executive's completion policy to one finished model step.

    ``state`` is the activation's plugin (strikes, failure and its capability
    execution ``ex``).

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
            from .completion import native_text_arguments
            result = await operate('task.complete', native_text_arguments(text.strip(), ctx))
        if not state.ex.done and voice is not None:
            await voice.retract(halt=True)  # Never voice a rejected reply further.
        if state.ex.done:
            return None
        return '\n'.join(block['text'] for block in result if block['type'] == 'text')
    if not has_calls and reason == 'stop':
        failed = state.strike('empty', 'Model returned two empty responses; no completion was accepted', limit=2)
        trace.append({'invalid_native_response': 'empty_public_response',
                      'attempt': state.strikes['empty'], 'recovery': 'failed' if failed else 'continuation'})
        if failed:
            emit('error', state.ex.summary)
            return None
        # A complete empty response has no action to replay. Prior Tool results
        # stay in history and the next boundary still enforces cancellation and budgets.
        emit('event', 'Empty model response; continuing current request')
        return EMPTY_FEEDBACK
    if reason not in {'stop', 'tool-calls'}:
        raise RuntimeError(f'Executive model ended with {reason}; no incomplete Tool is dispatched')
    return None


def adopt_fast_lane(menu, metrics: dict, ctx: dict) -> None:
    """A selected effect proposal may later be confirmed by a cue (never dispatched here)."""
    detail = metrics.get('fast_lane') or {}
    label = detail.get('selected_label', '')
    if (menu and detail.get('status') == 'selected' and len(label) == 1
            and 0 <= ord(label) - ord('B') < len(menu)):
        proposal = menu[ord(label) - ord('B')]
        if proposal['name'] in {'lights.set', 'application.launch', 'session.unlock'}:
            ctx['_reflex_proposal'] = deepcopy(proposal)

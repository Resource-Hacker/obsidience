"""AutoSaddler V2 scenario ports over Obsidience's ADK Executive loop and model owner.

Imported only by harness.optimize. The upstream engine owns candidate search;
Obsidience owns model reservations, frozen operation results and publication.
Executive and specialist trials run ``run_adk_session`` in an isolated
in-memory ADK session.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Mapping
from dataclasses import replace

from autosaddler.v2.core.domain import (ArtifactRef, Case, Cost, Evaluation, Observation, PatchVerdict,
                                      canonical_json, sha256_digest)
from autosaddler.v2.core.engine import AutoSaddlerEngine
from autosaddler.v2.core.policies import (FixedTaskSelectionPolicy, FullOnAcceptDevelopment,
                                        MatchedValidStrictImprovement, MeanDevelopmentRanking, PolicyBundle)
from autosaddler.v2.core.ports import ScenarioComponents
from autosaddler.v2.harness.component_map import ComponentMapHarnessSpace
from autosaddler.v2.prompting.models import SessionResult, SessionSpec, Usage
from autosaddler.v2.storage.local import LocalRunStore

from ...config import CONFIG
from ...knowledge.vault import Resolver
from ...models import llm, runtime
from .. import executor, trace as action_trace
from ..adk.runner import run_adk_session
from . import EXECUTIVE, HEIMDALL, admission, store as evaluation_store
from .cases import frozen_notes
from .evaluation import FrozenTrial, compare_observations, fixture_json


# The retired JSON action loop's protocol, verbatim in its decision captures.
LEGACY_ACTION_PROTOCOL = """\
## Action protocol
The provider constrains your public response to one JSON object. Return only:
{"tool": "<tool-name>", "args": { ... }}
To finish, call task.complete with the arguments required by its selected
Tool and Skill contract. Completion requirements depend on the Task. Do not
assume status and summary alone suffice for an evidence-bound inspection.
Outcome and evidence belong in separate args fields when the contract requires them.
Use private reasoning when available, but put no commentary or Markdown in the
public response. Never invent tool names.
"""
_LEGACY_FENCE = re.compile(r"```(?:action|json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _legacy_action(text: str) -> dict | None:
    match = _LEGACY_FENCE.search(text)
    try:
        value = json.loads(match.group(1) if match else text.strip(), strict=False)
    except ValueError:
        return None
    if (isinstance(value, dict) and set(value) == {'tool', 'args'} and isinstance(value['tool'], str)
            and value['tool'].strip() and isinstance(value['args'], dict)):
        return value
    return None


def native_wire(messages: list[dict], model, effort: str) -> list[dict]:
    """A specialist decision captured by the retired JSON action loop, in the ADK wire format.

    The capture's exact text is kept: its action protocol becomes the native
    Task protocol, each recorded action a native Tool call and its Observation
    that call's result. The Task guidance follows, as on a live request.
    """
    from ..native_turn import TASK_PROTOCOL
    rows, pending = [], None
    for index, message in enumerate(messages):
        content = message['content']
        if pending is not None and not (message['role'] == 'user' and content.startswith('Observation:\n')):
            raise ValueError('Captured decision has an action without its observation; a fresh capture is required')
        if message['role'] == 'system':
            if LEGACY_ACTION_PROTOCOL not in content:
                raise ValueError('Captured decision uses an unknown action protocol; a fresh capture is required')
            rows.append({'role': 'system', 'content': content.replace(LEGACY_ACTION_PROTOCOL, TASK_PROTOCOL)})
        elif pending is not None:
            rows.append({'role': 'tool', 'tool_call_id': pending, 'content': content})
            pending = None
        elif message['role'] == 'assistant' and (action := _legacy_action(content)) is not None:
            pending = f'call-{index}'
            rows.append({'role': 'assistant', 'content': '', 'tool_calls': [{
                'id': pending, 'type': 'function', 'function': {
                    'name': action['tool'],
                    'arguments': json.dumps(action['args'], ensure_ascii=False, separators=(',', ':'))}}]})
        else:
            rows.append({'role': message['role'], 'content': content})
    if pending is not None:
        raise ValueError('Captured decision has an action without its observation; a fresh capture is required')
    return llm._chat_payload(rows, model, max_tokens=None, temperature=None, reasoning_effort=effort)['messages']


def _latency_sensitive(document: dict) -> bool:
    return (document['agent'] == EXECUTIVE
            and document['model_contract']['reasoning_effort'] == 'none')


def _slowdowns(before, after, *, check_latency: bool) -> list[str]:
    """Gate speed only for Executive without reasoning."""
    if not check_latency:
        return []
    failures = []
    for old, new in zip(before, after):
        if not old['passed'] or old.get('error') or new.get('error'):
            continue
        for metric in ('duration_ms', 'first_public_ms'):
            if old.get(metric) is not None and new.get(metric) is not None:
                # These few paired samples are an admission bound, not a claim
                # of statistical speedup. Small scheduling noise has 200 ms slack.
                if new[metric] > old[metric] * 1.25 + 200:
                    failures.append(old['case_id'] + ': ' + metric)
    return failures


# A trial may take read-only steps before its graded call. A job measures the
# seed's controls, three training rounds and one accepted candidate's controls.
TRIAL_SECONDS = 240
JOB_SECONDS = 2400
MAX_TRAJECTORY_BYTES = 160_000
MAX_TRIAL_SUMMARY_CHARS = 32_000
# Optimizer sessions return whole instruction units as JSON: six Harness2 sessions of
# job 7c3cf1a0 stopped at the model's 3,584-token reply cap (2026-10-19) and every
# truncated reply is refused, so these background sessions get room for a full Runbook.
OPTIMIZER_MAX_TOKENS = 12_288

# Repetitions of one case are independent samples of one model: the unchanged
# baseline's training passes varied by up to two of five between measurements
# (2026-10-13 jobs; 2/4/2/4 within one job). Cases are therefore compared by
# their pass counts, never repetition against repetition, and the baseline's
# pass rate comes from every training trial it ran in the job, not its first
# five. The training trials both select a candidate and judge it, so its gain
# must be far outside that spread. Controls the baseline mostly fails cannot
# show a regression (2026-10-13: 11 of 20 passed, failing as the incident did),
# so the candidate must also pass most of them.
TRAIN_MARGIN = 4
CONTROL_FLOOR = 0.75


def _train_improved(before, after) -> bool:
    """Every training trial passes, at least TRAIN_MARGIN more than the baseline's rate predicts.

    ``before`` is all of the baseline's training trials; with five candidate
    trials its pass rate may be at most one in five.
    """
    passed, base = sum(row['passed'] for row in after), sum(row['passed'] for row in before)
    return (bool(after) and bool(before) and passed == len(after)
            and passed * len(before) - base * len(after) >= TRAIN_MARGIN * len(before))


def _case_passes(before, after) -> dict:
    """Each case's split and its passes for the baseline, then the candidate."""
    cases = {}
    for index, rows in enumerate((before, after)):
        for row in rows:
            cases.setdefault(row['case_id'], {'split': row['split'], 'passed': [0, 0]})['passed'][index] += row['passed']
    return cases


def _holdout_regressed(cases: dict) -> bool:
    """The controls pass less often in total, or one of them by two or more repetitions."""
    held = [case['passed'] for case in cases.values() if case['split'] == 'holdout']
    return sum(new for _, new in held) < sum(old for old, _ in held) or any(old - new >= 2 for old, new in held)


def _controls_pass(candidate) -> bool:
    """The candidate passes at least CONTROL_FLOOR of its control trials."""
    held = [row['passed'] for row in candidate if row['split'] == 'holdout']
    return bool(held) and sum(held) >= CONTROL_FLOOR * len(held)


class JobBudget:
    """Upstream's budget, ended by the first accepted candidate.

    That candidate's controls are then the job's last measurement.
    """
    def __init__(self, store, *, max_rollouts: int, max_iterations: int):
        self.store, self.max_rollouts, self.max_iterations = store, max_rollouts, max_iterations

    def allows_iteration(self, *, iteration: int, attempted_rollouts: int) -> bool:
        return (iteration < self.max_iterations and attempted_rollouts < self.max_rollouts
                and not any(event.payload.get('accepted') is True
                            for event in self.store.events_of_type('EvolutionRecorded')))


def _extra_tool_calls(before, after) -> list[str]:
    """Controls whose passing candidate trials average over half a Tool call more.

    The corrected training case may need the read its rejection asked for.
    """
    def calls(rows):
        cases = {}
        for row in rows:
            if row['split'] == 'holdout' and row['passed'] and not row.get('error'):
                cases.setdefault(row['case_id'], []).append(row['tool_count'])
        return {case: sum(counts) / len(counts) for case, counts in cases.items()}
    old, new = calls(before), calls(after)
    return [case for case in old if case in new and new[case] > old[case] + 0.5]


class CompleteImprovement(MatchedValidStrictImprovement):
    def __init__(self, *, check_latency: bool, store):
        self.check_latency, self.store = check_latency, store

    def compare(self, parent, child):
        if any(not row.is_valid for row in (*parent.observations, *child.observations)):
            return PatchVerdict(before_score=0, after_score=0,
                compared_case_ids=parent.requested_case_ids, accepted=False,
                reason='Incomplete evaluation cannot select an improvement')
        verdict = super().compare(parent, child)
        before = [dict(row.metadata['result']) for row in parent.observations]
        after = [dict(row.metadata['result']) for row in child.observations]
        # Every valid training trial the parent ran in this job, this iteration's included.
        trained = [row['metadata']['result'] for event in self.store.events_of_type('EvaluationCompleted')
                   for row in event.payload['evaluation']['observations']
                   if row['candidate_id'] == parent.candidate_id and row['split'] == 'train'
                   and not row['metadata']['result'].get('error')]
        if not _train_improved(trained, after) or _slowdowns(before, after, check_latency=self.check_latency):
            return replace(verdict, accepted=False,
                           reason=f'Candidate must pass every training trial, at least {TRAIN_MARGIN} more than '
                                  'the baseline pass rate over the job predicts, within the applicable execution bounds')
        return verdict


class NativeEvaluator:
    def __init__(self, document, space, store, context):
        self.document, self.space, self.store, self.context = document, space, store, context
        self.fingerprint = document['evaluator_revision']

    async def evaluate(self, candidate, cases, context):
        materialized = self.space.materialize(candidate, 'evaluate')
        try:
            body = json.loads((materialized.root / 'candidate.json').read_text())['identity']
        finally:
            materialized.release()
        frozen = Resolver(frozen_notes(self.document))
        subject = frozen.resolve(admission.subject_ref(self.document))
        frozen = Resolver([replace(note, body=body) if note.ref == subject.ref else note
                           for note in frozen_notes(self.document)])
        agent = frozen.resolve(self.document['agent'])
        task = frozen.resolve(self.document.get('task', EXECUTIVE))
        spine = executor.resolve_spine(task, frozen)
        model = runtime.configured_spec(self.document['model_contract']['spec']['id'])
        observations = []
        for case in cases:
            if case.split != context.split:
                raise ValueError('Evaluation split mismatch')
            for repetition in range(context.repetitions):
                saved = context.attempt_sink.completed(candidate_id=candidate.candidate_id,
                                                      case_id=case.case_id, repetition=repetition)
                if saved is not None:
                    observations.append(saved)
                    continue
                attempt_id, attempt_number = context.attempt_sink.start(candidate_id=candidate.candidate_id,
                    case_id=case.case_id, repetition=repetition)
                specification = json.loads(canonical_json(case.payload))
                sections = {}
                executor._activation_packet(task, agent, spine,
                    executor.ActivationBinding(specification['objective'], specification.get('bindings', {})),
                    '', specification.get('knowledge', ''), specification.get('conversation', ''),
                    accepted_resolver=frozen, provider_sections=sections)
                messages = executor.activation_messages(task,
                    {**sections, 'params': {}, 'objective': specification['objective']}, agent_name=agent.title)
                if self.document.get('evaluation_mode') == 'contract':
                    from .incidents import trial_read, validate_decision
                    sample = specification['sample']
                    messages = json.loads(json.dumps(sample['messages']))
                    # The instruction text the prompt carries: the Executive's Runtime section, a Runbook's body.
                    captured = admission.bound_instructions(subject)
                    proposed = admission.bound_instructions(frozen.resolve(subject.ref))
                    replacements = 0
                    for message in messages:
                        content = message.get('content')
                        if isinstance(content, str):
                            replacements += content.count(captured)
                            message['content'] = content.replace(captured, proposed)
                    if not replacements:
                        raise ValueError('The captured prompt does not contain its exact instruction body')
                    trial = DecisionTrial(sample, validate_decision, trial_read)
                    # Preserve provider roles and Tool-call/result pairing; the
                    # ordinary bootstrap is not a wire replay.
                    trial.wire_messages = (messages if sample.get('prompt_format') == 'native_wire' else native_wire(
                        messages, model, self.document['model_contract']['reasoning_effort']))
                else:
                    trial = NativeTrial(specification)
                trial_context = {}
                variant = 'baseline' if not candidate.parent_ids else 'candidate'
                token = action_trace.bind_trial(attempt_id, case_id=case.case_id,
                    split=specification['split'], variant=variant, repetition=repetition + 1)
                started = time.monotonic()
                trace, status, summary, error = [], 'failed', '', None
                try:
                    action_trace.emit('status', 'Instruction optimizer native Executive trial started')
                    try:
                        async with asyncio.timeout(TRIAL_SECONDS):
                            trace, status, summary = await run_adk_session(
                                task, model, messages, sorted(set(spine['tools']) | {'task.complete'}),
                                trial_context, agent.title, self.document['model_contract']['reasoning_effort'],
                                interruption_event=self.context.get('_foreground_interruption_event'), evaluation=trial)
                        error = trial.error
                        # A rejected/wrong Tool or exhausted decision budget is
                        # a task failure. A missing observation fixture remains
                        # an infrastructure gap, never a pass or dropped sample.
                    except asyncio.CancelledError:
                        context.attempt_sink.fail(attempt_id, 'cancelled', Cost(rollouts=1,
                            wall_seconds=time.monotonic() - started))
                        raise
                    except Exception as exc:
                        error = type(exc).__name__ + ': ' + str(exc)[:300]
                    metrics = [row['provider_metrics'] for row in trace if 'provider_metrics' in row]
                    # Keep only the trial's public Tool-call/result and error events;
                    # no provider prompts, reasoning or controller context projections.
                    trajectory = [row for row in trace if any(key in row for key in
                        ('tool', 'invalid_tool', 'invalid_native_response', 'native_tool_error'))]
                    complete = (len(canonical_json(trajectory).encode()) <= MAX_TRAJECTORY_BYTES
                                and len(summary) <= MAX_TRIAL_SUMMARY_CHARS)
                    if not complete:
                        error = 'Native trial exceeds its complete trajectory bound'
                        trajectory, summary = [], 'Complete trajectory unavailable: exceeded the artifact bound'
                    result = {'case_id': case.case_id, 'split': specification['split'], 'repetition': repetition + 1,
                        'passed': trial.passed and error is None, 'error': error, 'status': status,
                        'summary': summary, 'tool_count': trial.tool_count,
                        'duration_ms': round((time.monotonic() - started) * 1000, 3),
                        'first_public_ms': metrics[0].get('first_public_delta_ms') if metrics else None,
                        'prompt_tokens': trial_context.get('prompt_tokens'), 'actions': trial.calls,
                        'trajectory': trajectory, 'trajectory_complete': complete}
                    prefix = 'quarantine/dev' if case.split == 'development' else 'evaluations'
                    output = self.store.write_json(f'{prefix}/{attempt_id}.json', result, kind='native-executive-trial')
                    cost = Cost(rollouts=1, wall_seconds=time.monotonic() - started,
                                input_tokens=sum(int(m.get('prompt_tokens', 0)) for m in metrics),
                                output_tokens=sum(int(m.get('output_tokens', 0)) for m in metrics))
                    observation = Observation.create(candidate_id=candidate.candidate_id, case_id=case.case_id,
                        split=case.split, repetition=repetition, attempts=attempt_number,
                        disposition='execution_error' if error else 'success' if result['passed'] else 'task_failure',
                        score=None if error else float(result['passed']), evaluator_fingerprint=self.fingerprint,
                        objectives={'duration_ms': result['duration_ms'], 'tool_count': trial.tool_count},
                        output=output, trace=output, cost=cost, metadata={'result': result, 'engine': 'adk'})
                    context.attempt_sink.complete(attempt_id, observation, cost)
                    observations.append(observation)
                    action_trace.emit('status', 'Instruction optimizer trial ' + ('passed' if result['passed'] else 'did not pass'))
                finally:
                    action_trace.reset(token)
        return Evaluation(evaluation_id=sha256_digest(context.operation_id), candidate_id=candidate.candidate_id,
            split=context.split, purpose=context.purpose, iteration=context.iteration,
            requested_case_ids=tuple(case.case_id for case in cases), observations=tuple(observations),
            artifact_dir=ArtifactRef(uri='quarantine/dev' if context.split == 'development' else 'evaluations',
                                     kind='evaluation-directory'))


class DecisionTrial:
    """One captured decision point, graded by a read-only Capability validation.

    The model may first take the read-only steps its procedure or the rejection
    asks for (a cited Article, vault.validate). They are answered from the
    current Vault into this trial's own context, and the first other call is
    graded against the receipts that context then holds.
    """
    read_steps = 4

    def __init__(self, sample, validator, reader):
        self.sample, self.validator, self.reader = sample, validator, reader
        self.case = {'objective': sample['context'].get('objective', 'Continue the bound procedure')}
        self.context = self.schema_context = json.loads(json.dumps(sample['context']))
        # The decisions the live run had left at this step, so the budget in
        # each further Tool result continues the captured one.
        limit = CONFIG.max_steps
        self.max_steps = min(limit, max(1, limit - sample['step'] + 1))
        self.passed, self.error, self.tool_count, self.calls = False, None, 0, []

    async def handle(self, name, args):
        self.calls.append({'tool': name, 'args': args})
        self.tool_count += name != 'task.complete'
        if len(self.calls) <= self.read_steps:
            observation = await asyncio.to_thread(self.reader, self.sample, self.context, name, args)
            if observation is not None:
                return {'done': False, 'observation': observation}
        self.passed, reason = await asyncio.to_thread(
            self.validator, {**self.sample, 'context': self.context}, name, args)
        return {'done': True, 'status': 'completed' if self.passed else 'failed',
                'summary': reason, 'observation': json.dumps({'passed': self.passed, 'reason': reason})}


class NativeTrial(FrozenTrial):
    async def handle(self, name, args):
        if name == 'computer.observe':
            # query is descriptive text, not the observation's target binding.
            # Permit phrasing changes only for one exact frozen target/result.
            matches = [row for row in self.case['responses'] if row['tool'] == name
                       and {k: v for k, v in row['args'].items() if k != 'query'}
                       == {k: v for k, v in args.items() if k != 'query'}]
            if len(matches) == 1:
                value = matches[0]['result']
                self._responses[(name, fixture_json(args))] = value if isinstance(value, str) else fixture_json(value)
        result = await super().handle(name, args)
        if not result.get('done'):
            from ..completion import computer_completion_evidence
            try:
                observed = json.loads(result['observation'])
            except ValueError:
                observed = None
            if not isinstance(observed, dict):
                observed = {}
            witness = computer_completion_evidence(name, observed)
            if name == 'computer.observe':
                observation = observed.get('observation', {})
                # This decision-only scenario substitutes owner-recorded text
                # for an image. Its witness is confined to the isolated trial;
                # it cannot attest physical capture or enter a live receipt.
                if (observation.get('status') == 'observed'
                        and observation.get('visible_text') and observation.get('evidence_scope')
                        and observation.get('target') == args.get('target')):
                    witness = {'verified': True, 'target': args['target'],
                               'simulated': True, 'evidence_scope': 'reconstructed_text'}
            if witness is not None:
                result['completion_evidence'] = {**witness, 'simulated': True}
        return result


_LIST_ITEM = re.compile(r'\s*(?:[-*+]|\d+[.)])\s')
UNIT_TEXT_LIMIT = 2500


def editable_units(body: str, subject: str) -> list[tuple[int, tuple[int, int]]]:
    """The numbered units a candidate may edit: those inside the subject's bound spans."""
    starts = [0]
    for line in body.split('\n'):
        starts.append(starts[-1] + len(line) + 1)
    bounds = admission.bound_spans(body, subject)
    return [(number, (start, end)) for number, (start, end) in enumerate(instruction_units(body), 1)
            if any(low <= starts[start] and starts[end] - 1 <= high for low, high in bounds)]


def instruction_units(body: str) -> list[tuple[int, int]]:
    """Line spans of the body's paragraphs, list items and headings.

    Bodies are hard-wrapped, so a sentence spans physical lines but never
    units: replacing a unit whole, or adding one after it, leaves no fragment.
    """
    lines = body.split('\n')
    spans, start = [], None
    for index, line in enumerate(lines):
        if start is not None and (not line.strip() or _LIST_ITEM.match(line)
                                  or line.startswith('#') or lines[index - 1].startswith('#')):
            spans.append((start, index))
            start = None
        if start is None and line.strip():
            start = index
    if start is not None:
        spans.append((start, len(lines)))
    return spans


class IdentityHarnessSpace(ComponentMapHarnessSpace):
    """Apply bounded whole-unit edits through the upstream candidate finalizer."""

    def apply_mutation(self, session, outcome):
        output = outcome.result.structured_output
        edits = output.get('edits') if isinstance(output, Mapping) else None
        if not isinstance(edits, (list, tuple)) or not 1 <= len(edits) <= 3:
            raise ValueError('An identity candidate requires one to three edits')
        lines = json.loads((session.workspace / 'candidate.json').read_text())['identity'].split('\n')
        spans = instruction_units('\n'.join(lines))
        changes = {}
        for edit in edits:
            if not isinstance(edit, Mapping) or set(edit) != {'unit', 'action', 'text'}:
                raise ValueError('Each identity edit requires unit, action and text only')
            unit, action, text = edit['unit'], edit['action'], edit['text']
            if (type(unit) is not int or not 1 <= unit <= len(spans) or unit in changes
                    or action not in {'replace', 'insert_after'}
                    or not isinstance(text, str) or not text.strip() or len(text) > UNIT_TEXT_LIMIT):
                raise ValueError('Each identity edit must give one distinct unit of the current body its bounded text')
            changes[unit] = action, text.strip('\n').split('\n')
        # Last unit first: earlier spans keep their line numbers.
        for unit in sorted(changes, reverse=True):
            (start, end), (action, text) = spans[unit - 1], changes[unit]
            if action == 'replace':
                if '\n'.join(text).split() == '\n'.join(lines[start:end]).split():
                    raise ValueError('A replacement must change its unit')
                lines[start:end] = text
            else:
                # After a paragraph the text is its own paragraph; inside a list it is the next item.
                lines[end:end] = [''] + text if end == len(lines) or not lines[end].strip() else text
        self.apply_updates(session, {'identity': '\n'.join(lines)})


class TrainingEvidence:
    def __init__(self, store, document):
        self.store, self.document = store, document

    def build(self, evaluation):
        if evaluation.split != 'train':
            raise ValueError('Only training evidence may reach the optimizer')
        cases = {case['id']: case for case in self.document['suite']['cases'] if case['split'] == 'train'}
        rows = [{'case_id': row.case_id, 'objective': cases[row.case_id]['objective'],
                 'result': dict(row.metadata['result']),
                 **{key: cases[row.case_id][key] for key in
                    ('expected', 'responses', 'bindings', 'conversation', 'knowledge') if key in cases[row.case_id]},
                 **({'original_rejection': cases[row.case_id]['sample']['result'],
                     'original_arguments': cases[row.case_id]['sample']['args']}
                    if 'sample' in cases[row.case_id] else {})}
                for row in evaluation.observations]
        return self.store.write_json('evidence/' + evaluation.evaluation_id.removeprefix('sha256:') + '.json',
                                    {'problem': self.document['problem'], 'observations': rows}, kind='training-evidence')


class ExecutivePrompts:
    def __init__(self, store, document):
        self.store, self.document = store, document

    def session(self, kind, context):
        # The provider receives explicit bounded data, never filesystem tools
        # that could reach held-out cases, live Articles or desktop effects.
        data = {key: value for key, value in context.items() if 'development' not in key}
        if kind == 'diagnose_patch':
            data['training_evidence'] = self.store.read_json(context['evidence']['uri'])
            from ...capabilities.registry import argument_schema
            relevant = {'task.complete'}
            for case in self.document['suite']['cases']:
                if case['split'] != 'train':
                    continue
                relevant.update(row['tool'] for row in case.get('responses', []))
                if sample := case.get('sample'):
                    relevant.add(sample['tool'])
                    relevant.update({'source.read', 'vault.search'} & set(sample['allowed']))
            data['tool_contracts'] = {name: argument_schema(name) for name in sorted(relevant)}
            data['capability_instructions'] = {note.ref: note.body for note in frozen_notes(self.document)
                if note.kind in {'tool', 'skill'} and note.ref.rsplit('/', 1)[-1] in relevant}
        if kind in {'diagnose_patch', 'reflect'}:
            candidate_id = context['candidate_ids'][0]
            data['candidate'] = self.store.read_json('candidates/' + candidate_id.removeprefix('sha256:') + '/candidate.json')
        text = {'type': 'string'}
        if kind == 'evolve':
            properties = {'schema_version': {'const': 'autosaddler-evolution/v1'},
                          'parent_ids': {'type': 'array', 'items': text, 'minItems': 1, 'maxItems': 1},
                          'component_sources': {'type': 'object', 'properties': {}, 'additionalProperties': False},
                          'rationale': text}
            instruction = 'Select one existing accepted parent ID.'
        elif kind == 'diagnose_patch':
            # The body as its numbered units; the envelope around it is not instruction text.
            lines = data.pop('candidate')['identity'].split('\n')
            units = editable_units('\n'.join(lines), admission.subject_ref(self.document))
            if not units:
                raise ValueError('The instruction body has no unit to edit')
            data['instruction_units'] = [{'unit': number, 'text': '\n'.join(lines[start:end])}
                                         for number, (start, end) in units]
            properties = {'schema_version': {'const': 'autosaddler-diagnosis-patch/v1'},
                          'edits': {'type': 'array', 'minItems': 1, 'maxItems': 3, 'items': {
                              'type': 'object', 'properties': {
                                  'unit': {'type': 'integer', 'enum': [number for number, _span in units]},
                                  'action': {'type': 'string', 'enum': ['replace', 'insert_after']},
                                  'text': {'type': 'string', 'maxLength': UNIT_TEXT_LIMIT}},
                              'required': ['unit', 'action', 'text'], 'additionalProperties': False}},
                          'diagnosis': {'type': 'string', 'maxLength': 1000}}
            instruction = ('Diagnose why the training trials failed and return one to three small edits to the supplied Agent identity or Runbook. '
                           'training_evidence.observations holds each trial: result.actions are the calls the model made and '
                           'result.summary is the contract\'s reason for its outcome. Correct what those trials show; '
                           'original_rejection is the earlier incident and may no longer reproduce. '
                           'instruction_units is the body in order: each unit is one whole paragraph, list item or heading. '
                           'An edit names one unit, at most once. "replace" puts your text in place of that whole unit: write the '
                           'complete unit with its list marker and indentation, repeating word for word every sentence you are not changing. '
                           '"insert_after" adds your text as a new paragraph or list item after that unit and leaves the unit as it is. '
                           'Keep its identity, owner preferences, Article links and unrelated functionality. Make the smallest '
                           'instruction correction. Do not add case-specific answers, names, new capabilities, authority, '
                           'reasoning modes or extra mandatory Tool calls. Correctness comes first; preserve fast simple answers. '
                           'Do not copy the input envelope or metadata into the body.')
        elif kind == 'reflect':
            properties = {'schema_version': {'const': 'autosaddler-reflection/v1'},
                          'lessons': {'type': 'array', 'maxItems': 3, 'items': {
                              'type': 'object', 'properties': {
                                  'lesson': {'type': 'string', 'maxLength': 1000},
                                  'evidence_case_ids': {'type': 'array', 'items': {
                                      'type': 'string', 'enum': list(context.get('train_case_ids', []))},
                                      'maxItems': 6}},
                              'required': ['lesson', 'evidence_case_ids'], 'additionalProperties': False}}}
            instruction = 'Return at most three concise lessons grounded in the matched training outcomes.'
        else:
            raise ValueError('Unsupported AutoSaddler session kind')
        return SessionSpec(kind=kind, system_context=instruction,
            task_prompt=canonical_json(data), skills={}, workspace_files={}, capabilities=frozenset(),
            output_schema={'type': 'object', 'properties': properties,
                           'required': list(properties), 'additionalProperties': False})


class ReservedModelProvider:
    """An upstream AgentProvider using the Audit-selected model and shared lease."""
    def __init__(self, audit):
        self.spec = runtime.resolve_model(audit.meta.get('model'), HEIMDALL)
        self.effort = llm.normalize_reasoning_effort(audit.meta.get('reasoning_effort'))

    async def run(self, request):
        data = json.loads(request.spec.task_prompt)
        if request.spec.kind == 'evolve' and len(data['candidate_ids']) == 1:
            output = {'schema_version': 'autosaddler-evolution/v1', 'parent_ids': data['candidate_ids'],
                      'component_sources': {}, 'rationale': 'Only one accepted parent is available.'}
            return SessionResult(status='completed', structured_output=output, raw_response=canonical_json(output),
                                 tool_calls=(), usage=(), cost=Cost())
        action_trace.emit('status', 'Instruction optimizer ' + request.spec.kind.replace('_', ' '))
        started = time.monotonic()
        async with asyncio.timeout(request.timeout_seconds):
            async with runtime.lease(self.spec) as model:
                reply = await llm.chat([{'role': 'system', 'content': request.spec.system_context},
                                        {'role': 'user', 'content': request.spec.task_prompt}],
                                       model=model, reasoning_effort=self.effort,
                                       max_tokens=OPTIMIZER_MAX_TOKENS,
                                       response_schema=json.loads(canonical_json(request.spec.output_schema)))
        error = None
        output = None
        if reply.finish_reason != 'stop':
            error = 'Optimizer response did not finish; no partial candidate is admitted'
        else:
            try:
                output = json.loads(reply.content)
            except ValueError:
                error = 'Optimizer response was not a complete JSON object'
        usage = Usage(input_tokens=reply.prompt_tokens or 0, output_tokens=reply.completion_tokens or 0,
                      model=self.spec.id, duration_seconds=time.monotonic() - started,
                      status='failed' if error else 'success', error_type='invalid_output' if error else None)
        return SessionResult(status='failed' if error else 'completed', structured_output=output,
            raw_response=reply.content, error=error,
            tool_calls=(), usage=(usage,), cost=Cost(sessions=1, input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens, wall_seconds=time.monotonic() - started))


def comparison(document, rows, seed_id, selected_id, search=None):
    """``search``: Harness2's search measurements by candidate; the baseline's count toward its pass rate."""
    def ordered(candidate_id):
        # Upstream can re-evaluate a parent in later iterations. Keep its first
        # recorded observation for each case, rather than changing the final
        # baseline after seeing candidate outcomes.
        found = {}
        for row in rows.get(candidate_id, []):
            found.setdefault((row['case_id'], row['split'], row['repetition']), row)
        expected = [(c['id'], c['split'], n + 1) for c in document['suite']['cases']
                    for n in range(document['suite']['repetitions'])]
        return [found[key] for key in expected if key in found]
    baseline, candidate = ordered(seed_id), ordered(selected_id)
    # Coverage and bookkeeping; its repetition pairs do not decide the verdict.
    result = compare_observations(baseline, candidate)
    count = len(document['suite']['cases']) * document['suite']['repetitions']
    if len(baseline) != count or len(candidate) != count:
        result['verdict'] = 'incomplete'
    # The baseline's pass rate: every training trial it ran in the job. An
    # execution error is no evidence either way.
    trained = [row for row in (*rows.get(seed_id, []), *(search or {}).get(seed_id, []))
               if row['split'] == 'train' and not row.get('error')]
    result['baseline_train_passed'] = [sum(row['passed'] for row in trained), len(trained)]
    if result['verdict'] != 'incomplete':
        result['cases'] = _case_passes(baseline, candidate)
        result['verdict'] = ('regressed' if _holdout_regressed(result['cases']) else
                             'passed' if _controls_pass(candidate) and _train_improved(
                                 trained, [row for row in candidate if row['split'] == 'train'])
                             else 'not_improved')
    check_latency = _latency_sensitive(document)
    slowdowns = (_slowdowns(baseline, candidate, check_latency=check_latency)
                 if len(baseline) == len(candidate) else [])
    result['latency_checked'] = check_latency
    result['latency_regressions'] = slowdowns
    result['tool_count_regressions'] = (_extra_tool_calls(baseline, candidate)
                                        if len(baseline) == len(candidate) else [])
    if result['verdict'] == 'passed' and result['tool_count_regressions']:
        result['verdict'] = 'tool_count_regressed'
    elif result['verdict'] == 'passed' and slowdowns:
        result['verdict'] = 'latency_regressed'
    return result


async def run_autosaddler(case_id, document, audit, context):
    run_dir = evaluation_store.root() / 'executive/jobs' / case_id
    if any(path.is_symlink() for path in (run_dir, *run_dir.parents)):
        raise ValueError('Optimization artifacts cannot follow symlinks')
    store = LocalRunStore(run_dir=run_dir, run_id=case_id)
    store.initialize(resolved_config={'scenario': 'obsidience', 'case_id': case_id,
                                     'max_iterations': 3, 'upstream_revision': admission.UPSTREAM_REVISION},
                     resolved_entities={'resolved/optimizer.json': document['optimizer_contract']})
    baseline = Resolver(frozen_notes(document)).resolve(admission.subject_ref(document)).body
    space = IdentityHarnessSpace(baseline={'identity': baseline}, store_root=run_dir / 'candidates',
        validator=lambda components: admission.validate_body(components['identity'], baseline, admission.subject_ref(document)))
    cases = tuple(Case(case_id=case['id'], split='train' if case['split'] == 'train' else 'development', payload=case)
                  for case in document['suite']['cases'])
    evaluator = NativeEvaluator(document, space, store, context)
    scenario = ScenarioComponents(name='obsidience', version='2', harness_space=space,
        evaluator=evaluator, evidence_builder=TrainingEvidence(store, document), prompt_pack=ExecutivePrompts(store, document),
        train_cases=tuple(case for case in cases if case.split == 'train'),
        development_cases=tuple(case for case in cases if case.split == 'development'),
        required_capabilities=frozenset(), evaluation_repetitions=document['suite']['repetitions'])
    engine = AutoSaddlerEngine(store=store, scenario=scenario, provider=ReservedModelProvider(audit),
        policies=PolicyBundle(task_selection=FixedTaskSelectionPolicy(batch_size=len(scenario.train_cases)),
            acceptance=CompleteImprovement(check_latency=_latency_sensitive(document), store=store),
            development=FullOnAcceptDevelopment(), ranking=MeanDevelopmentRanking(),
            budget=JobBudget(store, max_rollouts=len(cases) * document['suite']['repetitions'] * 4, max_iterations=3)),
        diagnosis_patch_timeout_seconds=180, reflection_timeout_seconds=90)
    failure = None
    result = None
    try:
        async with asyncio.timeout(JOB_SECONDS):
            result = await engine.optimize()
    except Exception as exc:
        # A completed audit can report incomplete evidence. Cancellation still
        # propagates and never becomes a terminal report or candidate.
        failure = {'session': 'engine', 'error': type(exc).__name__ + ': ' + str(exc)[:1000]}
    rows = {}
    for event in store.events_of_type('EvaluationCompleted'):
        evaluation = event.payload.get('evaluation', {})
        for row in evaluation.get('observations', []):
            rows.setdefault(row['candidate_id'], []).append(dict(row['metadata']['result']))
    seed_id = space.seed().candidate_id
    selected_id = result.selected_candidate_id if result is not None else seed_id
    selected = store.read_json('candidates/' + selected_id.removeprefix('sha256:') + '/candidate.json')
    compared = comparison(document, rows, seed_id, selected_id)
    completed_operations = {event.payload.get('logical_operation_id')
                            for event in store.events_of_type('SessionCompleted')}
    failures = [{'session': event.payload.get('stage', event.payload.get('session_id', 'optimizer')),
                 'error': str(event.payload.get('error', event.payload.get('reason', 'Session failed')))[:1000],
                 'resolved': bool(event.payload.get('logical_operation_id')
                                  and event.payload['logical_operation_id'] in completed_operations)}
                for event in store.events_of_type('SessionFailed')]
    evaluated_change = any(candidate_id != seed_id for candidate_id in rows)
    failures.extend({'session': 'mutation',
                     'error': str(event.payload.get('verification_failure', 'Mutation rejected'))[:1000],
                     'resolved': evaluated_change}
                    for event in store.events_of_type('MutationRejected'))
    if failure:
        failures.append(failure)
    if any(not item.get('resolved') for item in failures):
        compared['verdict'] = 'incomplete'
    return {'schema_version': 1, 'case_id': case_id, 'audit_run_id': context['run_id'],
            'upstream_revision': admission.UPSTREAM_REVISION, 'evaluator_revision': document['evaluator_revision'],
            'model_contract': document['model_contract'], 'backend_contract': document['backend_contract'],
            'candidate_body': selected['identity'],
            'seed_id': seed_id, 'selected_id': selected_id, 'observations': rows, 'optimizer_failures': failures,
            'verdict': compared['verdict'], 'comparison': compared, 'scope': document['scope'],
            'job_path': str(run_dir.relative_to(CONFIG.project_root))}


async def run(case_id, document, audit, context):
    """One active engine; failures never select the rollback backend implicitly."""
    from .backend import contract
    if document.get('backend_contract') != contract():
        raise ValueError('Optimizer backend changed; prepare a fresh case')
    if document['backend_contract']['name'] == 'autosaddler':
        return await run_autosaddler(case_id, document, audit, context)
    from .harness2 import run as run_harness2
    return await run_harness2(case_id, document, audit, context)

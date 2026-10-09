"""AutoSaddler V2 scenario ports over Obsidience's ADK Executive loop and model owner.

Imported only by harness.optimize. The upstream engine owns candidate search;
Obsidience owns model reservations, frozen operation results and publication.
Executive trials run ``run_adk_session`` in an isolated in-memory ADK session.
"""
from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Mapping
from dataclasses import replace

from autosaddler.v2.core.domain import (ArtifactRef, Case, Cost, Evaluation, Observation, PatchVerdict,
                                      canonical_json, sha256_digest)
from autosaddler.v2.core.engine import AutoSaddlerEngine
from autosaddler.v2.core.policies import (BudgetPolicy, FixedTaskSelectionPolicy, FullOnAcceptDevelopment,
                                        MatchedValidStrictImprovement, MeanDevelopmentRanking, PolicyBundle)
from autosaddler.v2.core.ports import ScenarioComponents
from autosaddler.v2.harness.component_map import ComponentMapHarnessSpace
from autosaddler.v2.prompting.models import SessionResult, SessionSpec, Usage
from autosaddler.v2.storage.local import LocalRunStore

from ...knowledge.vault import Resolver
from ...models import llm, runtime
from .. import executor, optimization, refinement, trace as action_trace
from ..evaluation import FrozenTrial, compare_observations
from .runner import run_adk_session


def _latency_sensitive(document: dict) -> bool:
    return (document['agent'] == optimization.EXECUTIVE
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


def _extra_tool_calls(before, after) -> list[str]:
    return [old['case_id'] for old, new in zip(before, after)
            if old['passed'] and not old.get('error') and not new.get('error')
            and new['tool_count'] > old['tool_count']]


class CompleteImprovement(MatchedValidStrictImprovement):
    def __init__(self, *, check_latency: bool):
        self.check_latency = check_latency

    def compare(self, parent, child):
        if any(not row.is_valid for row in (*parent.observations, *child.observations)):
            return PatchVerdict(before_score=0, after_score=0,
                compared_case_ids=parent.requested_case_ids, accepted=False,
                reason='Incomplete evaluation cannot select an improvement')
        verdict = super().compare(parent, child)
        before = [dict(row.metadata['result']) for row in parent.observations]
        after = [dict(row.metadata['result']) for row in child.observations]
        if (any(row.disposition != 'success' for row in child.observations)
                or _extra_tool_calls(before, after)
                or _slowdowns(before, after, check_latency=self.check_latency)):
            return replace(verdict, accepted=False,
                           reason='Candidate must pass every case and preserve the applicable execution bounds')
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
        frozen = Resolver(refinement._notes(self.document))
        subject = frozen.resolve(optimization.subject_ref(self.document))
        frozen = Resolver([replace(note, body=body) if note.ref == subject.ref else note
                           for note in refinement._notes(self.document)])
        agent = frozen.resolve(self.document['agent'])
        task = frozen.resolve(self.document.get('task', optimization.EXECUTIVE))
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
                    from ..optimization_incidents import validate_decision
                    sample = specification['sample']
                    messages = json.loads(json.dumps(sample['messages']))
                    replacements = 0
                    for message in messages:
                        content = message.get('content')
                        if isinstance(content, str):
                            replacements += content.count(subject.body.strip())
                            message['content'] = content.replace(subject.body.strip(), body.strip())
                    if not replacements:
                        raise ValueError('The captured prompt does not contain its exact instruction body')
                    trial = DecisionTrial(sample, validate_decision)
                    if sample.get('prompt_format') == 'native_wire':
                        # Preserve provider roles and Tool-call/result pairing;
                        # the ordinary native bootstrap is not a wire replay.
                        trial.wire_messages = messages
                else:
                    trial = NativeTrial(specification)
                trial_context = {}
                variant = 'baseline' if not candidate.parent_ids else 'candidate'
                token = action_trace.bind_trial(attempt_id, case_id=case.case_id,
                    split=specification['split'], variant=variant, repetition=repetition + 1)
                started = time.monotonic()
                trace, status, summary, error = [], 'failed', '', None
                try:
                    action_trace.emit('status', 'AutoSaddler native Executive trial started')
                    try:
                        async with asyncio.timeout(90):
                            runner = run_adk_session if task.kind == 'agent' else executor._execute_session
                            trace, status, summary = await runner(
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
                    result = {'case_id': case.case_id, 'split': specification['split'], 'repetition': repetition + 1,
                        'passed': trial.passed and error is None, 'error': error, 'status': status,
                        'summary': summary[:2000], 'tool_count': trial.tool_count,
                        'duration_ms': round((time.monotonic() - started) * 1000, 3),
                        'first_public_ms': metrics[0].get('first_public_delta_ms') if metrics else None,
                        'prompt_tokens': trial_context.get('prompt_tokens'), 'actions': trial.calls}
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
                        output=output, trace=output, cost=cost, metadata={'result': result,
                            'engine': 'adk' if task.kind == 'agent' else 'specialist'})
                    context.attempt_sink.complete(attempt_id, observation, cost)
                    observations.append(observation)
                    action_trace.emit('status', 'AutoSaddler trial ' + ('passed' if result['passed'] else 'did not pass'))
                finally:
                    action_trace.reset(token)
        return Evaluation(evaluation_id=sha256_digest(context.operation_id), candidate_id=candidate.candidate_id,
            split=context.split, purpose=context.purpose, iteration=context.iteration,
            requested_case_ids=tuple(case.case_id for case in cases), observations=tuple(observations),
            artifact_dir=ArtifactRef(uri='quarantine/dev' if context.split == 'development' else 'evaluations',
                                     kind='evaluation-directory'))


class DecisionTrial:
    """One actual model decision graded by a read-only Capability validation."""
    max_steps = 2
    def __init__(self, sample, validator):
        self.sample, self.validator = sample, validator
        self.case = {'objective': sample['context'].get('objective', 'Continue the bound procedure')}
        self.schema_context = sample['context']
        self.passed, self.error, self.tool_count, self.calls = False, None, 0, []

    async def handle(self, name, args):
        self.calls.append({'tool': name, 'args': args})
        self.tool_count += name != 'task.complete'
        self.passed, reason = await asyncio.to_thread(self.validator, self.sample, name, args)
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
                from ..evaluation import _json
                value = matches[0]['result']
                self._responses[(name, _json(args))] = value if isinstance(value, str) else _json(value)
        result = await super().handle(name, args)
        if not result.get('done'):
            from ...capabilities.task.complete import computer_completion_evidence
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


class IdentityHarnessSpace(ComponentMapHarnessSpace):
    """Apply bounded exact edits through the upstream candidate finalizer."""

    def apply_mutation(self, session, outcome):
        output = outcome.result.structured_output
        edits = output.get('edits') if isinstance(output, Mapping) else None
        if not isinstance(edits, (list, tuple)) or not 1 <= len(edits) <= 3:
            raise ValueError('An identity candidate requires one to three exact edits')
        body = json.loads((session.workspace / 'candidate.json').read_text())['identity']
        for edit in edits:
            if not isinstance(edit, Mapping) or set(edit) != {'old', 'new'}:
                raise ValueError('Each identity edit requires old and new text only')
            old, new = edit['old'], edit['new']
            if (not isinstance(old, str) or not 1 <= len(old) <= 1000
                    or not isinstance(new, str) or len(new) > 1500 or old == new
                    or body.count(old) != 1):
                raise ValueError('An identity edit must uniquely match the current body')
            body = body.replace(old, new, 1)
        self.apply_updates(session, {'identity': body})


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
            data['capability_instructions'] = {note.ref: note.body for note in refinement._notes(self.document)
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
            properties = {'schema_version': {'const': 'autosaddler-diagnosis-patch/v1'},
                          'edits': {'type': 'array', 'minItems': 1, 'maxItems': 3, 'items': {
                              'type': 'object', 'properties': {
                                  'old': {'type': 'string', 'minLength': 1, 'maxLength': 1000},
                                  'new': {'type': 'string', 'maxLength': 1500}},
                              'required': ['old', 'new'], 'additionalProperties': False}},
                          'diagnosis': {'type': 'string', 'maxLength': 1000}}
            instruction = ('Diagnose the observed failure and return one to three small exact text edits to the supplied Agent identity or Runbook. '
                           'Each old string must occur exactly once in the current body; new replaces that string. '
                           'Return only the edits, never repeat the complete body. '
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
        self.spec = runtime.resolve_model(audit.meta.get('model'), refinement.HEIMDALL)
        self.effort = llm.normalize_reasoning_effort(audit.meta.get('reasoning_effort'))

    async def run(self, request):
        data = json.loads(request.spec.task_prompt)
        if request.spec.kind == 'evolve' and len(data['candidate_ids']) == 1:
            output = {'schema_version': 'autosaddler-evolution/v1', 'parent_ids': data['candidate_ids'],
                      'component_sources': {}, 'rationale': 'Only one accepted parent is available.'}
            return SessionResult(status='completed', structured_output=output, raw_response=canonical_json(output),
                                 tool_calls=(), usage=(), cost=Cost())
        action_trace.emit('status', 'AutoSaddler ' + request.spec.kind.replace('_', ' '))
        started = time.monotonic()
        async with asyncio.timeout(request.timeout_seconds):
            async with runtime.lease(self.spec) as model:
                reply = await llm.chat([{'role': 'system', 'content': request.spec.system_context},
                                        {'role': 'user', 'content': request.spec.task_prompt}],
                                       model=model, reasoning_effort=self.effort,
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


def comparison(document, rows, seed_id, selected_id):
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
    result = compare_observations(baseline, candidate)
    count = len(document['suite']['cases']) * document['suite']['repetitions']
    if len(baseline) != count or len(candidate) != count:
        result['verdict'] = 'incomplete'
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


async def run(case_id, document, audit, context):
    run_dir = refinement._root() / 'executive/jobs' / case_id
    if any(path.is_symlink() for path in (run_dir, *run_dir.parents)):
        raise ValueError('Optimization artifacts cannot follow symlinks')
    store = LocalRunStore(run_dir=run_dir, run_id=case_id)
    store.initialize(resolved_config={'scenario': 'obsidience', 'case_id': case_id,
                                     'max_iterations': 3, 'upstream_revision': optimization.UPSTREAM_REVISION},
                     resolved_entities={'resolved/optimizer.json': document['optimizer_contract']})
    baseline = Resolver(refinement._notes(document)).resolve(optimization.subject_ref(document)).body
    space = IdentityHarnessSpace(baseline={'identity': baseline}, store_root=run_dir / 'candidates',
        validator=lambda components: optimization.validate_body(components['identity'], baseline, optimization.subject_ref(document)))
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
            acceptance=CompleteImprovement(check_latency=_latency_sensitive(document)),
            development=FullOnAcceptDevelopment(), ranking=MeanDevelopmentRanking(),
            budget=BudgetPolicy(max_rollouts=len(cases) * document['suite']['repetitions'] * 4, max_iterations=3)),
        diagnosis_patch_timeout_seconds=180, reflection_timeout_seconds=90)
    failure = None
    result = None
    try:
        async with asyncio.timeout(900):
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
    if failure:
        failures.append(failure)
    if any(not item.get('resolved') for item in failures):
        compared['verdict'] = 'incomplete'
    return {'schema_version': 1, 'case_id': case_id, 'audit_run_id': context['run_id'],
            'upstream_revision': optimization.UPSTREAM_REVISION, 'evaluator_revision': document['evaluator_revision'],
            'model_contract': document['model_contract'], 'candidate_body': selected['identity'],
            'seed_id': seed_id, 'selected_id': selected_id, 'observations': rows, 'optimizer_failures': failures,
            'verdict': compared['verdict'], 'comparison': compared, 'scope': document['scope'],
            'job_path': str(run_dir.relative_to(refinement.CONFIG.project_root))}

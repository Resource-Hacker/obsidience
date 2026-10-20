"""Harness2's sequential method, bounded by the existing ADK/model/artifact owners.

Only training trajectories cross the upstream context seam. The upstream scheduler,
CLI providers, proposal cache, selector and shared library writer are never used.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import threading
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from autosaddler.v2.core.attempts import EventEvaluationAttemptSink
from autosaddler.v2.core.domain import Case, canonical_json, sha256_digest
from autosaddler.v2.core.ports import EvaluationContext, MutationContext, MutationOutcome
from autosaddler.v2.core.serde import evaluation_from, record
from autosaddler.v2.prompting.models import SessionRequest, SessionSpec, session_output_validation_error
from autosaddler.v2.storage.local import LocalRunStore
from harness2.core import prompts, recursion, tree
from harness2.core.proposer import ProposerError, Reply
from harness2.core.spec import BenchPrompts, RunView

from ...config import CONFIG
from ...knowledge.vault import Resolver
from ..adk import optimization as native
from . import admission, cases, store as artifacts

# k=1: baseline, INV, DOM, composition; six sessions permit one invalid-output
# retry for each stage, plus one optional training-only reflection.
MAX_SESSIONS = 7
SESSION_SECONDS = 180
MAX_ATTEMPTS_PER_TRIAL = 2
MAX_CONTEXT_BYTES = 600_000
# Reuse upstream's AGENTS.md text profile; the adapter admits only that one
# instruction file and uses ADK, never the Codex/OpenCode execution channels.
SURFACE = tree.SurfaceSpec(name='codex', always_on=('AGENTS.md',),
    always_on_max=16_000, always_on_cap_reason='Bounded accepted instruction body',
    skill_dir='skills', skill_name_rule='disabled', trigger_hint='',
    autotrigger_file='AGENTS.md', trigger_line='', subagent_requires_mode=False,
    plugin_dir=None, hooks_file=None, reject_empty_always_on=True)
PROMPTS = BenchPrompts(work='Improve an Agent identity or Runbook for reliable native Tool use.',
    domain_word='instruction contract', deliverable_word='native Tool decision',
    inv_levers='Ordering and clarity of the existing whole instruction units.',
    dom_levers='General procedural distinctions supported by the supplied training trajectories.',
    yardstick='Preserve accepted capabilities, authority, linked Articles and unrelated behavior.')


class Stopped(BaseException):
    """Leave upstream retry/catch blocks immediately after owned cancellation."""


class LoopBridge:
    """Upstream's synchronous workers use the owning loop, never another event loop."""
    def __init__(self):
        self.loop = asyncio.get_running_loop()
        self.stop = threading.Event()
        self.tasks = set()

    async def _owned(self, factory):
        if self.stop.is_set():
            raise asyncio.CancelledError
        task = asyncio.current_task()
        self.tasks.add(task)
        try:
            return await factory()
        finally:
            self.tasks.discard(task)

    def call(self, factory):
        if self.stop.is_set():
            raise Stopped()
        pending = asyncio.run_coroutine_threadsafe(self._owned(factory), self.loop)
        try:
            return pending.result()
        except concurrent.futures.CancelledError:
            raise Stopped() from None

    async def cancel(self):
        self.stop.set()
        tasks = tuple(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


class TrialBudget(EventEvaluationAttemptSink):
    """Count persisted starts, including interrupted work, across every resume."""
    def __init__(self, *, maximum, **kwargs):
        super().__init__(**kwargs)
        self.maximum = maximum

    def start(self, *, candidate_id, case_id, repetition):
        starts = self.store.events_of_type('EvaluationAttemptStarted')
        matching = [e for e in starts if self._matches(e.payload, candidate_id, case_id, repetition)]
        if len(starts) >= self.maximum or len(matching) >= MAX_ATTEMPTS_PER_TRIAL:
            raise ValueError('Harness2 frozen rollout/attempt budget exhausted')
        return super().start(candidate_id=candidate_id, case_id=case_id, repetition=repetition)


class Job:
    def __init__(self, case_id, document, audit, context):
        self.case_id, self.document, self.context = case_id, document, context
        self.run_dir = artifacts.root() / 'executive/jobs' / case_id
        if any(p.is_symlink() for p in (self.run_dir, *self.run_dir.parents)):
            raise ValueError('Optimization artifacts cannot follow symlinks')
        self.store = LocalRunStore(run_dir=self.run_dir, run_id=case_id)
        self.store.initialize(resolved_config={'scenario': 'obsidience-harness2', 'case_id': case_id,
            'backend_contract': document['backend_contract'], 'implementation': document['evaluator_revision'],
            'case_sha256': artifacts.sha256(artifacts.canonical_json(document).encode()),
            'k': 1, 'width': 1, 'max_sessions': MAX_SESSIONS},
            resolved_entities={'resolved/optimizer.json': document['optimizer_contract']})
        self.store.validate_integrity()
        self.baseline = Resolver(cases.frozen_notes(document)).resolve(admission.subject_ref(document)).body
        self.space = native.IdentityHarnessSpace(baseline={'identity': self.baseline},
            store_root=self.run_dir / 'candidates', validator=lambda values: admission.validate_body(
                values['identity'], self.baseline, admission.subject_ref(document)))
        self.seed = self.space.seed()
        self.candidates = {self.baseline: self.seed}
        self.evaluator = native.NativeEvaluator(document, self.space, self.store, context)
        self.provider = native.ReservedModelProvider(audit)
        self.training = tuple(Case(case_id=c['id'], split='train', payload=c)
                              for c in document['suite']['cases'] if c['split'] == 'train')
        self.controls = tuple(Case(case_id=c['id'], split='development', payload=c)
                              for c in document['suite']['cases'] if c['split'] == 'holdout')
        reps = document['suite']['repetitions']
        self.maximum = MAX_ATTEMPTS_PER_TRIAL * reps * (4 * len(self.training)
                                                         + 2 * len(document['suite']['cases']))
        self.bridge = LoopBridge()
        self.search = {}
        self.proposal_errors = []

    def candidate(self, body):
        if body in self.candidates:
            return self.candidates[body]
        # Every changed body came from the same whole-unit mutation validator.
        raise ValueError('Harness2 returned an instruction body without an admitted mutation')

    async def evaluate(self, candidate, split, purpose):
        selected = self.training if split == 'train' else self.controls
        op = sha256_digest(canonical_json([self.case_id, 'harness2', candidate.candidate_id, split, purpose]))
        cached = self.store.find('EvaluationCompleted', op)
        if cached:
            return evaluation_from(cached.payload['evaluation'])
        ctx = EvaluationContext(run_id=self.case_id, operation_id=op, iteration=1,
            purpose=('train_before' if candidate.candidate_id == self.seed.candidate_id else 'train_after')
                    if split == 'train' else 'development', split=split,
            repetitions=self.document['suite']['repetitions'], capture_traces=split == 'train',
            artifact_dir=self.run_dir / 'evaluations',
            attempt_sink=TrialBudget(store=self.store, evaluation_operation_id=op, maximum=self.maximum))
        result = await self.evaluator.evaluate(candidate, selected, ctx)
        self.store.append('EvaluationCompleted', op, {'evaluation': record(result)})
        return result

    async def provider_call(self, spec, label):
        op = sha256_digest(canonical_json([self.case_id, self.document['backend_contract'],
            self.document['optimizer_contract'], label, record(spec)]))
        done = self.store.find('SessionCompleted', op)
        if done:
            return done.payload['output'], True
        # Persist all starts, even incomplete/cancelled sessions, to bound resumes.
        starts = self.store.events_of_type('SessionStarted')
        if len(starts) >= MAX_SESSIONS:
            raise ValueError('Harness2 frozen session budget exhausted')
        attempt = sum(e.payload.get('logical_operation_id') == op for e in starts) + 1
        if attempt > 2:
            raise ValueError('Harness2 session retry budget exhausted')
        self.store.append('SessionStarted', op + ':' + str(attempt), {'logical_operation_id': op})
        result = await self.provider.run(SessionRequest(session_id=op, operation_id=op,
            spec=spec, workspace=self.run_dir / 'sessions', timeout_seconds=SESSION_SECONDS))
        error = result.error
        if result.structured_output is None:
            error = error or 'Missing structured output'
        elif not error:
            error = session_output_validation_error(spec.output_schema, result.structured_output)
        if result.status != 'completed' or error:
            self.store.append('SessionFailed', op + ':' + str(attempt), {'error': error or 'Incomplete response', 'cost': record(result.cost),
                'usage': [record(item) for item in result.usage]})
            raise ValueError(error or 'Harness2 session did not finish')
        output = json.loads(canonical_json(result.structured_output))
        self.store.append('SessionCompleted', op, {'output': output, 'cost': record(result.cost),
            'usage': [record(item) for item in result.usage]})
        return output, False

    def mutation(self, body, output, label):
        parent = self.candidate(body)
        if output.get('keep_base') is True:
            if output.get('edits'):
                raise ValueError('KEEP_BASE cannot also contain edits')
            return body
        session = self.space.begin_mutation(parent, MutationContext(iteration=1,
            patch_label=label, evidence=None, workspace_root=self.run_dir / 'mutations'))
        result = native.SessionResult(status='completed', structured_output=output,
            raw_response=canonical_json(output), tool_calls=(), usage=(), cost=native.Cost())
        self.space.apply_mutation(session, MutationOutcome(result=result, workspace_delta=None))
        child = self.space.finalize(session)
        materialized = self.space.materialize(child, 'evaluate')
        try:
            new = json.loads((materialized.root / 'candidate.json').read_text())['identity']
        finally:
            materialized.release()
        self.candidates[new] = child
        return new

    def session_spec(self, body, mission, evidence):
        lines = body.split('\n')
        units = [{'unit': i, 'text': '\n'.join(lines[a:b])}
                 for i, (a, b) in native.editable_units(body, admission.subject_ref(self.document))]
        if not units:
            raise ValueError('Instruction body has no editable units')
        # Preserve the existing narrow edit protocol, with an explicit unchanged incumbent.
        schema = {'type': 'object', 'properties': {
            'keep_base': {'type': 'boolean'},
            'edits': {'type': 'array', 'maxItems': 3, 'items': {'type': 'object', 'properties': {
                'unit': {'type': 'integer', 'enum': [u['unit'] for u in units]},
                'action': {'type': 'string', 'enum': ['replace', 'insert_after']},
                'text': {'type': 'string', 'maxLength': native.UNIT_TEXT_LIMIT}},
                'required': ['unit', 'action', 'text'], 'additionalProperties': False}},
            'diagnosis': {'type': 'string', 'maxLength': 1000}},
            'required': ['keep_base', 'edits', 'diagnosis'], 'additionalProperties': False}
        system = ('Apply the supplied Harness2 improvement/composition job to instruction_units only. '
            'All context files are supplied verbatim below; you have no filesystem or Tool access. '
            'Return structured JSON, never a file tree. KEEP_BASE means keep_base=true with edits=[]. '
            'Otherwise provide one to three complete whole-unit replacements or insertions. Preserve '
            'links, unrelated instructions, identity and owner preferences. Do not change grants, '
            'models, reasoning modes, capabilities or code, add case-specific answers, copy the input '
            'envelope, or add unnecessary mandatory Tool calls. Cite concrete training trajectory '
            'moments in diagnosis. A successful candidate still requires independent verification.')
        data = {'job': mission, 'instruction_units': units, 'context_files': evidence}
        encoded = canonical_json(data)
        if len(encoded.encode()) > MAX_CONTEXT_BYTES:
            raise ValueError('Harness2 context exceeds its complete evidence bound; no truncation is admitted')
        return SessionSpec(kind='diagnose_patch', system_context=system, task_prompt=encoded,
            skills={}, workspace_files={}, capabilities=frozenset(), output_schema=schema)


class TrainingAdapter:
    substrate = SimpleNamespace(surface=lambda: SURFACE)

    def __init__(self, job):
        self.job = job
        self.spec = SimpleNamespace(prompts=PROMPTS, allow_subagents=False, reserved_scripts=frozenset(),
            obs_trunc=50_000, proposer_deliverables='contents', leak_globs=())
        self.paths = {}

    def task_prompt(self, task_id):
        # Keep the old proposer's native contracts and frozen prerequisite text.
        # No hidden controls or mutable live Article bodies cross this seam.
        from ...capabilities.registry import argument_schema
        relevant = {'task.complete'}
        training = []
        for case in self.job.training:
            payload = case.payload
            relevant.update(row['tool'] for row in payload.get('responses', []))
            if sample := payload.get('sample'):
                relevant.add(sample['tool'])
                relevant.update({'source.read', 'vault.search'} & set(sample['allowed']))
            training.append({'id': case.case_id, 'objective': payload['objective'],
                **{key: payload[key] for key in ('bindings', 'conversation', 'knowledge') if key in payload}})
        instructions = {note.ref: note.body for note in cases.frozen_notes(self.job.document)
            if note.kind in {'tool', 'skill'} and note.ref.rsplit('/', 1)[-1] in relevant}
        return canonical_json({'problem': self.job.document['problem'], 'training_tasks': training,
            'tool_contracts': {name: argument_schema(name) for name in sorted(relevant)},
            'capability_instructions': instructions,
            'lessons': self.job.document.get('experience', [])})

    def task_files(self, task_id):
        return None

    def validate_tree(self, proposed):
        if set(proposed) != {'AGENTS.md'}:
            raise ValueError('Only the current instruction body is editable')
        admission.validate_body(proposed['AGENTS.md'], self.job.baseline,
                                admission.subject_ref(self.job.document))
        self.job.candidate(proposed['AGENTS.md'])

    def execute(self, task_id, harness_dir, run_id, *, timeout=None):
        body = (harness_dir / 'AGENTS.md').read_text() if harness_dir else self.job.baseline
        candidate = self.job.candidate(body)
        measured = self.job.bridge.call(lambda: self.job.evaluate(candidate, 'train', 'search'))
        self.job.search[candidate.candidate_id] = [dict(r.metadata['result']) for r in measured.observations]
        path = self.job.run_dir / 'training-rollouts' / run_id
        path.mkdir(parents=True, exist_ok=True)
        self.paths[path] = measured
        return path

    def _rows(self, run_dir):
        measured = self.paths[run_dir]
        expected = len(self.job.training) * self.job.document['suite']['repetitions']
        rows = [dict(r.metadata['result']) for r in measured.observations]
        if (len(rows) != expected or any(r.get('error') for r in rows)
                or any(not isinstance(r.get('trajectory'), list) or r.get('trajectory_complete') is not True
                       for r in rows)):
            raise ValueError('Incomplete/unreadable training trajectory cannot enter Harness2 context')
        return rows

    def delivered(self, run_dir):
        return all(row['passed'] for row in self._rows(run_dir))

    def trajectory(self, run_dir, *, obs_trunc):
        # A complete native trajectory is bounded upstream by the trial step budget;
        # fail closed instead of accepting the upstream unavailable/truncated sentinel.
        rows = self._rows(run_dir)
        text = '\n\n'.join('[ACTION]\n' + canonical_json({'case_id': row['case_id'],
            'repetition': row['repetition'], 'events': row['trajectory']}) + '\n[OBSERVATION]\n'
            + canonical_json({'status': row['status'], 'summary': row['summary']}) for row in rows)
        if len(text.encode()) > MAX_CONTEXT_BYTES or '\ufffd' in text:
            raise ValueError('Unreadable or oversized training trajectory')
        return text

    def deliverable_files(self, run_dir):
        self._rows(run_dir)
        return {}

    def deliverable_text(self, run_dir):
        return '\n\n'.join(row['summary'] for row in self._rows(run_dir))


class ReservedProposer:
    def __init__(self, job):
        self.job = job

    def call(self, mission, context_dir, label, *, harvest, max_attempts):
        body = (context_dir / 'harness/AGENTS.md').read_text()
        evidence = {}
        visible = {'task.md', 'rollouts', 'deliverables', 'harness', 'pool',
                   'library', 'decisions', 'source', 'attempt-rejection.txt'}
        for path in sorted(context_dir.rglob('*')):
            if path.relative_to(context_dir).parts[0] not in visible:
                continue
            if path.is_symlink():
                raise ProposerError('Symlink in training context')
            if path.is_file():
                if path.stat().st_size > MAX_CONTEXT_BYTES:
                    raise ProposerError('Oversized context cannot be served without truncation')
                value = path.read_text(encoding='utf-8', errors='strict')
                if any(marker in value for marker in ('(trajectory unavailable:', '(deliverable unavailable:',
                        '\ufffd')):
                    raise ProposerError('Incomplete training context is not usable evidence')
                evidence[path.relative_to(context_dir).as_posix()] = value
        spec = self.job.session_spec(body, mission, evidence)
        try:
            output, cached = self.job.bridge.call(lambda: self.job.provider_call(spec, label))
            new = self.job.bridge.call(lambda: self._mutation(body, output, label))
        except (ValueError, OSError, KeyError, TypeError) as exc:
            self.job.proposal_errors.append({'session': label, 'error': str(exc)[:1000]})
            # No harvested tree means upstream retries without overwriting the
            # admitted body. Supply the actual rejection as bounded retry evidence.
            (context_dir / 'attempt-rejection.txt').write_text(str(exc)[:1000])
            return Reply(label=label, text=str(exc), ok=False, workspace=None, attempts=1)
        workspace = context_dir / 'proposal'
        tree.write_tree(SURFACE, {'AGENTS.md': new}, workspace)
        return Reply(label=label, text='<notes>' + output['diagnosis'] + '</notes>', ok=True,
                     workspace=workspace, cached=cached, attempts=1, channel='obsidience-reserved-adk')

    async def _mutation(self, body, output, label):
        return self.job.mutation(body, output, label)


async def _method(job, adapter):
    def work():
        base_path = adapter.execute(job.case_id, None, 'base')
        base = RunView(label='base', run_id='base', run_dir=base_path,
                       ok=True, delivered=adapter.delivered(base_path))
        return recursion.run_sequential(job.case_id, 1, [base], adapter=adapter,
            prop=ReservedProposer(job), work_dir=job.run_dir / 'harness2',
            run_id_of=lambda label: label, base_tree={'AGENTS.md': job.baseline},
            library_dir=None, propose_workers=1, rollout_workers=1)
    worker = asyncio.create_task(asyncio.to_thread(work))
    try:
        return await asyncio.shield(worker)
    finally:
        # Returning/cancelling never leaves inference or an upstream executor alive.
        # A second foreground/timeout cancellation must not interrupt the drain.
        async def drain():
            await job.bridge.cancel()
            try:
                await worker
            except Stopped:
                pass
        cleanup = asyncio.create_task(drain())
        cancelled_during_drain = False
        while not cleanup.done():
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                cancelled_during_drain = True
        await cleanup
        if cancelled_during_drain:
            raise asyncio.CancelledError


async def run(case_id, document, audit, context):
    job = Job(case_id, document, audit, context)
    adapter = TrainingAdapter(job)
    failures, method = [], None
    selected = job.seed
    rows = {}
    lessons = []
    budget_events = job.store.events_of_type('ExtensionStateChanged')
    starts = {e.payload['segment']: e.payload for e in budget_events
              if e.payload.get('kind') == 'job_budget_start'}
    ends = {e.payload['segment']: e.payload for e in budget_events
            if e.payload.get('kind') == 'job_budget_end'}
    spent = sum(ends[key]['elapsed'] if key in ends else min(native.JOB_SECONDS,
                max(0, time.time() - value['started'])) for key, value in starts.items())
    segment, started = str(len(starts) + 1), time.monotonic()
    job.store.append('ExtensionStateChanged', 'budget-start:' + segment,
                     {'kind': 'job_budget_start', 'segment': segment, 'started': time.time()})
    try:
        if spent >= native.JOB_SECONDS:
            raise ValueError('Harness2 persisted job time budget exhausted')
        async with asyncio.timeout(native.JOB_SECONDS - spent):
            method = await _method(job, adapter)
            failures.extend({'session': s.label, 'error': s.error or 'Harness2 stage fell back'}
                            for s in method.stages if s.fell_back)
            failures.extend({'session': 'method', 'error': error} for error in method.errors)
            failures.extend({'session': label, 'error': rollout.error or 'Training trajectory unavailable'}
                            for label, rollout in method.rollouts.items() if not rollout.ok)
            final_body = method.trees[method.finals[-1]]['AGENTS.md']
            selected = job.candidate(final_body)
            # Independent full repeats are never exposed to the proposer or lessons.
            for candidate in (job.seed, selected):
                if candidate.candidate_id in rows:
                    continue
                observations = []
                for split in ('train', 'development'):
                    measured = await job.evaluate(candidate, split, 'independent-final')
                    observations.extend(dict(row.metadata['result']) for row in measured.observations)
                rows[candidate.candidate_id] = observations
            compared = native.comparison(document, rows, job.seed.candidate_id, selected.candidate_id)
            if compared['verdict'] == 'passed' and not failures:
                lessons = await _reflect(job, method)
    except Exception as exc:
        failures.append({'session': 'harness2', 'error': type(exc).__name__ + ': ' + str(exc)[:1000]})
    finally:
        job.store.append('ExtensionStateChanged', 'budget-end:' + segment,
                         {'kind': 'job_budget_end', 'segment': segment,
                          'elapsed': time.monotonic() - started})
    compared = native.comparison(document, rows, job.seed.candidate_id, selected.candidate_id)
    if failures:
        compared['verdict'] = 'incomplete'
    return {'schema_version': 1, 'case_id': case_id, 'audit_run_id': context['run_id'],
        'upstream_revision': document['upstream_revision'], 'backend_contract': document['backend_contract'],
        'evaluator_revision': document['evaluator_revision'], 'model_contract': document['model_contract'],
        'candidate_body': next(body for body, candidate in job.candidates.items()
                               if candidate.candidate_id == selected.candidate_id),
        'seed_id': job.seed.candidate_id, 'selected_id': selected.candidate_id,
        'observations': rows, 'optimizer_failures': failures, 'verdict': compared['verdict'],
        'comparison': compared, 'scope': document['scope'], 'job_path': str(job.run_dir.relative_to(CONFIG.project_root)),
        'search_observations': job.search, 'harness2': method.to_dict() if method else None,
        'pending_lessons': lessons}


async def _reflect(job, method):
    """Reflection sees search/training only; storage waits for publication's receipt gate."""
    # Independent results decide eligibility, but their contents never enter this call.
    train_ids = [case.case_id for case in job.training]
    prompt = native.ExecutivePrompts(job.store, job.document).session('reflect', {
        'candidate_ids': [job.candidate(method.trees[method.finals[-1]]['AGENTS.md']).candidate_id],
        'train_case_ids': train_ids, 'training_outcomes': job.search})
    prompt = replace(prompt, system_context=prompts.experience(PROMPTS) + '\n\n' + prompt.system_context)
    try:
        output, _ = await job.provider_call(prompt, 'training-reflection')
    except Exception:
        # Reflection is optional evidence, never a reason to weaken the final verdict.
        return []
    return output['lessons']

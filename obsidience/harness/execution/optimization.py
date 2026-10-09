"""AutoSaddler optimization owned by Heimdall's existing Audit activation.

Cases use independent registration or committed decision contracts. Models
receive training evidence only; candidate publication stays in the Article/Review authority.
AutoSaddler's journal is an internal job artifact, never another work queue.
"""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from ..config import CONFIG
from ..knowledge.index import INDEX
from ..knowledge.vault import Resolver, load_note, resolver
from . import refinement

UPSTREAM_REVISION = '6a2b7a9ab2412a8fe384fd5471d2a49b03a60013'
EXECUTIVE = 'Agents/Executive/Executive'
AUDITOR = refinement.AUDITOR
DECISION_CASE_COUNT = 5
EVALUATION_REPETITIONS = 5
_ACTIVE: set[str] = set()
_INSPECTED_RUNS: set[str] = set()
STALE_CASE_ERRORS = frozenset({
    'Executive optimizer implementation changed; prepare a fresh case',
    'An accepted Executive dependency changed; prepare a fresh case',
    'Execution model configuration changed; prepare a fresh case',
    'Audit model configuration changed; prepare a fresh case',
    'Captured decision predates the current implementation',
})


def reconcile_rejections(notes: list) -> None:
    """Send receipt-proven rejected steps to Audit, even when the Task recovered.

    This uses existing terminal runs and the ordinary event FIFO. It does not
    replay an action or manufacture AutoSaddler's independent evaluation cases.
    """
    from .scheduler import enqueue_named_event
    from ..knowledge.tasks import task_triggers
    import hashlib
    import time

    by_ref = {note.ref: note for note in notes}
    auditor = by_ref.get(AUDITOR)
    if (auditor is None or 'harness.rejected' not in task_triggers(auditor.meta)
            or str(auditor.meta.get('enabled', True)).lower() in {'false', '0', 'no', 'off'}):
        return
    runs = {str(note.meta.get('last_run')) for note in notes
            if note.kind == 'task' and note.meta.get('last_run')}
    runs.update(path.stem for path in sorted((refinement._root() / 'incidents').glob('*.json'),
                key=lambda path: path.stat().st_mtime, reverse=True)[:64])
    # The Executive is an Agent, so its latest run has no Task runtime row.
    executive = next((run for run in INDEX.runs(30) if run['task_ref'] == EXECUTIVE), None)
    if executive:
        runs.add(executive['id'])
    _INSPECTED_RUNS.intersection_update(runs)
    for run_id in sorted(runs - _INSPECTED_RUNS):
        run = INDEX.run(run_id)
        if not run or run['status'] not in {'completed', 'review', 'failed', 'blocked'}:
            continue
        if run['task_ref'] in {AUDITOR, 'Tasks/repair'}:
            _INSPECTED_RUNS.add(run_id)
            continue
        receipts = INDEX.tool_run_receipts(run_id)
        if not receipts or receipts.get('task_ref') != run['task_ref']:
            _INSPECTED_RUNS.add(run_id)
            continue
        try:
            entries = json.loads(run.get('trace') or '[]')
        except (TypeError, ValueError):
            entries = []
        if not isinstance(entries, list):
            entries = []
        from . import optimization_incidents as incidents
        if incidents.recovered_operational_incident(run_id):
            _INSPECTED_RUNS.add(run_id)
            continue
        rejected = None
        # The compact public trace may clip long rejection details. Prefer the
        # complete decision capture and its exact committed receipt when present.
        captured = refinement._root() / 'incidents' / (run_id + '.json')
        if captured.is_file():
            try:
                for identity in json.loads(captured.read_text()):
                    sample = refinement._load('decisions', identity)
                    if sample.get('rejected') and incidents._receipt_matches(sample):
                        rejected = {'tool': sample['tool'], 'reason': str(sample['result'])[:1500]}
                        break
            except (ValueError, OSError, KeyError, TypeError):
                pass  # Retained public evidence can still establish the incident.
        for entry in entries if rejected is None else []:
            if not isinstance(entry, dict) or not entry.get('tool'):
                continue
            observed = entry.get('obs', '')
            if not isinstance(observed, str) or not observed.startswith((
                    'Completion rejected:', 'Proposal rejected:', 'Tool prerequisite rejected:')):
                continue
            result = observed
            if entry.get('completion_rejected') and entry['tool'] == 'task.complete':
                # The public trace renders a sentence, but the receipt hashes
                # the completion authority's original structured rejection.
                args = entry.get('args') or {}
                result = {'accepted': False, 'status': str(args.get('status', 'completed')).strip(),
                          'summary': '', 'outcome': str(args.get('outcome', '')).strip(),
                          'evidence': args.get('evidence') or [],
                          'error': observed.removeprefix('Completion rejected: ').removesuffix('.')}
            encoded = json.dumps(result, sort_keys=True).encode()
            if any(call.get('tool') == entry['tool'] and call.get('status') == 'returned'
                   and call.get('result_chars') == len(encoded)
                   and call.get('result_sha256') == hashlib.sha256(encoded).hexdigest()
                   for call in receipts.get('calls', [])):
                rejected = {'tool': entry['tool'], 'reason': observed[:1500]}
                break
        if rejected is None:
            if run['status'] not in {'failed', 'blocked'}:
                _INSPECTED_RUNS.add(run_id)
                continue
            rejected = {'tool': 'execution', 'reason': str(run.get('summary') or 'Execution failed')[:1500]}
        subject = by_ref.get(run.get('runbook_ref')) or by_ref.get(run['task_ref'])
        if subject is None:
            continue
        definition = hashlib.sha256((CONFIG.vault_dir / subject.path).read_bytes()).hexdigest()
        reason = re.sub(r'[0-9a-f]{8}-[0-9a-f-]{27,}', '<source>', rejected['reason'])
        identity = hashlib.sha256(refinement._json(
            [run['task_ref'], definition, rejected['tool'], reason]).encode()).hexdigest()
        receipt_id = 'autosaddler-incident-' + identity
        prior = INDEX.run(receipt_id)
        if prior is not None:
            # Dispatch is not evaluation completion. A settled stale case with
            # no report may be prepared once for the new implementation, while
            # completed comparisons and active jobs remain deduplicated.
            previous = json.loads(prior.get('trace') or '[]')
            previous_case = previous[0].get('optimization_case') if previous else None
            try:
                state = status(previous_case) if previous_case else {}
            except (ValueError, KeyError, OSError):
                incidents.attention(identity, run_id, run['task_ref'],
                                    'Prior optimization evidence cannot be attested; implementation review is required')
                _INSPECTED_RUNS.add(run_id)
                continue
            occurrences = [row for row in INDEX.activations(AUDITOR)
                           if row['params'].get('optimization_case') == previous_case]
            finished_comparison = state.get('report') and state['report'].get('verdict') != 'incomplete'
            if (not previous_case or finished_comparison or state.get('active')
                    or state.get('stale_reason') not in STALE_CASE_ERRORS
                    or not occurrences or any(row['status'] not in {'completed', 'failed', 'blocked', 'cancelled'}
                                              for row in occurrences)):
                _INSPECTED_RUNS.add(run_id)
                continue
            identity = hashlib.sha256(refinement._json([identity, _IMPLEMENTATION_AT_IMPORT]).encode()).hexdigest()
            receipt_id = 'autosaddler-incident-' + identity
            if INDEX.run(receipt_id) is not None:
                _INSPECTED_RUNS.add(run_id)
                continue
        params = {'activation_key': receipt_id, 'rejection_case': identity,
                  'origin_run_id': run_id, 'subject_task': run['task_ref'],
                  'subject_definition': subject.ref, 'definition_sha256': definition,
                  'request': 'Improve ' + subject.ref + ': ' + rejected['reason'],
                  'rejected_step': rejected, 'queue_after_review': True}
        # All instruction improvement uses AutoSaddler, without an ordinary
        # model-authored inspection/proposal fallback.
        case_dir = refinement._root() / 'executive/cases'
        for path in sorted(case_dir.glob('*.json')) if run['task_ref'] == EXECUTIVE else []:
            try:
                document = refinement._load('executive/cases', path.stem)
                if document.get('origin', {}).get('id') == run_id:
                    current(path.stem)
                    params['optimization_case'] = path.stem
                    break
            except (ValueError, OSError, KeyError):
                continue
        if not params.get('optimization_case'):
            try:
                params['optimization_case'] = incidents.prepare(run_id)['case_id']
            except (ValueError, OSError, KeyError) as exc:
                incidents.attention(identity, run_id, run['task_ref'], str(exc), rejected['reason'])
                _INSPECTED_RUNS.add(run_id)
                continue
        incidents.attention(identity, run_id, run['task_ref'], '')
        try:
            deliveries = enqueue_named_event('harness.rejected', params, expected_task=AUDITOR)
        except ValueError as exc:
            # A broken optional Audit must not stop normal Task admission.
            from . import trace as action_trace
            action_trace.emit('error', 'Rejected action Audit could not be admitted', [str(exc)[:500]],
                              {'task_ref': AUDITOR, 'agent_ref': refinement.HEIMDALL})
            continue
        if len(deliveries) != 1 or deliveries[0]['state'] not in {'started', 'queued', 'processed'}:
            continue
        now = time.time()
        INDEX.record_run(overwrite=False, id=receipt_id, task_ref=AUDITOR, agent='scheduler',
            started=now, finished=now, status='dispatched', objective='AutoSaddler improvement for an agent incident',
            summary='Receipt-bound incident admitted one AutoSaddler job for this definition and failure.',
            trace=json.dumps([params], sort_keys=True))
        _INSPECTED_RUNS.add(run_id)


def model_contract(note, agent_ref: str) -> dict:
    from ..models import runtime
    contract = refinement._model_contract(note, agent_ref)
    spec = runtime.configured_spec(contract['spec']['id'])
    return {**contract, 'source_identity': runtime._model_source_identity(spec)}


def _revision() -> str:
    root = Path(__file__).parents[1]
    paths = [Path(__file__), root / 'execution/deepseek/optimization.py',
             root / 'execution/deepseek/runner.py', root / 'execution/native.py', root / 'execution/native_turn.py',
             root / 'execution/capability_core.py',
             root / 'execution/deepseek/plugin.mjs', root / 'execution/deepseek/package-lock.json',
             root / 'execution/deepseek/bridge.py', root / 'capabilities/harness/optimize.py',
             root / 'execution/executor.py', root / 'execution/evaluation.py', root / 'execution/trace.py',
             root / 'capabilities/registry.py', root / 'capabilities/task/complete.py',
             root / 'models/llm.py', root / 'models/context.py', root / 'models/runtime.py']
    paths.extend([root / 'execution/optimization_incidents.py', root / 'capabilities/vault/propose.py',
                  root / 'capabilities/source/read.py', root / 'execution/refinement.py',
                  root / 'memory/hindsight.py', root / 'knowledge/links.py', root / 'knowledge/format.py',
                  root / 'knowledge/review.py', root / 'knowledge/scope.py',
                  root / 'knowledge/curation.py', root / 'knowledge/source.py'])
    return refinement._hash(refinement._json({str(p.relative_to(root)): refinement._hash(p.read_bytes())
                                             for p in paths}).encode())


def _validate_suite_size(suite: dict) -> None:
    if (not isinstance(suite, dict) or not isinstance(suite.get('cases'), list)
            or len(suite['cases']) != DECISION_CASE_COUNT
            or suite.get('repetitions') != EVALUATION_REPETITIONS):
        raise ValueError('AutoSaddler requires five distinct decision cases repeated five times')


def prepare(specification: dict) -> dict:
    """Freeze a small owner-authored reconstruction and the actual native inputs."""
    from .evaluation import validate_suite
    from .executor import resolve_spine
    _validate_suite_size(specification.get('suite', {}))
    if 'task' in specification:
        registered = refinement.prepare_case(specification)
        document = refinement._current(registered['case_id'])
        return adopt_runbook_case(document)
    if set(specification) != {'origin_run_id', 'problem', 'suite'}:
        raise ValueError('Use origin_run_id, problem and suite only')
    validate_suite(specification['suite'])
    if not isinstance(specification['problem'], str) or not 1 <= len(specification['problem']) <= 2000:
        raise ValueError('A bounded, evidence-backed problem is required')
    origin = INDEX.run(str(specification['origin_run_id']))
    if not origin or origin.get('task_ref') != EXECUTIVE or origin.get('status') not in {'completed', 'failed', 'blocked'}:
        raise ValueError('Bind a real terminal Executive run')
    res = resolver(include_system=False)
    agent = res.resolve(EXECUTIVE)
    audit = res.resolve(AUDITOR)
    if agent is None or agent.kind != 'agent':
        raise ValueError('Accepted Executive identity is unavailable')
    spine = resolve_spine(agent, res)
    if spine.get('error'):
        raise ValueError(spine['error'])
    allowed = set(spine['tools']) | {'task.complete'}
    for case in specification['suite']['cases']:
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', case['id']):
            raise ValueError('Case IDs must be short trace identifiers')
        if any(row['tool'] not in allowed for row in case['responses']):
            raise ValueError('Case names a Tool outside accepted Executive authority')
    notes = [agent, *spine['skills'], *spine['tool_articles']]
    document = {**specification, 'schema_version': 1, 'agent': EXECUTIVE,
                'articles': {note.ref: (CONFIG.vault_dir / note.path).read_text() for note in notes},
                'model_contract': model_contract(agent, agent.ref),
                'optimizer_contract': model_contract(audit, refinement.HEIMDALL),
                'evaluator_revision': _revision(), 'upstream_revision': UPSTREAM_REVISION,
                'origin': {key: origin.get(key) for key in ('id', 'task_ref', 'status', 'summary')},
                'scope': 'Frozen Tool reconstruction through the native DeepSeek Executive; no live effects.'}
    case_id = refinement._store('executive/cases', document)
    return {'case_id': case_id, 'source_path': _source_path('cases', case_id), 'scope': document['scope']}


def adopt_runbook_case(document: dict) -> dict:
    """Use registered specialist cases with the same upstream optimization engine."""
    _validate_suite_size(document['suite'])
    res = resolver(include_system=False)
    document = {**document, 'subject': document['runbook'], 'evaluation_mode': 'frozen',
                'model_contract': model_contract(res.resolve(document['task']), document['agent']),
                'optimizer_contract': model_contract(res.resolve(AUDITOR), refinement.HEIMDALL),
                'evaluator_revision': _revision(), 'upstream_revision': UPSTREAM_REVISION,
                'scope': 'Specialist execution with frozen Tool results; no live effects.'}
    case_id = refinement._store('executive/cases', document)
    return {'case_id': case_id, 'source_path': _source_path('cases', case_id), 'scope': document['scope']}


def _source_path(lane: str, identity: str) -> str:
    return str((refinement._root() / 'executive' / lane / (identity + '.json')).relative_to(CONFIG.project_root))


def subject_ref(document: dict) -> str:
    return document.get('subject', EXECUTIVE)


def prepare_decisions(sample: dict, cases: list[dict]) -> dict:
    from .executor import resolve_spine
    suite = {'cases': cases, 'repetitions': EVALUATION_REPETITIONS}
    _validate_suite_size(suite)
    res = resolver(include_system=False)
    task = res.resolve(sample['context']['task'])
    agent = task if task.kind == 'agent' else res.resolve(task.meta.get('assignee', ''))
    spine = resolve_spine(task, res)
    subject = res.resolve(sample['subject'])
    if spine.get('error') or agent is None or subject is None:
        raise ValueError('Incident dependencies are not executable')
    if subject.kind not in {'agent', 'runbook'} or subject.ref in {'Runbooks/audit', 'Runbooks/repair'}:
        raise ValueError('The optimizer cannot rewrite its own authority or recovery procedure')
    notes = [agent, task, subject, *spine.get('runbooks', []), *spine['skills'], *spine['tool_articles']]
    document = {'schema_version': 2, 'evaluation_mode': 'contract', 'subject': subject.ref,
                'task': task.ref, 'agent': agent.ref,
                'problem': 'Correct the receipt-proven contract rejection: ' + str(sample['result'])[:1500],
                'suite': suite,
                'articles': {note.ref: (CONFIG.vault_dir / note.path).read_text() for note in notes},
                'model_contract': model_contract(task, agent.ref),
                'optimizer_contract': model_contract(res.resolve(AUDITOR), refinement.HEIMDALL),
                'evaluator_revision': _revision(), 'upstream_revision': UPSTREAM_REVISION,
                'origin': {'id': sample['run_id'], 'task_ref': task.ref},
                'scope': 'Captured decision contracts and independent accepted controls; no live action replay.'}
    case_id = refinement._store('executive/cases', document)
    return {'case_id': case_id, 'source_path': _source_path('cases', case_id), 'scope': document['scope']}


def current(case_id: str, accepted_resolver=None) -> dict:
    document = refinement._load('executive/cases', case_id)
    if _revision() != _IMPLEMENTATION_AT_IMPORT:
        raise ValueError('Reload the changed Harness before preparing or running optimization')
    if document['evaluator_revision'] != _revision() or document['upstream_revision'] != UPSTREAM_REVISION:
        raise ValueError('Executive optimizer implementation changed; prepare a fresh case')
    _validate_suite_size(document['suite'])
    res = accepted_resolver or resolver(include_system=False)
    for ref, raw in document['articles'].items():
        note = res.resolve(ref)
        if note is None or (CONFIG.vault_dir / note.path).read_text() != raw:
            raise ValueError('An accepted Executive dependency changed; prepare a fresh case')
    task = res.resolve(document.get('task', EXECUTIVE))
    if model_contract(task, document['agent']) != document['model_contract']:
        raise ValueError('Execution model configuration changed; prepare a fresh case')
    if model_contract(res.resolve(AUDITOR), refinement.HEIMDALL) != document['optimizer_contract']:
        raise ValueError('Audit model configuration changed; prepare a fresh case')
    if document.get('evaluation_mode') == 'contract':
        from .optimization_incidents import check_current
        for case in document['suite']['cases']:
            check_current(case['sample'])
    return document


def queue(case_id: str) -> dict:
    from .scheduler import enqueue_named_event
    document = current(case_id)
    result = enqueue_named_event('executive.optimize', {
        'optimization_case': case_id, 'activation_key': 'executive-optimize:' + case_id,
        'subject_definition': subject_ref(document),
        'request': 'Improve ' + subject_ref(document) + ': ' + document['problem'],
    }, expected_task=AUDITOR)
    return {'case_id': case_id, 'deliveries': result}


def validate_body(body: str, baseline: str, subject: str = EXECUTIVE) -> None:
    from ..knowledge.links import body_links
    if not isinstance(body, str) or not body.strip() or len(body) > min(16_000, len(baseline) + 2000):
        raise ValueError('Candidate identity body exceeds its compact instruction budget')
    if body.lstrip().startswith('---'):
        raise ValueError('Candidate must contain an Article body without metadata')
    if set(body_links(body, subject + '.md')) != set(body_links(baseline, subject + '.md')):
        raise ValueError('Candidate must preserve the exact authored Article links')


def _report_result(report_id: str, report: dict) -> dict:
    return {'case_id': report['case_id'], 'report_id': report_id, 'verdict': report['verdict'],
            'comparison': report['comparison'], 'source_path': _source_path('reports', report_id),
            'optimizer_failures': report.get('optimizer_failures', []),
            'upstream_revision': UPSTREAM_REVISION, 'scope': report['scope']}


async def optimize(case_id: str, context: dict) -> dict:
    params = context.get('params') or {}
    if context.get('task') != AUDITOR or params.get('optimization_case') != case_id or not context.get('run_id'):
        raise ValueError('Optimization requires the exact case bound to an active Audit')
    audit = load_note(AUDITOR + '.md')
    if not audit or audit.meta.get('assignee') != f'[[{refinement.HEIMDALL}]]':
        raise ValueError('Heimdall must own Executive optimization')
    document = current(case_id)
    from importlib.metadata import distribution
    provenance = json.loads(distribution('autosaddler').read_text('direct_url.json') or '{}')
    if provenance.get('vcs_info', {}).get('commit_id') != UPSTREAM_REVISION:
        raise ValueError('Install the pinned AutoSaddler revision from requirements-optimization.txt')
    if case_id in _ACTIVE:
        raise ValueError('This optimization case already has an active owner')
    _ACTIVE.add(case_id)
    try:
        from .deepseek.optimization import run
        # Cancellation is joined, including while the native provider is
        # generating. The foreground does not wait for an evaluation response.
        worker = asyncio.create_task(run(case_id, document, audit, context))
        interrupt = context.get('_foreground_interruption_event')
        waiter = asyncio.create_task(interrupt.wait()) if interrupt is not None else None
        try:
            if waiter is not None:
                await asyncio.wait((worker, waiter), return_when=asyncio.FIRST_COMPLETED)
                if interrupt.is_set():
                    context['interruption_reason'] = 'foreground_admission'
                    # Publication starts strictly after the joined worker.
                    context['_optimization_resume_case'] = case_id
                    raise asyncio.CancelledError('foreground_admission')
            report = await worker
        finally:
            for task in (worker, waiter):
                if task is not None and not task.done():
                    task.cancel()
            await asyncio.gather(*(t for t in (worker, waiter) if t is not None), return_exceptions=True)
        current(case_id)
        report_id = refinement._store('executive/reports', report)
        result = _report_result(report_id, report)
        if report['verdict'] == 'passed':
            from ..capabilities.vault.propose import stage_proposal
            agent = Resolver(refinement._notes(document)).resolve(subject_ref(document))
            context['_executive_optimization'] = {'case_id': case_id, 'report_id': report_id}
            try:
                staged = stage_proposal({'target': agent.path, 'action': 'update', 'title': agent.title,
                                         'body': report['candidate_body'],
                                         'reason': 'AutoSaddler validated instruction improvement: ' + result['source_path']}, context)
                result['proposal'] = Path(staged['staged']).name
            finally:
                context.pop('_executive_optimization', None)
        context['_harness_optimization'] = result
        from .optimization_incidents import attention
        baseline = report.get('observations', {}).get(report.get('seed_id'), [])
        if report['verdict'] != 'passed' and (not baseline or not all(row.get('passed') for row in baseline)):
            attention(case_id, context['run_id'], document.get('task', EXECUTIVE),
                      'AutoSaddler exhausted its bounded improvement attempt: ' + report['verdict'],
                      'Evidence and candidate history: ' + result['source_path'])
        from ..knowledge.vault import _atomic_write
        _atomic_write(refinement._root() / 'executive/jobs' / case_id / 'report.json', json.dumps(result, sort_keys=True))
        return result
    finally:
        _ACTIVE.discard(case_id)


def status(case_id: str) -> dict:
    document = refinement._load('executive/cases', case_id)
    report = refinement._root() / 'executive/jobs' / case_id / 'report.json'
    result = {'case_id': case_id, 'active': case_id in _ACTIVE, 'task': AUDITOR, 'scope': document['scope']}
    if report.is_file() and not report.is_symlink() and report.stat().st_size <= 16_000:
        result['report'] = json.loads(report.read_text())
    audit = load_note(AUDITOR + '.md')
    if audit and (audit.meta.get('params') or {}).get('optimization_case') == case_id:
        result['task_status'] = audit.meta.get('status')
        result['run_id'] = audit.meta.get('last_run')
    try:
        current(case_id)
        result['current'] = True
    except ValueError as exc:
        result.update(current=False, stale_reason=str(exc))
    return result


def proposal_binding(context: dict, target: str, action: str, title: str, body: str, metadata: dict) -> dict | None:
    """Called by the existing proposal writer before its atomic staging write."""
    case_id = (context.get('params') or {}).get('optimization_case')
    if not case_id:
        return None
    marker = context.get('_executive_optimization')
    if not isinstance(marker, dict) or marker.get('case_id') != case_id or context.get('task') != AUDITOR:
        raise ValueError('This Audit may stage only the controller-selected optimization candidate')
    report = refinement._load('executive/reports', marker['report_id'])
    document = current(case_id)
    agent = Resolver(refinement._notes(document)).resolve(subject_ref(document))
    if (report['verdict'] != 'passed' or report['audit_run_id'] != context['run_id']
            or target != agent.path or action != 'update' or title != agent.title or metadata
            or body.strip() != report['candidate_body'].strip()):
        raise ValueError('Proposal differs from the measured Executive candidate')
    return dict(marker)


def review_blocker(note, accepted_resolver=None) -> str | None:
    marker = note.meta.get('optimization')
    receipts = INDEX.tool_run_receipts(str(note.meta.get('run_id', ''))) if note.meta.get('task') == AUDITOR else None
    bound = any(call.get('tool') == 'harness.optimize' for call in (receipts or {}).get('calls', []))
    if marker is None and not bound:
        return None
    try:
        if not isinstance(marker, dict) or set(marker) != {'case_id', 'report_id'}:
            raise ValueError('Executive candidate lost its optimization binding')
        document = current(marker['case_id'], accepted_resolver)
        report = refinement._load('executive/reports', marker['report_id'])
        agent = Resolver(refinement._notes(document)).resolve(subject_ref(document))
        if (report['verdict'] != 'passed' or report['case_id'] != marker['case_id']
                or note.meta.get('task') != AUDITOR or note.meta.get('run_id') != report['audit_run_id']
                or note.meta.get('target') != agent.path or note.meta.get('action') != 'update'
                or note.meta.get('authored_fields') != [] or note.title != agent.title
                or note.body.strip() != report['candidate_body'].strip()):
            raise ValueError('Executive candidate or evaluation identity changed')
        run = INDEX.run(report['audit_run_id'])
        if not run or run.get('status') not in {'completed', 'review'} or not receipts:
            raise ValueError('The owning Audit has not finished with complete Tool evidence')
        from .deepseek.optimization import comparison
        if comparison(document, report['observations'], report['seed_id'], report['selected_id']) != report['comparison']:
            raise ValueError('Executive candidate comparison does not match the recorded outcomes')
        result = {**_report_result(marker['report_id'], report), 'proposal': Path(note.path).name}
        expected_hash = refinement._hash(json.dumps(json.dumps(result, sort_keys=True), sort_keys=True).encode())
        calls = receipts.get('calls', [])
        if not any(call.get('tool') == 'harness.optimize' and call.get('status') == 'returned'
                   and call.get('result_sha256') == expected_hash for call in calls):
            raise ValueError('The optimization report lacks its exact returned Tool receipt')
    except (ValueError, OSError, KeyError, TypeError) as exc:
        return str(exc)
    return None


def publish_validated() -> None:
    """Apply owner-authorized instruction improvements after the Audit receipt.

    The existing Review writer revalidates the candidate, code, model, inputs
    and complete returned optimization receipt under its normal write lock.
    """
    from ..knowledge import review
    from .optimization_incidents import attention
    audit = load_note(AUDITOR + '.md')
    if audit is None or audit.meta.get('optimization_auto_apply') is not True:
        return
    for path in sorted(CONFIG.staging_dir.glob('*.md')):
        note = load_note(str(path.relative_to(CONFIG.vault_dir)))
        marker = note.meta.get('optimization') if note else None
        if not isinstance(marker, dict) or note.meta.get('task') != AUDITOR:
            continue
        run = INDEX.run(str(note.meta.get('run_id', '')))
        if not run or run['status'] not in {'completed', 'review'}:
            continue
        try:
            document = current(marker['case_id'])
            subject = Resolver(refinement._notes(document)).resolve(subject_ref(document))
            if subject.kind not in {'agent', 'runbook'} or note.meta.get('authored_fields') != []:
                raise ValueError('Automatic optimization publication is restricted to instruction bodies')
            review.approve(path.name)
            attention(marker['case_id'], run['id'], document.get('task', EXECUTIVE), '')
            from . import trace as action_trace
            action_trace.emit('status', 'AutoSaddler instruction improvement applied', [subject.ref],
                              {'task_ref': AUDITOR, 'agent_ref': refinement.HEIMDALL})
        except (ValueError, OSError, KeyError) as exc:
            attention(marker.get('case_id', path.stem), run['id'], AUDITOR,
                      'Validated instruction publication needs review: ' + str(exc))


# Disk edits cannot attest a still-running process as the new implementation.
_IMPLEMENTATION_AT_IMPORT = _revision()

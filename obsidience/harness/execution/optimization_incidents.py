"""Receipt-bound decision cases for the AutoSaddler scenario.

This is a capture/evaluation adapter, not an optimizer or an action retry loop.
The ordinary Capability owner validates proposed decisions without committing
them. Unsupported effects remain explicit Review findings.
"""
from __future__ import annotations

from copy import deepcopy
import json

from ..config import CONFIG
from ..knowledge.index import INDEX
from ..knowledge.vault import _atomic_write, load_note, resolver
from . import refinement

SUPPORTED = {'task.complete', 'vault.propose'}
CONTEXT_FIELDS = {
    'task', 'agent', '_agent_ref', 'objective', 'event', 'params', 'interactive',
    '_source_reads', '_article_reads', '_vault_searches', '_created_tasks',
    'staged_proposals', 'maintenance_candidate', '_memory_proposal_rejection',
    '_link_proposal_rejection', '_proposal_read_prerequisite', 'handoff_source_id',
    '_merge_retained_updates',
    '_computer_act_scope', '_computer_request_target', 'trace',
}


def snapshot(dispatch, name: str, args: dict) -> dict | None:
    if (name not in SUPPORTED or dispatch.task.ref in {refinement.AUDITOR, 'Tasks/repair'}
            or dispatch.visual_context_seen or not dispatch.ctx.get('run_id')):
        return None
    context = {key: value for key, value in dispatch.ctx.items() if key in CONTEXT_FIELDS}
    messages = getattr(dispatch, 'decision_messages', dispatch.messages)
    if not messages:
        return None
    try:
        # No partial transcript, image, private lease, cancellation object or
        # live mutable context is admitted as a complete replay input.
        raw = json.dumps({'context': context, 'messages': messages,
                          'prompt_format': getattr(dispatch, 'prompt_format', 'activation'),
                          'args': args, 'tool': name, 'allowed': dispatch.allowed}, ensure_ascii=False)
        if len(raw.encode()) > 160_000:
            return None
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


def record(sample: dict | None, run_id: str, step: int, result: object, status: str) -> None:
    if sample is None:
        return
    rejected = (isinstance(result, dict) and result.get('accepted') is False
                or isinstance(result, str) and result.startswith(('Proposal rejected:', 'Tool prerequisite rejected:')))
    if status != 'returned':
        return
    if not rejected and sample['tool'] == 'task.complete' and (
            not isinstance(result, dict) or not result.get('accepted') or result.get('status') == 'failed'):
        return
    from . import optimization
    task = load_note(sample['context']['task'] + '.md')
    if task is None:
        return
    subject = task if task.kind == 'agent' else resolver().resolve(task.meta.get('runbook', ''))
    if subject is None or subject.kind not in {'agent', 'runbook'}:
        return
    sample = {**sample, 'run_id': run_id, 'step': step, 'result': result,
              'rejected': bool(rejected), 'subject': subject.ref,
              'subject_sha256': refinement._hash((CONFIG.vault_dir / subject.path).read_bytes()),
              'implementation': optimization._IMPLEMENTATION_AT_IMPORT}
    # Freeze Articles consulted by the validator, not the whole changing wiki.
    refs = set(sample['context'].get('_article_reads', {}))
    if sample['tool'] == 'vault.propose':
        from ..knowledge.links import metadata_ref
        refs.add(metadata_ref(str(sample['args'].get('target', ''))))
    sample['read_revisions'] = {note.ref: refinement._hash((CONFIG.vault_dir / note.path).read_bytes())
                                for ref in refs if (note := load_note(ref + '.md')) is not None}
    if rejected:
        identity = refinement._store('decisions', sample)
        path = refinement._root() / 'incidents' / (run_id + '.json')
        previous = json.loads(path.read_text()) if path.exists() else []
        if identity not in previous and len(previous) < 4:
            _atomic_write(path, json.dumps([*previous, identity]))
    else:
        key = refinement._hash((task.ref + ':' + sample['tool']).encode())
        # Keep enough independent runs for four controls even when the current
        # incident's own recovery is the newest accepted decision.
        path = refinement._root() / 'controls' / (key + '.json')
        previous = json.loads(path.read_text()) if path.exists() else []
        previous = [row for row in previous if row['run_id'] != run_id]
        _atomic_write(path, json.dumps(
            [*previous[-(optimization.DECISION_CASE_COUNT - 1):], sample], ensure_ascii=False))
        optimization._INSPECTED_RUNS.clear()  # New independent controls can unblock an incident.


def _receipt_matches(sample: dict) -> bool:
    receipts = INDEX.tool_run_receipts(sample['run_id']) or {}
    encoded = json.dumps(sample['result'], sort_keys=True).encode()
    signature = sample['tool'] + ':sha256:' + refinement._hash(json.dumps(sample['args'], sort_keys=True).encode())
    return any(call.get('tool') == sample['tool'] and call.get('status') == 'returned'
               and call.get('result_sha256') == refinement._hash(encoded)
               and call.get('result_chars') == len(encoded)
               and call.get('signature') == signature and call.get('step') == sample['step']
               for call in receipts.get('calls', []))


def check_current(sample: dict) -> None:
    from . import optimization
    if sample.get('validation_revision', sample['implementation']) != optimization._revision():
        raise ValueError('Captured decision predates the current implementation')
    _check_evidence(sample)


def _check_evidence(sample: dict) -> None:
    messages = sample.get('messages')
    if (not isinstance(messages, list) or not messages
            or any(not isinstance(row, dict) or not isinstance(row.get('content'), str) for row in messages)):
        raise ValueError('Historical decision has no complete text-only provider prompt; a fresh capture is required')
    for ref, expected in {sample['subject']: sample['subject_sha256'], **sample['read_revisions']}.items():
        note = load_note(ref + '.md')
        if note is None or refinement._hash((CONFIG.vault_dir / note.path).read_bytes()) != expected:
            raise ValueError('Captured decision dependency changed: ' + ref)
    if not _receipt_matches(sample):
        raise ValueError('Captured decision has no exact committed Tool receipt')
    subject = load_note(sample['subject'] + '.md')
    if not any(subject.body.strip() in row['content'] for row in messages):
        raise ValueError('The captured prompt does not contain its exact instruction body')


def revalidate(sample: dict) -> dict:
    """Derive a current contract case without rewriting the historical capture.

    Only unchanged, receipt-attested text inputs can be used. This is a new
    counterfactual decision evaluation, not a replay of historical implementation
    behavior. Publication still pins the complete current implementation.
    """
    from . import executor, optimization
    _check_evidence(sample)
    task = load_note(sample['context']['task'] + '.md')
    if task is None:
        raise ValueError('Captured decision Task no longer exists')
    spine = executor.resolve_spine(task, resolver())
    if spine.get('error') or set(sample['allowed']) - (set(spine['tools']) | {'task.complete'}):
        raise ValueError('Captured decision Tool authority changed')
    return {**deepcopy(sample), 'validation_revision': optimization._revision(),
            'validation_scope': 'Current contract on unchanged captured inputs; no historical effect replay'}


def prepare(run_id: str) -> dict:
    from . import optimization
    path = refinement._root() / 'incidents' / (run_id + '.json')
    if not path.is_file():
        recover_capture(run_id)
    if not path.is_file():
        raise ValueError('This historical execution has no complete decision evidence; retain its receipts for implementation review')
    samples = [refinement._load('decisions', identity) for identity in json.loads(path.read_text())]
    selected, errors = None, []
    for sample in samples:
        try:
            current = revalidate(sample)
            valid, _reason = validate_decision(current, current['tool'], current['args'])
            if valid:
                errors.append('Captured arguments satisfy the current contract; the original operational outcome is not an instruction grade')
                continue
            selected = current
            break
        except ValueError as exc:
            errors.append(str(exc))
    if selected is None:
        raise ValueError(errors[0] if errors else 'No captured rejection is eligible for isolated evaluation')
    key = refinement._hash((selected['context']['task'] + ':' + selected['tool']).encode())
    controls_path = refinement._root() / 'controls' / (key + '.json')
    controls = json.loads(controls_path.read_text()) if controls_path.exists() else []
    eligible = []
    seen_runs = {selected['run_id']}
    for control in reversed(controls):
        if control['run_id'] in seen_runs:
            continue
        try:
            control = revalidate(control)
            valid, _reason = validate_decision(control, control['tool'], control['args'])
            if valid:
                eligible.append(control)
                seen_runs.add(control['run_id'])
        except ValueError:
            continue
    required = optimization.DECISION_CASE_COUNT - 1
    if len(eligible) < required:
        raise ValueError(f'Awaiting independent accepted decisions for the five-case evaluation '
                         f'({len(eligible)}/{required} held-out controls available)')
    cases = []
    for index, sample in enumerate([selected, *eligible[:required]]):
        cases.append({'id': f'decision-{index}', 'split': 'train' if index == 0 else 'holdout',
                      'objective': sample['context'].get('objective', 'Continue the bound procedure'),
                      'sample': sample})
    return optimization.prepare_decisions(selected, cases)


def recover_capture(run_id: str) -> None:
    """Reconstruct retained decisions only from byte-attested read results.

    Historical initial prompts are not persisted here: this explicitly uses
    the current compiler, never claims exact historical execution, and stops
    before any unaccounted effect. No mutating Tool is called.
    """
    from types import SimpleNamespace
    import re
    from . import executor
    from ..capabilities.source.read import execute as source_read
    from ..capabilities.vault.read import execute as vault_read
    from ..capabilities.vault.search import execute as vault_search

    run = INDEX.run(run_id)
    if not run or run['task_ref'] == 'Agents/Executive/Executive':
        return
    task = load_note(run['task_ref'] + '.md')
    activation = INDEX.activation(str(run.get('activation_id', '')))
    if task is None or not activation:
        return
    res = resolver()
    agent = res.resolve(task.meta.get('assignee', ''))
    spine = executor.resolve_spine(task, res)
    if agent is None or spine.get('error'):
        return
    params = activation['params']
    context = {'task': task.ref, 'agent': agent.title, '_agent_ref': agent.ref, 'run_id': run_id,
               'event': params.get('event'), 'params': params, 'objective': run.get('objective', ''), 'trace': []}
    sections = {}
    executor._activation_packet(task, agent, spine,
        executor.ActivationBinding(context['objective'], params), '', '',
        accepted_resolver=res, provider_sections=sections)
    messages = executor.activation_messages(task, {**sections, 'params': params,
                            'objective': context['objective']}, agent_name=agent.title)
    receipts = INDEX.tool_run_receipts(run_id) or {}
    events = [json.loads(row[0]) for row in INDEX.db.execute(
        'SELECT entry FROM trace_events WHERE entry LIKE ?', ('%' + run_id + '%',))]
    results = {(e.get('step'), e.get('payload', {}).get('name')): e['payload'].get('result')
               for e in events if e.get('run_id') == run_id and e.get('payload', {}).get('kind') == 'tool'
               and e['payload'].get('phase') == 'result'}
    decisions = [row for row in json.loads(run.get('trace') or '[]') if row.get('tool')]
    calls = receipts.get('calls', [])
    for entry, call in zip(decisions, calls):
        name, args = entry['tool'], entry.get('args', {})
        signature = name + ':sha256:' + refinement._hash(json.dumps(args, sort_keys=True).encode())
        if call.get('tool') != name or call.get('signature') != signature or call.get('status') != 'returned':
            return
        if name in {'source.read', 'vault.read'}:
            result = (source_read if name == 'source.read' else vault_read)(args, context)
        elif name == 'vault.search' and (call['step'], name) not in results:
            result = vault_search(args, context)
        else:
            result = results.get((call['step'], name))
            if result is None and name == 'vault.propose' and isinstance(entry.get('obs'), str):
                result = entry['obs']  # Must still match the complete result receipt below.
        raw = json.dumps(result, sort_keys=True).encode()
        if refinement._hash(raw) != call['result_sha256'] or len(raw) != call['result_chars']:
            if name == 'vault.search' and call.get('read_only') is True:
                # Search snippets are not inputs to proposal syntax/citation
                # validation. Omit missing bytes explicitly; do not recreate
                # their private search receipts or use this as completion proof.
                messages.append({'role': 'user', 'content':
                    'A historical Knowledge search occurred. Its complete result is unavailable in this reconstruction.'})
                continue
            return
        if name == 'vault.search':
            if not isinstance(result, str) or not (result.startswith('- [[') or result == 'No results.') or 'query' not in args:
                return
            context.setdefault('_vault_searches', {})[args['query']] = {'refs': re.findall(r'^- \[\[([^]]+)\]\]', result, re.M)}
        elif name in SUPPORTED:
            dispatch = SimpleNamespace(task=task, ctx=context, messages=messages,
                                       allowed=spine['tools'], visual_context_seen=False)
            sample = snapshot(dispatch, name, args)
            if sample is None:
                return
            sample['reconstructed'] = True
            record(sample, run_id, call['step'], result, 'returned')
            if name == 'vault.propose' and not str(result).startswith('Proposal rejected:'):
                return  # The accepted operation is a control, never replayed.
        elif name not in {'source.read', 'vault.read'}:
            return
        messages.extend([{'role': 'assistant', 'content': json.dumps({'tool': name, 'args': args})},
                         {'role': 'user', 'content': 'Observation:\n' + (result if isinstance(result, str) else json.dumps(result))}])
        context['trace'].append(entry)


def validate_decision(sample: dict, tool: str, args: dict) -> tuple[bool, str]:
    """Use executable contracts as the rubric; never execute a proposed effect."""
    from ..capabilities.registry import argument_schema
    from ..capabilities.task.complete import execute as complete
    from ..capabilities.source.read import precondition_error
    from ..knowledge.scope import assert_proposal_scope
    from ..capabilities.vault.propose import stage_proposal
    import jsonschema

    context = deepcopy(sample['context'])
    context['run_id'] = sample['run_id']
    context['task_note'] = load_note(context['task'] + '.md')
    try:
        if tool not in sample['allowed']:
            raise ValueError('Decision exceeds the captured Tool authority')
        jsonschema.validate(args, argument_schema(tool))
        if error := precondition_error(tool, args, context):
            raise ValueError(error)
        # A missing prerequisite has a code-owned next operation. A model may
        # not replace a rejected success claim with a fabricated failure.
        original_error = str(sample['result'].get('error', '')) if isinstance(sample['result'], dict) else str(sample['result'])
        if sample['rejected'] and sample['tool'] == 'task.complete':
            if 'successful Knowledge search' in original_error:
                return (tool == 'vault.search' and bool(str(args.get('query', '')).strip()),
                        'The completion contract requires a topic search before success')
            if 'complete bound' in original_error or 'read the bound' in original_error.lower():
                expected = (context.get('params') or {}).get('source_citation')
                return (tool == 'source.read' and bool(expected) and expected in json.dumps(args),
                        'The completion contract requires the bound Source')
        if tool != sample['tool']:
            raise ValueError('This decision case requires the original operation or its attested prerequisite')
        if tool == 'task.complete':
            if args.get('status') == 'failed':
                raise ValueError('Turning a correctable rejection into failure is not an improvement')
            outcome = complete(args, context)
            return bool(outcome.get('accepted')), str(outcome.get('error') or 'Completion contract satisfied')
        if tool == 'vault.propose':
            from ..knowledge.links import metadata_ref
            if (args.get('action', 'create') != sample['args'].get('action', 'create')
                    or metadata_ref(str(args.get('target', ''))) != metadata_ref(str(sample['args'].get('target', '')))):
                raise ValueError('Changing the requested target or operation cannot pass this case')
            assert_proposal_scope(str(args.get('target', '')), context, resolver())
            stage_proposal(args, context, validate_only=True)
            return True, 'Proposal contract satisfied without staging or publication'
        raise ValueError('No independent contract evaluator for this operation')
    except (ValueError, PermissionError, jsonschema.ValidationError) as exc:
        return False, str(exc)[:1500]


def notifications() -> list[dict]:
    """Project unresolved optimizer outcomes into the existing health Review."""
    rows = []
    path = refinement._root() / 'optimization-attention.json'
    if path.is_file():
        for row in json.loads(path.read_text()):
            if (recovered_operational_incident(row.get('run_id', ''))
                    or superseding_evaluation(row)):
                continue
            reason = row.get('reason', '')
            evidence_gap = ('no complete decision evidence' in reason or 'no complete text-only provider prompt' in reason
                            or 'dependency changed:' in reason or 'original operational outcome is not an instruction grade' in reason)
            if evidence_gap or reason.startswith('Awaiting independent accepted decisions'):
                # No owner action can repair these; they stay in the attention
                # record and health status instead of Review.
                continue
            rows.append({**row, 'title': 'AutoSaddler', 'task': row.get('task', refinement.AUDITOR)})
    return rows


def superseding_evaluation(row: dict) -> str | None:
    """A complete, receipt-attested replacement resolves an old engine failure.

    Candidate quality remains with the replacement report and its own finding.
    This only removes a superseded incomplete-evaluation warning from the live
    projection; neither historical report nor attention evidence is modified.
    """
    from . import optimization
    if row.get('reason') != 'AutoSaddler exhausted its bounded improvement attempt: incomplete':
        return None
    try:
        previous = refinement._load('executive/cases', row['key'])
        old_run = INDEX.run(row['run_id'])
        if not old_run or not previous.get('origin'):
            return None
        paths = sorted((refinement._root() / 'executive/jobs').glob('*/report.json'),
                       key=lambda p: p.stat().st_mtime, reverse=True)[:64]
        for path in paths:
            if path.is_symlink() or path.stat().st_size > 16_000 or path.parent.name == row['key']:
                continue
            result = json.loads(path.read_text())
            if result.get('verdict') == 'incomplete' or result.get('comparison', {}).get('counts', {}).get('total') != optimization.DECISION_CASE_COUNT * optimization.EVALUATION_REPETITIONS:
                continue
            current = refinement._load('executive/cases', path.parent.name)
            if current.get('origin') != previous['origin'] or current.get('subject') != previous.get('subject'):
                continue
            report = refinement._load('executive/reports', result['report_id'])
            run = INDEX.run(report['audit_run_id'])
            expected = optimization._report_result(result['report_id'], report)
            if report['verdict'] == 'passed' and isinstance(result.get('proposal'), str):
                expected['proposal'] = result['proposal']
            if (result != expected or report['case_id'] != path.parent.name or not run
                    or run['status'] not in {'completed', 'review', 'failed'}
                    or run['task_ref'] != optimization.AUDITOR
                    or not run.get('finished') or run['finished'] <= (old_run.get('finished') or 0)):
                continue
            encoded = json.dumps(json.dumps(result, sort_keys=True), sort_keys=True).encode()
            signature = 'harness.optimize:sha256:' + refinement._hash(json.dumps({'case_id': report['case_id']}, sort_keys=True).encode())
            if any(call.get('tool') == 'harness.optimize' and call.get('status') == 'returned'
                   and call.get('signature') == signature and call.get('result_chars') == len(encoded)
                   and call.get('result_sha256') == refinement._hash(encoded)
                   for call in (INDEX.tool_run_receipts(run['id']) or {}).get('calls', [])):
                return report['case_id']
    except (ValueError, OSError, KeyError, TypeError):
        pass
    return None


def recovered_operational_incident(run_id: str) -> str | None:
    """Resolve only a valid decision whose exact occurrence subsequently completed.

    A later unrelated success cannot clear an incident. Correctable rejected
    arguments remain optimizer input even if the Task eventually recovered.
    Original attention records and Tool receipts are never deleted.
    """
    run = INDEX.run(run_id)
    if not run or not run.get('activation_id'):
        return None
    path = refinement._root() / 'incidents' / (run_id + '.json')
    if not path.is_file():
        return None
    try:
        original = INDEX.tool_run_receipts(run_id) or {}
        for (identity,) in INDEX.db.execute(
                "SELECT id FROM runs WHERE activation_id=? AND task_ref=? AND status='completed' AND finished>? ORDER BY finished DESC LIMIT 8",
                (run['activation_id'], run['task_ref'], run['finished'])):
            coverage = INDEX.tool_run_receipts(identity) or {}
            calls = coverage.get('calls', [])
            entries = [entry for entry in json.loads(INDEX.run(identity)['trace']) if entry.get('tool')]
            if (coverage.get('params_sha256') != original.get('params_sha256')
                    or not calls or len(calls) != len(entries)
                    or any(call.get('status') != 'returned' for call in calls)
                    or calls[-1].get('tool') != 'task.complete'
                    or entries[-1].get('tool') != 'task.complete' or entries[-1].get('accepted') is not True):
                continue
            # The terminal trace holds normalized authority output, not the
            # model's original arguments. Attest the returned result itself.
            result = json.dumps({'accepted': True, **entries[-1]['args'], 'error': ''}, sort_keys=True).encode()
            if (calls[-1].get('result_sha256') == refinement._hash(result)
                    and calls[-1].get('result_chars') == len(result)):
                # Rebuild historical decision contexts only after a later exact
                # occurrence has attested completion. Every original evidence
                # gate still applies before resolving the incident.
                samples = [refinement._load('decisions', sample_id)
                           for sample_id in json.loads(path.read_text())]
                if not samples or any(not _receipt_matches(sample) or not validate_decision(
                        sample, sample['tool'], sample['args'])[0] for sample in samples):
                    return None
                return identity
    except (ValueError, OSError, KeyError, TypeError):
        pass  # Evidence uncertainty remains visible, never a resolution.
    return None


def attention(identity: str, run_id: str, task: str, reason: str, detail: str = '') -> None:
    path = refinement._root() / 'optimization-attention.json'
    rows = json.loads(path.read_text()) if path.is_file() else []
    before = list(rows)
    rows = [row for row in rows if row['key'] != identity
            and not (reason and row.get('run_id') == run_id and row.get('task') == task)]
    if reason:
        rows.append({'key': identity, 'run_id': run_id, 'task': task, 'reason': reason[:1000], 'detail': detail[:2000]})
    if rows != before:
        _atomic_write(path, json.dumps(rows[-64:], sort_keys=True))

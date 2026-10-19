"""Receipt-bound decision cases for the AutoSaddler scenario.

This is a capture/evaluation adapter, not an optimizer or an action retry loop.
The ordinary Capability owner validates proposed decisions without committing
them. Unsupported effects remain explicit Review findings.
"""
from __future__ import annotations

from copy import deepcopy
import json

from ...config import CONFIG
from ...knowledge.index import INDEX
from ...knowledge.vault import _atomic_write, load_note, resolver
from . import AUDITOR, store

SUPPORTED = {'task.complete', 'vault.propose'}
CONTEXT_FIELDS = {
    'task', 'agent', '_agent_ref', 'objective', 'event', 'params', 'interactive',
    '_source_reads', '_article_reads', '_vault_searches', '_created_tasks',
    'staged_proposals', 'maintenance_candidate', '_memory_proposal_rejection',
    '_link_proposal_rejection', '_proposal_read_prerequisite', 'handoff_source_id',
    '_merge_retained_updates', '_assignment_read_refs',
    '_computer_act_scope', '_computer_request_target', 'trace',
}


def snapshot(dispatch, name: str, args: dict) -> dict | None:
    if (name not in SUPPORTED or dispatch.task.ref in {AUDITOR, 'Tasks/repair'}
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
    from . import admission
    task = load_note(sample['context']['task'] + '.md')
    if task is None:
        return
    subject = task if task.kind == 'agent' else resolver().resolve(task.meta.get('runbook', ''))
    if subject is None or subject.kind not in {'agent', 'runbook'}:
        return
    sample = {**sample, 'run_id': run_id, 'step': step, 'result': result,
              'rejected': bool(rejected), 'subject': subject.ref,
              'subject_sha256': store.sha256((CONFIG.vault_dir / subject.path).read_bytes()),
              'implementation': admission.IMPLEMENTATION_AT_IMPORT}
    # Freeze Articles consulted by the validator, not the whole changing wiki.
    refs = set(sample['context'].get('_article_reads', {}))
    if sample['tool'] == 'vault.propose':
        from ...knowledge.links import metadata_ref
        refs.add(metadata_ref(str(sample['args'].get('target', ''))))
    sample['read_revisions'] = {note.ref: store.sha256((CONFIG.vault_dir / note.path).read_bytes())
                                for ref in refs if (note := load_note(ref + '.md')) is not None}
    if rejected:
        identity = store.save('decisions', sample)
        path = store.root() / 'incidents' / (run_id + '.json')
        previous = json.loads(path.read_text()) if path.exists() else []
        if identity not in previous:
            # Four at most: the run's first three rejections and its newest one.
            _atomic_write(path, json.dumps([*previous[:3], identity]))
    else:
        key = store.sha256((task.ref + ':' + sample['tool']).encode())
        # Keep enough independent runs for four controls even when the current
        # incident's own recovery is the newest accepted decision.
        path = store.root() / 'controls' / (key + '.json')
        previous = json.loads(path.read_text()) if path.exists() else []
        previous = [row for row in previous if row['run_id'] != run_id]
        _atomic_write(path, json.dumps(
            [*previous[-(admission.DECISION_CASE_COUNT - 1):], sample], ensure_ascii=False))
        admission.INSPECTED_RUNS.clear()  # New independent controls can unblock an incident.


def receipt_matches(sample: dict) -> bool:
    receipts = INDEX.tool_run_receipts(sample['run_id']) or {}
    encoded = json.dumps(sample['result'], sort_keys=True).encode()
    signature = sample['tool'] + ':sha256:' + store.sha256(json.dumps(sample['args'], sort_keys=True).encode())
    return any(call.get('tool') == sample['tool'] and call.get('status') == 'returned'
               and call.get('result_sha256') == store.sha256(encoded)
               and call.get('result_chars') == len(encoded)
               and call.get('signature') == signature and call.get('step') == sample['step']
               for call in receipts.get('calls', []))


def check_current(sample: dict) -> None:
    from . import admission
    if sample.get('validation_revision', sample['implementation']) != admission.implementation_revision():
        raise ValueError('Captured decision predates the current implementation')
    _check_evidence(sample)


def _check_evidence(sample: dict) -> None:
    messages = sample.get('messages')
    if (not isinstance(messages, list) or not messages
            or any(not isinstance(row, dict) or not isinstance(row.get('content'), str) for row in messages)):
        raise ValueError('Historical decision has no complete text-only provider prompt; a fresh capture is required')
    for ref, expected in {sample['subject']: sample['subject_sha256'], **sample['read_revisions']}.items():
        note = load_note(ref + '.md')
        if note is None or store.sha256((CONFIG.vault_dir / note.path).read_bytes()) != expected:
            raise ValueError('Captured decision dependency changed: ' + ref)
    if not receipt_matches(sample):
        raise ValueError('Captured decision has no exact committed Tool receipt')
    subject = load_note(sample['subject'] + '.md')
    if not any(subject.body.strip() in row['content'] for row in messages):
        raise ValueError('The captured prompt does not contain its exact instruction body')


def _current_instructions(sample: dict) -> dict:
    """Put the subject's current body where the captured one was, as a candidate trial does.

    The captured body is found by its exact hash in the Vault's audit history.
    Without it the sample is returned unchanged and fails the dependency check.
    """
    import subprocess
    from ...knowledge import format as article_format
    subject = load_note(sample['subject'] + '.md')
    messages = sample.get('messages')
    if subject is None or not isinstance(messages, list):
        return sample
    current = store.sha256((CONFIG.vault_dir / subject.path).read_bytes())
    if current == sample['subject_sha256']:
        return sample
    git = ['git', '-C', str(CONFIG.vault_dir)]
    try:
        commits = subprocess.run([*git, 'log', '--format=%H', '-n', '64', '--', subject.path],
                                 capture_output=True, text=True, check=True, timeout=10).stdout.split()
        for commit in commits:
            raw = subprocess.run([*git, 'show', f'{commit}:{subject.path}'],
                                 capture_output=True, check=True, timeout=10).stdout
            if store.sha256(raw) == sample['subject_sha256']:
                captured = article_format.loads(raw.decode('utf-8'))[1].strip()
                break
        else:
            return sample
    except (OSError, subprocess.SubprocessError, UnicodeDecodeError, ValueError):
        return sample
    if not captured:
        return sample
    messages = deepcopy(messages)
    replaced = 0
    for message in messages:
        if isinstance(message, dict) and isinstance(message.get('content'), str):
            replaced += message['content'].count(captured)
            message['content'] = message['content'].replace(captured, subject.body.strip())
    if not replaced:
        return sample
    return {**sample, 'messages': messages, 'subject_sha256': current, 'captured_subject_sha256': sample['subject_sha256']}


def revalidate(sample: dict, current_instructions: bool = False) -> dict:
    """Derive a current contract case without rewriting the historical capture.

    Only unchanged, receipt-attested text inputs can be used. This is a new
    counterfactual decision evaluation, not a replay of historical implementation
    behavior. Publication still pins the complete current implementation. An
    owner re-check may judge the current instructions instead of the captured
    ones; Articles the validator consulted must still be unchanged.
    """
    from .. import executor
    from . import admission
    if current_instructions:
        sample = _current_instructions(sample)
    _check_evidence(sample)
    task = load_note(sample['context']['task'] + '.md')
    if task is None:
        raise ValueError('Captured decision Task no longer exists')
    spine = executor.resolve_spine(task, resolver())
    if spine.get('error') or set(sample['allowed']) - (set(spine['tools']) | {'task.complete'}):
        raise ValueError('Captured decision Tool authority changed')
    return {**deepcopy(sample), 'validation_revision': admission.implementation_revision(),
            'validation_scope': ('Current contract and current instructions on otherwise unchanged captured inputs; '
                                 'no historical effect replay' if sample.get('captured_subject_sha256') else
                                 'Current contract on unchanged captured inputs; no historical effect replay')}


def prepare(run_id: str, current_instructions: bool = False) -> dict:
    """Automatic admission judges the captured instructions; an owner re-check may judge the current ones."""
    from . import admission
    path = store.root() / 'incidents' / (run_id + '.json')
    if not path.is_file():
        recover_capture(run_id)
    if not path.is_file():
        raise ValueError('This historical execution has no complete decision evidence; retain its receipts for implementation review')
    samples = [store.load('decisions', identity) for identity in json.loads(path.read_text())]
    selected, errors = None, []
    # The unrecovered rejection is the run's last; it corrected the earlier ones itself.
    for sample in samples[-1:]:
        try:
            current = revalidate(sample, current_instructions)
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
    key = store.sha256((selected['context']['task'] + ':' + selected['tool']).encode())
    controls_path = store.root() / 'controls' / (key + '.json')
    controls = json.loads(controls_path.read_text()) if controls_path.exists() else []
    eligible = []
    seen_runs = {selected['run_id']}
    for control in reversed(controls):
        if control['run_id'] in seen_runs:
            continue
        try:
            control = revalidate(control, current_instructions)
            valid, _reason = validate_decision(control, control['tool'], control['args'])
            if valid:
                eligible.append(control)
                seen_runs.add(control['run_id'])
        except ValueError:
            continue
    required = admission.DECISION_CASE_COUNT - 1
    if len(eligible) < required:
        raise ValueError(f'Awaiting independent accepted decisions for the five-case evaluation '
                         f'({len(eligible)}/{required} held-out controls available)')
    cases = []
    for index, sample in enumerate([selected, *eligible[:required]]):
        cases.append({'id': f'decision-{index}', 'split': 'train' if index == 0 else 'holdout',
                      'objective': sample['context'].get('objective', 'Continue the bound procedure'),
                      'sample': sample})
    return admission.prepare_decisions(selected, cases)


def recover_capture(run_id: str) -> None:
    """Reconstruct retained decisions only from byte-attested read results.

    Historical initial prompts are not persisted here: this explicitly uses
    the current compiler, never claims exact historical execution, and stops
    before any unaccounted effect. No mutating Tool is called.
    """
    from types import SimpleNamespace
    import re
    from .. import executor
    from ...capabilities.source.read import execute as source_read
    from ...capabilities.vault.read import execute as vault_read
    from ...capabilities.vault.search import execute as vault_search

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
        signature = name + ':sha256:' + store.sha256(json.dumps(args, sort_keys=True).encode())
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
        if store.sha256(raw) != call['result_sha256'] or len(raw) != call['result_chars']:
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


def contract_dead_end(run: dict, entries: list, sample: dict | None) -> str | None:
    """Name a terminal failure that no Agent or Runbook body edit can correct.

    A cited Article that vault.read returned only in part, and a run that ended
    without a dispatchable Tool call, are Tool-contract or code findings.
    """
    found = []
    failed = run['status'] in {'failed', 'blocked'}
    # Only the read-receipt rejection of a run that never completed, and only a
    # search lead: the completion gate requires a read of nothing else.
    if (failed and sample is not None and sample['tool'] == 'task.complete' and isinstance(sample['result'], dict)
            and 'complete current read' in str(sample['result'].get('error', ''))):
        evidence = sample['args'].get('evidence')
        cited = '\n'.join(str(item) for item in evidence) if isinstance(evidence, list) else ''
        leads = {ref for row in sample['context'].get('_vault_searches', {}).values() for ref in row.get('refs', [])}
        for ref, read in sample['context'].get('_article_reads', {}).items():
            if read.get('complete') is False and ref in leads and ref in cited:
                found.append(f'the rejected completion cites [[{ref}]], which vault.read returned only in part '
                             f'(ranges {read.get("ranges")} of {read.get("total_characters")} characters)')
    summary = str(run.get('summary') or '')
    last = entries[-1] if entries and isinstance(entries[-1], dict) else {}
    limit = last.get('finish_reason') == 'max-tokens' or 'ended with max-tokens' in summary
    if failed and (limit or 'valid action block' in summary or 'invalid native Tool calls' in summary):
        found.append(f'the run ended on "{summary[:200]}"' + (' with its last reply cut off at the output limit' if limit else ''))
    if not found:
        return None
    return ('Implementation finding, not an instruction failure: ' + '; '.join(found)
            + f'. Run {run["id"]}; no optimization job was admitted.')


TRIAL_READS = ('source.read', 'vault.read', 'vault.search', 'vault.validate')


def trial_read(sample: dict, context: dict, tool: str, args: dict) -> str | None:
    """Answer a trial's read-only step from the current Vault, or None when the call is the graded one.

    A search, an Article or Source read and vault.validate change nothing. Their
    receipts enter ``context``, the trial's own copy, exactly as a live run's
    would, so the contract then grades the following call on what was read.
    """
    from importlib import import_module
    from ...capabilities.registry import argument_schema
    from ...capabilities.source.read import precondition_error
    import jsonschema

    if tool not in TRIAL_READS or tool == sample['tool'] or tool not in sample['allowed']:
        return None
    try:
        jsonschema.validate(args, argument_schema(tool))
    except jsonschema.ValidationError:
        return None
    context.setdefault('run_id', sample['run_id'])
    if error := precondition_error(tool, args, context):
        observation, dispatched = 'Tool prerequisite rejected: ' + error, False
    else:
        observation, dispatched = import_module('...capabilities.' + tool, __package__).execute(args, context), True
    context.setdefault('trace', []).append({'tool': tool, 'args': args, 'obs': observation,
                                            **({} if dispatched else {'not_dispatched': True})})
    return observation


def validate_decision(sample: dict, tool: str, args: dict) -> tuple[bool, str]:
    """Use executable contracts as the rubric; never execute a proposed effect."""
    from ...capabilities.registry import argument_schema
    from ...capabilities.task.complete import execute as complete
    from ...capabilities.source.read import precondition_error
    from ...knowledge.scope import assert_proposal_scope
    from ...knowledge.proposals import stage_proposal
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
        if tool != sample['tool']:
            raise ValueError('This decision case requires the original operation after any read-only steps')
        if tool == 'task.complete':
            # A model may not replace a rejected success claim with a fabricated failure.
            if args.get('status') == 'failed':
                raise ValueError('Turning a correctable rejection into failure is not an improvement')
            outcome = complete(args, context)
            return bool(outcome.get('accepted')), str(outcome.get('error') or 'Completion contract satisfied')
        if tool == 'vault.propose':
            from ...knowledge.links import metadata_ref
            if (args.get('action', 'create') != sample['args'].get('action', 'create')
                    or metadata_ref(str(args.get('target', ''))) != metadata_ref(str(sample['args'].get('target', '')))):
                raise ValueError('Changing the requested target or operation cannot pass this case')
            assert_proposal_scope(str(args.get('target', '')), context, resolver())
            stage_proposal(args, context, validate_only=True)
            return True, 'Proposal contract satisfied without staging or publication'
        raise ValueError('No independent contract evaluator for this operation')
    except (ValueError, PermissionError, jsonschema.ValidationError) as exc:
        return False, str(exc)[:1500]


def _exhausted_verdict(reason: str) -> str | None:
    """Keep historical AutoSaddler findings compatible with the selected optimizer."""
    for prefix in ('AutoSaddler exhausted its bounded improvement attempt: ',
                   'Instruction optimizer exhausted its bounded improvement attempt: '):
        if isinstance(reason, str) and reason.startswith(prefix):
            return reason.removeprefix(prefix)
    return None


def notifications() -> list[dict]:
    """Project unresolved optimizer outcomes into the existing health Review."""
    rows = []
    path = store.root() / 'optimization-attention.json'
    if path.is_file():
        files = _evaluation_files()
        for row in json.loads(path.read_text()):
            # A job's finding names its Audit run; the incident is the origin's.
            if (recovered_operational_incident(row.get('origin_run_id') or row.get('run_id', ''))
                    or superseding_evaluation(row, files)):
                continue
            reason = row.get('reason', '')
            evidence_gap = ('no complete decision evidence' in reason or 'no complete text-only provider prompt' in reason
                            or 'dependency changed:' in reason or 'original operational outcome is not an instruction grade' in reason)
            if (evidence_gap or reason.startswith('Awaiting independent accepted decisions')
                    or reason.startswith('Implementation finding')):
                # No owner action can repair these; they stay in the attention
                # record and health status instead of Review. A dead-end run is
                # already in Review as its own failed Task.
                continue
            if _exhausted_verdict(reason) == 'not_improved':
                reason = 'No instruction candidate met the quality gate; the current instructions were kept.'
            rows.append({**row, 'reason': reason, 'title': 'Instruction improvement',
                         'task': row.get('task', AUDITOR)})
    return rows


# File-attested replacement reports per finding, for one state of the exhausted
# findings and job reports. The scheduler tick then repeats only the ledger reads.
_REPLACEMENTS: dict = {}


def _evaluation_files() -> tuple:
    """Identify what a replacement attestation reads: exhausted findings, and job reports as last written."""
    root = store.root()
    attention_path = root / 'optimization-attention.json'
    findings = json.loads(attention_path.read_text()) if attention_path.is_file() else []
    # Admission rewrites the record in another order on every inspection pass.
    return (frozenset((row.get('key'), row.get('run_id'), row.get('reason')) for row in findings
                      if _exhausted_verdict(row.get('reason')) is not None),
            tuple(sorted((path.parent.name, path.stat().st_mtime_ns)
                         for path in (root / 'executive/jobs').glob('*/report.json'))))


def _replacement_reports(row: dict, baseline_failure: bool) -> list[dict]:
    """Attest from job artifacts alone which reports may replace this finding, newest first."""
    from . import admission
    found = []
    try:
        previous = store.load('executive/cases', row['key'])
        if not previous.get('origin'):
            return found
        paths = sorted((store.root() / 'executive/jobs').glob('*/report.json'),
                       key=lambda p: p.stat().st_mtime, reverse=True)[:64]
        attention_path = store.root() / 'optimization-attention.json'
        findings = json.loads(attention_path.read_text()) if attention_path.is_file() else []
        for path in paths:
            if path.is_symlink() or path.stat().st_size > 16_000 or path.parent.name == row['key']:
                continue
            result = json.loads(path.read_text())
            if result.get('comparison', {}).get('counts', {}).get('total') != admission.DECISION_CASE_COUNT * admission.EVALUATION_REPETITIONS:
                continue
            current = store.load('executive/cases', path.parent.name)
            if current.get('origin') != previous['origin'] or current.get('subject') != previous.get('subject'):
                continue
            report = store.load('executive/reports', result['report_id'])
            replacement_finding = any(
                finding.get('key') == report['case_id']
                and finding.get('run_id') == report['audit_run_id']
                and _exhausted_verdict(finding.get('reason')) == report['verdict']
                for finding in findings)
            if result.get('verdict') == 'incomplete' and not replacement_finding:
                continue
            if baseline_failure:
                # Replays of the incident (the training case) that all pass resolve
                # it. If the replacement still fails, keep its own finding instead of
                # two warnings for the same incident. An unapplied candidate alone
                # cannot clear the quality warning.
                baseline = [item for item in report.get('observations', {}).get(report.get('seed_id'), [])
                            if item.get('split') == 'train']
                baseline_passed = bool(baseline) and all(item.get('passed') and not item.get('error')
                                                         for item in baseline)
                if not baseline_passed and not replacement_finding:
                    continue
            audit_run_id = report['audit_run_id']
            expected = admission.report_result(result['report_id'], report)
            if report['verdict'] == 'passed' and isinstance(result.get('proposal'), str):
                expected['proposal'] = result['proposal']
            if result != expected or report['case_id'] != path.parent.name:
                continue
            encoded = json.dumps(json.dumps(result, sort_keys=True), sort_keys=True).encode()
            signature = 'harness.optimize:sha256:' + store.sha256(json.dumps({'case_id': report['case_id']}, sort_keys=True).encode())
            found.append({'case_id': report['case_id'], 'audit_run_id': audit_run_id, 'signature': signature,
                          'result_chars': len(encoded), 'result_sha256': store.sha256(encoded)})
    except (ValueError, OSError, KeyError, TypeError):
        pass  # Nothing after unattestable evidence may resolve the finding.
    return found


def superseding_evaluation(row: dict, files: tuple | None = None) -> str | None:
    """A receipt-attested replacement resolves an old engine or baseline failure.

    Candidate quality remains with the replacement report and its own finding.
    A new finding replaces an older finding for the same incident; an entirely
    passing baseline may resolve it. Historical reports and attention remain.
    """
    reason = row.get('reason')
    baseline_failure = _exhausted_verdict(reason) == 'not_improved'
    if not baseline_failure and _exhausted_verdict(reason) != 'incomplete':
        return None
    try:
        old_run = INDEX.run(row['run_id'])
        if not old_run:
            return None
        files = files or _evaluation_files()
        if _REPLACEMENTS.get('files') != files:
            _REPLACEMENTS.clear()
            _REPLACEMENTS['files'] = files
        if (row['key'], reason) not in _REPLACEMENTS:
            _REPLACEMENTS[row['key'], reason] = _replacement_reports(row, baseline_failure)
        for candidate in _REPLACEMENTS[row['key'], reason]:
            run = INDEX.run(candidate['audit_run_id'])
            if (not run or run['status'] not in {'completed', 'review', 'failed'}
                    or run['task_ref'] != AUDITOR
                    or not run.get('finished') or run['finished'] <= (old_run.get('finished') or 0)):
                continue
            if any(call.get('tool') == 'harness.optimize' and call.get('status') == 'returned'
                   and call.get('signature') == candidate['signature']
                   and call.get('result_chars') == candidate['result_chars']
                   and call.get('result_sha256') == candidate['result_sha256']
                   for call in (INDEX.tool_run_receipts(run['id']) or {}).get('calls', [])):
                return candidate['case_id']
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
    path = store.root() / 'incidents' / (run_id + '.json')
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
            if (calls[-1].get('result_sha256') == store.sha256(result)
                    and calls[-1].get('result_chars') == len(result)):
                # Rebuild historical decision contexts only after a later exact
                # occurrence has attested completion. Every original evidence
                # gate still applies before resolving the incident.
                samples = [store.load('decisions', sample_id)
                           for sample_id in json.loads(path.read_text())]
                if not samples or any(not receipt_matches(sample) or not validate_decision(
                        sample, sample['tool'], sample['args'])[0] for sample in samples):
                    return None
                return identity
    except (ValueError, OSError, KeyError, TypeError):
        pass  # Evidence uncertainty remains visible, never a resolution.
    return None


def attention(identity: str, run_id: str, task: str, reason: str, detail: str = '', origin: str = '') -> None:
    path = store.root() / 'optimization-attention.json'
    rows = json.loads(path.read_text()) if path.is_file() else []
    before = list(rows)
    rows = [row for row in rows if row['key'] != identity
            and not (reason and row.get('run_id') == run_id and row.get('task') == task)]
    if reason:
        rows.append({'key': identity, 'run_id': run_id, 'task': task, 'reason': reason[:1000], 'detail': detail[:2000],
                     **({'origin_run_id': origin} if origin else {})})
    if rows != before:
        _atomic_write(path, json.dumps(rows[-64:], sort_keys=True))

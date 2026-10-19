"""Bounded training lessons, committed only after the existing Review/Audit gate.

These internal optimizer artifacts are neither Knowledge nor Hindsight. A case
embeds its exact experience snapshot; resuming never reads newer lessons.
"""
from __future__ import annotations

import json

from ...config import CONFIG
from ...knowledge.index import INDEX
from ...knowledge.vault import Resolver, resolver
from . import AUDITOR, cases, store

MAX_LESSONS = 6


def scope(document):
    from .admission import subject_ref
    subject = subject_ref(document)
    return store.sha256(store.canonical_json({'subject': subject,
        'task': document.get('task'), 'agent': document['agent'],
        'model': document['model_contract'], 'optimizer': document['optimizer_contract'],
        'backend': document['backend_contract'],
        'implementation': document['evaluator_revision'],
        'frozen_articles': document['articles']}).encode())


def freeze(document):
    """Capture only compatible, already-published lessons at case preparation."""
    if document['backend_contract']['name'] != 'harness2':
        return []
    key = scope(document)
    found = []
    directory = store.root() / 'executive/experience'
    paths = sorted(directory.glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True)[:64]
    for path in paths:
        row = store.load('executive/experience', path.stem)
        if row.get('scope') == key:
            found.extend(row['lessons'])
        if len(found) >= MAX_LESSONS:
            break
    return found[:MAX_LESSONS]


def published(marker: dict | None, proposal_id: str) -> None:
    """Call only after Review has committed approval and synced the accepted body.

    The durable Review row, accepted bytes, independent result and exact returned
    Audit receipt are all checked again. This routine performs no model calls.
    """
    if marker is None:
        return
    from . import admission, backend
    from ..adk.optimization import comparison
    if not isinstance(marker, dict) or set(marker) != {'case_id', 'report_id'}:
        raise ValueError('Published optimizer lesson lost its exact binding')
    report = store.load('executive/reports', marker['report_id'])
    if report.get('backend_contract', {}).get('name') != 'harness2' or not report.get('pending_lessons'):
        return
    document = store.load('executive/cases', marker['case_id'])
    admission.validate_report_backend(document, report)
    decision = INDEX.review_decision(proposal_id)
    run = INDEX.run(report['audit_run_id'])
    subject = Resolver(cases.frozen_notes(document)).resolve(admission.subject_ref(document))
    accepted = resolver(include_system=False).resolve(subject.ref)
    if (not decision or decision.get('decision') != 'approved'
            or decision.get('run_id') != report['audit_run_id'] or decision.get('target') != subject.path
            or decision.get('task_ref') != AUDITOR or not run or run.get('status') not in {'completed', 'review'}
            or accepted is None or accepted.body.strip() != report['candidate_body'].strip()
            or report['case_id'] != marker['case_id'] or report['verdict'] != 'passed'
            or report.get('optimizer_failures') or document['backend_contract'] != backend.contract()
            or document['evaluator_revision'] != admission.implementation_revision()
            or comparison(document, report['observations'], report['seed_id'], report['selected_id']) != report['comparison']
            or report['comparison']['verdict'] != 'passed'):
        raise ValueError('Published optimizer lesson lacks its committed approval and independent result')
    receipts = INDEX.tool_run_receipts(report['audit_run_id']) or {}
    result = {**admission.report_result(marker['report_id'], report), 'proposal': proposal_id}
    expected = store.sha256(json.dumps(json.dumps(result, sort_keys=True), sort_keys=True).encode())
    if not any(call.get('tool') == 'harness.optimize' and call.get('status') == 'returned'
               and call.get('result_sha256') == expected for call in receipts.get('calls', [])):
        raise ValueError('Published optimizer lesson lacks its exact Audit receipt')
    train = {row['id'] for row in document['suite']['cases'] if row['split'] == 'train'}
    lessons = report['pending_lessons']
    if not isinstance(lessons, list) or len(lessons) > 3:
        raise ValueError('Optimizer lessons exceed their bound')
    for row in lessons:
        if (not isinstance(row, dict) or set(row) != {'lesson', 'evidence_case_ids'}
                or not isinstance(row['lesson'], str) or not 1 <= len(row['lesson']) <= 1000
                or not isinstance(row['evidence_case_ids'], list) or not row['evidence_case_ids']
                or not set(row['evidence_case_ids']) <= train):
            raise ValueError('Optimizer lesson is not grounded solely in training')
    # Scope to the newly accepted instruction, so lessons transfer to the next
    # case only while exactly those instructions/models/backend remain in force.
    following = {**document, 'articles': {**document['articles'], subject.ref:
        (CONFIG.vault_dir / subject.path).read_text()}}
    store.save('executive/experience', {'schema_version': 1, 'scope': scope(following),
        'case_id': marker['case_id'], 'report_id': marker['report_id'],
        'proposal_id': proposal_id, 'lessons': lessons})

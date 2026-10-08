"""Retain an explicitly requested note through the Agent's Hindsight bank."""
from __future__ import annotations


def execute(args: dict, context: dict) -> str:
    from ...knowledge.scope import execution_scope
    from ...knowledge.vault import resolver
    from ...knowledge.links import metadata_ref
    from ...memory.hindsight import MEMORY

    agent, allowed = execution_scope(context, resolver())
    if not context.get('run_id'):
        raise ValueError('Memory retention requires its originating execution')
    if not MEMORY.enabled:
        raise RuntimeError('Hindsight memory is not configured')
    refs = [metadata_ref(str(raw)) for raw in args.get('related_refs', [])]
    if any(ref not in allowed for ref in refs):
        raise PermissionError('Memory references must remain within the Agent\'s checked-out graph')
    created = MEMORY.enqueue(agent.ref, args['text'], source='observation',
                             identifier=context['run_id'], related_refs=refs)
    return ('Observation queued for Hindsight retention.' if created else
            'This exact observation has already been queued for Hindsight retention.')

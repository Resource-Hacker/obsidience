"""Run one controller-bound native Executive optimization inside Heimdall Audit."""
import json


async def execute(args: dict, context: dict) -> str:
    from ...execution.optimization import AUDITOR, optimize
    if set(args) != {'case_id'} or not isinstance(args['case_id'], str):
        return json.dumps({'error': 'Use the exact bound case_id only'})
    if context.get('_harness_optimization_attempted'):
        return json.dumps({'error': 'This Audit already attempted optimization; report its outcome and finish'})
    bound = (context.get('params') or {}).get('optimization_case')
    if (context.get('task') == AUDITOR and context.get('run_id')
            and isinstance(bound, str) and args['case_id'] != bound):
        # An argument typo has not entered the optimizer or spent its attempt.
        # The exact binding remains independently checked by optimize().
        return json.dumps({'error': 'Use the exact bound case_id; optimization was not dispatched',
                           'case_id': args['case_id'], 'bound_case_id': bound})
    context['_harness_optimization_attempted'] = True
    try:
        result = await optimize(args['case_id'], context)
    except (ValueError, OSError, KeyError, RuntimeError) as exc:
        result = {'error': str(exc), 'case_id': args['case_id']}
    return json.dumps(result, sort_keys=True)

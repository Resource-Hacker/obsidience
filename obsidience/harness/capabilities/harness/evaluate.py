"""Evaluate one bound Runbook proposal using frozen Tool fixtures."""

import json


async def execute(args: dict, context: dict) -> str:
    from obsidience.harness.execution.refinement import evaluate_proposal

    if set(args) != {"proposal"} or not isinstance(args["proposal"], str):
        return json.dumps({"error": "Use the exact bound proposal filename"})
    try:
        result = await evaluate_proposal(args["proposal"], context)
    except (ValueError, OSError, KeyError) as exc:
        return json.dumps({"error": str(exc)})
    context["_harness_evaluation"] = result
    return json.dumps(result, sort_keys=True)

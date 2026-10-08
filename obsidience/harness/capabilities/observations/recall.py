"""Recall historical memory from the executing Agent's Hindsight bank."""
import json


async def execute(args: dict, context: dict) -> str:
    from obsidience.harness.knowledge.scope import execution_scope
    from obsidience.harness.knowledge.vault import resolver
    from obsidience.harness.memory.hindsight import MEMORY
    from obsidience.harness.execution import activity

    agent, _allowed = execution_scope(context, resolver())
    result = await MEMORY.recall(agent.ref, args["query"], timeout=6, budget="mid")
    refs = [row["ref"] for row in result.get("memories", [])]
    if refs:
        activity.emit_operation("read", "returned", refs, label="Hindsight recall",
                                run_id=str(context.get("run_id", "")))
    return json.dumps(result, ensure_ascii=False)

"""Adapter for ``source.handoff``."""

from __future__ import annotations


def execute(args: dict, context: dict) -> str:
    """Write one cited Darwin finding to the physical Source Inbox."""
    from obsidience.harness.knowledge.source import SourceError, handoff_source

    if str(context.get("agent", "")) != "Darwin" or not str(
        context.get("task", "")
    ).startswith("Tasks/research/"):
        return "Source handoff rejected: only Darwin Research Tasks may write the Inbox."
    try:
        from .read import bound_read_error, required_source

        if error := bound_read_error(context):
            raise SourceError(error)
        if not isinstance(args, dict) or set(args) != {"title", "content"}:
            raise SourceError("handoff requires exactly title and content")
        if not isinstance(args.get("title"), str) or not args["title"].strip():
            raise SourceError("handoff title must be nonempty text")
        content = args["content"]
        if not isinstance(content, str):
            raise SourceError("handoff content must be text")
        if bound := required_source(context):
            from obsidience.harness.knowledge.source import validate_source_citations

            citations = validate_source_citations(content, required=True)
            if not any(item["citation"] == bound["citation"]
                       and item["content_sha256"] == bound["content_sha256"] for item in citations):
                raise SourceError("handoff must cite its exact activating Source: " + bound["citation"])
        result = handoff_source(
            title=args["title"],
            content=content,
            research_task=str(context.get("task", "")) if context.get("run_id") else "",
            research_run_id=str(context.get("run_id", "")),
            **({"feed_source_id": context["params"]["source_id"]}
               if context.get("task") == "Tasks/research/distill" else {}),
        )
    except SourceError as exc:
        return f"Source handoff rejected: {exc}"
    context["handoff_source_id"] = result["id"]
    event = result.get("source_event")
    count = len(event.get("occurrences") or []) if isinstance(event, dict) else 0
    return (
        f"Research {'dropped' if result['created'] else 'already present'} at "
        f"obsidience/evidence/{result['path']} as {result['citation']} "
        f"({result['content_sha256']}). "
        f"source.inbox activated {count} Ingest Task{'s' if count != 1 else ''}."
    )

"""Adapter for ``source.read``."""

from __future__ import annotations

import json
import re
import uuid

MAX_RECEIPTS = 256


def required_source(context: dict) -> dict | None:
    """Resolve only the admitted Learn event, never model-supplied arguments."""
    from obsidience.harness.knowledge.source import SourceError, feed_binding_matches, feed_source_binding, research_source_binding

    if context.get("task") not in {"Tasks/research/learn", "Tasks/research/distill"}:
        return None
    params = context.get("params") if isinstance(context.get("params"), dict) else {}
    if context.get("task") == "Tasks/research/distill":
        feed = feed_source_binding(str(params.get("source_id", "")))
        if (params.get("event") != "source.added" or feed is None
                or not feed_binding_matches(params.get("feed_binding"), feed)):
            raise SourceError("Distill requires its exact controller-bound Feed item")
    return research_source_binding({**params, "event": context.get("event") or params.get("event")})


def bound_read_error(context: dict) -> str | None:
    """Check the existing execution-local, hash-attested complete-read receipt."""
    from obsidience.harness.knowledge.source import SourceError

    try:
        bound = required_source(context)
    except SourceError as exc:
        return str(exc)
    if bound is None:
        return None
    receipt = context.get("_source_reads", {}).get(bound["citation"], {})
    length = receipt.get("total_characters")
    if (receipt.get("citation") == bound["citation"]
            and receipt.get("content_sha256") == bound["content_sha256"]
            and type(length) is int and length > 0
            and any(isinstance(part, list) and len(part) == 2
                    and all(type(position) is int for position in part)
                    and part == [0, length] for part in receipt.get("ranges", []))):
        return None
    return (
        f"Read the complete activating Source first with source.read: {bound['citation']}. "
        "Continue at Next offset until End of Source; external references are evidence metadata, "
        "not substitutes for these exact bytes."
    )


def precondition_error(name: str, args: dict, context: dict) -> str | None:
    """Enforce Learn's first Runbook step before any independent work dispatch."""
    if name == "task.complete" and args.get("status") == "failed":
        return None
    error = bound_read_error(context)
    if error is None:
        if context.get("task") == "Tasks/research/distill" and name == "web.fetch":
            url = context["params"]["feed_binding"]["reporting_url"]
            values = args.get("urls") if "urls" in args else [args.get("url")]
            if not url or values != [url]:
                return "Distill may fetch only the exact reporting_url bound to this Feed item."
        return None
    if name == "source.read":
        from obsidience.harness.knowledge.source import SourceError

        try:
            bound = required_source(context)
        except SourceError:
            return error
        values = args.get("sources") if "sources" in args else [args.get("source")]
        if (isinstance(values, list) and len(values) == 1
                and isinstance(values[0], str)
                and values[0] in {bound["citation"], bound["citation"][9:]}):
            return None
    return error


def available_tools(allowed: list[str], context: dict) -> list[str]:
    """Project the same Source prerequisite into the next model decision."""
    if bound_read_error(context) is None:
        return allowed
    return [name for name in allowed if name in {"source.read", "task.complete"}]


def _forget(context: dict, value: str) -> None:
    """Failed aliases cannot leave a canonical successful-read receipt alive."""
    reads = context.get("_source_reads", {})
    reads.pop(value, None)
    try:
        source_id = uuid.UUID(value.strip().removeprefix("source://").rsplit("/", 1)[-1])
    except ValueError:
        return
    reads.pop("source://" + str(source_id), None)


def execute(args: dict, context: dict) -> str:
    args = args or {}
    if error := precondition_error("source.read", args, context):
        return "Source read rejected: " + error
    batch = "sources" in args
    if batch and "source" in args:
        return "Invalid arguments: use source or sources, never both."
    values = args.get("sources") if batch else [args.get("source", "")]
    if (not isinstance(values, list) or not 1 <= len(values) <= 10
            or any(not isinstance(value, str) or not value.strip() or len(value) > 128
                   or any(ord(ch) < 32 or 127 <= ord(ch) <= 159 for ch in value) for value in values)):
        return "Invalid sources: use one source or 1-10 nonempty Source references, each at most 128 characters without controls."
    # Validate the entire batch before get_source, which may restore missing
    # immutable material through the existing Source owner.
    if batch:
        try:
            citations = ["source://" + str(uuid.UUID(value.strip().removeprefix("source://")))
                         for value in values]
        except ValueError:
            return "Invalid sources: use an exact UUID or source://UUID for every Source reference."
        if len(set(citations)) != len(citations):
            return "Invalid sources: duplicate Source citations are not allowed."
        values = citations
    offset = args.get("offset", 0)
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        return "Invalid offset: use a nonnegative character offset."
    limit = args.get("limit", 6000 if batch else 12000)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 12000:
        return "Invalid limit: use an integer from 1 to 12000 characters."
    if batch and limit * len(values) > 60000:
        return "Invalid limit: batch Source pages may total at most 60000 characters."
    results = []
    for value in values:
        cancel = context.get("_capability_cancel_event")
        if cancel is not None and cancel.is_set():
            _forget(context, value)
            ok, output = False, "Source read cancelled."
        else:
            ok, output = _read(value, offset, limit, context)
        if not batch:
            return output
        results.append({"source": value, "ok": ok, "result": output})
    return json.dumps({"results": results}, ensure_ascii=False)


def _private_source_allowed(result: dict, context: dict) -> bool:
    """Raw evidence cannot be a back door into another Agent's Observations."""
    from obsidience.harness.config import CONFIG
    from obsidience.harness.knowledge.scope import execution_scope
    from obsidience.harness.knowledge.vault import resolver
    from pathlib import Path
    from urllib.parse import unquote, urlsplit
    try:
        agent, allowed = execution_scope(context, resolver())
    except PermissionError:
        return False
    origin = str(result.get("source_ref", ""))
    if origin.startswith("obsidience://observations/temporary/"):
        receipt = context.get("_observation_archive", {})
        if (isinstance(receipt, dict) and receipt.get("citation") == result.get("citation")
                and receipt.get("content_sha256") == result.get("content_sha256")):
            return True  # This execution received these exact bytes as an explicit handoff.
        refs = re.findall(r"^## \[\[([^]\n]+)\]\]$", str(result.get("content", "")), re.M)
        return bool(refs) and all(ref.startswith(agent.ref.rsplit("/", 1)[0] + "/") for ref in refs)
    parsed = urlsplit(origin)
    path = None
    if parsed.scheme == "file":
        path = Path(unquote(parsed.path))
    elif not parsed.scheme and origin:
        path = Path(unquote(origin))
        if not path.is_absolute():
            path = CONFIG.project_root / path
    if path is not None:
        # Normalize traversal and symlinks before classifying a Knowledge file.
        path = path.resolve()
        vault_root = CONFIG.vault_dir.resolve()
        if path.is_relative_to(vault_root):
            return path.relative_to(vault_root).with_suffix("").as_posix() in allowed

    return True


def _read(value: str, offset: int, limit: int, context: dict) -> tuple[bool, str]:
    from obsidience.harness.knowledge.source import SourceError, get_source

    try:
        result = get_source(value)
    except (SourceError, OSError) as exc:
        _forget(context, value)
        return False, f"Source unavailable: {exc}"
    cancel = context.get("_capability_cancel_event")
    if cancel is not None and cancel.is_set():
        _forget(context, result["citation"])
        return False, "Source read cancelled."
    if not _private_source_allowed(result, context):
        _forget(context, result["citation"])
        return False, "Source is outside the Agent's permitted evidence scope."
    content = result["content"]
    end = min(offset + limit, len(content))
    if offset > len(content):
        _forget(context, result["citation"])
        return False, f"Invalid offset: Source has {len(content)} characters."
    reads = context.setdefault("_source_reads", {})
    previous = reads.get(result["citation"], {})
    ranges = previous.get("ranges", []) if previous.get("content_sha256") == result["content_sha256"] else []
    merged = []
    for start, stop in sorted([*ranges, [offset, end]]):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(stop, merged[-1][1])
        else:
            merged.append([start, stop])
    if result["citation"] not in reads and len(reads) >= MAX_RECEIPTS:
        del reads[next(iter(reads))]
    reads[result["citation"]] = {
        "citation": result["citation"], "content_sha256": result["content_sha256"],
        "ranges": merged[-MAX_RECEIPTS:], "total_characters": len(content),
    }
    reference = result["source_ref"] or "(none)"
    if any(ord(ch) < 32 or 127 <= ord(ch) <= 159 or ch in "\u2028\u2029" for ch in reference):
        # Reference is arbitrary evidence metadata. Keep it on one physical
        # header line so it cannot impersonate a pageable content envelope.
        reference = json.dumps(reference, ensure_ascii=True)
    continuation = f"Next offset: {end}" if end < len(content) else "End of Source."
    return True, (
        f"{result['citation']} · {result['source_type']} · {result['captured_at']}\n"
        f"Reference: {reference}\n"
        f"SHA-256: {result['content_sha256']}\n\n"
        f"Characters {offset}-{end} of {len(content)}. {continuation}\n\n"
        f"{content[offset:end]}"
    )

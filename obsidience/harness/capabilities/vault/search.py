"""Adapter for ``vault.search``."""

from __future__ import annotations

import json
import sqlite3
from copy import deepcopy

MAX_RECEIPTS = 256


def execute(args: dict, context: dict) -> str:
    from obsidience.harness.knowledge.retrieval import normalize_search_scope, search
    from obsidience.harness.knowledge.vault import iter_notes, Resolver
    from obsidience.harness.knowledge.scope import execution_scope

    args = args or {}
    batch = "queries" in args
    if batch and "query" in args:
        return "Invalid arguments: use query or queries, never both."
    queries = args.get("queries") if batch else [args.get("query", "")]
    if (not isinstance(queries, list) or not 1 <= len(queries) <= 10
            or any(not isinstance(query, str) or not query.strip() or len(query) > 300 for query in queries)):
        return "Invalid queries: use one query or 1-10 queries, each 1-300 characters of nonempty text."
    if batch and len(set(queries)) != len(queries):
        return "Invalid queries: duplicate queries are not allowed."
    scope = None
    if "scope" in args:
        try:
            scope = normalize_search_scope(args["scope"])
        except ValueError as exc:
            for query in queries:
                context.get("_vault_searches", {}).pop(query, None)
            return f"Invalid search scope: {exc}."
    cancel = context.get("_capability_cancel_event")
    if cancel is not None and cancel.is_set():
        for query in queries:
            context.get("_vault_searches", {}).pop(query, None)
        return (json.dumps({"results": [{"query": query, "ok": False, "result": "Search cancelled."}
                                        for query in queries]}) if batch else "Search cancelled.")
    snapshot = iter_notes()
    try:
        _agent, allowed = execution_scope(context, Resolver(snapshot))
    except PermissionError as exc:
        return str(exc)
    context["_last_context_refs"] = []
    results = []
    for query in queries:
        cancel = context.get("_capability_cancel_event")
        ok = False
        try:
            if cancel is not None and cancel.is_set():
                output = "Search cancelled."
            else:
                hits = search(query, scope=scope, snapshot=snapshot, allowed_refs=allowed)
                hits = hits[:5 if batch else 10]
                if cancel is not None and cancel.is_set():
                    output = "Search cancelled."
                else:
                    output = "\n".join(
                        f"- [[{hit['ref']}]] ({hit['kind']}) — {hit['snippet'][:160]}" for hit in hits
                    ) if hits else "No results."
                    receipts = context.setdefault("_vault_searches", {})
                    if query not in receipts and len(receipts) >= MAX_RECEIPTS:
                        del receipts[next(iter(receipts))]
                    receipts[query] = {"refs": [hit["ref"] for hit in hits]}
                    context["_last_context_refs"].extend(hit["ref"] for hit in hits)
                    if scope is not None:
                        receipts[query]["scope"] = deepcopy(scope)
                    ok = True
        except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
            if not batch:
                raise
            output = f"Search unavailable: {str(exc)[:400]}"
        if not ok:
            context.get("_vault_searches", {}).pop(query, None)
        if not batch:
            return output
        results.append({"query": query, "ok": ok, "result": output})
    return json.dumps({"results": results}, ensure_ascii=False)

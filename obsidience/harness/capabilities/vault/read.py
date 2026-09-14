"""Adapter for ``vault.read``."""

from __future__ import annotations

import hashlib
import json
import re

PAGE_CHARACTERS = 8000
MAX_RECEIPTS = 256
ARTICLE_BODY_END = "--- End of Article body ---"
INBOUND_REFERENCES_HEADING = "## Accepted inbound references"


def execute(args: dict, context: dict) -> str:
    from obsidience.harness.knowledge.vault import (
        SYSTEM_DIRS, Resolver, _NOTE_WRITE_LOCK, iter_notes, load_note,
    )

    args = args or {}
    batch = "refs" in args
    if batch and "ref" in args:
        return "Invalid arguments: use ref or refs, never both."
    refs = args.get("refs") if batch else [args.get("ref", "")]
    if (not isinstance(refs, list) or not 1 <= len(refs) <= 10
            or any(not isinstance(ref, str) or not ref.strip() or len(ref) > 500
                   or any(ord(ch) < 32 or 127 <= ord(ch) <= 159 for ch in ref) for ref in refs)):
        return "Invalid refs: use one ref or 1-10 nonempty Article refs, each at most 500 characters without controls."
    refs = [ref.strip() for ref in refs]
    offset = args.get("offset", 0)
    expected = args.get("expected_sha256")
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        return "Invalid offset: use a nonnegative character offset from a returned Article page."
    if expected is not None and (
        not isinstance(expected, str) or re.fullmatch(r"[0-9a-f]{64}", expected) is None
    ):
        return "Invalid expected_sha256: use the exact view_sha256 from a returned Article page."
    if offset and expected is None:
        return "A continuation page requires expected_sha256 from the preceding Article view."
    cancel = context.get("_capability_cancel_event")
    if cancel is not None and cancel.is_set():
        if batch:
            return json.dumps({"results": [{"ref": ref, "ok": False, "result": "Article read cancelled."}
                                          for ref in refs]}, ensure_ascii=False)
        return "Article read cancelled."
    # One current snapshot and backlink traversal serve every requested page.
    # The existing owner lock prevents a group publication splitting this view.
    with _NOTE_WRITE_LOCK:
        from obsidience.harness.knowledge.scope import execution_scope
        notes = iter_notes()
        try:
            _agent, allowed = execution_scope(context, Resolver(notes))
        except PermissionError as exc:
            return str(exc)
        notes = [note for note in notes if note.ref in allowed]
        res = Resolver(notes)
        selected = [res.resolve(ref) for ref in refs]
        identities = [note.ref if note else ref for ref, note in zip(refs, selected)]
        if batch and len(set(identities)) != len(identities):
            return "Invalid refs: duplicate Article refs are not allowed."
        inbound = {note.ref: set() for note in selected if note}
        for candidate in notes:
            if candidate.ref.split("/", 1)[0] in SYSTEM_DIRS:
                continue
            for raw in candidate.links:
                target = res.resolve(raw)
                if target and target.ref in inbound and target.ref != candidate.ref:
                    inbound[target.ref].add(candidate.ref)
        context["_last_context_refs"] = []
        results = []
        for ref, note in zip(refs, selected):
            if cancel is not None and cancel.is_set():
                ok, output = False, "Article read cancelled."
            elif note:
                ok, output = _read(note, sorted(inbound[note.ref]), offset, expected, context)
            else:
                context.get("_article_reads", {}).pop(ref.removesuffix(".md"), None)
                ok, output = False, f"Note not found: {ref}"
            if not batch:
                return output
            results.append({"ref": note.ref if note else ref, "ok": ok, "result": output})
    return json.dumps({"results": results}, ensure_ascii=False)


def _read(note, inbound: list[str], offset: int, expected: str | None, context: dict) -> tuple[bool, str]:
    from obsidience.harness.knowledge.format import lifecycle_metadata

    graph_context = (
        f"\n\n{ARTICLE_BODY_END}\n\n{INBOUND_REFERENCES_HEADING}\n"
        "Generated read-only graph context, not Article content. These Articles link TO this "
        "Article; this list does not establish outgoing relationships. Never copy this section "
        "or the end marker into a proposed body.\n"
        + (
            "\n".join(f"- [[{item}]]" for item in inbound[:24])
            if inbound
            else "None."
        )
        + (f"\nShowing the first 24 of {len(inbound)} inbound references." if len(inbound) > 24 else "")
    )
    lifecycle = lifecycle_metadata(note.meta)
    lifecycle_context = (
        "Article lifecycle (document metadata, not Task execution or verification):\n"
        + json.dumps(lifecycle, ensure_ascii=False, sort_keys=True) + "\n\n"
    )
    article = note.text()
    view = lifecycle_context + article + graph_context
    # The revision covers the complete Article and backlink snapshot, including
    # backlinks outside its bounded presentation. A changed view is never
    # silently substituted for the evidence used by an earlier action.
    revision = hashlib.sha256(json.dumps(
        {"view": view, "inbound": inbound}, ensure_ascii=False,
        sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    if expected is not None and expected != revision:
        context.get("_article_reads", {}).pop(note.ref, None)
        return False, (
            "Article view changed: the Article, its lifecycle or inbound references no longer match "
            "expected_sha256. No replacement content was returned. Read offset 0 without "
            "expected_sha256 to explicitly obtain the current view; do not treat it as the old evidence."
        )
    if offset > len(view):
        context.get("_article_reads", {}).pop(note.ref, None)
        return False, f"Invalid offset: the attested Article view has {len(view)} characters."
    end = min(offset + PAGE_CHARACTERS, len(view))
    reads = context.setdefault("_article_reads", {})
    previous = reads.get(note.ref, {})
    ranges = previous.get("ranges", []) if previous.get("view_sha256") == revision else []
    merged = []
    for start, stop in sorted([*ranges, [offset, end]]):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(stop, merged[-1][1])
        else:
            merged.append([start, stop])
    if note.ref not in reads and len(reads) >= MAX_RECEIPTS:
        del reads[next(iter(reads))]
    reads[note.ref] = {
        "article_sha256": hashlib.sha256(article.encode("utf-8")).hexdigest(),
        "view_sha256": revision, "ranges": merged[-MAX_RECEIPTS:], "total_characters": len(view),
        "complete": merged == [[0, len(view)]],
    }
    context.setdefault("_last_context_refs", []).append(note.ref)
    state = "End of Article view." if end == len(view) else f"Continue at offset {end} with the same expected_sha256."
    identity = json.dumps({"ref": note.ref, "view_sha256": revision}, ensure_ascii=False, sort_keys=True)
    return True, f"Article: {identity}\nCharacters {offset}-{end} of {len(view)}. {state}\n\n{view[offset:end]}"

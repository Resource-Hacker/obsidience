"""obsidience CLI: serve / status / index / search / tasks / run / review / chat."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys


def main() -> None:
    ap = argparse.ArgumentParser(prog="obsidience", description="The vault is the harness.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve", help="run the daemon (API + scheduler)")
    sub.add_parser("status", help="vault + harness status")
    sub.add_parser("index", help="sync the search index")
    p = sub.add_parser("search", help="hybrid search"); p.add_argument("query", nargs="+")
    sub.add_parser("tasks", help="list tasks")
    p = sub.add_parser("run", help="run one task now"); p.add_argument("ref")
    p = sub.add_parser("review", help="list/approve/reject proposals")
    p.add_argument("action", nargs="?", choices=["list", "approve", "reject"], default="list")
    p.add_argument("name", nargs="?")
    p.add_argument("--reason", default="")
    args = ap.parse_args()

    if args.cmd == "serve":
        from .server import main as serve
        serve(); return

    if args.cmd == "status":
        from . import voice
        from .review import list_proposals
        from .vault import iter_notes
        notes = iter_notes()
        tasks = [n for n in notes if n.kind == "task"]
        print(f"notes: {len(notes)}  tasks: {len(tasks)}  proposals: {len(list_proposals())}")
        for t in tasks:
            print(f"  [{t.meta.get('status', 'draft'):>7}] {t.ref}"
                  + (f"  ⏰ {t.meta.get('schedule')}" if t.meta.get("schedule") else "")
                  + (f"  ⛔ {t.meta.get('blocked_reason')}" if t.meta.get("blocked_reason") else ""))
        print("voice:", voice.available()); return

    if args.cmd == "index":
        from .indexer import INDEX
        print(json.dumps(INDEX.sync())); return

    if args.cmd == "search":
        from .indexer import INDEX
        from .retrieval import search
        INDEX.sync()
        for hit in search(" ".join(args.query)):
            print(f"[[{hit['ref']}]] ({hit['kind']}) — {hit['snippet'][:100]}")
        return

    if args.cmd == "tasks":
        from .vault import iter_notes
        for n in iter_notes():
            if n.kind == "task":
                print(f"[{n.meta.get('status', 'draft'):>7}] {n.ref}  runbook={n.meta.get('runbook')}")
        return

    if args.cmd == "run":
        from .executor import run_task
        from .indexer import INDEX
        from .vault import load_note, resolver
        INDEX.sync()
        note = load_note(args.ref + ".md") or resolver().resolve(args.ref)
        if not note:
            sys.exit(f"task not found: {args.ref}")
        result = asyncio.run(run_task(note))
        print(json.dumps(result, indent=2)); return

    if args.cmd == "review":
        from .review import approve, list_proposals, reject
        if args.action == "list":
            props = list_proposals()
            if not props:
                print("no pending proposals")
            for p in props:
                print(f"• {p['file']}\n    {p['action']} → {p['target']}  (by {p['agent']})"
                      f"\n    reason: {p['reason'][:120]}")
        elif args.action == "approve":
            print(json.dumps(approve(args.name)))
        else:
            print(json.dumps(reject(args.name, args.reason)))
        return


if __name__ == "__main__":
    main()

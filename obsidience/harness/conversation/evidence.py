"""Bounded historical execution records, never current state or action authority.

Read the existing conversation/run ledger. Execution records exclude public
summaries and model-authored evidence. Accepted failure/review replies are
projected separately as exact historical dialogue, never execution receipts.
"""

from __future__ import annotations

import json
import math
import re
import time

from ..computer.applications import canonical_application_id

MAX_RECORDS = 4
MAX_TOOLS = 8
MAX_TRACE_BYTES = 512_000
MAX_TRACE_ENTRIES = 512
MAX_PUBLIC_REPLIES = 32
MAX_PUBLIC_REPLY_CHARS = 2_000
_EFFECT_TOOLS = {"application.launch", "computer.act", "window.activate", "window.place"}
_COMPUTER_TOOLS = _EFFECT_TOOLS | {"computer.observe"}
_OPAQUE_ID = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
_TOOL_NAME = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*){1,3}\Z")
_TASK_REF = re.compile(r"Tasks/[A-Za-z0-9][A-Za-z0-9_ /.-]{0,150}\Z")
_STATUSES = {"completed", "failed", "interrupted", "waiting", "pending", "blocked", "running"}


def historical_steered_turns(conversation, *, conversation_id: str, before_sequence: int | None = None) -> set[str]:
    """Applied clarification IDs from exact completed runs, not assistant prose."""
    turns = conversation.index.conversation_turns(conversation_id)
    if before_sequence is not None:
        turns = [turn for turn in turns if turn["sequence"] < before_sequence]
    replies = {turn["run_id"]: turn for turn in turns
               if turn["role"] == "assistant" and turn.get("run_id") and turn["state"] == "final"}
    users = [turn for turn in turns if turn["role"] == "user" and turn.get("run_id") in replies][-64:]
    applied = set()
    for run_id in {turn["run_id"] for turn in users}:
        with conversation.index.lock:
            row = conversation.index.db.execute("SELECT trace FROM runs WHERE id=? AND status='completed'", (run_id,)).fetchone()
        if not row or not isinstance(row[0], str) or len(row[0]) > MAX_TRACE_BYTES:
            continue
        entries = _trace(row[0])
        if not entries:
            continue
        packet = entries[0]
        if not isinstance(packet, dict) or not isinstance(packet.get("steering_turn_ids"), list):
            continue
        admitted = packet.get("interactive_turn", {})
        if (not isinstance(admitted, dict) or admitted.get("conversation_id") != conversation_id
                or admitted.get("reply_to_turn_id") != replies[run_id].get("reply_to")):
            continue
        applied.update(turn["id"] for turn in users if turn["run_id"] == run_id
                       and turn["id"] in packet["steering_turn_ids"][:8]
                       and turn["sequence"] < replies[run_id]["sequence"])
    return applied


def _target(value: object) -> dict | None:
    if not isinstance(value, dict):
        return None
    kind, name = value.get("kind"), value.get("name")
    if kind == "application" and isinstance(name, str):
        canonical = canonical_application_id(name)
        return {"kind": kind, "name": canonical} if canonical else None
    if kind == "pane" and isinstance(name, str) and re.fullmatch(r"[a-z][a-z0-9_-]{0,47}", name):
        return {"kind": kind, "name": name}
    return None


def _tool_record(entry: dict) -> dict | None:
    name = entry.get("tool")
    if not isinstance(name, str) or len(name) > 64 or not _TOOL_NAME.fullmatch(name):
        return None
    record = {"tool": name}
    if name not in _COMPUTER_TOOLS:
        return record
    record["verified"] = False
    witness, args = entry.get("completion_evidence"), entry.get("args")
    if not isinstance(witness, dict) or not isinstance(args, dict):
        return record
    actual = _target(witness.get("target"))
    requested = (
        _target({"kind": "application", "name": args.get("application")})
        if name in {"application.launch", "computer.act"}
        else _target(args.get("target"))
    )
    focused = (
        name == "computer.observe" and isinstance(args.get("target"), dict)
        and args["target"].get("kind") == "focused" and "name" not in args["target"]
    )
    if name == "application.launch" and actual is not None and requested == actual:
        # A failed launch remains historical evidence without becoming readiness
        # or authority to repeat the operation.
        outcome = witness.get("launch_outcome")
        if outcome in {"terminated_before_ready", "timeout", "launcher_timeout"}:
            record.update(target=actual, launch_outcome=outcome)
    if (
        witness.get("verified") is not True or actual is None
        or (requested != actual and not focused)
        or entry.get("interrupted") is True or witness.get("stale") is True
    ):
        return record
    if name == "computer.act":
        effect = witness.get("effect")
        if (
            witness.get("verified_scope") != "click"
            or witness.get("semantic_postcondition_verified") is not False
            or not isinstance(effect, dict) or effect.get("kind") != "click"
            or not isinstance(effect.get("label"), str) or not effect["label"]
            or len(effect["label"]) > 160
        ):
            return record
        record.update({
            "delivery": "acknowledged", "verified_scope": "click",
            "semantic_postcondition_verified": False,
        })
    else:
        record["verified_scope"] = {
            "computer.observe": "observation", "window.activate": "focus",
            "window.place": "placement", "application.launch": "application_ready",
        }[name]
    record.update({"verified": True, "target": actual})
    return record


def _trace(value: object) -> list[dict] | None:
    if not isinstance(value, str) or len(value.encode("utf-8")) > MAX_TRACE_BYTES:
        return None
    try:
        entries = json.loads(value)
    except (ValueError, RecursionError):
        return None
    if (
        not isinstance(entries, list) or len(entries) > MAX_TRACE_ENTRIES
        or not all(isinstance(entry, dict) for entry in entries)
    ):
        return None
    return entries


def historical_evidence(
    conversation, *, conversation_id: str, before_sequence: int, limit: int = 4,
) -> list[dict]:
    """Project up to four exact prior replies' execution records, chronologically.

    ``effect_dispatched`` concerns computer input/launch/window effects only:
    false means no such Tool was recorded, true requires acknowledged click
    evidence, and null means dispatch cannot be established. A ready application
    may already have been open. Historical witnesses never authorize replay or
    establish the current screen, focus, geometry, or game state.
    """
    if type(before_sequence) is not int or type(limit) is not int or limit <= 0:
        return []
    with conversation.index.lock:
        pairs = conversation.complete_pairs(
            conversation_id=conversation_id, before_sequence=before_sequence,
        )
        failures = historical_public_replies(conversation, conversation_id=conversation_id,
                                            before_sequence=before_sequence)
        # These local descriptors join accepted failure runs; they are never
        # written as assistant conversation rows or labelled successful dialogue.
        for user in conversation.index.conversation_turns(conversation_id):
            failed = failures.get(user["id"])
            if failed is not None and failed["status"] == "failed":
                pairs.append((user, {"conversation_id": conversation_id, "role": "assistant",
                                    "state": "failed", "reply_to": user["id"], "run_id": failed["run_id"]}))
        pairs = sorted(pairs, key=lambda pair: pair[0]["sequence"])[-min(limit, MAX_RECORDS):]
        records = []
        for user, assistant in pairs:
            run_id = assistant.get("run_id")
            if (
                user.get("conversation_id") != conversation_id
                or assistant.get("conversation_id") != conversation_id
                or user.get("role") != "user" or assistant.get("role") != "assistant"
                or user.get("state") != "final" or assistant.get("state") not in {"final", "failed"}
                or assistant.get("reply_to") != user.get("id")
                or not isinstance(run_id, str) or not _OPAQUE_ID.fullmatch(run_id)
            ):
                continue
            run = conversation.index.run(run_id)
            if not isinstance(run, dict) or run.get("id") != run_id:
                continue
            task_ref = run.get("task_ref")
            if (
                not isinstance(task_ref, str) or not _TASK_REF.fullmatch(task_ref)
                or any(part in {".", "..", ""} for part in task_ref.split("/"))
                or run.get("status") not in _STATUSES
            ):
                continue
            entries = _trace(run.get("trace"))
            if entries is not None and any(
                not isinstance(entry["interactive_turn"], dict)
                or entry["interactive_turn"].get("conversation_id") != conversation_id
                or entry["interactive_turn"].get("reply_to_turn_id") != user.get("id")
                for entry in entries if "interactive_turn" in entry
            ):
                continue
            tools = []
            complete_trace = entries is not None
            for entry in entries or []:
                if "tool" not in entry:
                    continue
                tool = _tool_record(entry)
                if tool is None:
                    complete_trace = False
                else:
                    tools.append(tool)
            has_effect_tool = any(tool["tool"] in _EFFECT_TOOLS for tool in tools)
            acknowledged_click = any(tool.get("delivery") == "acknowledged" for tool in tools)
            records.append({
                "scope": "historical_execution", "current_state": False,
                "effect_scope": "computer", "run_id": run_id, "task_ref": task_ref,
                "status": run["status"], "evidence_available": complete_trace,
                "effect_dispatched": (
                    True if acknowledged_click else False
                    if complete_trace and not has_effect_tool else None
                ),
                "tools": tools[-MAX_TOOLS:],
                "omitted_tool_count": max(0, len(tools) - MAX_TOOLS),
            })
        return records


def historical_public_replies(
    conversation, *, conversation_id: str, before_sequence: int | None,
) -> dict[str, dict[str, str]]:
    """Recover exact accepted public failure/review replies for unanswered turns.

    These are historical dialogue, not successful execution evidence. Ordinary
    persisted replies take precedence. Ambiguous runs, reused run references,
    raw exceptions and unaccepted model output never become conversation text.
    """
    ledger = getattr(conversation, "index", None)
    if (
        ledger is None or not hasattr(ledger, "db")
        or (before_sequence is not None and type(before_sequence) is not int)
    ):
        return {}
    with ledger.lock:
        turns = ledger.conversation_turns(conversation_id)
        if before_sequence is None:
            cutoff = time.time()
        else:
            boundary = [turn for turn in turns
                        if turn.get("sequence") == before_sequence
                        and turn.get("conversation_id") == conversation_id
                        and turn.get("role") == "user" and turn.get("state") == "final"]
            if len(boundary) != 1:
                return {}
            cutoff = boundary[0].get("created_at")
        if type(cutoff) not in (int, float) or not math.isfinite(cutoff):
            return {}
        # A later continuation or reply must not rewrite what was available
        # when the originating request was admitted.
        turns = [turn for turn in turns if turn["created_at"] <= cutoff]
        replied = {turn.get("reply_to") for turn in turns
                   if turn.get("role") == "assistant" and turn.get("state") == "final"}
        unanswered = {
            turn["id"]: turn for turn in turns
            if turn.get("role") == "user" and turn.get("state") == "final"
            and turn.get("conversation_id") == conversation_id
            and turn["id"] not in replied
            and (before_sequence is None or turn["sequence"] < before_sequence)
        }
        unanswered = dict(list(unanswered.items())[-MAX_PUBLIC_REPLIES:])
        if not unanswered:
            return {}
        # The current conversation's actual user timestamps bound the read;
        # no global historical trace scan or derived persistent cache is needed.
        oldest = min(turn["created_at"] for turn in unanswered.values())
        rows = ledger.db.execute(
            "SELECT id,status,summary,trace FROM runs "
            "WHERE started>=? AND finished>=started AND finished<=? ORDER BY started",
            (oldest, cutoff),
        ).fetchall()
        candidates: dict[str, list[tuple]] = {}
        for run_id, status, summary, raw_trace in rows:
            entries = _trace(raw_trace)
            if entries is None:
                continue
            bindings = [entry["interactive_turn"] for entry in entries if "interactive_turn" in entry]
            if len(bindings) != 1 or not isinstance(bindings[0], dict):
                continue
            binding = bindings[0]
            turn_id = binding.get("reply_to_turn_id")
            if (
                binding.get("conversation_id") != conversation_id
                or not isinstance(turn_id, str) or turn_id not in unanswered
            ):
                continue
            candidates.setdefault(turn_id, []).append((run_id, status, summary, entries))
        replies = {}
        for turn_id, matched in candidates.items():
            if len(matched) != 1:
                continue
            run_id, status, summary, entries = matched[0]
            if status not in {"failed", "review"} or not isinstance(run_id, str) or not _OPAQUE_ID.fullmatch(run_id):
                continue
            if ledger.db.execute(
                "SELECT 1 FROM conversation_turns "
                "WHERE role='assistant' AND run_id=? AND created_at<=? LIMIT 1",
                (run_id, cutoff),
            ).fetchone():
                continue
            accepted = [entry.get("args") for entry in entries
                        if entry.get("tool") == "task.complete" and entry.get("accepted") is True]
            if len(accepted) != 1 or not isinstance(accepted[0], dict):
                continue
            completion = accepted[0]
            valid_statuses = {status, "completed"} if status == "review" else {status}
            text = completion.get("summary")
            if (
                not isinstance(completion.get("status"), str)
                or completion["status"] not in valid_statuses
                or not isinstance(text, str) or text != summary or not text.strip()
                or len(text) > MAX_PUBLIC_REPLY_CHARS
                or any(ord(char) < 32 and char not in "\n\t" for char in text)
            ):
                continue
            replies[turn_id] = {"run_id": run_id, "status": status, "text": text}
        return replies

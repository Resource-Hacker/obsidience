"""Bounded live Executive trace for Task actions."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import re
import time
import threading
import uuid
from collections import deque
from contextvars import ContextVar, Token

MAX_EVENT_CHARS = 65_536
MAX_PAYLOAD_CHARS = 49_152
MAX_SECTION_CHARS = 12_288
MAX_HISTORY_CHARS = 2_097_152
_HISTORY: deque[tuple[dict, int]] = deque()
_HISTORY_CHARS = 0
_SUBSCRIBERS: set[asyncio.Queue] = set()
_LEDGER = None
_LOOP: asyncio.AbstractEventLoop | None = None
_LOCK = threading.RLock()
_JOURNAL_AVAILABLE = True
_CONTEXT: ContextVar[dict] = ContextVar("public_action_trace", default={})
LATENCY_STAGES = frozenset({
    "input_final", "preparation", "selection", "activation", "model_wait",
    "model_preflight", "model_first_public", "model_complete", "answer_committed",
    "speech_received", "aec_ready", "first_pcm", "first_output_write",
    "speech_onset", "first_partial", "speech_final",
})
_PRIVATE_KEYS = {
    "point", "image", "image_url", "image_png", "pixels", "capture", "capture_token",
    "observation_lease", "scene_lease", "reasoning", "reasoning_content", "chain_of_thought", "analysis",
}
_SECRET_KEYS = {
    "password", "passwd", "secret", "token", "api_key", "apikey", "access_token",
    "refresh_token", "client_secret", "authorization", "cookie", "set_cookie",
    "credentials", "private_key",
}
_PAYLOAD_FIELDS = {
    "run": ("kind", "status", "task_title", "agent_title", "model", "reasoning_effort", "summary"),
    "tool": ("kind", "name", "phase", "status", "duration_ms", "arguments", "result"),
    "packet": ("kind", "refs", "retrieval_ms", "knowledge_accounting", "instruction_accounting", "sections"),
    "model": ("kind", "phase", "model", "model_label", "metrics", "error"),
    "context": ("kind", "projection"),
    "latency": ("kind", "stage", "monotonic_ms", "duration_ms", "turn_id",
                "run_id", "speech_sequence", "generation"),
}
_SECRET_TEXT = (
    re.compile(r"\b(?:sk|pk)-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{12,}", re.IGNORECASE),
    re.compile(r'''(?i)(\b(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|password|passwd|secret|credential|authorization|cookie|token)["']?\s*[:=]\s*)(?:"[^"\n]*"|'[^'\n]*'|[^\s,;]+)'''),
    re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://[^\s/:]+:[^\s/@]+@"),
    re.compile(r"data:image/[^;\s]+;base64,[A-Za-z0-9+/=]+", re.IGNORECASE),
    re.compile(r"-----BEGIN [^-]*PRIVATE KEY-----.*?(?:-----END [^-]*PRIVATE KEY-----|\Z)", re.DOTALL),
)


def bind(run_id: str, task_ref: str, agent_ref: str) -> Token:
    """Correlate events in this execution, including its joined Tool workers."""
    return _CONTEXT.set({**_CONTEXT.get(), "run_id": run_id, "task_ref": task_ref, "agent_ref": agent_ref})


def bind_trial(trial_id: str, *, case_id: str, split: str, variant: str, repetition: int) -> Token:
    """Label frozen evaluation inside its existing execution, never a new run."""
    if (not isinstance(trial_id, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", trial_id)
            or not isinstance(case_id, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", case_id)
            or _redact(trial_id) != trial_id or _redact(case_id) != case_id
            or not isinstance(split, str) or split not in {"train", "holdout"}
            or not isinstance(variant, str) or variant not in {"baseline", "candidate"}
            or type(repetition) is not int or not 1 <= repetition <= 3):
        raise ValueError("Invalid evaluation trace identity")
    return _CONTEXT.set({**_CONTEXT.get(), "trial": {
        "id": trial_id, "case_id": case_id, "split": split,
        "variant": variant, "repetition": repetition,
    }})


def bind_turn(turn_id: str, *, speech_sequence: int | None = None, generation: int | None = None) -> Token:
    """Carry exact conversation identity through existing executor/worker scopes."""
    context = {"turn_id": turn_id}
    for key, value in (("speech_sequence", speech_sequence), ("generation", generation)):
        if type(value) is int and value >= 0:
            context[key] = value
    return _CONTEXT.set(context)


def latency(stage: str, *, monotonic_ns: int | None = None,
            duration_ms: float | None = None, **correlation) -> None:
    """Bounded phase measurements, never execution authority or private content.

    Durations describe the named phase and may overlap. Timestamps order edges
    on this workstation's monotonic clock; public milliseconds retain useful
    precision even when nanoseconds exceed JavaScript's exact integer range.
    """
    stamp = time.monotonic_ns() if monotonic_ns is None else monotonic_ns
    if (not isinstance(stage, str) or stage not in LATENCY_STAGES
            or type(stamp) is not int or not 0 <= stamp < 2**63):
        return
    payload = {"kind": "latency", "stage": stage, "monotonic_ms": stamp / 1_000_000}
    if duration_ms is not None:
        if (type(duration_ms) not in (int, float) or not 0 <= duration_ms <= 86_400_000
                or not math.isfinite(duration_ms)):
            return
        payload["duration_ms"] = round(duration_ms, 3)
    identity = {**_CONTEXT.get(), **correlation}
    for key in ("turn_id", "run_id"):
        value = identity.get(key)
        if isinstance(value, str) and 0 < len(value) <= 128:
            payload[key] = value
    for key in ("speech_sequence", "generation"):
        value = identity.get(key)
        if type(value) is int and 0 <= value < 2**53:
            payload[key] = value
    metadata = {key: identity[key] for key in ("run_id", "task_ref", "agent_ref") if key in identity}
    metadata["payload"] = payload
    emit("measurement", "Latency: " + stage.replace("_", " "), [], metadata)


def reset(token: Token) -> None:
    _CONTEXT.reset(token)


def start(ledger) -> None:
    """Attach the public projection to the existing ledger and API event loop."""
    global _LEDGER, _LOOP, _HISTORY_CHARS, _JOURNAL_AVAILABLE
    _LEDGER, _LOOP = ledger, asyncio.get_running_loop()
    with _LOCK:
        _HISTORY.clear()
        _HISTORY.extend((entry, len(_encode(entry))) for entry in ledger.trace_history())
        _HISTORY_CHARS = sum(size for _, size in _HISTORY)
        _JOURNAL_AVAILABLE = True


def stop() -> None:
    global _LEDGER, _LOOP
    _LEDGER, _LOOP = None, None


def _encode(value: object) -> str:
    # ASCII encoding makes the character budget a UTF-8 byte budget too.
    return json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":"))


def _redact(text: str) -> str:
    for pattern in _SECRET_TEXT:
        text = pattern.sub(lambda match: match.group(1) + '"[REDACTED]"' if match.lastindex else "[REDACTED]", text)
    return text


def _clip_text(text: str, limit: int) -> str:
    text = text[:MAX_SECTION_CHARS]
    if len(_encode(text)) <= limit:
        return text
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if len(_encode(text[:middle])) <= limit:
            low = middle
        else:
            high = middle - 1
    return text[:low]


def public_value(value: object, limit: int = MAX_PAYLOAD_CHARS) -> tuple[object, bool]:
    """Bound a display copy; never serialize opaque objects or private fields."""
    remaining = limit
    truncated = False

    def project(item: object, depth: int = 0) -> object:
        nonlocal remaining, truncated
        if depth >= 8 or remaining < 32:
            truncated = True
            remaining -= 4
            return None
        if isinstance(item, str):
            # Tool adapters sometimes return their JSON envelope as text.
            if item.lstrip().startswith(("{", "[")):
                try:
                    decoded = json.loads(item)
                except (ValueError, RecursionError):
                    pass
                else:
                    return project(decoded, depth + 1)
            clean = _redact(item)
            text = _clip_text(clean, max(0, remaining - 2))
            truncated |= len(text) != len(clean)
            remaining -= len(_encode(text))
            return text
        if isinstance(item, dict):
            result = {}
            remaining -= 2
            for index, (key, child) in enumerate(item.items()):
                if index >= 64 or remaining < 64:
                    truncated = True
                    break
                if not isinstance(key, str):
                    continue
                normalized = key.lower().replace("-", "_")
                if normalized.startswith(("_", "private_")) or normalized in _PRIVATE_KEYS:
                    truncated = True
                    continue
                name = _redact(key)[:120]
                cost = len(_encode(name)) + 2
                if remaining < cost + 32:
                    truncated = True
                    break
                remaining -= cost
                result[name] = project("[REDACTED]" if normalized in _SECRET_KEYS else child, depth + 1)
            if isinstance(item.get("text"), str) and type(item.get("truncated")) is bool:
                result["truncated"] = item["truncated"] or result.get("text") != item["text"]
            return result
        if isinstance(item, (list, tuple)):
            result = []
            remaining -= 2
            for index, child in enumerate(item):
                if index >= 64 or remaining < 32:
                    truncated = True
                    break
                remaining -= 1
                # A long first page must not consume every later batch result.
                available = remaining
                quota = remaining // (min(len(item), 64) - index)
                remaining = quota
                result.append(project(child, depth + 1))
                remaining = available - (quota - remaining)
            return result
        if item is None or isinstance(item, (bool, int)) or isinstance(item, float) and math.isfinite(item):
            remaining -= len(_encode(item))
            return item
        # bytes, capture/lease objects and arbitrary reprs never enter the stream.
        truncated = True
        remaining -= 4
        return None

    result = project(value)
    return result, truncated


def packet_payload(sections: dict[str, str], refs: list[str], retrieval_ms: float, *,
                   knowledge_accounting: dict | None = None, instruction_accounting: list | None = None) -> dict:
    """Project compiler-owned sections, retaining identities when text is clipped."""
    projected = []
    remaining = MAX_PAYLOAD_CHARS - 4_096
    accounting = None
    if knowledge_accounting:
        accounting, clipped = public_value(knowledge_accounting, 16_384)
        if clipped:
            accounting["truncated"] = True
        remaining -= len(_encode(accounting)) + 128
    titles = {
        "header": "Thinking Packet", "identity": "Agent Identity", "task": "Task",
        "objective": "Objective", "tools": "Tools", "skills": "Skills", "runbook": "Runbook",
        "bindings": "Bindings", "knowledge": "Relevant Knowledge", "immediate": "Immediate Observations",
        "begin": "Execution instructions",
    }
    for key, original in sections.items():
        if not original:
            continue
        clean = original
        redacted_bindings = False
        if key == "bindings" and "\n" in original:
            heading, _, body = original.partition("\n")
            if body.startswith("{"):
                safe, redacted_bindings = public_value(body)
                clean = heading + "\n" + json.dumps(safe, sort_keys=True)
        clean = _redact(clean)
        limit = min(MAX_SECTION_CHARS, max(0, remaining))
        text = _clip_text(clean, limit)
        remaining -= len(_encode(text))
        projected.append({
            "key": key, "title": titles.get(key, key),
            "chars": len(original), "sha256": hashlib.sha256(original.encode()).hexdigest(),
            "truncated": redacted_bindings or len(text) != len(clean),
            "text": text,
        })
    return {"kind": "packet", "refs": refs, "retrieval_ms": retrieval_ms,
            **({"knowledge_accounting": accounting} if accounting is not None else {}),
            **({"instruction_accounting": public_value(instruction_accounting, 8192)[0]} if instruction_accounting else {}),
            "sections": projected}


def emit(channel: str, line: str, detail: list[str] | None = None, metadata: dict | None = None) -> None:
    global _HISTORY_CHARS
    if channel in {"reasoning", "analysis", "private"}:
        return
    metadata = metadata or {}
    trial = _CONTEXT.get().get("trial")
    if trial is not None:
        line = (f"Simulation · {trial['variant'].title()} · {trial['case_id']} · "
                f"repetition {trial['repetition']} · " + str(line).removeprefix("Simulation · "))
    payload = metadata.get("payload")
    safe_payload = None
    payload_clipped = False
    if isinstance(payload, dict) and payload.get("kind") in _PAYLOAD_FIELDS:
        fields = (*_PAYLOAD_FIELDS[payload["kind"]], "simulated")
        projected = {key: payload[key] for key in fields if key in payload and key != "simulated"}
        if trial is not None or payload.get("simulated") is True:
            projected["simulated"] = True
        safe_payload, payload_clipped = public_value(projected)
        payload_clipped |= bool(set(payload) - set(fields))
        payload_clipped |= any(
            part.get("truncated") is True for part in payload.get("sections", []) if isinstance(part, dict)
        )
        if isinstance(payload.get("knowledge_accounting"), dict):
            payload_clipped |= payload["knowledge_accounting"].get("truncated") is True
        if isinstance(safe_payload, dict) and safe_payload.get("kind") == "tool":
            field = "arguments" if safe_payload.get("phase") == "start" else "result"
            value = safe_payload.get(field)
            detail = (value if isinstance(value, str) else _encode(value)).splitlines()
    safe_details, details_clipped = public_value((detail or [])[:12], 7_168)
    entry = {
        "id": uuid.uuid4().hex,
        "at": int(time.time() * 1000),
        "channel": str(channel)[:24],
        "line": _redact(str(line)).replace("\n", " ")[:300],
        "detail": [(item if isinstance(item, str) else _encode(item))[:500] for item in safe_details[:12]],
        "truncated": bool(metadata.get("truncated")) or payload_clipped,
    }
    for key in ("run_id", "task_ref", "agent_ref", "call_id"):
        value = metadata.get(key, _CONTEXT.get().get(key))
        if isinstance(value, str) and value:
            entry[key] = _redact(value)[:256]
    if type(metadata.get("step")) is int and metadata["step"] >= 0:
        entry["step"] = metadata["step"]
    if trial is not None:
        entry["trial"] = dict(trial)
        # These are public display correlations only. Durable Tool receipts
        # continue to belong exclusively to the outer executor context.
        if ("call_id" not in entry and entry.get("step", 0) > 0
                and isinstance(safe_payload, dict) and safe_payload.get("kind") in {"tool", "model"}):
            entry["call_id"] = f"{trial['id']}:{safe_payload['kind']}:{entry['step']}"
    if safe_payload is not None:
        entry["payload"] = safe_payload
    else:
        entry["truncated"] |= details_clipped
    size = len(_encode(entry))
    if size > MAX_EVENT_CHARS:
        # Keep correlation and the short event if hostile escaping/metadata
        # exceeds the hard envelope after the ordinary payload projection.
        entry.pop("payload", None)
        entry["truncated"] = True
        size = len(_encode(entry))
    # Worker threads keep their captured correlation, but only the API loop
    # touches subscriber queues and orders durable public events.
    if _LOOP is not None:
        try:
            current = asyncio.get_running_loop()
        except RuntimeError:
            current = None
        if current is not _LOOP:
            _LOOP.call_soon_threadsafe(_publish, entry)
            return
    _publish(entry)


def _publish(entry: dict) -> None:
    global _HISTORY_CHARS, _JOURNAL_AVAILABLE
    with _LOCK:
        if _LEDGER is not None:
            try:
                entry["seq"] = _LEDGER.append_trace(entry, max_events=500, max_chars=MAX_HISTORY_CHARS)
            except Exception:
                # Observability is fail-open; execution receipts independently
                # fail closed before effects. Never claim replay is complete.
                _JOURNAL_AVAILABLE = False
                logging.getLogger(__name__).exception("Public trace journal unavailable")
        size = len(_encode(entry))
        while _HISTORY and (len(_HISTORY) >= 500 or _HISTORY_CHARS + size > MAX_HISTORY_CHARS):
            _old, old_size = _HISTORY.popleft()
            _HISTORY_CHARS -= old_size
        _HISTORY.append((entry, size))
        _HISTORY_CHARS += size
    for queue in tuple(_SUBSCRIBERS):
        if queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        queue.put_nowait(entry)


def history() -> list[dict]:
    with _LOCK:
        return [dict(entry) for entry, _size in _HISTORY]


def replay(after_seq: int | None = None) -> dict:
    """A bounded cursor gap requires an explicit retained-history snapshot."""
    entries = history()
    sequences = [entry["seq"] for entry in entries if type(entry.get("seq")) is int]
    oldest, latest = (sequences[0], sequences[-1]) if sequences else (0, 0)
    gap = after_seq is not None and (
        not _JOURNAL_AVAILABLE or after_seq < oldest - 1 or after_seq > latest
    )
    snapshot = after_seq is None or gap
    return {
        "type": "snapshot" if snapshot else "replay",
        "entries": entries if snapshot else [entry for entry in entries if entry.get("seq", 0) > after_seq],
        "cursor": latest, "gap": gap, "journal_available": _JOURNAL_AVAILABLE,
    }


def subscribe() -> asyncio.Queue:
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    _SUBSCRIBERS.add(queue)
    return queue


def unsubscribe(queue: asyncio.Queue) -> None:
    _SUBSCRIBERS.discard(queue)


def input_speech_timing(value: object) -> dict | None:
    """Accept only bounded timing evidence, independent of transcript contents."""
    if (not isinstance(value, dict) or type(value.get("speech_sequence")) is not int
            or not 0 < value["speech_sequence"] < 2**31):
        return None
    rows = value.get("stages")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 3:
        return None
    allowed = {"speech_onset": 0, "first_partial": 1, "speech_final": 2}
    stages = []
    previous_stage, previous_ns = -1, 0
    now = time.monotonic_ns()
    for row in rows:
        if not isinstance(row, dict):
            return None
        stage, instant = row.get("stage"), row.get("monotonic_ns")
        if (not isinstance(stage, str) or stage not in allowed or allowed[stage] <= previous_stage
                or type(instant) is not int or not previous_ns <= instant <= now
                or instant <= 0):
            return None
        stages.append({"stage": stage, "monotonic_ns": instant})
        previous_stage, previous_ns = allowed[stage], instant
    if stages[-1]["stage"] != "speech_final":
        return None
    return {"speech_sequence": value["speech_sequence"], "stages": stages}

"""Scheduler: one asyncio loop; cron for scheduled tasks, ready-queue for one-shots."""

from __future__ import annotations

import asyncio
import time
import uuid

from croniter import croniter

from ..config import CONFIG
from ..knowledge.index import INDEX
from ..knowledge.tasks import task_triggers
from ..knowledge.vault import Note, iter_notes, load_note, mutate_note_metadata, update_status
from .executor import run_task

_running: set[str] = set()
_background: set[asyncio.Task] = set()
_last_fired: dict[str, float] = {}
_ACTIVE_EVENT_STATUSES = {"pending", "running"}
REALTIME_TASK_REF = "Tasks/executive/realtime"
INTERRUPTED_RUN_SUMMARY = "interrupted by harness restart; outcome is unknown"


def _is_specialist_task(note: Note) -> bool:
    """Return true only for a Task assigned to a non-Executive Agent Article."""

    assignee = note.meta.get("assignee")
    if not assignee:
        return False
    from ..knowledge.vault import resolver

    agent = resolver().resolve(str(assignee))
    return bool(agent and agent.kind == "agent" and str(agent.meta.get("role", "")) != "executive")


def _realtime_allows(note: Note) -> bool:
    """Pause autonomous specialist claims while retaining exact Executive delegation."""

    from ..realtime.runtime import RUNTIME

    if not RUNTIME.scheduler_paused() or not _is_specialist_task(note):
        return True
    params = note.meta.get("params")
    return bool(
        isinstance(params, dict)
        and params.get("realtime_delegate") is True
        and str(params.get("created_by_task_ref", "")) == REALTIME_TASK_REF
    )


def _other_task_active(task_ref: str) -> bool:
    """See every Task owner, including chat and Realtime outside this loop."""

    if any(ref != task_ref for ref in _running):
        return True
    return any(
        note.kind == "task"
        and note.ref != task_ref
        and str(note.meta.get("status", "")) == "running"
        for note in iter_notes()
    )


def reconcile_interrupted_runs() -> list[str]:
    """Close interrupted attempts and retry their durable event commitment."""
    interrupted = []
    for note in iter_notes():
        if note.kind != "task":
            continue
        status = str(note.meta.get("status", ""))
        was_running = status == "running"
        params = note.meta.get("params")
        retry_event = bool(
            task_triggers(note.meta)
            and isinstance(params, dict)
            and (params.get("activation_key") or params.get("event"))
        )
        was_interrupted = (
            status == "failed"
            and str(note.meta.get("blocked_reason", "")) == INTERRUPTED_RUN_SUMMARY
            and retry_event
        )
        if not was_running and not was_interrupted:
            continue
        run_id = str(note.meta.get("last_run") or f"interrupted-{int(time.time())}")
        if retry_event:
            def requeue(meta: dict) -> None:
                meta["status"] = "pending"
                meta["status_updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                meta["summary"] = INTERRUPTED_RUN_SUMMARY
                meta.pop("blocked_reason", None)
                queue = _dedupe_waiting_events(meta)
                if queue:
                    meta["event_queue"] = queue
                else:
                    meta.pop("event_queue", None)

            mutate_note_metadata(note, requeue)
        else:
            update_status(note, "failed", {"blocked_reason": INTERRUPTED_RUN_SUMMARY})
        if was_running:
            INDEX.record_run(
                id=run_id,
                task_ref=note.ref,
                objective=note.title,
                agent="interpreter",
                started=note.mtime,
                finished=time.time(),
                status="failed",
                summary=INTERRUPTED_RUN_SUMMARY,
                trace="[]",
                reasoning_effort=str(note.meta.get("reasoning_effort", "")),
            )
        interrupted.append(note.ref)
    return interrupted


def _event_queue(meta: dict) -> list[dict]:
    raw = meta.get("event_queue")
    if not isinstance(raw, list):
        return []
    return [dict(item) for item in raw if isinstance(item, dict)]


def _event_key(params: dict) -> tuple[str, ...]:
    candidate_refs = params.get("candidate_refs")
    if params.get("event") == "task.create" and isinstance(candidate_refs, list):
        refs = tuple(sorted({str(ref).strip() for ref in candidate_refs if str(ref).strip()}))
        if refs:
            return ("task.create-candidate", str(params.get("target_task", "")), *refs)
    activation_key = str(params.get("activation_key", ""))
    if activation_key:
        return ("activation", activation_key)
    model_id = str(params.get("model_id", ""))
    if model_id:
        return (
            "model.added",
            model_id,
            str(params.get("model_fingerprint", "")),
        )
    source_ref = str(params.get("source_ref", ""))
    if source_ref:
        return (
            str(params.get("event", "source")),
            source_ref,
            str(params.get("source_sha256", "")),
        )
    return (
        str(params.get("target_agent", "")),
        str(params.get("target_task", "")),
        str(params.get("output_runbook", "")),
    )


def _dedupe_waiting_events(meta: dict) -> list[dict]:
    """Keep one FIFO occurrence per active event identity."""
    active = meta.get("params")
    seen = {_event_key(active)} if isinstance(active, dict) else set()
    queue = []
    for waiting in _event_queue(meta):
        key = _event_key(waiting)
        if key in seen:
            continue
        seen.add(key)
        queue.append(waiting)
    return queue


def enqueue_named_event(
    event: str,
    params: dict,
    *,
    expected_task: str | None = None,
) -> list[dict]:
    """Route one occurrence only through ordinary enabled graph Tasks."""
    subscribers = []
    for note in iter_notes():
        if note.kind != "task" or event not in task_triggers(note.meta):
            continue
        enabled = note.meta.get("enabled", True)
        if enabled is False or str(enabled).strip().lower() in {"0", "false", "no", "off"}:
            continue
        subscribers.append(note)
    if expected_task is not None and [note.ref for note in subscribers] != [expected_task]:
        found = ", ".join(note.ref for note in subscribers) or "none"
        raise ValueError(
            f"{event} must resolve exactly to {expected_task}; got {found}"
        )
    return [
        {"task": note.ref, **enqueue_event(note, {"event": event, **params})}
        for note in subscribers
    ]


def enqueue_event(task: Note, params: dict) -> dict:
    """Append an event occurrence to its ordinary Task's durable FIFO.

    The active occurrence remains in ``params``. Waiting occurrences live in
    ``event_queue`` on that same graph Task, so restarts and rapid UI events do
    not require a second hidden event system.
    """
    result = {"state": "queued", "status": "pending", "position": 1, "queue_depth": 1}

    def mutate(meta: dict) -> None:
        queue = _event_queue(meta)
        current_status = str(meta.get("status", "draft"))
        key = _event_key(params)
        active_params = meta.get("params")
        if (
            params.get("activation_key")
            and isinstance(active_params, dict)
            and _event_key(active_params) == key
        ):
            result.update(
                state="started" if current_status in _ACTIVE_EVENT_STATUSES else "processed",
                status=current_status,
                position=0,
                queue_depth=len(queue),
            )
            return
        if current_status == "review":
            if params.get("queue_after_review") is True:
                for index, waiting in enumerate(queue):
                    if _event_key(waiting) == key:
                        result.update(
                            state="queued", status="review", position=index + 1,
                            queue_depth=len(queue),
                        )
                        return
                queue.append(dict(params))
                meta["event_queue"] = queue
                result.update(
                    state="queued", status="review", position=len(queue),
                    queue_depth=len(queue),
                )
                return
            # Review is unresolved runtime state, not an idle Task definition.
            # Curate will see the same lead again on a later pass; do not stack
            # or overwrite another Merge while its owner decision is pending.
            result.update(
                state="deferred",
                status="review",
                reason="target_awaiting_review",
                position=0,
                queue_depth=len(queue),
            )
            return
        # A failed or blocked event occurrence is still the unresolved active
        # commitment. New occurrences wait behind it until it is retried or
        # explicitly resolved; they must never overwrite its bound inputs.
        active = current_status in _ACTIVE_EVENT_STATUSES or (
            current_status in {"failed", "blocked"}
            and isinstance(active_params, dict)
            and bool(active_params.get("activation_key") or active_params.get("event"))
        )
        if active and isinstance(active_params, dict) and _event_key(active_params) == key:
            result.update(state="started", position=0, queue_depth=len(queue))
            return
        for index, waiting in enumerate(queue):
            if _event_key(waiting) == key:
                result.update(state="queued", position=index + 1, queue_depth=len(queue))
                return
        queue.append(dict(params))
        if active:
            result.update(state="queued", position=len(queue), queue_depth=len(queue))
        else:
            meta["params"] = queue.pop(0)
            meta["status"] = "pending"
            meta["triggered_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            meta.pop("blocked_reason", None)
            result.update(state="started", position=0, queue_depth=len(queue))
        if queue:
            meta["event_queue"] = queue
        else:
            meta.pop("event_queue", None)

    mutate_note_metadata(task, mutate)
    return result


def advance_event_queue(task: Note) -> dict:
    """Promote the next queued occurrence after the active run finishes."""
    result = {"promoted": False, "queue_depth": 0}

    def mutate(meta: dict) -> None:
        queue = _event_queue(meta)
        active_params = meta.get("params")
        if isinstance(active_params, dict):
            active_key = _event_key(active_params)
            queue = [waiting for waiting in queue if _event_key(waiting) != active_key]
        if not queue:
            meta.pop("event_queue", None)
            return
        meta["params"] = queue.pop(0)
        meta["status"] = "pending"
        meta["triggered_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        meta.pop("blocked_reason", None)
        if queue:
            meta["event_queue"] = queue
        else:
            meta.pop("event_queue", None)
        result.update(promoted=True, queue_depth=len(queue))

    mutate_note_metadata(task, mutate)
    return result


def due_tasks() -> list:
    now = time.time()
    due = []
    for note in iter_notes():
        if note.kind != "task" or note.ref in _running:
            continue
        if not _realtime_allows(note):
            continue
        params = note.meta.get("params")
        if (
            isinstance(params, dict)
            and params.get("wait_for_idle") is True
            and _other_task_active(note.ref)
        ):
            continue
        status = str(note.meta.get("status", "draft"))
        schedule = note.meta.get("schedule")
        if schedule and status in ("pending", "completed", "review", "failed"):
            base = _last_fired.get(note.ref) or note.mtime
            try:
                nxt = croniter(str(schedule), base).get_next(float)
            except (ValueError, KeyError):
                continue
            if nxt <= now and status != "review":  # never re-fire past an unreviewed result
                due.append(note)
        elif not schedule and status == "pending":
            due.append(note)
    return due


async def _run(note, **run_kwargs) -> None:
    _last_fired[note.ref] = time.time()
    try:
        await run_task(note, **run_kwargs)
    except Exception as exc:  # noqa: BLE001 — a failed runtime must close its Task state
        run_id = f"failed-{uuid.uuid4().hex[:12]}"
        summary = f"execution failed before completion: {exc}"
        update_status(note, "failed", {
            "blocked_reason": summary,
            "last_run": run_id,
            "summary": summary,
        })
        INDEX.record_run(
            id=run_id,
            task_ref=note.ref,
            objective=(
                " ".join(str((run_kwargs.get("runtime_params") or {}).get("request") or "").split())
                or note.title
            ),
            agent="runtime",
            started=_last_fired[note.ref],
            finished=time.time(),
            status="failed",
            summary=summary,
            trace="[]",
            reasoning_effort=str(
                run_kwargs.get("reasoning_effort") or note.meta.get("reasoning_effort", "")
            ),
            model=str(run_kwargs.get("model") or note.meta.get("model", "")),
        )
        print(f"[scheduler] {note.ref} failed: {exc}")
    finally:
        current = load_note(note.path)
        active_params = None if current is None else current.meta.get("params")
        queued_occurrence = bool(
            task_triggers(note.meta)
            or (isinstance(active_params, dict) and active_params.get("event") == "task.create")
        )
        if queued_occurrence:
            # Review is unresolved Task state. Preserve the waiting FIFO until
            # the owner has decided every proposal from this activation. A
            # failed occurrence retains its bound params for an explicit retry.
            if current and str(current.meta.get("status")) == "completed":
                advance_event_queue(current)


def _claim(note: Note) -> None:
    """Reserve a Task before it waits for the single executor slot."""
    if note.ref in _running:
        raise RuntimeError(f"{note.ref} is already queued or running")
    _running.add(note.ref)


async def _run_claimed(note: Note, **run_kwargs) -> None:
    try:
        await _run(note, **run_kwargs)
    finally:
        _running.discard(note.ref)


def launch(note, **run_kwargs) -> asyncio.Task:
    """Start one tracked Task through the same failure boundary as the scheduler."""
    _claim(note)
    task = asyncio.create_task(_run_claimed(note, **run_kwargs))
    _background.add(task)
    task.add_done_callback(_background.discard)
    return task


async def shutdown() -> None:
    """Cancel and join active Task launches before the harness event loop closes."""
    active = [task for task in _background if not task.done()]
    for task in active:
        task.cancel()
    if active:
        await asyncio.gather(*active, return_exceptions=True)


async def loop() -> None:
    sem = asyncio.Semaphore(CONFIG.concurrency)
    while True:
        try:
            from ..knowledge.source import dispatch_pending_source_events

            dispatch_pending_source_events()
            INDEX.sync()
            for note in due_tasks():
                _claim(note)
                async def bounded(n=note):
                    try:
                        async with sem:
                            await _run(n)
                    finally:
                        _running.discard(n.ref)
                task = asyncio.create_task(bounded())
                _background.add(task)
                task.add_done_callback(_background.discard)
        except Exception as exc:  # noqa: BLE001 — the tick must survive anything
            print(f"[scheduler] tick error: {exc}")
        await asyncio.sleep(CONFIG.tick_seconds)

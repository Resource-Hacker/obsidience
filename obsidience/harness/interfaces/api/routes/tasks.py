"""Task queue: admission state, activation, owner settings, cancellation and runs."""

from __future__ import annotations

import asyncio
import time

from croniter import croniter
from fastapi import APIRouter, HTTPException

from ....execution import activity as knowledge_activity
from ....execution import scheduler
from ....execution.assignments import ensure_task_runbook
from ....execution.executor import task_descendants
from ....execution.ledger import current_task_issue
from ....execution.optimization import AUDITOR
from ....knowledge.dependencies import task_exclusion_path, task_taxonomy_path
from ....knowledge.index import INDEX
from ....knowledge.links import metadata_ref
from ....knowledge.tasks import task_triggers
from ....knowledge.vault import Note, Resolver, load_note, resolver, write_note
from ....models import llm
from ....models import runtime as model_runtime
from ....realtime import runtime as realtime

router = APIRouter()


def _is_enabled(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"false", "no", "off", "0"}
    return value is not False


def task_execution_state(note: Note, accepted_resolver: Resolver) -> dict:
    """Present current admission separately from the immutable last attempt."""
    status = str(note.meta.get("status", "draft"))
    issue = current_task_issue(note)
    previous = INDEX.run(str(note.meta.get("last_run") or ""))
    if previous and previous.get("task_ref") != note.ref:
        previous = None
    last_run = ({key: previous.get(key) for key in ("id", "status", "finished", "summary")}
                if previous else None)
    result = {"state": "idle", "reason": "", "last_run": last_run,
              "retry_allowed": False, "retry_blocked_reason": ""}
    if status == "cancelled":
        result["reason"] = str(note.meta.get("summary") or "Cancelled by the owner.")
    elif status in {"running", "review"}:
        result.update(state=status, reason=str(note.meta.get("blocked_reason") or ""))
    elif issue:
        if issue["kind"] == "unresolved_occurrence":
            blocked = scheduler.retry_blocked_reason(note, previous)
        elif issue["kind"] == "scheduled_draft":
            blocked = "Resolve the scheduled Task's draft state before running it."
        else:
            blocked = "Resolve the Task configuration before running it."
        result.update(state="needs_attention", reason=issue["reason"],
                      retry_allowed=not blocked, retry_blocked_reason=blocked)
    elif (status == "pending" or (
        status in {"completed", "failed"} and note.meta.get("schedule")
        and str(note.meta.get("blocked_reason", "")).startswith(scheduler.RESOURCE_WAIT_PREFIX)
    )):
        if scheduler.memory_curation_paused(note):
            result.update(state="waiting", label="Paused: memory curation",
                          reason="The owner paused Hindsight-to-Knowledge curation; this occurrence and its FIFO remain retained.")
        elif not scheduler._realtime_allows(note, accepted_resolver):
            result.update(state="waiting", label="Paused: Realtime" if realtime.RUNTIME.scheduler_paused() else "Paused: foreground",
                          reason="Background work is paused while Realtime or foreground input owns execution.")
        else:
            error = scheduler._resource_error(note, accepted_resolver=accepted_resolver)
            if error:
                result.update(state="waiting", label=("Waiting: GPU memory" if isinstance(
                    error, model_runtime.ModelMemoryUnavailable) else "Waiting: hardware"),
                    reason=scheduler.RESOURCE_WAIT_PREFIX + str(error), resource=error.as_dict())
            else:
                result.update(state="ready", reason="Waiting for its turn in the existing execution queue.")
    return result


@router.get("/api/tasks")
def tasks():
    out = []
    accepted_resolver = resolver(include_system=False)
    for n in accepted_resolver.by_ref.values():
        if n.kind != "task":
            continue
        subtasks = n.meta.get("subtasks") or []
        refs = [metadata_ref(str(x)) for x in subtasks] if isinstance(subtasks, list) else []
        excluded = n.meta.get("exclude_subtasks") or []
        excluded_refs = (
            [metadata_ref(str(x)) for x in excluded]
            if isinstance(excluded, list) else [metadata_ref(str(excluded))]
        )
        try:
            effort = llm.normalize_reasoning_effort(n.meta.get("reasoning_effort"))
        except ValueError:
            effort = llm.normalize_reasoning_effort(None)
        status = str(n.meta.get("status", "draft"))
        try:
            model = model_runtime.normalize_model(n.meta.get("model"))
        except ValueError:
            model = model_runtime.AUTO_MODEL
        assignee_ref = metadata_ref(str(n.meta.get("assignee", "")))
        resolved_model = model_runtime.resolve_model(
            model,
            assignee_ref or "Agents/Executive/Executive",
        )
        resolved_model = resolved_model.id
        schedule = n.meta.get("schedule")
        next_run = None
        if schedule and status in ("pending", "completed", "failed", "running"):
            try:
                next_run = croniter(str(schedule), time.time()).get_next(float)
            except (ValueError, KeyError):
                pass
        out.append({"ref": n.ref, "title": n.title,
                    "status": n.meta.get("status", "draft"),
                    "assignee": assignee_ref,
                    "runbook": metadata_ref(str(n.meta.get("runbook", ""))),
                    "subtasks": len(refs),
                    "subtask_refs": refs,
                    "excluded_subtask_refs": excluded_refs,
                    "taxonomy_path": task_taxonomy_path(n),
                    "reasoning_effort": effort,
                    "model": model,
                    "resolved_model": resolved_model,
                    # Accepts Codex/Claude Code session models for its optimizer sessions.
                    "session_models": n.ref == AUDITOR,
                    "triggers": list(task_triggers(n.meta)),
                    "queue_depth": len(n.meta.get("event_queue", []))
                    if isinstance(n.meta.get("event_queue"), list) else 0,
                    "enabled": _is_enabled(n.meta.get("enabled", True)),
                    "schedule": schedule,
                    "next_run": next_run,
                    "blocked_reason": n.meta.get("blocked_reason"),
                    "last_run": n.meta.get("last_run"),
                    "execution": task_execution_state(n, accepted_resolver)})
    return out


@router.post("/api/tasks")
async def create_task(payload: dict):
    """Activate or schedule one accepted Library Task from the Tasks pane."""
    requested = str(payload.get("task", "")).strip()
    task = resolver().resolve(requested)
    if not requested or not task or task.kind != "task":
        raise HTTPException(400, f"task not found: {requested or '(empty)'}")
    if str(task.meta.get("status", "draft")) == "running":
        raise HTTPException(409, "task is already running")
    schedule = str(payload.get("schedule") or "").strip()
    if schedule:
        try:
            croniter(schedule, time.time()).get_next(float)
        except (ValueError, KeyError) as exc:
            raise HTTPException(400, f"invalid cron schedule: {schedule}") from exc
    raw_params = payload.get("params") or {}
    if not isinstance(raw_params, dict) or len(raw_params) > 8:
        raise HTTPException(400, "params must be an object with at most 8 fields")
    meta = dict(task.meta)
    if schedule:
        meta["schedule"] = schedule
        state = "scheduled"
    else:
        meta.pop("schedule", None)
        meta["triggered_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        state = "started"
    if raw_params:
        meta["params"] = raw_params
    else:
        meta.pop("params", None)
    meta["status"] = "pending"
    write_note(task.path, meta, task.body)
    readiness = ensure_task_runbook(load_note(task.path), resolver())
    INDEX.sync()
    knowledge_activity.emit_operation("edit", "completed", [task.ref], label="Task queued", refresh=True)
    return {"task": task.ref, "state": state, "status": meta["status"],
            "dependencies": readiness}


@router.patch("/api/tasks/{ref:path}/reasoning")
async def set_task_reasoning(ref: str, payload: dict):
    """Persist an owner-selected inference setting on one task."""
    note = load_note(ref + ".md") or resolver().resolve(ref)
    if not note or note.kind != "task":
        raise HTTPException(404, f"task not found: {ref}")
    if str(note.meta.get("status", "draft")) == "running":
        raise HTTPException(409, "cannot edit a running task")
    try:
        effort = llm.normalize_reasoning_effort(payload.get("reasoning_effort"))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    meta = dict(note.meta)
    meta["reasoning_effort"] = effort
    write_note(note.path, meta, note.body)
    INDEX.sync()
    knowledge_activity.emit_operation("edit", "completed", [note.ref], label="Task reasoning saved", refresh=True)
    return {"task": note.ref, "reasoning_effort": effort}


@router.patch("/api/tasks/{ref:path}/model")
async def set_task_model(ref: str, payload: dict):
    """Persist one model preference on one Task Article."""
    note = load_note(ref + ".md") or resolver().resolve(ref)
    if not note or note.kind != "task":
        raise HTTPException(404, f"task not found: {ref}")
    if str(note.meta.get("status", "draft")) == "running":
        raise HTTPException(409, "cannot edit a running task")
    try:
        model = model_runtime.normalize_model(payload.get("model"))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if model_runtime.is_cloud(model):
        if note.ref != AUDITOR:
            # Cloud CLIs answer whole sessions; they cannot run this Task's native Tool loop.
            raise HTTPException(400, "Codex and Claude Code models serve Audit's optimizer sessions only")
        offered = await asyncio.to_thread(model_runtime.cloud_catalog)
        if model not in {row["id"] for row in offered if row["available"]}:
            raise HTTPException(400, f"{model} is not offered by the installed, signed-in CLI")
    meta = dict(note.meta)
    meta["model"] = model
    write_note(note.path, meta, note.body)
    INDEX.sync()
    knowledge_activity.emit_operation("edit", "completed", [note.ref], label="Task model saved", refresh=True)
    agent_ref = metadata_ref(str(meta.get("assignee", ""))) or "Agents/Executive/Executive"
    return {
        "task": note.ref,
        "model": model,
        "resolved_model": model_runtime.resolve_model(model, agent_ref).id,
    }


@router.patch("/api/tasks/{ref:path}/exclusions")
async def set_task_exclusions(ref: str, payload: dict):
    """Persist explicit descendant-subtree exclusions on one parent Task."""
    note = load_note(ref + ".md") or resolver().resolve(ref)
    if not note or note.kind != "task":
        raise HTTPException(404, f"task not found: {ref}")
    if str(note.meta.get("status", "draft")) == "running":
        raise HTTPException(409, "cannot edit a running task")
    requested = payload.get("excluded_subtask_refs", [])
    if not isinstance(requested, list) or len(requested) > 64:
        raise HTTPException(400, "excluded_subtask_refs must be a list of at most 64 refs")

    res = resolver()
    descendants, error = task_descendants(note, res)
    if error:
        raise HTTPException(400, error)
    by_ref = {child.ref: child for child in descendants}
    root_path = task_taxonomy_path(note)
    selected: list[str] = []
    for raw in requested:
        ref = metadata_ref(str(raw))
        if ref.startswith("@library/Tasks/"):
            path = task_exclusion_path(str(raw), res)
            if not root_path or not path.startswith(root_path + "/"):
                raise HTTPException(400, f"excluded subtask is not a descendant: {raw}")
            canonical = ref
        else:
            child = res.resolve(ref)
            if child and child.kind == "task" and child.ref in by_ref:
                canonical = child.ref
            else:
                path = task_exclusion_path(str(raw), res)
                if not root_path or not path.startswith(root_path + "/"):
                    raise HTTPException(400, f"excluded subtask is not a descendant: {raw}")
                canonical = ref
        if canonical not in selected:
            selected.append(canonical)

    ordered = selected
    meta = dict(note.meta)
    if ordered:
        meta["exclude_subtasks"] = [f"[[{child_ref}]]" for child_ref in ordered]
    else:
        meta.pop("exclude_subtasks", None)
    write_note(note.path, meta, note.body)
    INDEX.sync()
    knowledge_activity.emit_operation("edit", "completed", [note.ref], label="Task exclusions saved", refresh=True)
    return {"task": note.ref, "excluded_subtask_refs": ordered}


@router.post("/api/tasks/{ref:path}/cancel")
async def cancel_occurrences(ref: str, payload: dict | None = None):
    """Owner cancellation of a Task's unresolved head and waiting occurrences."""
    note = load_note(ref + ".md") or resolver(include_system=False).resolve(ref)
    if not note or note.kind != "task" or note.ref.startswith(("_", ".")):
        raise HTTPException(404, f"task not found: {ref}")
    payload = payload or {}
    reason, expected, event = payload.get("reason"), payload.get("expected_last_run"), payload.get("event")
    if set(payload) - {"reason", "expected_last_run", "event"}:
        raise HTTPException(400, "only reason, expected_last_run and event are accepted")
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 500:
        raise HTTPException(400, "reason is required and limited to 500 characters")
    if not isinstance(expected, str) or not expected:
        raise HTTPException(400, "expected_last_run must name the Task's current last run")
    if event is not None and (not isinstance(event, str) or not event):
        raise HTTPException(400, "event must be an exact event name")
    try:
        return scheduler.cancel_task_occurrences(note, reason=reason, expected_last_run=expected, event=event)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/api/tasks/{ref:path}/run")
async def run_now(ref: str, payload: dict | None = None):
    note = load_note(ref + ".md") or resolver(include_system=False).resolve(ref)
    if (not note or note.kind != "task" or note.ref.startswith(("_", "."))
            or note.meta.get("article_status") == "deprecated"):
        raise HTTPException(404, f"task not found: {ref}")
    if str(note.meta.get("status", "draft")) == "running":
        raise HTTPException(409, "task is already running")
    if "retry_run_id" in (payload or {}):
        expected = (payload or {}).get("retry_run_id")
        if not isinstance(expected, str) or not expected:
            raise HTTPException(400, "retry_run_id must name the exact previous attempt")
        if any(key in (payload or {}) for key in ("params", "model")):
            raise HTTPException(400, "retry preserves the occurrence inputs and Task model")
        try:
            return scheduler.retry_failed_occurrence(note, expected)
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(409, str(exc)) from exc
    if str(note.meta.get("status", "draft")) == "review":
        raise HTTPException(409, "resolve the pending Review before running this Task")
    stored = note.meta.get("params")
    if str(note.meta.get("status", "")) in {"failed", "blocked"} and isinstance(stored, dict) and (
        stored.get("activation_key") or stored.get("event")
    ):
        raise HTTPException(409, "retry must name the exact failed attempt; its inputs and waiting queue are retained")
    try:
        requested_effort = (payload or {}).get("reasoning_effort", note.meta.get("reasoning_effort"))
        effort = llm.normalize_reasoning_effort(requested_effort)
        requested_model = (payload or {}).get("model")
        model = (
            model_runtime.normalize_model(requested_model)
            if requested_model is not None else None
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    raw_params = (payload or {}).get("params") or {}
    if not isinstance(raw_params, dict):
        raise HTTPException(400, "params must be an object")
    if len(raw_params) > 8:
        raise HTTPException(400, "too many runtime params")
    runtime_params: dict[str, str] = {}
    for raw_key, raw_value in raw_params.items():
        key = str(raw_key).strip()
        value = str(raw_value).strip()
        if not key or len(key) > 64 or len(value) > 500:
            raise HTTPException(400, "runtime params are invalid")
        runtime_params[key] = value
    from ....execution.completion import validate_computer_outcome

    stored_params = note.meta.get("params")
    preserve_pending = str(note.meta.get("status", "")) == "pending" and "params" not in (payload or {})
    expected_key = (payload or {}).get("expected_activation_key")
    if expected_key is not None:
        if not isinstance(expected_key, str) or not expected_key:
            raise HTTPException(400, "expected_activation_key must identify the pending occurrence")
        if (not preserve_pending or not isinstance(stored_params, dict)
                or expected_key != stored_params.get("activation_key")):
            raise HTTPException(409, "pending occurrence changed; refresh its activation key")
    bound_params = {**(stored_params if isinstance(stored_params, dict) else {}), **runtime_params}
    outcome_error = validate_computer_outcome(
        bound_params.get("computer_outcome"), bound_params.get("computer_scope"),
    )
    if outcome_error:
        raise HTTPException(400, outcome_error)
    try:
        scheduler.launch(
            note,
            owner_requested=True,
            reasoning_effort=effort,
            model=model,
            runtime_params=None if preserve_pending else runtime_params,
        )
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    preference = model or model_runtime.normalize_model(note.meta.get("model"))
    agent_ref = metadata_ref(str(note.meta.get("assignee", ""))) or "Agents/Executive/Executive"
    return {
        "started": note.ref,
        "reasoning_effort": effort,
        "model": preference,
        "resolved_model": model_runtime.resolve_model(preference, agent_ref).id,
    }

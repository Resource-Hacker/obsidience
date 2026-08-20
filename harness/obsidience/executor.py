"""The graph interpreter: resolve the spine, brief, run the tool loop, leave a receipt.

Spine (edges, deterministic): task -> assignee charter -> runbook.
Flesh (vectors, contextual): the activation briefing.
"""

from __future__ import annotations

import json
import time
import uuid

from . import llm, retrieval
from .config import CONFIG
from .indexer import INDEX
from .receipts import write_receipt
from .tools import DEFAULT_TOOLS, run_tool, tool_docs
from .vault import Note, resolver, update_status

LAWS = """\
## Laws
1. Follow the runbook exactly. If it cannot be followed, finish with status "failed" and say why.
2. You cannot edit the vault; you can only stage proposals for owner review.
3. Prefer searching the vault over assuming. Cite notes as [[wikilinks]] in summaries.
"""


def resolve_spine(task: Note) -> tuple[Note | None, Note | None, str | None]:
    """Return (charter, runbook, error)."""
    res = resolver()
    charter = res.resolve(str(task.meta.get("assignee", "Operator")))
    if not charter:
        return None, None, f"assignee charter not found: {task.meta.get('assignee')}"
    rb_ref = task.meta.get("runbook")
    if not rb_ref:
        return charter, None, "task has no runbook"
    runbook = res.resolve(str(rb_ref))
    if not runbook:
        return charter, None, f"awaiting-runbook: {rb_ref} not found"
    return charter, runbook, None


async def run_task(task: Note) -> dict:
    run_id = uuid.uuid4().hex[:12]
    started = time.time()
    charter, runbook, err = resolve_spine(task)
    if err:
        update_status(task, "blocked", {"blocked_reason": err})
        INDEX.record_run(id=run_id, task_ref=task.ref, agent=charter.title if charter else "?",
                         started=started, finished=time.time(), status="blocked",
                         summary=err, receipt_path="", trace="[]")
        return {"run_id": run_id, "status": "blocked", "summary": err}

    update_status(task, "active", {"last_run": run_id})
    allowed = list(charter.meta.get("tools") or DEFAULT_TOOLS)
    if "finish" not in allowed:
        allowed.append("finish")
    params = task.meta.get("params") or {}
    queries = [task.title, runbook.title]
    if params:
        queries.append(" ".join(f"{k} {v}" for k, v in list(params.items())[:6]))
    brief = retrieval.briefing(queries, exclude={task.ref, runbook.ref, charter.ref})

    system = "\n\n".join([
        f"You are {charter.title}, an agent of the Obsidience vault.",
        charter.body.strip(), LAWS, tool_docs(allowed), llm.PROTOCOL,
    ])
    user = "\n\n".join(filter(None, [
        f"# Task: {task.title}\n{task.body.strip()}",
        f"Params: {json.dumps(params)}" if params else "",
        f"Acceptance criteria: {json.dumps(task.meta.get('acceptance'))}" if task.meta.get("acceptance") else "",
        f"# Runbook: {runbook.title}\n{runbook.body.strip()}", brief,
        "Begin. Follow the runbook step by step.",
    ]))

    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    trace: list[dict] = []
    status, summary = "failed", "session ended without finish"
    ctx = {"agent": charter.title, "task": task.ref}

    for _step in range(CONFIG.max_steps):
        try:
            reply = await llm.chat(messages)
        except Exception as exc:  # noqa: BLE001 — surface LLM transport errors into the receipt
            status, summary = "failed", f"LLM error: {exc}"
            break
        messages.append({"role": "assistant", "content": reply})
        action = llm.parse_action(reply)
        if not action:
            messages.append({"role": "user", "content":
                             "No valid action block found. Reply with exactly one ```action``` block."})
            trace.append({"invalid": reply[:400]})
            continue
        name, args = action.get("tool"), action.get("args") or {}
        if name == "finish":
            status = str(args.get("status", "done"))
            if status not in ("done", "failed", "review"):
                status = "done"
            summary = str(args.get("summary", ""))[:2000]
            trace.append({"tool": "finish", "args": {"status": status}})
            break
        if name not in allowed:
            obs = f"Tool '{name}' is not permitted for this charter."
        else:
            try:
                obs = run_tool(name, args, ctx)
            except Exception as exc:  # noqa: BLE001
                obs = f"Tool error: {exc}"
        trace.append({"tool": name, "args": args, "obs": obs[:600]})
        messages.append({"role": "user", "content": f"Observation:\n{obs}"})

    # acceptance criteria present and not failed -> owner confirms unless auto_done
    if status == "done" and task.meta.get("acceptance") and not task.meta.get("auto_done"):
        status = "review"

    finished = time.time()
    receipt_path = write_receipt(task, charter, run_id, status, summary, trace,
                                 started, finished)
    update_status(task, status, {"last_run": run_id, "blocked_reason": None})
    INDEX.record_run(id=run_id, task_ref=task.ref, agent=charter.title, started=started,
                     finished=finished, status=status, summary=summary,
                     receipt_path=receipt_path, trace=json.dumps(trace)[:20000])
    INDEX.sync()
    return {"run_id": run_id, "status": status, "summary": summary, "receipt": receipt_path}

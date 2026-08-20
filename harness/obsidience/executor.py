"""The interpreter. Not a graph primitive — it performs:

    Task -> choose Runbook (leaf) | expand Subtasks (container, in order)
         -> load required Skills -> authorize and invoke Tools
         -> collect evidence -> update Task state

Spine resolution is edge-exact (wikilinks); retrieval only builds the briefing.
"""

from __future__ import annotations

import json
import time
import uuid

from . import llm, retrieval
from .config import CONFIG
from .indexer import INDEX
from .receipts import write_receipt
from .tools import ALWAYS_ALLOWED, REGISTRY, run_tool, tool_docs
from .vault import Note, Resolver, resolver, update_status

MAX_TASK_DEPTH = 3

LAWS = """\
## Laws
1. Follow the runbook exactly. If it cannot be followed, complete with status "failed" and say why.
2. You cannot edit the vault; you can only stage proposals for owner review.
3. Use only the authorized tools. Prefer searching the vault over assuming; cite notes as [[wikilinks]].
"""


def _links(value) -> list[str]:
    if not value:
        return []
    return [str(v) for v in (value if isinstance(value, list) else [value])]


def resolve_spine(task: Note, res: Resolver) -> dict:
    """Edge-exact resolution: runbook -> skills -> authorized tool set."""
    subtask_refs = _links(task.meta.get("subtasks"))
    if subtask_refs:
        subtasks = []
        for ref in subtask_refs:
            child = res.resolve(ref)
            if not child or child.kind != "task":
                return {"error": f"subtask not found or not a task: {ref}"}
            subtasks.append(child)
        return {"subtasks": subtasks}

    rb_ref = task.meta.get("runbook")
    if not rb_ref:
        return {"error": "awaiting-runbook: leaf task has no runbook"}
    runbook = res.resolve(str(rb_ref))
    if not runbook:
        return {"error": f"awaiting-runbook: {rb_ref} not found"}

    skills: list[Note] = []
    tool_names: set[str] = set(ALWAYS_ALLOWED)
    for skill_ref in _links(runbook.meta.get("skills")):
        skill = res.resolve(skill_ref)
        if not skill:
            return {"error": f"skill not found: {skill_ref}"}
        skills.append(skill)
        for t in _links(skill.meta.get("tools")):
            tool_names.add(t.strip("[]"))
    for t in _links(runbook.meta.get("tools")):  # runbook-level extras
        tool_names.add(t.strip("[]"))
    unknown = sorted(t for t in tool_names if t not in REGISTRY)
    if unknown:
        return {"error": f"unbound tools (no registry implementation): {unknown}"}
    return {"runbook": runbook, "skills": skills, "tools": sorted(tool_names)}


async def run_task(task: Note, depth: int = 0) -> dict:
    run_id = uuid.uuid4().hex[:12]
    started = time.time()
    res = resolver()
    spine = resolve_spine(task, res)

    if "error" in spine:
        update_status(task, "blocked", {"blocked_reason": spine["error"]})
        INDEX.record_run(id=run_id, task_ref=task.ref, agent="interpreter", started=started,
                         finished=time.time(), status="blocked", summary=spine["error"],
                         receipt_path="", trace="[]")
        return {"run_id": run_id, "status": "blocked", "summary": spine["error"]}

    update_status(task, "running", {"last_run": run_id, "blocked_reason": None})

    # ---- container task: its subtasks are how it completes ----
    if "subtasks" in spine:
        if depth >= MAX_TASK_DEPTH:
            update_status(task, "failed", {"blocked_reason": "max task depth exceeded"})
            return {"run_id": run_id, "status": "failed", "summary": "max task depth exceeded"}
        results, worst = [], "completed"
        order = {"completed": 0, "review": 1, "blocked": 2, "failed": 3}
        for child in spine["subtasks"]:
            child_result = await run_task(child, depth + 1)
            results.append({"task": child.ref, **{k: child_result[k] for k in ("status", "summary")}})
            if order.get(child_result["status"], 3) > order[worst]:
                worst = child_result["status"]
            if child_result["status"] in ("failed", "blocked"):
                break  # later subtasks depend on earlier ones — stop the chain
        summary = "; ".join(f"[[{r['task']}]] {r['status']}" for r in results)
        finished = time.time()
        receipt = write_receipt(task, "interpreter", run_id, worst, summary,
                                [{"tool": "subtask", "args": {"ref": r["task"]}, "obs": r["summary"][:160]}
                                 for r in results], started, finished)
        update_status(task, worst, {"last_run": run_id})
        INDEX.record_run(id=run_id, task_ref=task.ref, agent="interpreter", started=started,
                         finished=finished, status=worst, summary=summary[:2000],
                         receipt_path=receipt, trace=json.dumps(results)[:20000])
        INDEX.sync()
        return {"run_id": run_id, "status": worst, "summary": summary, "receipt": receipt}

    # ---- leaf task: runbook + skills + authorized tools ----
    runbook: Note = spine["runbook"]
    skills: list[Note] = spine["skills"]
    allowed: list[str] = spine["tools"]
    params = task.meta.get("params") or {}

    queries = [task.title, runbook.title]
    if params:
        queries.append(" ".join(f"{k} {v}" for k, v in list(params.items())[:6]))
    exclude = {task.ref, runbook.ref} | {s.ref for s in skills}
    brief = retrieval.briefing(queries, exclude=exclude)

    skills_block = "\n\n".join(
        f"### Skill: {s.title}\n{s.body.strip()[:2500]}" for s in skills
    )
    system = "\n\n".join(filter(None, [
        "You are the Obsidience interpreter executing one task from the vault.",
        LAWS,
        ("## Skills (how to use your tools correctly)\n\n" + skills_block) if skills_block else "",
        tool_docs(allowed),
        llm.PROTOCOL,
    ]))
    user = "\n\n".join(filter(None, [
        f"# Task: {task.title}\n{task.body.strip()}",
        f"Params: {json.dumps(params)}" if params else "",
        f"Acceptance criteria: {json.dumps(task.meta.get('acceptance'))}" if task.meta.get("acceptance") else "",
        f"# Runbook: {runbook.title}\n{runbook.body.strip()}",
        brief,
        "Begin. Follow the runbook step by step.",
    ]))

    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    trace: list[dict] = []
    status, summary = "failed", "session ended without task.complete"
    ctx = {"agent": "interpreter", "task": task.ref}

    for _step in range(CONFIG.max_steps):
        try:
            reply = await llm.chat(messages)
        except Exception as exc:  # noqa: BLE001 — surface LLM transport errors into the receipt
            status, summary = "failed", f"LLM error: {exc}"
            break
        messages.append({"role": "assistant", "content": reply})
        action = llm.parse_action(reply)
        if not action:
            invalids = sum(1 for t in trace[-3:] if "invalid" in t)
            if invalids >= 2:
                status, summary = "failed", "three consecutive replies without a valid action block"
                break
            messages.append({"role": "user", "content":
                             "No valid action block found. Reply with exactly one ```action``` block. "
                             "Keep proposal bodies concise — a truncated block cannot be parsed."})
            trace.append({"invalid": reply[:400]})
            continue
        name, args = action.get("tool"), action.get("args") or {}
        if name == "finish":  # legacy alias small models reach for
            name = "task.complete"
        if name == "task.complete":
            status = str(args.get("status", "completed"))
            if status not in ("completed", "failed", "review"):
                status = "completed"
            summary = str(args.get("summary", ""))[:2000]
            trace.append({"tool": "task.complete", "args": {"status": status}})
            break
        call_sig = f"{name}:{json.dumps(args, sort_keys=True)}"
        repeats = sum(1 for t in trace if t.get("sig") == call_sig)
        if repeats >= 2:
            obs = ("You have repeated this exact call three times; the result will not change. "
                   "Vary your approach or call task.complete now with your best status.")
        elif name not in allowed:
            obs = f"Tool '{name}' is not authorized for this task."
        else:
            try:
                obs = run_tool(name, args, ctx)
            except Exception as exc:  # noqa: BLE001
                obs = f"Tool error: {exc}"
        trace.append({"tool": name, "args": args, "obs": obs[:600], "sig": call_sig})
        remaining = CONFIG.max_steps - _step - 1
        nudge = ("\n\n(FINAL STEP — call task.complete now with your best status and summary.)"
                 if remaining == 1 else
                 f"\n\n({remaining} steps remain — wrap up soon.)" if remaining <= 3 else "")
        messages.append({"role": "user", "content": f"Observation:\n{obs}{nudge}"})

    # acceptance criteria present and successful -> owner confirms unless auto_done
    if status == "completed" and task.meta.get("acceptance") and not task.meta.get("auto_done"):
        status = "review"

    finished = time.time()
    receipt_path = write_receipt(task, "interpreter", run_id, status, summary, trace,
                                 started, finished)
    update_status(task, status, {"last_run": run_id, "blocked_reason": None})
    INDEX.record_run(id=run_id, task_ref=task.ref, agent="interpreter", started=started,
                     finished=finished, status=status, summary=summary,
                     receipt_path=receipt_path, trace=json.dumps(trace)[:20000])
    INDEX.sync()
    return {"run_id": run_id, "status": status, "summary": summary, "receipt": receipt_path}

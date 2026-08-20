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

from . import llm, retrieval, trace as action_trace
from .config import CONFIG
from .indexer import INDEX
from .receipts import runbook_hash, write_receipt
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


async def run_task(task: Note, depth: int = 0, reasoning_effort: str | None = None) -> dict:
    run_id = uuid.uuid4().hex[:12]
    started = time.time()
    res = resolver()
    spine = resolve_spine(task, res)
    effort = llm.normalize_reasoning_effort(
        reasoning_effort if reasoning_effort is not None else task.meta.get("reasoning_effort")
    )

    if "error" in spine:
        action_trace.emit("error", f"{task.title} blocked", [spine["error"]])
        update_status(task, "blocked", {"blocked_reason": spine["error"]})
        INDEX.record_run(id=run_id, task_ref=task.ref, agent="interpreter", started=started,
                         finished=time.time(), status="blocked", summary=spine["error"],
                         receipt_path="", trace="[]")
        return {"run_id": run_id, "status": "blocked", "summary": spine["error"]}

    update_status(task, "running", {"last_run": run_id, "blocked_reason": None})

    # ---- container task: its subtasks are how it completes ----
    if "subtasks" in spine:
        action_trace.emit("run", f"{task.title} started", [f"{len(spine['subtasks'])} subtasks"])
        if depth >= MAX_TASK_DEPTH:
            update_status(task, "failed", {"blocked_reason": "max task depth exceeded"})
            return {"run_id": run_id, "status": "failed", "summary": "max task depth exceeded"}
        results, worst = [], "completed"
        order = {"completed": 0, "review": 1, "blocked": 2, "failed": 3}
        for child in spine["subtasks"]:
            action_trace.emit("run", f"{task.title} → {child.title}")
            child_result = await run_task(child, depth + 1, effort)
            results.append({"task": child.ref, **{k: child_result[k] for k in ("status", "summary")}})
            if order.get(child_result["status"], 3) > order[worst]:
                worst = child_result["status"]
            if child_result["status"] in ("failed", "blocked"):
                break  # later subtasks depend on earlier ones — stop the chain
        summary = "; ".join(f"[[{r['task']}]] {r['status']}" for r in results)
        finished = time.time()
        receipt = write_receipt(task, "interpreter", run_id, worst, summary,
                                [{"tool": "subtask", "args": {"ref": r["task"]}, "obs": r["summary"][:160]}
                                 for r in results], started, finished,
                                reasoning_effort=effort)
        update_status(task, worst, {"last_run": run_id})
        INDEX.record_run(id=run_id, task_ref=task.ref, agent="interpreter", started=started,
                         finished=finished, status=worst, summary=summary[:2000],
                         receipt_path=receipt, trace=json.dumps(results)[:20000])
        INDEX.sync()
        action_trace.emit("status", f"{task.title} {worst}", [summary])
        return {"run_id": run_id, "status": worst, "summary": summary, "receipt": receipt}

    # ---- leaf task: runbook + skills + authorized tools ----
    runbook: Note = spine["runbook"]
    runbook_sha256 = runbook_hash(runbook)
    skills: list[Note] = spine["skills"]
    allowed: list[str] = spine["tools"]
    params = task.meta.get("params") or {}

    # Agent identity: the task's assignee is a literal agent note; the
    # interpreter executes the session AS that agent (HEREBRUM model).
    agent = (res.resolve(str(task.meta.get("assignee", "")))
             if task.meta.get("assignee") else res.resolve("Agent/Obsidience"))
    agent_name = agent.title if agent and agent.kind == "agent" else "Obsidience"
    action_trace.emit("run", f"{agent_name} started {task.title}", [f"reasoning: {effort}"])
    if agent and agent.meta.get("tools"):
        grant = set(ALWAYS_ALLOWED)
        for raw in _links(agent.meta.get("tools")):
            tool_note = res.resolve(raw)
            binding = str(tool_note.meta.get("binding", "")) if tool_note and tool_note.kind == "tool" else ""
            grant.add(binding.removeprefix("builtin:") if binding else raw.strip("[]"))
        allowed = [t for t in allowed if t in grant]

    queries = [task.title, runbook.title]
    if params:
        queries.append(" ".join(f"{k} {v}" for k, v in list(params.items())[:6]))
    exclude = {task.ref, runbook.ref} | {s.ref for s in skills}
    brief = retrieval.briefing(queries, exclude=exclude)

    skills_block = "\n\n".join(
        f"### Skill: {s.title}\n{s.body.strip()[:2500]}" for s in skills
    )
    persona = (f"You are {agent_name}, an agent of the Obsidience vault.\n{agent.body.strip()}"
               if agent and agent.kind == "agent"
               else "You are the Obsidience interpreter executing one task from the vault.")
    system = "\n\n".join(filter(None, [
        persona,
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
    ctx = {"agent": agent_name, "task": task.ref}

    for _step in range(CONFIG.max_steps):
        try:
            reply = await llm.chat(messages, reasoning_effort=effort)
        except Exception as exc:  # noqa: BLE001 — surface LLM transport errors into the receipt
            status, summary = "failed", f"LLM error: {exc}"
            action_trace.emit("error", f"{task.title} LLM error", [str(exc)])
            break
        messages.append({"role": "assistant", "content": reply})
        action = llm.parse_action(reply)
        if not action:
            invalids = sum(1 for t in trace[-3:] if "invalid" in t)
            if invalids >= 2:
                status, summary = "failed", "three consecutive replies without a valid action block"
                action_trace.emit("error", f"{agent_name} produced no valid action", [summary])
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
            action_trace.emit("status", f"{agent_name} completed {task.title}: {status}", [summary])
            break
        action_trace.emit("tool", f"{agent_name} → {name}", [json.dumps(args, default=str)[:1000]])
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
        action_trace.emit("result", f"{name} returned", str(obs).splitlines()[:12])
        remaining = CONFIG.max_steps - _step - 1
        nudge = ("\n\n(FINAL STEP — call task.complete now with your best status and summary.)"
                 if remaining == 1 else
                 f"\n\n({remaining} steps remain — wrap up soon.)" if remaining <= 3 else "")
        messages.append({"role": "user", "content": f"Observation:\n{obs}{nudge}"})

    # acceptance criteria present and successful -> owner confirms unless auto_done
    if status == "completed" and task.meta.get("acceptance") and not task.meta.get("auto_done"):
        status = "review"

    finished = time.time()
    receipt_path = write_receipt(task, agent_name, run_id, status, summary, trace,
                                 started, finished, runbook, runbook_sha256,
                                 reasoning_effort=effort)
    update_status(task, status, {"last_run": run_id, "blocked_reason": None})
    INDEX.record_run(id=run_id, task_ref=task.ref, agent=agent_name, started=started,
                     finished=finished, status=status, summary=summary,
                     receipt_path=receipt_path, trace=json.dumps(trace)[:20000])
    INDEX.sync()
    action_trace.emit("status", f"{task.title} ended {status}", [summary])
    return {"run_id": run_id, "status": status, "summary": summary, "receipt": receipt_path}

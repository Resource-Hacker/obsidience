"""Bounded Runbook refinement over existing Tasks, executor, Source and Review.

AutoSaddler v2 supplies the matched-case and immutable-candidate design reference
(MIT, 30e20ce004486c58e7ee97c66182a8d0d41ec90e). No upstream engine is imported.
These are internal evaluation artifacts, not external Source intake or Articles.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from dataclasses import asdict, replace
from pathlib import Path

from ..config import CONFIG
from ..knowledge import format as article_format
from ..knowledge.index import INDEX
from ..knowledge.vault import Note, Resolver, load_note, resolver

GENERATOR = "Tasks/generate/runbook"
AUDITOR = "Tasks/audit"
DARWIN = "Agents/Darwin/Darwin"
HEIMDALL = "Agents/Heimdall/Heimdall"
MAX_ARTIFACT_BYTES = 512_000


def _json(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _root() -> Path:
    return CONFIG.source_dir / "evaluations"


def _identity(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
        raise ValueError("Evaluation identity must be an exact SHA256")
    return value


def _store(lane: str, document: dict) -> str:
    raw = _json(document).encode()
    if len(raw) > MAX_ARTIFACT_BYTES:
        raise ValueError("Evaluation artifact exceeds its byte bound")
    identity = _hash(raw)
    directory = _root() / lane
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (identity + ".json")
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise ValueError("Evaluation artifacts cannot follow symlinks")
    # Atomic publication keeps a killed writer from leaving an admitted partial
    # artifact. Existing content identities are immutable and byte-attested.
    from ..knowledge.vault import _atomic_write
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError("Evaluation artifact identity conflicts")
    else:
        _atomic_write(path, raw.decode())
    return identity


def _load(lane: str, identity: str) -> dict:
    path = _root() / lane / (_identity(identity) + ".json")
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise ValueError("Evaluation artifacts cannot follow symlinks")
    if path.stat().st_size > MAX_ARTIFACT_BYTES:
        raise ValueError("Evaluation artifact exceeds its byte bound")
    raw = path.read_bytes()
    if _hash(raw) != identity:
        raise ValueError("Evaluation artifact bytes changed")
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise ValueError("Evaluation artifact must be an object")
    return result


def _code_revision() -> str:
    paths = [Path(__file__), Path(__file__).with_name("evaluation.py"),
             Path(__file__).with_name("executor.py"),
             Path(__file__).parents[1] / "models" / "llm.py",
             Path(__file__).parents[1] / "models" / "context.py",
             Path(__file__).parents[1] / "models" / "runtime.py",
             Path(__file__).parents[1] / "knowledge" / "dependencies.py",
             Path(__file__).parents[1] / "capabilities" / "harness" / "evaluate.py"]
    return _hash(_json({str(path.relative_to(Path(__file__).parents[1])):
                        _hash(path.read_bytes()) for path in paths}).encode())


def _model_contract(task: Note, agent_ref: str) -> dict:
    from ..models import llm, runtime
    spec = runtime.resolve_model(task.meta.get("model"), agent_ref)
    return {"spec": json.loads(json.dumps(asdict(spec), default=str)),
            "profile": runtime._read_settings()["models"][spec.id],
            "reasoning_effort": llm.normalize_reasoning_effort(task.meta.get("reasoning_effort")),
            "temperature": CONFIG.llm_temperature, "executor_max_steps": CONFIG.max_steps}


def _notes(document: dict) -> list[Note]:
    out = []
    for ref, raw in document["articles"].items():
        meta, body = article_format.loads(raw)
        out.append(Note(ref + ".md", str(meta.get("title") or ref.rsplit("/", 1)[-1]), meta, body))
    return out


def prepare_case(specification: dict) -> dict:
    """Developer-owned fixture registration; no model-authored expectations.

    Freeze exact accepted dependencies and a real originating execution. This
    is an explicit reconstruction, never a claim that clipped trace is replay.
    """
    from .evaluation import validate_suite
    from .executor import resolve_spine
    validate_suite(specification["suite"])
    required = {"schema_version", "task", "runbook", "origin_run_id", "problem", "suite"}
    if set(specification) != required or specification["schema_version"] != 1:
        raise ValueError("Invalid case specification fields")
    if not isinstance(specification["problem"], str) or not 1 <= len(specification["problem"]) <= 2000:
        raise ValueError("Case requires a bounded problem statement")
    res = resolver()
    task = res.resolve(specification["task"])
    if task is None or task.kind != "task" or task.ref != specification["task"]:
        raise ValueError("Case requires one exact accepted Task")
    spine = resolve_spine(task, res)
    books = spine.get("runbooks", [])
    if "error" in spine or len(books) != 1 or books[0].ref != specification["runbook"] or books[0].children:
        raise ValueError("First refinement slice requires one applicable leaf Runbook")
    agent = res.resolve(str(task.meta.get("assignee", "")))
    if agent is None or agent.kind != "agent":
        raise ValueError("Case Task requires one accepted Agent")
    origin = INDEX.run(str(specification["origin_run_id"]))
    if not origin or origin.get("task_ref") != task.ref or origin.get("status") not in {"failed", "blocked", "completed"}:
        raise ValueError("Case requires a real terminal execution of its exact Task")
    if origin.get("runbook_ref") != books[0].ref:
        raise ValueError("Origin execution must identify the subject Runbook")
    selected = [agent, task, *books, *spine["skills"], *spine["tool_articles"]]
    articles = {note.ref: (CONFIG.vault_dir / note.path).read_text() for note in selected}
    allowed = {tool.title for tool in spine["tool_articles"]} | {"task.complete"}
    for case in specification["suite"]["cases"]:
        named = {response["tool"] for response in case["responses"]} | set(case["expected"]["required_tools"])
        if named - allowed:
            raise ValueError("Fixture names Tools outside the accepted Task authority")
    document = {**specification, "agent": agent.ref, "articles": articles,
                "base_sha256": _hash(articles[books[0].ref].encode()),
                "model_contract": _model_contract(task, agent.ref),
                "evaluator_revision": _code_revision(),
                "origin": {key: origin.get(key) for key in (
                    "id", "task_ref", "runbook_ref", "runbook_sha256", "status", "summary")},
                "evidence_scope": "Explicit regression reconstruction from a recorded execution; not complete historical replay."}
    identity = _store("cases", document)
    return {"case_id": identity, "task": task.ref, "runbook": books[0].ref,
            "source_path": str((_root() / "cases" / (identity + ".json")).relative_to(CONFIG.project_root))}


def _current(case_id: str, *, accepted_resolver: Resolver | None = None) -> dict:
    document = _load("cases", case_id)
    from .evaluation import validate_suite
    validate_suite(document["suite"])
    for ref, raw in document["articles"].items():
        if (CONFIG.vault_dir / (ref + ".md")).read_text() != raw:
            raise ValueError(f"Frozen Article changed: {ref}; prepare a fresh case")
    notes = Resolver(_notes(document))
    from .executor import resolve_spine
    current = accepted_resolver if accepted_resolver is not None else resolver()
    current_task = current.resolve(document["task"])
    current_spine = resolve_spine(current_task, current)
    frozen_spine = resolve_spine(notes.resolve(document["task"]), notes)
    def identities(spine):
        return {key: [note.ref for note in spine.get(key, [])]
                for key in ("runbooks", "skills", "tool_articles")}
    if "error" in current_spine or identities(current_spine) != identities(frozen_spine):
        raise ValueError("Current Task dependency selection changed after case preparation")
    if _model_contract(notes.resolve(document["task"]), document["agent"]) != document["model_contract"]:
        raise ValueError("Task model configuration changed after case preparation")
    if _code_revision() != document["evaluator_revision"]:
        raise ValueError("Evaluator implementation changed; prepare a fresh case")
    return document


def _envelope(case_id: str, document: dict) -> dict:
    return {"case_id": case_id, "case_sha256": case_id, "subject_task": document["task"],
            "subject_agent": document["agent"], "runbook_ref": document["runbook"],
            "base_sha256": document["base_sha256"], "evaluator_revision": document["evaluator_revision"]}


def activation_context(case_id: str) -> dict:
    document = _current(case_id)
    return {**_envelope(case_id, document),
            "objective": "Investigate this recorded failure and propose one body-only refinement of "
                         + document["runbook"] + ". Preserve the accepted title, metadata, Skills and Tool authority.",
            "problem": document["problem"], "origin": document["origin"],
            "evidence_scope": document["evidence_scope"],
            "training_cases": [case for case in document["suite"]["cases"] if case["split"] == "train"],
            "output": document["runbook"] + ".md",
            "acceptance": "Independent Heimdall evaluation and ordinary Review; these examples alone cannot establish acceptance."}


def proposal_context(context: dict) -> dict | None:
    params = context.get("params")
    case_id = params.get("refinement_case") if isinstance(params, dict) else None
    if not case_id:
        return None
    if context.get("task") != GENERATOR or not context.get("run_id"):
        raise ValueError("Runbook refinement requires an active Generate Runbook execution")
    generator = load_note(GENERATOR + ".md")
    if generator is None or generator.meta.get("assignee") != f"[[{DARWIN}]]":
        raise ValueError("Darwin must own Runbook refinement")
    envelope = _envelope(case_id, _current(case_id))
    receipt_id = "refinement-author-" + _hash(str(context["run_id"]).encode())
    origin = INDEX.run(receipt_id)
    witness = _json([{"case_id": case_id, "generator_run_id": context["run_id"]}])
    if origin is not None and origin.get("trace") != witness:
        raise ValueError("One Generate execution cannot switch refinement cases")
    if origin is None:
        now = time.time()
        INDEX.record_run(id=receipt_id, task_ref=GENERATOR, agent="interpreter", started=now,
            finished=now, status="dispatched", objective="Bound Runbook refinement",
            summary="Generate bound to an immutable refinement case", trace=witness, overwrite=False)
    return envelope


def validate_candidate(target: str, action: str, title: str, body: str,
                       authored_meta: dict, envelope: dict) -> None:
    document = _current(envelope["case_id"])
    _validate_candidate_body(target, action, title, body, authored_meta, envelope, document)


def _validate_candidate_body(target: str, action: str, title: str, body: str,
                             authored_meta: dict, envelope: dict, document: dict) -> None:
    """Validate candidate content against the caller's already-attested case."""
    from ..capabilities.vault.propose import validate_generated_runbook
    if envelope != _envelope(envelope["case_id"], document):
        raise ValueError("Refinement context changed")
    book = Resolver(_notes(document)).resolve(document["runbook"])
    if action != "update" or target != book.path or title != book.title or authored_meta:
        raise ValueError("Refinement is a body-only update of the exact Runbook; omit all metadata and preserve its title")
    if body.strip() == book.body.strip():
        raise ValueError("Refinement must contain a concrete candidate change")
    skills = book.meta.get("skills") or []
    validate_generated_runbook(target, body, {"output_runbook": target, "skills": skills,
        "tools": [str(ref).strip("[]").replace("Skills/", "Tools/", 1) for ref in skills]}, skills,
        allow_implicit_completion=True)


def _proposal(name: str) -> Note:
    if not isinstance(name, str) or Path(name).name != name or not name.endswith(".md"):
        raise ValueError("Evaluation requires one exact pending proposal filename")
    note = load_note("_staging/" + name)
    if note is None or not isinstance(note.meta.get("refinement"), dict):
        raise ValueError("Proposal is not a pending Runbook refinement")
    return note


def candidate_staged(staged_path: str, context: dict) -> None:
    note = _proposal(Path(staged_path).name)
    if note.meta.get("run_id") != context.get("run_id"):
        raise ValueError("Refinement handoff must match its generating execution")
    _queue_evaluation(note)


def _queue_evaluation(note: Note) -> None:
    from .scheduler import enqueue_named_event
    digest = _hash((CONFIG.vault_dir / note.path).read_bytes())
    receipt_id = "runbook-evaluation-" + digest
    if INDEX.run(receipt_id):
        return
    audit = load_note(AUDITOR + ".md")
    if audit is None or audit.meta.get("assignee") != f"[[{HEIMDALL}]]":
        raise ValueError("Heimdall Audit is unavailable")
    results = enqueue_named_event("runbook.proposed", {
        "proposal": Path(note.path).name, "proposal_sha256": digest,
        "refinement_case": note.meta["refinement"]["case_id"],
        "activation_key": receipt_id, "queue_after_review": True,
    }, expected_task=AUDITOR)
    if len(results) != 1 or results[0]["state"] not in {"started", "queued", "processed"}:
        raise ValueError("Runbook evaluation could not enter the existing Audit queue")
    now = time.time()
    INDEX.record_run(id=receipt_id, task_ref=AUDITOR, agent="scheduler", started=now,
        finished=now, status="dispatched", summary="Runbook candidate admitted to independent Audit",
        objective="Evaluate a proposed Runbook", trace=_json([{"proposal_sha256": digest}]), overwrite=False)


def reconcile_candidates() -> None:
    """Recover a stage-to-queue interruption on the existing scheduler tick."""
    for path in sorted(CONFIG.staging_dir.glob("*.md")):
        note = load_note(str(path.relative_to(CONFIG.vault_dir)))
        if note and isinstance(note.meta.get("refinement"), dict):
            try:
                _queue_evaluation(note)
            except (OSError, ValueError):
                # The exact pending Review retains the failure for inspection;
                # an unavailable Auditor cannot break other scheduled work.
                continue


def _validate_proposal(note: Note, *, accepted_resolver: Resolver | None = None) -> tuple[dict, str]:
    envelope = note.meta["refinement"]
    document = _current(envelope["case_id"], accepted_resolver=accepted_resolver)
    if (note.meta.get("task") != GENERATOR or not note.meta.get("run_id")
            or note.meta.get("base_sha256") != document["base_sha256"]
            or envelope != _envelope(envelope["case_id"], document)
            or note.meta.get("authored_fields") != []):
        raise ValueError("Refinement proposal provenance or authority changed")
    _validate_candidate_body(note.meta["target"], note.meta["action"], note.title,
                             note.body, {}, envelope, document)
    return document, _hash((CONFIG.vault_dir / note.path).read_bytes())


def _result(report_id: str, report: dict) -> dict:
    return {"evaluation_report": report_id, "verdict": report["comparison"]["verdict"],
            "comparison": report["comparison"], "proposal": report["proposal"],
            "source_path": str((_root() / "reports" / report["proposal_sha256"] / (report_id + ".json")).relative_to(CONFIG.project_root)),
            "scope": "Frozen Tool simulation; no live effects or historical replay. Review remains required."}


def _compare(document: dict, observations: dict) -> dict:
    from .evaluation import compare_observations
    expected = [(case["id"], case["split"], repetition)
                for case in document["suite"]["cases"]
                for repetition in range(1, document["suite"]["repetitions"] + 1)]
    for variant in ("baseline", "candidate"):
        actual = [(row.get("case_id"), row.get("split"), row.get("repetition"))
                  for row in observations[variant]]
        if actual != expected:
            raise ValueError("Evaluation does not cover the complete frozen case suite")
    return compare_observations(observations["baseline"], observations["candidate"])


async def evaluate_proposal(name: str, context: dict) -> dict:
    from . import executor, trace as action_trace
    from .evaluation import FrozenTrial
    from ..models import llm, runtime
    params = context.get("params") or {}
    if context.get("task") != AUDITOR or not context.get("run_id") or params.get("proposal") != name:
        raise ValueError("Evaluation requires the exact candidate bound to an active Audit")
    audit = load_note(AUDITOR + ".md")
    if audit is None or audit.meta.get("assignee") != f"[[{HEIMDALL}]]":
        raise ValueError("Independent Heimdall ownership is required")
    note = _proposal(name)
    document, digest = _validate_proposal(note)
    if params.get("proposal_sha256") != digest or params.get("refinement_case") != note.meta["refinement"]["case_id"]:
        raise ValueError("Audit candidate identity changed after admission")
    if context["run_id"] == note.meta["run_id"]:
        raise ValueError("Candidate author cannot evaluate its own proposal")
    frozen = Resolver(_notes(document))
    task, agent = frozen.resolve(document["task"]), frozen.resolve(document["agent"])
    spine = executor.resolve_spine(task, frozen)
    model = runtime.resolve_model(task.meta.get("model"), agent.ref)
    allowed = sorted({tool.title for tool in spine["tool_articles"]} | {"task.complete"})
    observations = {"baseline": [], "candidate": []}
    # Pair adjacent trials to reduce drift; each model lease is released by the
    # ordinary executor. Foreground preemption cancels the owning Audit Tool.
    for case in document["suite"]["cases"]:
        for repetition in range(1, document["suite"]["repetitions"] + 1):
            for variant in observations:
                selected = spine if variant == "baseline" else {**spine,
                    "runbook": replace(spine["runbook"], body=note.body),
                    "runbooks": [replace(spine["runbook"], body=note.body)]}
                sections = {}
                executor._activation_packet(task, agent, selected,
                    executor.ActivationBinding(case["objective"], case.get("bindings", {})),
                    "", case.get("knowledge", ""), case.get("conversation", ""),
                    accepted_resolver=frozen, provider_sections=sections)
                messages = [{"role": "system", "content": "\n\n".join([
                    f"You are {agent.title}, executing one graph-selected Task in Obsidience.",
                    executor.LAWS, llm.PROTOCOL, sections["provider_system"]])}]
                if sections["provider_conversation"]:
                    messages.append({"role": "user", "content": sections["provider_conversation"]})
                messages.append({"role": "user", "content": sections["provider_user"]})
                trial, trial_context = FrozenTrial(case), {}
                started = time.monotonic()
                trial_id = _hash(_json([context["run_id"], case["id"], variant, repetition]).encode())
                token = action_trace.bind_trial(trial_id, case_id=case["id"], split=case["split"],
                                               variant=variant, repetition=repetition)
                try:
                    action_trace.emit("status", "Trial started")
                    try:
                        async with asyncio.timeout(180):
                            trace, status, summary = await executor._execute_session(
                                task, model, messages, allowed, trial_context, agent.title,
                                document["model_contract"]["reasoning_effort"],
                                interruption_event=context.get("_foreground_interruption_event"), evaluation=trial)
                        error = trial.error
                        if not any(row.get("tool") == "task.complete" for row in trace):
                            error = error or "Trial ended without a completion"
                    except asyncio.CancelledError:
                        action_trace.emit("status", "Trial cancelled")
                        raise
                    except Exception as exc:
                        trace, status, summary, error = [], "failed", "Evaluation could not finish", type(exc).__name__
                    observations[variant].append({"case_id": case["id"], "split": case["split"],
                        "repetition": repetition, "passed": trial.passed and error is None, "error": error,
                        "status": status, "summary": summary[:2000], "tool_count": trial.tool_count,
                        "duration_ms": round((time.monotonic() - started) * 1000, 3),
                        "prompt_tokens": trial_context.get("prompt_tokens"),
                        "trace_sha256": _hash(_json(trace).encode()), "actions": trial.calls})
                    action_trace.emit("status", "Trial finished", [
                        "Fixed criteria passed" if trial.passed and error is None else "Fixed criteria not satisfied",
                        *(["Incomplete evidence: " + error] if error else []),
                    ])
                finally:
                    action_trace.reset(token)
    # Revalidate after the provider work. A changed candidate or contract cannot
    # acquire an acceptance receipt from an evaluation of earlier bytes.
    current, current_digest = _validate_proposal(_proposal(name))
    if current != document or current_digest != digest:
        raise ValueError("Candidate changed during evaluation")
    report = {"schema_version": 1, "proposal": name, "proposal_sha256": digest,
        "case_id": note.meta["refinement"]["case_id"], "base_sha256": document["base_sha256"],
        "evaluator_revision": document["evaluator_revision"], "model_contract": document["model_contract"],
        "audit_run_id": context["run_id"], "generator_run_id": note.meta["run_id"],
        "observations": observations, "comparison": _compare(document, observations)}
    report_id = _store("reports/" + digest, report)
    return _result(report_id, report)


def review_blocker(note: Note, *, accepted_resolver: Resolver | None = None) -> str | None:
    envelope = note.meta.get("refinement")
    if envelope is None:
        # Removing the marker from a refinement-authored proposal is not a way
        # to bypass evaluation. The original execution parameters attest it.
        origin = INDEX.run("refinement-author-" + _hash(str(note.meta.get("run_id", "")).encode()))
        if origin is not None:
            return "Refinement candidate lost its controller binding"
        return None
    try:
        if not isinstance(envelope, dict):
            raise ValueError("Malformed refinement binding")
        document, digest = _validate_proposal(note, accepted_resolver=accepted_resolver)
        reports = sorted((_root() / "reports" / digest).glob("*.json"))
        if len(reports) > 32:
            raise ValueError("Too many evaluation attempts; prepare a new case")
        reason = "Independent Heimdall evaluation is pending"
        for path in reports:
            report = _load("reports/" + digest, path.stem)
            if (report.get("proposal_sha256") != digest or report.get("case_id") != envelope["case_id"]
                    or report.get("evaluator_revision") != document["evaluator_revision"]
                    or report.get("model_contract") != document["model_contract"]
                    or report.get("generator_run_id") != note.meta.get("run_id")
                    or report.get("audit_run_id") == note.meta.get("run_id")):
                continue
            run_id = str(report.get("audit_run_id", ""))
            run, receipts = INDEX.run(run_id), INDEX.tool_run_receipts(run_id)
            if not run or run.get("task_ref") != AUDITOR or run.get("status") != "completed" or not receipts:
                continue
            result = json.dumps(_result(path.stem, report), sort_keys=True)
            receipt_hash = _hash(json.dumps(result, sort_keys=True).encode())
            if receipts.get("task_ref") != AUDITOR or not any(
                call["tool"] == "harness.evaluate" and call["status"] == "returned"
                and call["result_sha256"] == receipt_hash for call in receipts["calls"]):
                continue
            comparison = _compare(document, report["observations"])
            if comparison != report["comparison"]:
                continue
            if comparison["verdict"] == "passed":
                return None
            reason = "Independent evaluation: " + comparison["verdict"] + "; candidate is not eligible for approval"
        return reason
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return "Runbook evaluation is stale or invalid: " + str(exc)

"""Adapter for the executor-owned ``task.complete`` terminal decision."""

from __future__ import annotations

from pathlib import Path
import unicodedata

from obsidience.harness.computer.applications import canonical_application_id

MAX_EVIDENCE_ITEMS = 8
MAX_EVIDENCE_CHARS = 500
MAX_VISUAL_VERIFICATION_CHARS = 1000

COMPUTER_OUTCOME_TOOLS = {
    "focus": "window.activate",
    "placement": "window.place",
    "observe": "computer.observe",
    "action": "computer.act",
    "launch": "application.launch",
}


def validate_computer_outcome(outcome: object, scope: object = None) -> str | None:
    """Validate a controller binding without classifying request prose."""
    if outcome is None or outcome == "" or outcome == "answer":
        return None if scope is None or scope == "" else "an answer cannot carry a computer scope"
    if not isinstance(outcome, str) or outcome not in COMPUTER_OUTCOME_TOOLS:
        return "the controller's requested computer outcome is invalid"
    if outcome == "action":
        if not isinstance(scope, str) or scope not in {"input", "state"}:
            return "an action requires an explicit computer_scope of input or state"
    elif scope is not None and scope != "":
        return "computer_scope applies only to an action outcome"
    return None


def _computer_target(value: object) -> dict | None:
    """Keep only the Tool's bounded public identity, never private window IDs."""
    if not isinstance(value, dict):
        return None
    kind, name = value.get("kind"), value.get("name")
    if (
        kind not in ("application", "pane")
        or not isinstance(name, str)
        or not name
        or len(name) > (256 if kind == "application" else 48)
        or any(ord(character) < 32 or ord(character) == 127 for character in name)
    ):
        return None
    if kind == "application":
        name = canonical_application_id(name) or name
    return {"kind": kind, "name": name}


def computer_request_target_error(name: str, args: dict, context: dict) -> str | None:
    """Reject an explicit contradiction of the controller's application binding.

    Missing/malformed arguments remain with the Capability's own validator.
    A focused observation may resolve normally; acceptance checks its witness.
    """
    if name not in COMPUTER_OUTCOME_TOOLS.values():
        return None
    params = context.get("params") if isinstance(context.get("params"), dict) else {}
    if not params.get("application"):
        return None
    binding = _computer_target({"kind": "application", "name": params["application"]})
    if binding is None:
        return "The controller's requested application binding is invalid."
    application = binding["name"]
    if name in {"application.launch", "computer.act"}:
        target = _computer_target({"kind": "application", "name": args.get("application")})
    else:
        target = _computer_target(args.get("target"))
    if target is None or target == {"kind": "application", "name": application}:
        return None
    return (
        f"The explicit Tool target contradicts the requested application {application}. "
        "Nothing was dispatched. Correct the target using that canonical binding; "
        "do not substitute another application or pane."
    )


def computer_completion_evidence(
    name: str, result: dict | None, *, image_attached: bool = False,
) -> dict | None:
    """Project a real Tool result for acceptance, before trace text is truncated.

    Only the executor calls this after dispatch. Model-authored summary and
    evidence strings cannot substitute for this bounded controller witness.
    """
    if name not in COMPUTER_OUTCOME_TOOLS.values():
        return None
    result = result or {}
    target = _computer_target(result.get("target"))
    verified = False
    effect = None
    if name == "window.activate":
        verified = result.get("status") == "completed" and result.get("active") is True
    elif name == "window.place":
        destination = result.get("destination") or {}
        observed = result.get("observed") or {}
        verified = (
            result.get("status") == "completed"
            and isinstance(destination, dict)
            and isinstance(observed, dict)
            and bool(destination.get("surface"))
            and observed.get("surface") == destination.get("surface")
            and (
                "tile" not in destination
                or (
                    isinstance(destination["tile"], dict)
                    and set(destination["tile"]) == {"left", "top", "right", "bottom"}
                    and all(type(value) is int for value in destination["tile"].values())
                    and isinstance(observed.get("tile"), dict)
                    and all(type(value) is int for value in observed["tile"].values())
                    and observed["tile"] == destination["tile"]
                )
            )
        )
    elif name == "application.launch":
        target = _computer_target({"kind": "application", "name": result.get("application")})
        verified = (
            result.get("state") == "ready"
            and result.get("ready") is True
            and isinstance(result.get("window"), dict)
            and bool(result["window"])
        )
    elif name == "computer.observe":
        observation = result.get("observation") or {}
        target = _computer_target(observation.get("target")) if isinstance(observation, dict) else None
        visual = (
            observation.get("visual_evidence") or {}
            if isinstance(observation, dict) else {}
        )
        verified = (
            isinstance(observation, dict)
            and observation.get("status") == "observed"
            and isinstance(visual, dict)
            and visual.get("freshness") == "validated_after_capture"
            and visual.get("attached") is True
            and image_attached
        )
    elif name == "computer.act":
        observed = result.get("observation")
        clicked = result.get("effect")
        visual = observed.get("visual_evidence") if isinstance(observed, dict) else None
        label = clicked.get("label") if isinstance(clicked, dict) else None
        verified = (
            result.get("status") == "completed"
            and result.get("delivery") == "acknowledged"
            and isinstance(clicked, dict)
            and clicked.get("kind") == "click"
            and clicked.get("verified") is True
            and isinstance(label, str)
            and 0 < len(label) <= 300
            and bool(label.strip())
            and not any(ord(character) < 32 or ord(character) == 127 for character in label)
            and target is not None
            and target["kind"] == "application"
            and isinstance(observed, dict)
            and observed.get("status") == "observed"
            and _computer_target(observed.get("target")) == target
            and observed["target"].get("surface") == result["target"].get("surface")
            and isinstance(visual, dict)
            and visual.get("freshness") == "validated_after_capture"
            and visual.get("attached") is True
            and image_attached
        )
        if verified:
            # This witnesses the grounded click, never the optional semantic
            # postcondition suggested in the model's Tool arguments.
            effect = {"kind": "click", "label": _normalized_click_text(label)}
    return {
        "verified": bool(verified and target),
        **({"target": target} if target else {}),
        **({"effect": effect} if effect else {}),
        **({"verified_scope": "click", "semantic_postcondition_verified": False} if effect else {}),
    }


def _normalized_click_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _computer_completion_error(task, status: str, context: dict, verification=None) -> str | None:
    if status != "completed":
        return None
    params = context.get("params") if isinstance(context.get("params"), dict) else {}
    outcome = params.get("computer_outcome", "")
    scope = params.get("computer_scope")
    invalid = validate_computer_outcome(outcome, scope)
    if invalid:
        return invalid
    if task.ref != "Tasks/executive/operate":
        if outcome in COMPUTER_OUTCOME_TOOLS:
            return "the controller-bound computer outcome requires the Computer Use Task; the selected Task does not match"
        return None
    expected = COMPUTER_OUTCOME_TOOLS.get(outcome)
    candidates = [
        item for item in context.get("trace", [])
        if isinstance(item, dict)
        and item.get("tool") in (
            {expected} if expected else COMPUTER_OUTCOME_TOOLS.values()
        )
    ]
    witness = candidates[-1].get("completion_evidence") if candidates else None
    if candidates and candidates[-1].get("tool") == "computer.act" and isinstance(witness, dict):
        effect = witness.get("effect")
        if not (
            witness.get("verified_scope") == "click"
            and witness.get("semantic_postcondition_verified") is False
            and isinstance(effect, dict)
            and effect.get("kind") == "click"
            and isinstance(effect.get("label"), str)
            and bool(effect["label"])
        ):
            witness = None
    if (
        isinstance(witness, dict)
        and witness.get("verified") is True
        and _computer_target(witness.get("target")) is not None
    ):
        application = params.get("application")
        if application:
            bound = _computer_target({"kind": "application", "name": application})
            if bound is None or witness.get("target") != bound:
                return (
                    "The verified Tool result does not match the controller's "
                    "requested application. Do not claim completion for a different "
                    "target; report the mismatch and never replay uncertain delivery."
                )
        if outcome == "action" and scope == "state":
            current = context.get("_computer_response_observation")
            if not (
                isinstance(current, dict)
                and current.get("verified") is True
                and _computer_target(current.get("target")) == witness["target"]
            ):
                return (
                    "the requested application state requires the actual fresh post-action image "
                    "in this completion response, for the same Task action and target; "
                    "a click receipt or historical evidence cannot establish it"
                )
            if not verification or verification["status"] != "established":
                return (
                    "the requested application state requires verification with status established "
                    "and an observation describing the visible evidence for the bound objective; "
                    "if the image does not establish it, finish failed without replaying input"
                )
        return None
    required = expected or "the selected computer Tool"
    return (
        f"Computer Use completion requires a verified result from {required} "
        "in this execution. Intent, a failed Tool, input acknowledgement, and "
        "model-authored evidence do not establish that outcome. If the target "
        "is unclear, finish failed with the clarification question in summary; "
        "otherwise report the exact blocker. Never replay uncertain delivery."
    )


def _staged_proposal_states(context: dict) -> tuple[list[dict], list[dict], list[dict]]:
    """Return pending, approved, and rejected controller-bound proposals."""
    from obsidience.harness.config import CONFIG
    from obsidience.harness.knowledge.index import INDEX

    pending: list[dict] = []
    approved: list[dict] = []
    rejected: list[dict] = []
    for item in context.get("staged_proposals") or []:
        if not isinstance(item, dict):
            continue
        if item.get("auto_approved") is True:
            approved.append(item)
            continue
        staged = str(item.get("staged", "")).strip()
        if not staged:
            pending.append(item)
            continue
        path = Path(staged)
        if not path.is_absolute():
            path = CONFIG.vault_dir / path
        if path.is_file():
            pending.append(item)
            continue
        decision = INDEX.review_decision(Path(staged).name)
        if not decision or any(
            decision.get(key) != value
            for key, value in {
                "run_id": str(context.get("run_id", "")),
                "task_ref": str(context.get("task", "")),
                "target": str(item.get("target", "")),
            }.items()
        ):
            pending.append(item)
        elif decision["decision"] == "approved":
            approved.append(item)
        else:
            rejected.append(item)
    return pending, approved, rejected


def _pending_staged_proposals(context: dict) -> list[dict]:
    return _staged_proposal_states(context)[0]


def _approved_staged_proposals(context: dict) -> list[dict]:
    return _staged_proposal_states(context)[1]


def _generated_runbook_completion_error(status: str, context: dict) -> str | None:
    from obsidience.harness.execution.refinement import proposal_context

    try:
        refinement = proposal_context(context) if context.get("task") == "Tasks/generate/runbook" else None
    except (OSError, ValueError) as exc:
        return None if status == "failed" else f"Runbook refinement context is invalid: {exc}"
    if refinement is not None:
        from obsidience.harness.knowledge.vault import load_note

        expected = refinement["runbook_ref"] + ".md"
        matched = False
        for item in _pending_staged_proposals(context):
            if item.get("target") != expected or item.get("action") != "update":
                continue
            staged = load_note(str(item.get("staged", "")))
            if staged is not None and staged.meta.get("refinement") == refinement:
                matched = True
                break
        if matched and status != "review":
            return 'a staged Runbook refinement must finish with status "review"'
        if not matched and status != "failed":
            return f'no validated refinement proposal for {expected} was staged; finish with "failed" or stage that update'
        return None
    if context.get("event") != "task.assigned":
        return None
    params = context.get("params")
    if not isinstance(params, dict):
        return "Runbook generation is missing assignment event parameters"
    expected = str(params.get("output_runbook", "")).strip()
    staged = _pending_staged_proposals(context)
    matched = any(
        isinstance(item, dict)
        and item.get("target") == expected
        and item.get("action") in {"create", "update"}
        for item in (staged if isinstance(staged, list) else [])
    )
    if matched and status != "review":
        return 'a staged Runbook must finish with status "review"'
    if not matched and status != "failed":
        return (
            f"no validated proposal for {expected or '(missing output path)'} was staged "
            'during this execution; call vault.propose, then finish with status "review"'
        )
    return None


def _runbook_evaluation_completion_error(status: str, context: dict) -> str | None:
    params = context.get("params")
    if (context.get("task") != "Tasks/audit" or not isinstance(params, dict)
            or not params.get("refinement_case") or not params.get("proposal")):
        return None
    if status == "failed":
        return None
    if status != "completed":
        return "Runbook evaluation Audit reports its finding as completed; it does not stage its own Review"
    evaluation = context.get("_harness_evaluation")
    if (not isinstance(evaluation, dict) or evaluation.get("proposal") != params["proposal"]
            or not isinstance(evaluation.get("evaluation_report"), str) or not evaluation["evaluation_report"].strip()
            or not isinstance(evaluation.get("verdict"), str)
            or evaluation.get("verdict") not in {"passed", "not_improved", "regressed", "incomplete"}):
        return "Runbook evaluation Audit requires the actual harness.evaluate result for its exact proposal"
    return None


def _completion_error(
    task,
    status: str,
    outcome: str,
    evidence: list[str],
    context: dict,
    verification=None,
) -> str | None:
    from obsidience.harness.capabilities.source.read import bound_read_error, required_source

    if status != "failed":
        if error := bound_read_error(context):
            return error
        bound = required_source(context)
        if bound and status == "completed" and not context.get("handoff_source_id"):
            if task.ref == "Tasks/research/distill":
                return "Distill completion requires its successful source.handoff; otherwise finish failed with the actual blocker"
            citation = bound["citation"]
            from obsidience.harness.knowledge.source import SourceError, validate_source_citations

            try:
                citations = validate_source_citations("\n".join(evidence), required=True)
            except (SourceError, OSError) as exc:
                return "Source-bound Learn completion evidence is invalid: " + str(exc)
            if outcome != "no_change" or not any(
                item["citation"] == citation and item["content_sha256"] == bound["content_sha256"]
                for item in citations
            ):
                return (
                    "Source-bound Learn completion requires successful source.handoff, or "
                    'outcome "no_change" with explicit evidence citing ' + citation
                )
    if task.ref == "Tasks/repair" and status == "completed":
        from obsidience.harness.execution.repair import PASS_ATTEMPT_LIMIT, repair_attempt_count

        snapshot = context.get("_harness_snapshot")
        if not isinstance(snapshot, dict) or snapshot.get("status") not in {"healthy", "degraded"}:
            return "Repair completion requires a current harness.status snapshot after the last recovery operation"
        if (repair_attempt_count(context) < PASS_ATTEMPT_LIMIT
                and any(row.get("operation") == "retry" for row in snapshot.get("repair_plan", []) if isinstance(row, dict))):
            return "Repair still has an eligible recovery operation; perform it or report the pass failed"
    error = _generated_runbook_completion_error(status, context)
    if error:
        return error
    error = _runbook_evaluation_completion_error(status, context)
    if error:
        return error
    error = _computer_completion_error(task, status, context, verification)
    if error:
        return error
    staged, approved, rejected = _staged_proposal_states(context)
    if staged and status != "review":
        return 'an execution with staged proposals must finish with status "review"'
    if outcome and outcome not in {"changed", "no_change"}:
        return "outcome must be changed or no_change"
    if outcome == "no_change" and status != "completed":
        return 'outcome "no_change" requires status "completed"'
    if outcome == "no_change" and staged:
        return 'outcome "no_change" cannot accompany staged proposals'
    if outcome == "no_change" and approved:
        return 'outcome "no_change" cannot accompany an approved change'
    if outcome == "no_change" and rejected:
        return 'outcome "no_change" cannot accompany a reviewed proposal'
    if outcome == "no_change" and not evidence:
        return 'outcome "no_change" requires explicit evidence'

    params = context.get("params") if isinstance(context.get("params"), dict) else {}
    if (task.ref == "Tasks/ingest" and context.get("event") == "source.inbox"
            and params.get("feed_binding") and status == "completed"
            and not any((context.get("feed_publication_result") or {}).get(key)
                        for key in ("auto_approved", "already_current"))):
        return "Feed Ingest completion requires its actual bound publication; disabled Auto-curate remains Review"
    evidence_bound_completion = bool(
        context.get("maintenance_candidate")
        or (
            task.ref == "Tasks/ingest"
            and context.get("event") == "source.inbox"
        )
        or (
            task.ref in {"Tasks/research/question", "Tasks/research/learn"}
            and params.get("created_by_run_id")
            and not context.get("handoff_source_id")
        )
    )
    if (
        status == "completed"
        and not staged
        and not approved
        and not rejected
        and evidence_bound_completion
        and (
            outcome != "no_change" or not evidence
        )
    ):
        return (
            "this evidence-bound execution has no staged change; complete with "
            'outcome "no_change" and explicit evidence'
        )
    if status != "review":
        return None
    staged_targets = {
        str(item.get("target", ""))
        for item in (staged or [])
        if isinstance(item, dict) and item.get("target")
    }
    from obsidience.harness.knowledge.review import list_proposals

    incomplete = [
        row
        for row in list_proposals()
        if (
            str(row.get("task", "")) == task.ref
            or str(row.get("target", "")) in staged_targets
        )
        and str(row.get("blocked_reason", "")).startswith(
            "Merge is incomplete; no redirect proposal exists for:"
        )
    ]
    if incomplete:
        detail = " | ".join(str(row["blocked_reason"]) for row in incomplete)
        return (
            "review cannot complete while an archive lacks redirect proposals. "
            + detail
            + ". Read every exact missing Article, stage its complete redirect update, "
            "then call task.complete again."
        )
    if staged:
        return None
    if task.meta.get("acceptance"):
        return None
    return (
        "review requires a proposal staged by this exact execution or an explicit "
        "acceptance gate authored on the Task; a deferred downstream activation "
        "completes the calling Task honestly"
    )


def execute(args: dict, context: dict) -> dict:
    from obsidience.harness.knowledge.vault import resolver

    args = args or {}
    context = context or {}
    requested_status = str(args.get("status", "completed")).strip()
    if requested_status not in ("completed", "failed", "review"):
        return {
            "accepted": False,
            "status": "",
            "summary": "",
            "outcome": "",
            "evidence": [],
            "error": "status must be completed, failed, or review",
        }
    outcome = str(args.get("outcome", "")).strip()
    raw_evidence = args.get("evidence", [])
    if raw_evidence is None:
        raw_evidence = []
    if not isinstance(raw_evidence, list) or len(raw_evidence) > MAX_EVIDENCE_ITEMS:
        return {
            "accepted": False,
            "status": requested_status,
            "summary": "",
            "outcome": outcome,
            "evidence": [],
            "error": f"evidence must be a list with at most {MAX_EVIDENCE_ITEMS} entries",
        }
    evidence = [
        " ".join(item.split())
        for item in raw_evidence
        if isinstance(item, str) and item.strip()
    ]
    if len(evidence) != len(raw_evidence) or any(
        len(item) > MAX_EVIDENCE_CHARS for item in evidence
    ):
        return {
            "accepted": False,
            "status": requested_status,
            "summary": "",
            "outcome": outcome,
            "evidence": [],
            "error": (
                "evidence entries must be nonempty strings of at most "
                f"{MAX_EVIDENCE_CHARS} characters"
            ),
        }
    approved = _approved_staged_proposals(context)
    if requested_status == "completed" and approved:
        if not outcome:
            outcome = "changed"
        if not evidence:
            evidence = [
                (
                    (
                        "Owner Auto-curate approved "
                        if item.get("auto_approved") is True
                        else "Owner review approved "
                    )
                    + str(item.get("target", "")).strip()
                )[:MAX_EVIDENCE_CHARS]
                for item in approved[:MAX_EVIDENCE_ITEMS]
                if str(item.get("target", "")).strip()
            ]
    task = context.get("task_note")
    if task is None:
        task = resolver().resolve(str(context.get("task", "")))
    if not task or task.kind != "task":
        return {
            "accepted": False,
            "status": requested_status,
            "summary": "",
            "error": "active Task execution context is incomplete",
        }
    verification = args.get("verification")
    valid_verification = (
        isinstance(verification, dict)
        and set(verification) == {"status", "observation"}
        and isinstance(verification["status"], str)
        and verification["status"] in {"established", "not_established"}
        and isinstance(verification["observation"], str)
        and 0 < len(verification["observation"].strip()) <= MAX_VISUAL_VERIFICATION_CHARS
        and len(verification["observation"]) <= MAX_VISUAL_VERIFICATION_CHARS
        and not any(ord(char) < 32 or ord(char) == 127 for char in verification["observation"])
    )
    if verification is not None and not valid_verification and requested_status == "completed":
        error = (
            "verification requires exactly status established|not_established and "
            "a nonempty observation of at most 1000 characters"
        )
    else:
        verification = dict(verification) if valid_verification else None
        error = _completion_error(task, requested_status, outcome, evidence, context, verification)
    if error:
        return {
            "accepted": False,
            "status": requested_status,
            "summary": "",
            "outcome": outcome,
            "evidence": evidence,
            "error": error,
        }
    return {
        "accepted": True,
        "status": requested_status,
        "summary": str(args.get("summary", ""))[:2000],
        "outcome": outcome,
        "evidence": evidence,
        # This is the Task model's interpretation of the supplied image, not
        # independent machine verification of application semantics.
        **({"verification": verification} if verification is not None else {}),
        "error": "",
    }

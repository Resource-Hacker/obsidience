"""Adapter for the executor-owned ``task.complete`` terminal decision.

It validates the argument shape and records the decision; the acceptance
policy belongs to ``execution.completion``.
"""

from __future__ import annotations

import re

from obsidience.harness.execution.completion import (
    completion_error, evidence_bound_completion, public_claim_error, staged_proposal_states,
)

MAX_EVIDENCE_ITEMS = 8
MAX_EVIDENCE_CHARS = 500
# Chat-template control tokens (Gemma's <|channel>, <tool_call|>) in an entry are
# leaked generation, not a citation: an accepted Curate completion once carried
# them after its Source, which the substring citation check still found.
_CONTROL_MARKUP = re.compile(r"<\|[^<>\s]{1,40}>|<[^<>\s|]{1,40}\|>")
MAX_VISUAL_VERIFICATION_CHARS = 1000


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
        len(item) > MAX_EVIDENCE_CHARS or _CONTROL_MARKUP.search(item) for item in evidence
    ):
        return {
            "accepted": False,
            "status": requested_status,
            "summary": "",
            "outcome": outcome,
            "evidence": [],
            "error": (
                "evidence entries must be nonempty plain strings of at most "
                f"{MAX_EVIDENCE_CHARS} characters, without model control markup"
            ),
        }
    task = context.get("task_note")
    if task is None:
        task = resolver().resolve(str(context.get("task", "")))
    summary = str(args.get("summary", ""))[:2000]
    pending, approved, rejected = staged_proposal_states(context)
    if "status" not in args and pending:
        # A staged proposal can finish only in review. Without the (optional)
        # status, Curate 39bacc10adc4 defaulted to completed three times and was
        # rejected for no-change evidence until the Task blocked (2026-10-19).
        requested_status = "review"
    if (requested_status == "completed" and not outcome
            and context.get("event") == "observations.memory.ready"
            and not any((pending, approved, rejected))
            and not context.get("_memory_proposal_rejection")):
        # An inspection with no proposal has no Article change. The full
        # Source, topic search and any claimed read evidence are checked below.
        outcome = "no_change"
    if (requested_status == "review" and task and not task.meta.get("acceptance")
            and not pending and not rejected):
        # Review state belongs to the publication owner. Do not spend another
        # model call correcting a status that Auto-curate has already settled.
        if approved:
            requested_status, outcome = "completed", "changed"
            summary = "Approved Article changes: " + ", ".join(
                str(item.get("target", "")) for item in approved)
            evidence = []  # Filled below from the exact publication receipts.
        elif task.ref == "Tasks/curate" and context.get("_created_tasks"):
            requested_status = "completed"
            outcome = "no_change" if evidence_bound_completion(task.ref, context) else ""
            delegated = ", ".join(str(item["target_task_ref"]) for item in context["_created_tasks"])
            summary = f"Delegated {delegated}; downstream work retains its own execution and Review."
            evidence = [summary[:MAX_EVIDENCE_CHARS]]
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
    if (context.get("event") == "observations.memory.ready"
            and (requested_status != args.get("status", "completed")
                 or (requested_status == "completed" and (outcome == "no_change" or approved)))):
        # The complete read of this Source is checked below; a no-change
        # inspection cites it even when the model listed only Articles, and so
        # does a recommendation the owner approved before completion.
        citation = str((context.get("params") or {}).get("source_citation", ""))
        if citation and citation not in evidence:
            evidence.append(citation)
    conversational = (task is not None and task.kind == "agent"
                      and context.get("interactive") is True
                      and context.get("_agent_ref") == task.ref
                      and (task.ref == "Agents/Executive/Executive"
                           or context.get("_conversation_agent_ref") == task.ref))
    if not task or (task.kind != "task" and not conversational):
        return {
            "accepted": False,
            "status": requested_status,
            "summary": "",
            "error": "active execution context is incomplete",
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
        error = completion_error(task, requested_status, outcome, evidence, context, verification)
        if not error and conversational and (requested_status == "completed"
                or context.get("_discord_control_failed") in {"play", "resume", "continuous"}):
            error = public_claim_error(summary, context)
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
        "summary": summary[:2000],
        "outcome": outcome,
        "evidence": evidence,
        # This is the Task model's interpretation of the supplied image, not
        # independent machine verification of application semantics.
        **({"verification": verification} if verification is not None else {}),
        "error": "",
    }

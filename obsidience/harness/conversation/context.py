"""Read-only conversation and activation projections; no observation Articles."""
from datetime import datetime
from ..knowledge.index import INDEX
from ..execution.loops import sessions


def project_conversation(conversation, *, conversation_id, before_sequence=None):
    native = sessions().context(conversation_id, before_sequence)
    rows = INDEX.conversation_turns(conversation_id, before_sequence=before_sequence)
    if native is None:
        native = "Historical public dialogue; it does not establish current state or authorize effects.\n\n" + "\n\n".join(
            f"{row['role']}: {row['text']}" for row in rows)
    snapshot = sessions().view(conversation_id) or {}
    return {"body": native, "ref": None,
            "compaction_count": snapshot.get("compaction_count", 0),
            "latest_sequence": max((row["sequence"] for row in rows), default=0)}


def project_activation_context(agent_ref: str, task_ref: str, activation_id: str,
                               bindings: dict, evidence: list[dict], status: str = "running", *,
                               objective: str = "", context_refs: list[str] | None = None,
                               begin: bool = False) -> dict:
    """One Agent-owned readable view of controller context, never hidden reasoning."""
    if not agent_ref.startswith("Agents/") or agent_ref.count("/") != 2 or not activation_id:
        raise ValueError("Working context requires an exact Agent and activation")
    latest = []
    for item in evidence[-8:]:
        if not isinstance(item, dict) or not item.get("tool"):
            continue
        witness = item.get("completion_evidence")
        row = {"tool": str(item["tool"]), "kind": "controller_receipt"}
        if isinstance(witness, dict):
            row.update({key: witness[key] for key in (
                "verified", "target", "verified_scope", "semantic_postcondition_verified") if key in witness})
        elif item.get("not_dispatched") is True:
            row["delivery"] = "not_dispatched"
        elif item.get("must_not_replay") is True or item.get("interrupted"):
            row["delivery"] = "uncertain"
        else:
            row["delivery"] = "returned_without_computer_state_attestation"
        latest.append(row)
    # Local offset, matching local_clock: a UTC date that has already rolled
    # over must not compete with the owner's current date.
    context = {"activation_id": activation_id, "task_ref": task_ref, "status": status,
        "binding_source": "controller", "observed_at": datetime.now().astimezone().isoformat(),
        "entities": {key: bindings[key] for key in ("application", "computer_outcome", "computer_scope") if key in bindings},
        "evidence": latest, "uncertainty": "Only the listed receipts establish effects; dialogue and target labels do not.",
        "current_objective": "The exact current request is supplied once in the Objective section."}
    continuation = bindings.get("continuation_result")
    if isinstance(continuation, dict):
        context["finding"] = {key: continuation[key] for key in (
            "source_citation", "content_sha256", "accepted_knowledge", "disposition") if key in continuation}
    return {"context": context}

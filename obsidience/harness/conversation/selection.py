"""Admit owner conversation to the Executive identity before packet routing."""
from __future__ import annotations

from ..knowledge.dependencies import resolve_dependencies
from ..knowledge.vault import Note, resolver

EXECUTIVE_REF = "Agents/Executive/Executive"
MAX_REQUEST_CHARS = 8_000


class TaskAdmissionError(ValueError):
    """The accepted Executive assignment or input is unavailable."""


def _text(value: object, maximum: int, *, empty: bool = False) -> str:
    if (not isinstance(value, str) or len(value) > maximum
            or (not empty and not value.strip())
            or any(ord(char) < 32 and char not in "\n\t" for char in value)):
        raise TaskAdmissionError("Executive input is invalid or exceeds its bound.")
    return value


def project_historical_evidence(records: list | None) -> list[dict]:
    """Retain semantic receipts only; never serialize raw trace/args/images."""
    if records is None:
        return []
    if not isinstance(records, list):
        raise TaskAdmissionError("Historical execution evidence must be a list.")
    projected = []
    for record in records[-4:]:
        if not isinstance(record, dict):
            raise TaskAdmissionError("Historical execution evidence is invalid.")
        effect = record.get("effect_dispatched")
        if effect is not None and type(effect) is not bool:
            raise TaskAdmissionError("Historical effect delivery must be boolean or null.")
        available = record.get("evidence_available", False)
        omitted = record.get("omitted_tool_count", 0)
        if type(available) is not bool or type(omitted) is not int or not 0 <= omitted <= 1_000_000:
            raise TaskAdmissionError("Historical evidence availability or omission count is invalid.")
        row = {"scope": "historical_execution", "current_state": False,
               "effect_scope": "computer", "evidence_available": available,
               "run_id": _text(record.get("run_id"), 128),
               "task_ref": _text(record.get("task_ref"), 256),
               "status": _text(record.get("status"), 32),
               "effect_dispatched": effect, "tools": []}
        tools = record.get("tools", [])
        if not isinstance(tools, list):
            raise TaskAdmissionError("Historical Tool evidence must be a list.")
        row["omitted_tool_count"] = omitted + max(0, len(tools) - 8)
        for item in tools[-8:]:
            if not isinstance(item, dict):
                raise TaskAdmissionError("Historical Tool evidence is invalid.")
            witness = {"tool": _text(item.get("tool"), 96)}
            target = item.get("target")
            if isinstance(target, dict) and target.get("kind") in {"application", "pane"}:
                witness["target"] = {"kind": target["kind"], "name": _text(target.get("name"), 256)}
            for key in ("verified_scope", "delivery"):
                if key in item:
                    witness[key] = _text(item[key], 32)
            if item.get("semantic_postcondition_verified") is False:
                witness["semantic_postcondition_verified"] = False
            if type(item.get("verified")) is bool:
                witness["verified"] = item["verified"]
            if item.get("tool") == "application.launch" and item.get("launch_outcome") in {
                "terminated_before_ready", "timeout", "launcher_timeout",
            }:
                witness["launch_outcome"] = item["launch_outcome"]
            row["tools"].append(witness)
        projected.append(row)
    return projected


def admit_executive(text: str, source_name: str) -> tuple[Note, dict, str]:
    """Validate the accepted conversational profile without inventing a Task."""
    _text(text, MAX_REQUEST_CHARS)
    if source_name not in {"voice", "text"}:
        raise TaskAdmissionError("Executive input source must be voice or text.")
    res = resolver(include_system=False)
    agent = res.resolve(EXECUTIVE_REF)
    if agent is None or agent.kind != "agent":
        raise TaskAdmissionError("The accepted Executive Agent is unavailable.")
    dependency = resolve_dependencies(agent, res, agent_ref=agent.ref)
    if dependency.get("error"):
        raise TaskAdmissionError(str(dependency["error"]))
    event = "voice.activation" if source_name == "voice" else "chat.request"
    return agent, {"request": text, "source": source_name, "event": event}, event

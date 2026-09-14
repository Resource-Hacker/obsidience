"""Select a bounded packet from the Executive's accepted capability catalog.

This component has no Tool dispatcher, Task queue, HTTP client or model process
of its own. Its caller supplies a leased model; it uses the Harness provider
client, and cancellation unwinds through those owners. The compiler resolves IDs
to exact accepted Articles and retains the original owner Objective.
"""
from __future__ import annotations

import hashlib
import json
import time

from ..capabilities.registry import ALWAYS_ALLOWED
from ..execution import trace
from ..knowledge.links import metadata_ref
from ..models import llm
from .context_bindings import _description
from .selection import project_historical_evidence

MAX_SELECTED_TOOLS = 24
MAX_CONTEXT_CHARS = 12_000

INSTRUCTIONS = """Select the smallest complete capability packet for the LATEST owner request.
Return only Tool names needed for that request. This selects instructions, not
Tool calls or arguments. The Executive will act after the packet is compiled.
Return an empty list for ordinary conversation, general knowledge, or a request
that needs clarification. Completion is always supplied by the compiler.
Use preceding dialogue only to resolve references or a correction to an
unresolved request. The latest explicit names and negations override history.
Never repeat already fulfilled operations or select effects merely mentioned in
quotes, hypotheticals or historical receipts. Preserve ALL requested operations
in combined requests. Permission to click requests input when its referent is
clear; it does not request launch, focus or placement.
Current screen contents require computer.observe. Clicks require computer.act.
Focus and placement use the Scene already provided to the Executive; they do not
need an image unless interpreting visible content. Opening uses application.launch.
Current service health requires harness.status. External research uses web.search
and web.fetch; an exact supplied URL usually needs only web.fetch. Local Vault
questions use vault.search and vault.read. Pick task.create for explicitly
delegated, separately queueable specialist work, not routine questions or actions.
Select follow-up evidence Tools needed to finish the complete request, but no
speculative effects. Skill prerequisites are supplied by the compiler.
The accepted catalog below is the only set of selectable capabilities.
"""


def narrow_spine(spine: dict, selected: list[str]) -> dict:
    """Close exact prerequisites and inherited guidance within the Agent catalog."""
    tools = {tool.title: tool for tool in spine["tool_articles"] if not tool.children}
    skills = {skill.ref: skill for skill in spine["skills"]}
    paired = {metadata_ref(str(skill.meta.get("tool", ""))): skill
              for skill in skills.values() if not skill.children}
    wanted = set(selected) | set(ALWAYS_ALLOWED)
    if wanted - tools.keys():
        raise ValueError("Packet router selected a capability outside the accepted catalog")
    included: set[str] = set()

    def visit(ref: str, stack: tuple[str, ...] = (), *, children: bool = True) -> None:
        if ref in stack:
            raise ValueError("Cyclic packet Skill prerequisite")
        if ref in included:
            return
        skill = skills.get(ref)
        if skill is None:
            raise ValueError("Packet prerequisite is outside the accepted Agent catalog")
        requirements = skill.meta.get("requires", [])
        if not isinstance(requirements, list) or len(requirements) > MAX_SELECTED_TOOLS:
            raise ValueError("Invalid packet Skill prerequisites")
        for raw in [*(skill.children if children else []), *requirements]:
            visit(metadata_ref(raw), (*stack, ref))
        included.add(ref)

    for name in sorted(wanted):
        visit(paired[tools[name].ref].ref)
    while parents := [skill for skill in skills.values() if skill.ref not in included
                      and any(metadata_ref(child) in included for child in skill.children)]:
        for parent in parents:
            visit(parent.ref, children=False)
    selected_skills = [skill for skill in spine["skills"] if skill.ref in included]
    selected_refs = {metadata_ref(str(skill.meta.get("tool", ""))) for skill in selected_skills}
    while parents := [tool for tool in spine["tool_articles"] if tool.ref not in selected_refs
                      and any(metadata_ref(child) in selected_refs for child in tool.children)]:
        selected_refs.update(tool.ref for tool in parents)
    selected_tools = [tool for tool in spine["tool_articles"] if tool.ref in selected_refs]
    return {**spine, "skills": selected_skills, "tool_articles": selected_tools,
            "tools": sorted(tool.title for tool in selected_tools if not tool.children)}


async def route_packet(spine: dict, *, objective: str, conversation: str,
                       evidence: list[dict] | None, model, continuation: dict | None = None) -> tuple[dict, dict]:
    """Select with the caller's leased model; malformed output enables no Tools."""
    catalog = [{"tool": tool.title, "description": _description(tool.body)["description"].split(". ")[0]}
               for tool in sorted(spine["tool_articles"], key=lambda item: item.title)
               if not tool.children and tool.title not in ALWAYS_ALLOWED]
    names = [row["tool"] for row in catalog]
    schema = {"type": "object", "properties": {"tools": {
        "type": "array", "items": {"type": "string", "enum": names},
        "maxItems": MAX_SELECTED_TOOLS}}, "required": ["tools"], "additionalProperties": False}
    # Keep the latest conversational material whole within the explicit bound.
    # It is data under a user boundary and cannot add catalog entries or rules.
    context = {"preceding_dialogue": conversation[-MAX_CONTEXT_CHARS:],
               "dialogue_truncated": len(conversation) > MAX_CONTEXT_CHARS,
               "historical_receipts": project_historical_evidence(evidence),
               "latest_owner_request": objective}
    if continuation:
        context["continuation"] = {
            "research_already_finished": True,
            "instruction": "Select only remaining work; do not delegate the completed research again.",
            "disposition": str(continuation.get("disposition", ""))[:100],
        }
    catalog_text = json.dumps(catalog, ensure_ascii=False, separators=(",", ":"))
    started = time.monotonic()
    trace.emit("event", "Executive packet routing started")
    reply = await llm.chat(
        [{"role": "system", "content": INSTRUCTIONS + catalog_text},
         {"role": "user", "content": json.dumps(context, ensure_ascii=False)}],
        model=model, reasoning_effort="none", temperature=0,
        max_tokens=256, response_schema=schema, measurements=False,
    )
    if reply.finish_reason != "stop":
        raise ValueError("Packet router did not finish a complete selection")
    value = json.loads(reply.content)
    if (not isinstance(value, dict) or set(value) != {"tools"}
            or not isinstance(value["tools"], list) or len(value["tools"]) > MAX_SELECTED_TOOLS
            or any(not isinstance(name, str) or name not in names for name in value["tools"])):
        raise ValueError("Packet router returned an invalid selection")
    packet_spine = narrow_spine(spine, value["tools"])
    duration = (time.monotonic() - started) * 1000
    routing = {"version": 1, "model": model.id, "tools": packet_spine["tools"],
               "duration_ms": round(duration, 3),
               "prompt_tokens": reply.prompt_tokens,
               "provider_metrics": reply.provider_metrics,
               "catalog_sha256": hashlib.sha256(catalog_text.encode()).hexdigest()}
    trace.latency("selection", duration_ms=duration)
    trace.emit("event", "Executive packet routed", [
        "Tools: " + ", ".join(packet_spine["tools"]),
        f"Router: {model.id}; {duration:.1f} ms",
    ])
    return packet_spine, routing

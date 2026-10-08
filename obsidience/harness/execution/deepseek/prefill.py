"""Disposable speech-prefix preparation, with no agent run or Tool dispatch."""
from __future__ import annotations

import asyncio
import hashlib
import json

from .model import admitted_events, request_payload
from .runner import memory_message, recall_query, recall_reply, tool_schemas
from .. import trace as action_trace
from ..executor import activation_messages, compile_activation
from ...conversation.evidence import historical_evidence
from ...conversation.context import project_conversation
from ...conversation.selection import admit_executive
from ...models import llm, runtime as model_runtime
from ...models.context import ContextBudgetExceeded, PROMPT_SAFETY_TOKENS, TaskContext, count_payload

# Digests of the latest speech-partial warm sent for the selected conversation:
# its whole request, runtime context and recalled memory. Never prompt content.
_PREPARED: dict[str, dict] = {}


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def report_reuse(conversation_id: str, context: str, memory: str) -> None:
    """Compare final admission's fresh context and memory with the warmed ones.

    Diagnostic only. Final admission always sends its own fresh request; the
    engine reuses the cached prefix exactly as far as the bytes still match.
    """
    prepared = _PREPARED.pop(conversation_id, None)
    if prepared is None:
        return
    same_context = prepared["context"] == _digest(context)
    same_memory = prepared["memory"] == _digest(memory)
    action_trace.emit("measurement", "Speech context preparation " + (
        "reused" if same_context and same_memory else "superseded"), [
        f"context: {'same' if same_context else 'changed'}",
        f"memory: {'same' if same_memory else 'changed'}",
        f"warm: {'completed' if prepared['completed'] else 'interrupted'}",
    ])


async def prepare(conversation, text: str, response_contract: str, *, idle: bool = False) -> dict:
    """Warm the canonical prompt using provisional text; discard all generation.

    Standby warms the stable prefix. A speech partial also warms the runtime
    context and recalled memory for its provisional text, stopping before the
    owner request. Final admission recompiles and recalls from the final
    transcript; cache reuse is exact-prefix matching in the resident engine,
    never acceptance of a draft.
    """
    agent, params, _event = admit_executive(text or "Executive", "voice")
    if idle:
        params["request"] = ""
        _PREPARED.pop(conversation.conversation_id, None)
    spec = model_runtime.resolve_model(agent.meta.get("model"), agent.ref)
    if not spec.runtime.startswith("llama.cpp"):
        return {"status": "unsupported"}
    effort = llm.normalize_reasoning_effort(agent.meta.get("reasoning_effort", "none"))
    if not idle and effort == 'none':
        from .commands import recognize_command
        command = recognize_command(text, ['lights.set', 'media.pause', 'task.complete'])
        if command is not None:
            from ..executor import resolve_spine
            from ...knowledge.vault import resolver
            spine = resolve_spine(agent, resolver(include_system=False))
            if command['name'] in spine.get('tools', []):
                # This exact complete prefix currently needs no model. A later
                # revision or final transcript is independently recognized; this
                # skips optional warming only and never accepts a command.
                return {'status': 'explicit_command', 'command_route': 'hassil'}
    async with model_runtime.resident_prefill(spec, load_if_idle=idle) as available:
        if not available:
            return {"status": "busy_or_unavailable"}
        # A cold persisted conversation can exceed the short speculative-speech
        # budget. Idle preparation still yields immediately to foreground work;
        # allow its full prefix to finish instead of repeatedly discarding it.
        async with asyncio.timeout(60 if idle else 10):
            conversation_id = conversation.conversation_id
            from .sessions import refresh, prefill_messages
            native = await refresh(conversation_id)
            # Standby stops at the stable compiler prefix: its Scene, clock,
            # Knowledge and memory would be stale by the next request. A speech
            # partial warms them for its own text, as the memory hook would.
            stable_only = bool(native) and idle
            recall = None
            if native and not idle:
                from ...memory.hindsight import MEMORY
                # The final transcript's turn follows the same latest exchange.
                recall = asyncio.create_task(MEMORY.recall(agent.ref, recall_query(text, conversation_id),
                                                           speculative=True),
                                             name="obsidience-speech-recall")
            try:
                if stable_only:
                    # The stable prefix renders neither Bindings nor the text
                    # conversation, so skip their synchronous ledger scans.
                    context, evidence = "", []
                else:
                    # Native history replaces the text conversation projection.
                    context = "" if native else project_conversation(
                        conversation, conversation_id=conversation_id,
                    )["body"]
                    latest = conversation.history(conversation_id, limit=1)
                    before_sequence = max((turn["sequence"] for turn in latest), default=0) + 1
                    evidence = historical_evidence(
                        conversation, conversation_id=conversation_id, before_sequence=before_sequence,
                    )
                if native:
                    params['conversation_id'] = conversation_id
                activation = await compile_activation(
                    agent, params=params, interactive=True, emit_activity=False,
                    conversation_context=context, conversation_evidence=evidence,
                )
                memory = memory_message(recall_reply(await recall)) if recall is not None else ""
            finally:
                if recall is not None and not recall.done():
                    recall.cancel()
                    await asyncio.gather(recall, return_exceptions=True)
            messages = activation_messages(
                agent, activation, agent_name=agent.title, response_contract=response_contract,
                active_exclusions=activation["spine"].get("excluded_subtasks", frozenset()),
                preparation_prefix=stable_only,
            )
            record = None
            if native:
                context_text = messages[1]["content"] if len(messages) > 1 else ""
                # Native history can outgrow Gemma's bounded SWA checkpoints.
                # Stop before the pending owner request: final admission appends
                # its own text after an identical context, or replaces the
                # context from the last checkpoint that still matches.
                messages = prefill_messages(conversation_id, messages, '' if idle else text,
                                            memory=memory, preparation_prefix=True)
            payload = request_payload(messages, spec, effort, tool_schemas(activation["spine"]["tools"]))
            if native and not idle:
                digest = _digest(json.dumps(payload, ensure_ascii=False, sort_keys=True))
                previous = _PREPARED.get(conversation_id)
                if previous is not None and previous["payload"] == digest and previous["completed"]:
                    # The engine already holds this exact prefix; repeating it
                    # would only spend another checkpoint.
                    return {"status": "unchanged"}
                record = {"payload": digest, "context": _digest(context_text),
                          "memory": _digest(memory), "completed": False}
                # Only the selected conversation's pending utterance matters.
                _PREPARED.clear()
                _PREPARED[conversation_id] = record
            async with llm.provider_client() as client:
                capacity = spec.context_tokens - spec.max_output_tokens - PROMPT_SAFETY_TOKENS
                if not spec.supports_input_token_limit:
                    tokens = await count_payload(payload, spec, client)
                    if tokens > capacity:
                        return {"status": "context_pressure"}
                # b10078 emits one token even for n_predict=0. Bound that work
                # explicitly; this caller has no output, Tool or persistence port.
                payload.update(max_tokens=1, stream=False)
                payload.pop("stream_options", None)
                projection = TaskContext()
                try:
                    # One bounded JSON response; share the exact admission guard
                    # without consuming events or exposing the discarded token.
                    async with admitted_events(client, payload, spec, projection, capacity, {}) as events:
                        await events.response.aread()
                        usage = events.response.json().get("usage") or {}
                    if spec.supports_input_token_limit:
                        tokens = projection.last_projection["input_tokens"]
                except ContextBudgetExceeded:
                    return {"status": "context_pressure"}
                if record is not None:
                    record["completed"] = True
                return {"status": "prepared", "prompt_tokens": tokens,
                        "cached_tokens": (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)}

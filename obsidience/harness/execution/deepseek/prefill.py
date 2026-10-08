"""Disposable speech-prefix preparation, with no agent run or Tool dispatch."""
from __future__ import annotations

import asyncio

from .model import admitted_events, request_payload
from .runner import tool_schemas
from ..executor import activation_messages, compile_activation
from ...conversation.evidence import historical_evidence
from ...conversation.context import project_conversation
from ...conversation.selection import admit_executive
from ...models import llm, runtime as model_runtime
from ...models.context import ContextBudgetExceeded, PROMPT_SAFETY_TOKENS, TaskContext, count_payload


async def prepare(conversation, text: str, response_contract: str, *, idle: bool = False) -> dict:
    """Warm the canonical prompt using provisional text; discard all generation.

    Final admission recompiles from the final transcript and fresh state. Cache
    reuse is exact-prefix matching in the resident engine, never acceptance of a draft.
    """
    agent, params, _event = admit_executive(text or "Executive", "voice")
    if idle:
        params["request"] = ""
    spec = model_runtime.resolve_model(agent.meta.get("model"), agent.ref)
    if not (spec.runtime.startswith("llama.cpp")
            or (spec.id == model_runtime.FLASH_NEXT_MODEL and spec.supports_input_token_limit)):
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
        idle_timeout = 300 if spec.id == model_runtime.FLASH_NEXT_MODEL else 60
        async with asyncio.timeout(idle_timeout if idle else 10):
            conversation_id = conversation.conversation_id
            from .sessions import refresh, prefill_messages
            native = await refresh(conversation_id)
            if native:
                # Native preparation stops before Bindings and never renders the
                # text conversation, so skip their synchronous ledger scans.
                params['conversation_id'] = conversation_id
                context, evidence = "", []
            else:
                context = project_conversation(
                    conversation, conversation_id=conversation_id,
                )["body"]
                latest = conversation.history(conversation_id, limit=1)
                before_sequence = max((turn["sequence"] for turn in latest), default=0) + 1
                evidence = historical_evidence(
                    conversation, conversation_id=conversation_id, before_sequence=before_sequence,
                )
            activation = await compile_activation(
                agent, params=params, interactive=True, emit_activity=False,
                conversation_context=context, conversation_evidence=evidence,
            )
            # Native history can outgrow Gemma's bounded SWA checkpoints. Warming
            # past the shared prefix evicts the checkpoint needed when final
            # admission replaces query-dependent context and adds fresh memory.
            # Stop at the compiler boundary; the real request keeps every block.
            preparation_prefix = bool(native) or spec.id == model_runtime.FLASH_NEXT_MODEL
            messages = activation_messages(
                agent, activation, agent_name=agent.title, response_contract=response_contract,
                preparation_prefix=preparation_prefix,
            )
            if native:
                messages = prefill_messages(conversation_id, messages, '' if idle else text,
                                            preparation_prefix=preparation_prefix)
            payload = request_payload(messages, spec, effort, tool_schemas(activation["spine"]["tools"]))
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
                return {"status": "prepared", "prompt_tokens": tokens,
                        "cached_tokens": (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0),
                        # The stable prefix excludes request text; identify its native history.
                        "native_revision": native.get("revision") if native and preparation_prefix else None}

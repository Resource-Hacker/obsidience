"""Disposable speech-prefix preparation, with no agent run or Tool dispatch."""
from __future__ import annotations

import asyncio

from .model import request_payload
from .runner import tool_schemas
from ..executor import activation_messages, compile_activation
from ...conversation.evidence import historical_evidence
from ...conversation.observations import project_immediate_observations
from ...conversation.selection import admit_executive
from ...models import llm, runtime as model_runtime
from ...models.context import PROMPT_SAFETY_TOKENS, count_payload


async def prepare(conversation, text: str, response_contract: str) -> dict:
    """Warm the canonical prompt using provisional text; discard all generation.

    Final admission recompiles from the final transcript and fresh state. Cache
    reuse is exact-prefix matching in llama.cpp, never acceptance of a draft.
    """
    agent, params, _event = admit_executive(text, "voice")
    spec = model_runtime.resolve_model(agent.meta.get("model"), agent.ref)
    if not spec.runtime.startswith("llama.cpp"):
        return {"status": "unsupported"}
    effort = llm.normalize_reasoning_effort(agent.meta.get("reasoning_effort", "none"))
    async with model_runtime.resident_prefill(spec) as available:
        if not available:
            return {"status": "busy_or_unavailable"}
        async with asyncio.timeout(10):
            conversation_id = conversation.conversation_id
            context = project_immediate_observations(
                conversation, conversation_id=conversation_id, materialize=False,
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
            messages = activation_messages(
                agent, activation, agent_name=agent.title, response_contract=response_contract,
            )
            payload = request_payload(messages, spec, effort, tool_schemas(activation["spine"]["tools"]))
            async with llm.provider_client() as client:
                tokens = await count_payload(payload, spec, client)
                if tokens > spec.context_tokens - spec.max_output_tokens - PROMPT_SAFETY_TOKENS:
                    return {"status": "context_pressure"}
                # b10078 emits one token even for n_predict=0. Bound that work
                # explicitly; this caller has no output, Tool or persistence port.
                payload.update(max_tokens=1, stream=False)
                payload.pop("stream_options", None)
                response = await client.post(spec.base_url + "/chat/completions", json=payload)
                response.raise_for_status()
                usage = response.json().get("usage") or {}
                return {"status": "prepared", "prompt_tokens": tokens,
                        "cached_tokens": (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)}

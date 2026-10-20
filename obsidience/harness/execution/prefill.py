"""Disposable speech-prefix preparation, with no agent run or Tool dispatch."""
from __future__ import annotations

import asyncio
import hashlib
import json
import re

from .native import admitted_events, request_payload
from .native_turn import memory_message, recall_query, recall_reply, tool_schemas
from . import trace as action_trace
from .executor import activation_messages, compile_activation
from ..conversation.evidence import historical_evidence
from ..conversation.context import project_conversation
from ..conversation.selection import admit_executive
from ..models import llm, runtime as model_runtime
from ..models.context import ContextBudgetExceeded, PROMPT_SAFETY_TOKENS, TaskContext, count_payload

# Digests of the latest speech-partial warm sent for the selected conversation:
# its whole request, runtime context and recalled memory. Never prompt content.
_PREPARED: dict[str, dict] = {}
# Speech-partial recalls of the pending utterance, oldest first: (Agent ref,
# query, task), at most one running. Cancelling a warm or speculative
# admission leaves its recall running, bounded by the recall's own timeout;
# speech_recall keeps those that still stand in for the newest words and
# discards the rest.
_RECALLS: list[tuple] = []
# A partial's recall stands in for later words of the same utterance when its
# words are a word prefix holding at least this share of their characters.
# Partials change every 150-250 ms and a recall takes 280-670 ms, so at 0.8
# nearly every partial restarted recall and its admission waited for it on the
# verdict's critical path (2026-10-19). Memory then reflects the request's
# first half or more; trace "Speech recall prefix agreement" measures the cost.
RECALL_PREFIX_COVERAGE = 0.5
_NOT_WORD = re.compile(r"[^\w']+")


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def speech_key(text: str) -> str:
    """A transcript's words, ignoring case, punctuation and spacing."""
    words = _NOT_WORD.sub(" ", text.replace("’", "'").casefold()).split()
    return " ".join(word for word in (word.strip("'") for word in words) if word)


def _covers(registered: tuple, query: tuple) -> bool:
    """Whether a registered speech recall query stands in for this one.

    The previous-request half must be identical; the request half must have
    the same words or be a word prefix covering RECALL_PREFIX_COVERAGE.
    """
    if registered[1] != query[1]:
        return False
    partial, final = speech_key(registered[0]), speech_key(query[0])
    return bool(partial) and (partial == final or (
        final.startswith(partial + " ") and len(partial) >= RECALL_PREFIX_COVERAGE * len(final)))


def _start_recall(agent_ref, query: tuple) -> tuple:
    from ..memory.hindsight import MEMORY
    return agent_ref, query, asyncio.create_task(
        MEMORY.recall(agent_ref, *query, speculative=True), name="obsidience-speech-recall")


async def speech_recall(agent_ref, query: tuple, *, adopt: bool = False,
                        cover: bool = False) -> tuple[asyncio.Task, str, float]:
    """The provisional speech recall for one Agent and query, how it was
    reused, and the share of the request's characters its query held.

    The identical Agent and query reuses a registered task ("exact"). With
    cover=True (speech admission) a registered recall of the same words
    ("words") or a covering word prefix ("prefix") stands in without waiting
    for a fresh one: the newest finished, else the earliest started. Only when
    none covers does a new recall start, and only once the utterance's running
    recall has finished: Hindsight completes a recall's SQL and rerank even
    after the client cancels it, so per-partial recalls that were superseded
    and cancelled competed for its CPU with the one finally used (single
    recalls then took 620-1340 ms, 2026-10-19). A speech partial keeps its
    recall registered for later partials and the final admission; adopt=True
    (final admission) takes ownership instead. Registered recalls that no
    longer stand in for this query are discarded.
    """
    global _RECALLS
    while True:
        mine = [entry for entry in _RECALLS if entry[0] == agent_ref]
        chosen = next((entry for entry in mine if entry[1] == query), None)
        reused = "exact" if chosen is not None else ""
        covering = [entry for entry in mine if cover and _covers(entry[1], query)]
        if chosen is None and covering:
            finished = [entry for entry in covering if entry[2].done()]
            chosen = finished[-1] if finished else covering[0]
            reused = "words" if speech_key(chosen[1][0]) == speech_key(query[0]) else "prefix"
        if chosen is not None:
            break
        running = {entry[2] for entry in mine if not entry[2].done() and entry[1][1] == query[1]}
        if not running:
            chosen = _start_recall(agent_ref, query)
            break
        # Cancelling the waiter leaves the running recall registered.
        await asyncio.wait(running)
    keep = [] if adopt else [entry for entry in _RECALLS if entry is chosen or entry in covering]
    if not adopt and chosen not in keep:
        keep.append(chosen)
    dropped = [entry for entry in _RECALLS if entry not in keep and entry is not chosen]
    _RECALLS = keep
    if dropped:
        from .native_turn import discard_recall
        await asyncio.gather(*(discard_recall(entry) for entry in dropped))
    held, words = speech_key(chosen[1][0]), speech_key(query[0])
    return chosen[2], reused, round(len(held) / len(words), 3) if words else 1.0


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


async def prepare(conversation, text: str, response_contract: str, *, idle: bool = False,
                  interruption: str = "") -> dict:
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
    elif interruption:
        # Final admission renders the same cue into the same runtime context.
        params["speech_interruption"] = interruption
    spec = model_runtime.resolve_model(agent.meta.get("model"), agent.ref)
    if not spec.runtime.startswith("llama.cpp"):
        return {"status": "unsupported"}
    effort = llm.normalize_reasoning_effort(agent.meta.get("reasoning_effort", "none"))
    if not idle and effort == 'none':
        from .commands import recognize_command
        command = recognize_command(text, ['lights.set', 'tv.control', 'media.pause', 'task.complete'])
        if command is not None:
            from .executor import resolve_spine
            from ..knowledge.vault import resolver
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
            from .adk import sessions
            refresh, prefill_messages = sessions.refresh, sessions.prefill_messages
            native = await refresh(conversation_id)
            # Standby stops at the stable compiler prefix: its Scene, clock,
            # Knowledge and memory would be stale by the next request. A speech
            # partial warms them for its own text, as the memory hook would.
            stable_only = bool(native) and idle
            recall = None
            if native and not idle:
                # The final transcript's turn follows the same latest exchange.
                recall, _, _ = await speech_recall(agent.ref, recall_query(text, conversation_id))
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
            # Shielded: a cancelled warm leaves the registered recall for
            # the next partial or final admission of the same text.
            memory = memory_message(recall_reply(await asyncio.shield(recall))) if recall is not None else ""
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
            # Speech admission, ordinary ADK steps and this warm share one system
            # message, admission rules included; admission adds only a trailing reminder.
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
                payload.update(max_tokens=1, stream=False,
                               **model_runtime.slot_fields(spec, model_runtime.EXECUTIVE_SLOT))
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

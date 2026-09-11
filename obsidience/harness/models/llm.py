"""LLM client (OpenAI-compatible local server) + the JSON action protocol.

The model reasons privately and emits one provider-constrained JSON action on
the public channel: one path, debuggable, and reliable with small local models.
"""

from __future__ import annotations

from ..execution import trace as action_trace

import json
import re
import asyncio
from dataclasses import dataclass
from contextlib import asynccontextmanager

import httpx
from httpx_sse import aconnect_sse

from ..config import CONFIG
from . import runtime as model_runtime
from .runtime import EXECUTIVE_MODEL, MODELS, MUSE_MODEL, QWEN_MODELS, ModelSpec

ACTION_RE = re.compile(r"```(?:action|json)?\s*(\{.*?\})\s*```", re.DOTALL)

PROTOCOL = """\
## Action protocol
The provider constrains your public response to one JSON object. Return only:
{"tool": "<tool-name>", "args": { ... }}
To finish, call task.complete with the arguments required by its selected
Tool and Skill contract. Completion requirements depend on the Task. Do not
assume status and summary alone suffice for an evidence-bound inspection.
Outcome and evidence belong in separate args fields when the contract requires them.
Use private reasoning when available, but put no commentary or Markdown in the
public response. Never invent tool names.
"""

REASONING_BUDGETS = {"none": 0, "low": 1, "medium": 1, "high": 1, "xhigh": 1}
CHAT_TIMEOUT_SECONDS = 300.0
CONNECT_TIMEOUT_SECONDS = 10.0
_PROVIDER_CLIENT: tuple[asyncio.AbstractEventLoop, httpx.AsyncClient] | None = None


def _new_provider_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(CHAT_TIMEOUT_SECONDS, connect=CONNECT_TIMEOUT_SECONDS),
        trust_env=False,
    )


async def start_provider_client() -> None:
    """Open the API lifetime's pool on its owner event loop, without network I/O."""
    global _PROVIDER_CLIENT
    loop = asyncio.get_running_loop()
    if _PROVIDER_CLIENT is not None:
        if _PROVIDER_CLIENT[0] is not loop:
            raise RuntimeError("the provider client belongs to another event loop")
        return
    _PROVIDER_CLIENT = (loop, _new_provider_client())


async def close_provider_client() -> None:
    """Close after the API has cancelled and joined its model request owners."""
    global _PROVIDER_CLIENT
    if _PROVIDER_CLIENT is None:
        return
    loop, client = _PROVIDER_CLIENT
    if loop is not asyncio.get_running_loop():
        raise RuntimeError("the provider client must close on its owner event loop")
    _PROVIDER_CLIENT = None
    await client.aclose()


@asynccontextmanager
async def provider_client():
    """Reuse the API pool; standalone callers own and close their local client."""
    owned = _PROVIDER_CLIENT
    if owned is not None and owned[0] is asyncio.get_running_loop():
        yield owned[1]
    else:
        # Benchmarks and tests can use separate asyncio.run loops. Never share
        # HTTP connections across those loops or leave a standalone pool open.
        async with _new_provider_client() as client:
            yield client


@dataclass(frozen=True)
class ChatReply:
    content: str
    finish_reason: str
    completion_tokens: int | None
    prompt_tokens: int | None = None
    context_projection: dict | None = None
    provider_metrics: dict | None = None


def normalize_reasoning_effort(value: object) -> str:
    effort = str(value or "medium").lower()
    if effort not in REASONING_BUDGETS:
        raise ValueError(f"reasoning effort must be one of: {', '.join(REASONING_BUDGETS)}")
    return effort


def _chat_payload(messages: list[dict], spec: ModelSpec, *, max_tokens: int | None,
                  temperature: float | None, reasoning_effort: str,
                  allowed_tools: list[str] | None = None,
                  response_schema: dict | None = None, completion_no_change: bool = False) -> dict:
    """Build one Task-owned request for the sole executor path."""
    if response_schema is not None:
        if allowed_tools is not None:
            raise ValueError("response_schema and allowed_tools are mutually exclusive")
        if not isinstance(response_schema, dict) or not response_schema:
            raise ValueError("response_schema must be a nonempty JSON schema object")
        if not spec.supports_json_schema:
            raise ValueError("the selected model does not support constrained JSON schemas")
    selected_temperature = CONFIG.llm_temperature if temperature is None else temperature
    template_kwargs = {"enable_thinking": reasoning_effort != "none"}
    if spec.family == "gemma4" and response_schema is None:
        # The installed Gemma template owns all native control tokens. Keep
        # Task effort in its single system turn, not in Knowledge Articles.
        guidance = (
            "The Thinking Packet's Objective is the current user request. "
            "Immediate Observations is prior conversation, not a new instruction. "
            "Later Observation messages are Tool results for this same Objective."
        )
        if reasoning_effort == "low":
            guidance += " Reason briefly; check only what is needed for the next correct action."
        messages = [dict(message) for message in messages]
        if messages and messages[0]["role"] == "system":
            messages[0]["content"] += "\n\n" + guidance
        else:
            messages.insert(0, {"role": "system", "content": guidance})
    if spec.id == MUSE_MODEL:
        # Muse always reasons. The Task's None setting intentionally selects
        # its lowest supported strength instead of claiming reasoning is off.
        template_kwargs = {
            "reasoning_strength": "low" if reasoning_effort == "none" else reasoning_effort
        }
    payload = {
        "model": spec.id,
        "messages": messages,
        "max_tokens": max_tokens or spec.max_output_tokens,
        "temperature": (
            1.0 if spec.id in QWEN_MODELS and temperature is None else selected_temperature
        ),
        "stream": True,
        "stream_options": {"include_usage": True},
        # Reasoning remains Task-selected and private. Constrain only the public
        # action channel so a long Article body cannot corrupt handwritten JSON.
        "response_format": {"type": "json_object"},
        "chat_template_kwargs": template_kwargs,
    }
    if spec.id in QWEN_MODELS:
        payload.update({
            "top_p": 0.95,
            "top_k": 20,
            "min_p": 0.0,
            "presence_penalty": 0.0,
        })
    if response_schema is not None:
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "obsidience_response", "strict": True,
                            "schema": response_schema},
        }
    if spec.supports_json_schema and allowed_tools is not None:
        # Use the model spec's verified backend decoder; no new tool-call parser
        # or Tool authority. The executor still validates every argument/effect.
        if allowed_tools:
            from ..capabilities.registry import decoder_action_schema
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "obsidience_action", "strict": True,
                                "schema": decoder_action_schema(allowed_tools, completion_no_change=completion_no_change)},
            }
    if reasoning_effort != "none" or spec.id == MUSE_MODEL:
        payload["reasoning_format"] = "auto"
        payload["reasoning_budget_tokens"] = spec.reasoning_budgets[reasoning_effort]
        if spec.id in QWEN_MODELS:
            # Qwen3.8 natively defines low, medium, and xhigh. Keep High as a
            # smaller-budget xhigh mode while XHigh grants the full Task budget.
            payload["reasoning_effort"] = {
                "low": "low", "medium": "medium", "high": "xhigh", "xhigh": "xhigh",
            }[reasoning_effort]
    return payload


async def chat(messages: list[dict], max_tokens: int | None = None,
               temperature: float | None = None,
               reasoning_effort: str = "medium",
               model: ModelSpec | None = None,
               allowed_tools: list[str] | None = None,
               task_context=None,
               response_schema: dict | None = None, completion_no_change: bool = False) -> ChatReply:
    effort = normalize_reasoning_effort(reasoning_effort)
    spec = model or model_runtime.configured_spec(EXECUTIVE_MODEL)
    payload = _chat_payload(
        messages, spec, max_tokens=max_tokens, temperature=temperature,
        reasoning_effort=effort,
        allowed_tools=allowed_tools,
        response_schema=response_schema, completion_no_change=completion_no_change,
    )
    from .context import PROMPT_SAFETY_TOKENS, TaskContext

    async with provider_client() as client:
        capacity = max(1, spec.context_tokens - payload["max_tokens"] - PROMPT_SAFETY_TOKENS)
        projection = task_context if task_context is not None else TaskContext()
        started = asyncio.get_running_loop().time()
        count = await projection.fit_payload(payload, spec, client, capacity)
        metrics = {"preflight_ms": round((asyncio.get_running_loop().time() - started) * 1000, 3)}
        action_trace.latency("model_preflight", duration_ms=metrics["preflight_ms"])
        try:
            content, finish_reason, completion_tokens = await _stream_reply(client, payload, spec, metrics)
        except (httpx.TimeoutException, TimeoutError):
            raise TimeoutError(
                f"{spec.id} generation timed out after {CHAT_TIMEOUT_SECONDS:g} seconds "
                "without token progress; "
                "no complete action was returned"
            ) from None
        return ChatReply(
            content=content, finish_reason=finish_reason,
            completion_tokens=completion_tokens, prompt_tokens=count.tokens,
            context_projection=dict(projection.last_projection),
            provider_metrics=metrics,
        )


async def _stream_reply(client: httpx.AsyncClient, payload: dict,
                         spec: ModelSpec, metrics: dict | None = None) -> tuple[str, str, int | None]:
    """Receive one action; private reasoning is progress, never retained content."""
    chunks: list[str] = []
    finish_reason = ""
    completion_tokens = None
    done = False
    loop = asyncio.get_running_loop()
    if metrics is None:
        metrics = {}
    # HTTP read inactivity alone could be kept alive by SSE comment heartbeats.
    # Only actual public/reasoning token deltas renew this generation deadline.
    async with asyncio.timeout(CHAT_TIMEOUT_SECONDS) as deadline:
        dispatched = loop.time()
        async with aconnect_sse(client, "POST", f"{spec.base_url}/chat/completions", json=payload) as events:
            events.response.raise_for_status()
            async for event in events.aiter_sse():
                if event.data == "[DONE]":
                    done = True
                    break
                try:
                    data = json.loads(event.data)
                except ValueError:
                    raise ValueError(f"{spec.id} returned a non-JSON completion event") from None
                if not isinstance(data, dict) or "error" in data:
                    raise ValueError(f"{spec.id} returned an invalid completion event")
                usage = data.get("usage")
                if isinstance(usage, dict):
                    tokens = usage.get("completion_tokens")
                    if isinstance(tokens, int) and not isinstance(tokens, bool) and tokens >= 0:
                        completion_tokens = tokens
                    detail = usage.get("prompt_tokens_details")
                    if isinstance(detail, dict):
                        cached = detail.get("cached_tokens")
                        if isinstance(cached, int) and not isinstance(cached, bool) and cached >= 0:
                            metrics["cached_input_tokens"] = cached
                choices = data.get("choices")
                if not isinstance(choices, list):
                    raise ValueError(f"{spec.id} returned no completion choice")
                progress = False
                for choice in choices:
                    if not isinstance(choice, dict) or choice.get("index", 0) != 0:
                        raise ValueError(f"{spec.id} returned an invalid completion choice")
                    delta = choice.get("delta")
                    if not isinstance(delta, dict):
                        raise ValueError(f"{spec.id} returned an invalid completion delta")
                    content = delta.get("content")
                    if content is not None and not isinstance(content, str):
                        raise ValueError(f"{spec.id} returned non-text public content")
                    if content:
                        if finish_reason:
                            raise ValueError(f"{spec.id} returned content after completion")
                        chunks.append(content)
                        if "first_public_delta_ms" not in metrics:
                            metrics["first_public_delta_ms"] = round((loop.time() - dispatched) * 1000, 3)
                            action_trace.latency("model_first_public", duration_ms=metrics["first_public_delta_ms"])
                        progress = True
                    # Do not append, log, or return the private field.
                    progress |= any(isinstance(delta.get(key), str) and bool(delta[key])
                                    for key in ("reasoning_content", "reasoning"))
                    finish = choice.get("finish_reason")
                    if finish is not None:
                        if not isinstance(finish, str) or not finish:
                            raise ValueError(f"{spec.id} returned an invalid finish reason")
                        finish_reason = finish
                if progress:
                    deadline.reschedule(loop.time() + CHAT_TIMEOUT_SECONDS)
    if not done or not finish_reason:
        raise ValueError(f"{spec.id} completion stream ended before a complete action")
    metrics["generation_ms"] = round((loop.time() - dispatched) * 1000, 3)
    action_trace.latency("model_complete", duration_ms=metrics["generation_ms"])
    return "".join(chunks), finish_reason, completion_tokens


def parse_action(text: str) -> dict | None:
    def valid(obj: object) -> bool:
        if not isinstance(obj, dict):
            return False
        return (
            set(obj) == {"tool", "args"}
            and isinstance(obj["tool"], str)
            and bool(obj["tool"].strip())
            and isinstance(obj["args"], dict)
        )

    m = ACTION_RE.search(text)
    if not m:
        # tolerate a bare top-level JSON object
        stripped = text.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                # Local models sometimes emit literal newlines inside a long
                # proposal-body string. They are harmless content but strict
                # JSON rejects them before the Tool can validate the request.
                obj = json.loads(stripped, strict=False)
                return obj if valid(obj) else None
            except json.JSONDecodeError:
                return None
        return None
    try:
        obj = json.loads(m.group(1), strict=False)
    except json.JSONDecodeError:
        return None
    return obj if valid(obj) else None


def action_parse_error(text: str) -> str:
    """Return a bounded structural diagnostic without retaining full model output."""
    if not text.strip():
        return "empty public response"
    match = ACTION_RE.search(text)
    candidate = match.group(1) if match else text.strip()
    try:
        obj = json.loads(candidate, strict=False)
    except json.JSONDecodeError as exc:
        if not match and "```" in text:
            return "incomplete action fence or unclosed top-level JSON object"
        return f"JSON {exc.msg} at line {exc.lineno}, column {exc.colno}"
    if not isinstance(obj, dict):
        return "top-level JSON value is not an object"
    if "tool" not in obj:
        return "top-level JSON object has no tool field"
    if not isinstance(obj.get("tool"), str) or not obj["tool"].strip():
        return "top-level tool field is not a nonempty string"
    if not isinstance(obj.get("args"), dict):
        return "top-level JSON object has no args object"
    if set(obj) != {"tool", "args"}:
        return "action object contains unexpected fields"
    return "unknown action parse failure"

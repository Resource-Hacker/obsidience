"""LLM client (OpenAI-compatible local server) + the JSON action protocol.

The model reasons privately and emits one provider-constrained JSON action on
the public channel: one path, debuggable, and reliable with small local models.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

import httpx

from ..config import CONFIG
from . import runtime as model_runtime
from .runtime import EXECUTIVE_MODEL, MODELS, MUSE_MODEL, QWEN_MODELS, ModelSpec

ACTION_RE = re.compile(r"```(?:action|json)?\s*(\{.*?\})\s*```", re.DOTALL)

PROTOCOL = """\
## Action protocol
The provider constrains your public response to one JSON object. Return only:
{"tool": "<tool-name>", "args": { ... }}
To complete the task, use:
{"tool": "task.complete", "args": {"status": "completed|failed|review", "summary": "<one paragraph result>"}}
Use private reasoning when available, but put no commentary or Markdown in the
public response. Never invent tool names.
"""

REALTIME_PROTOCOL = """\
## Realtime response protocol
Return exactly one JSON object. For a direct spoken answer, return:
{"reply": "<one or two concise sentences>"}
When an authorized Tool is required, return only:
{"tool": "<tool-name>", "args": { ... }}
After the Tool observation, return the verified reply object. Never call
task.complete, narrate private reasoning, describe the packet, or expose an
internal error in the public reply.
"""

REASONING_BUDGETS = {"none": 0, "low": 1, "medium": 1, "high": 1, "xhigh": 1}


@dataclass(frozen=True)
class ChatReply:
    content: str
    finish_reason: str
    completion_tokens: int | None


def normalize_reasoning_effort(value: object) -> str:
    effort = str(value or "medium").lower()
    if effort not in REASONING_BUDGETS:
        raise ValueError(f"reasoning effort must be one of: {', '.join(REASONING_BUDGETS)}")
    return effort


def _chat_payload(messages: list[dict], spec: ModelSpec, *, max_tokens: int | None,
                  temperature: float | None, reasoning_effort: str) -> dict:
    """Build one Task-owned request for the sole executor path."""
    selected_temperature = CONFIG.llm_temperature if temperature is None else temperature
    template_kwargs = {"enable_thinking": reasoning_effort != "none"}
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
        "stream": False,
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
               model: ModelSpec | None = None) -> ChatReply:
    effort = normalize_reasoning_effort(reasoning_effort)
    spec = model or model_runtime.configured_spec(EXECUTIVE_MODEL)
    payload = _chat_payload(
        messages, spec, max_tokens=max_tokens, temperature=temperature,
        reasoning_effort=effort,
    )
    async with httpx.AsyncClient(timeout=300) as client:
        r = await client.post(f"{spec.base_url}/chat/completions", json=payload)
        r.raise_for_status()
        data = r.json()
        choice = data["choices"][0]
        completion_tokens = data.get("usage", {}).get("completion_tokens")
        return ChatReply(
            content=choice["message"].get("content") or "",
            finish_reason=str(choice.get("finish_reason") or "unknown"),
            completion_tokens=(
                int(completion_tokens) if isinstance(completion_tokens, int) else None
            ),
        )


def parse_action(text: str, *, allow_reply: bool = False) -> dict | None:
    def valid(obj: object) -> bool:
        if not isinstance(obj, dict):
            return False
        if not allow_reply:
            return "tool" in obj
        if set(obj) == {"reply"}:
            return isinstance(obj["reply"], str) and bool(obj["reply"].strip())
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


def action_parse_error(text: str, *, allow_reply: bool = False) -> str:
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
    if allow_reply:
        if "reply" in obj and "tool" in obj:
            return "Realtime response contains both reply and tool fields"
        if "reply" in obj:
            if not isinstance(obj.get("reply"), str) or not obj["reply"].strip():
                return "top-level reply field is not a nonempty string"
            return "Realtime reply object contains unexpected fields"
        if "tool" in obj:
            if not isinstance(obj.get("tool"), str) or not obj["tool"].strip():
                return "top-level tool field is not a nonempty string"
            if not isinstance(obj.get("args"), dict):
                return "top-level JSON object has no args object"
            return "Realtime tool object contains unexpected fields"
    if "tool" not in obj:
        return (
            "top-level JSON object has neither a tool nor reply field"
            if allow_reply
            else "top-level JSON object has no tool field"
        )
    if not isinstance(obj.get("args"), dict):
        return "top-level JSON object has no args object"
    return "unknown action parse failure"

"""LLM client (OpenAI-compatible llama.cpp server) + the JSON-action protocol.

We use a fenced-JSON action protocol instead of native tool calling: one code
path, debuggable, and reliable with small local models.
"""

from __future__ import annotations

import json
import re

import httpx

from .config import CONFIG

ACTION_RE = re.compile(r"```(?:action|json)?\s*(\{.*?\})\s*```", re.DOTALL)

PROTOCOL = """\
## Action protocol
Respond with exactly ONE fenced action block per turn and nothing after it:
```action
{"tool": "<tool-name>", "args": { ... }}
```
To complete the task, use:
```action
{"tool": "task.complete", "args": {"status": "completed|failed|review", "summary": "<one paragraph result>"}}
```
Think briefly before the block if useful. Never invent tool names.
"""

REASONING_BUDGETS = {
    "none": 0,
    "low": 256,
    "medium": 768,
    "high": 1536,
}


def normalize_reasoning_effort(value: object) -> str:
    effort = str(value or "medium").lower()
    if effort not in REASONING_BUDGETS:
        raise ValueError(f"reasoning effort must be one of: {', '.join(REASONING_BUDGETS)}")
    return effort


async def chat(messages: list[dict], max_tokens: int | None = None,
               temperature: float | None = None,
               reasoning_effort: str = "medium") -> str:
    effort = normalize_reasoning_effort(reasoning_effort)
    payload = {
        "model": CONFIG.llm_model,
        "messages": messages,
        "max_tokens": max_tokens or CONFIG.llm_max_tokens,
        "temperature": CONFIG.llm_temperature if temperature is None else temperature,
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": effort != "none"},
    }
    if effort != "none":
        payload["reasoning_format"] = "auto"
        payload["reasoning_budget_tokens"] = REASONING_BUDGETS[effort]
    async with httpx.AsyncClient(timeout=300) as client:
        r = await client.post(f"{CONFIG.llm_base_url}/chat/completions", json=payload)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"] or ""


async def chat_stream(messages: list[dict], temperature: float | None = None):
    """Yield content deltas (for the operator chat pane)."""
    payload = {
        "model": CONFIG.llm_model,
        "messages": messages,
        "max_tokens": CONFIG.llm_max_tokens,
        "temperature": CONFIG.llm_temperature if temperature is None else temperature,
        "stream": True,
    }
    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream("POST", f"{CONFIG.llm_base_url}/chat/completions", json=payload) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    return
                try:
                    delta = json.loads(data)["choices"][0]["delta"].get("content")
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue
                if delta:
                    yield delta


def parse_action(text: str) -> dict | None:
    m = ACTION_RE.search(text)
    if not m:
        # tolerate a bare top-level JSON object
        stripped = text.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                obj = json.loads(stripped)
                return obj if isinstance(obj, dict) and "tool" in obj else None
            except json.JSONDecodeError:
                return None
        return None
    try:
        obj = json.loads(m.group(1))
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) and "tool" in obj else None

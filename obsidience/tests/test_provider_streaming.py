from __future__ import annotations

import asyncio
from dataclasses import replace
import json
import time

import httpx
import pytest

from obsidience.harness.models import llm
from obsidience.harness.models.runtime import MODELS, SPECIALIST_MODEL


ACTION = '{"tool":"task.complete","args":{"status":"completed","summary":"Done 日本語"}}'


def event(delta=None, finish=None):
    return ("data: " + json.dumps({"choices": [{"delta": delta or {}, "finish_reason": finish}]}) + "\n\n").encode()


class Stream(httpx.AsyncByteStream):
    def __init__(self, pieces, delay=0):
        self.pieces, self.delay, self.closed = pieces, delay, False
        self.entered = asyncio.Event()

    async def __aiter__(self):
        self.entered.set()
        for piece in self.pieces:
            if self.delay:
                await asyncio.sleep(self.delay)
            yield piece

    async def aclose(self):
        self.closed = True


def wire(monkeypatch, stream):
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path.endswith("input_tokens"):
            return httpx.Response(200, json={"input_tokens": 30})
        payload = json.loads(request.content)
        assert payload["stream"] is True
        assert payload["stream_options"] == {"include_usage": True}
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=stream)

    client_type = httpx.AsyncClient
    monkeypatch.setattr(llm.httpx, "AsyncClient", lambda **kwargs: client_type(
        **kwargs, transport=httpx.MockTransport(handler)))
    return calls


def request():
    return llm.chat([{"role": "user", "content": "Bounded request"}], model=MODELS[SPECIALIST_MODEL])


def test_progressing_reasoning_can_exceed_former_total_deadline(monkeypatch):
    monkeypatch.setattr(llm, "CHAT_TIMEOUT_SECONDS", 0.15)
    stream = Stream([
        *[event({"reasoning_content": "private reasoning sentinel"}) for _ in range(5)],
        event({"content": ACTION}, "stop"),
        b'data: {"choices": [], "usage": {"completion_tokens": 6041}}\n\n',
        b"data: [DONE]\n\n",
    ], delay=0.04)
    calls = wire(monkeypatch, stream)
    started = time.monotonic()
    reply = asyncio.run(request())
    assert time.monotonic() - started > llm.CHAT_TIMEOUT_SECONDS
    assert reply.content == ACTION
    assert reply.finish_reason == "stop"
    assert reply.completion_tokens == 6041
    # Five private progress events precede the sixth, first public event.
    # Measuring the private first token as public TTFT would be about 40ms.
    assert reply.provider_metrics["first_public_delta_ms"] >= 200
    assert reply.provider_metrics["generation_ms"] >= reply.provider_metrics["first_public_delta_ms"]
    assert reply.provider_metrics["preflight_ms"] >= 0
    assert "private reasoning sentinel" not in repr(reply)
    assert len([r for r in calls if not r.url.path.endswith("input_tokens")]) == 1
    assert stream.closed


def test_provider_metrics_are_bounded_numeric_transport_observations(monkeypatch):
    stream = Stream([
        event({"role": "assistant"}),
        event({"content": ACTION}, "stop"),
        b'data: {"choices": [], "usage": {"completion_tokens": 42, "prompt_tokens_details": {"cached_tokens": 4000}}}\n\n',
        b"data: [DONE]\n\n",
    ], delay=0.01)
    wire(monkeypatch, stream)
    reply = asyncio.run(request())
    assert set(reply.provider_metrics) == {
        "preflight_ms", "first_public_delta_ms", "generation_ms", "cached_input_tokens",
    }
    assert reply.provider_metrics["cached_input_tokens"] == 4000
    assert reply.provider_metrics["first_public_delta_ms"] >= 15
    assert reply.provider_metrics["generation_ms"] >= reply.provider_metrics["first_public_delta_ms"]
    assert all(isinstance(value, (int, float)) for value in reply.provider_metrics.values())
    assert ACTION not in repr(reply.provider_metrics)


@pytest.mark.parametrize("piece", [b": heartbeat\n\n", event({"role": "assistant"})])
def test_heartbeats_and_empty_role_events_do_not_mask_stall(monkeypatch, piece):
    monkeypatch.setattr(llm, "CHAT_TIMEOUT_SECONDS", 0.08)
    stream = Stream([piece] * 30, delay=0.02)
    calls = wire(monkeypatch, stream)
    with pytest.raises(TimeoutError, match="without token progress"):
        asyncio.run(request())
    assert stream.closed
    assert len([r for r in calls if not r.url.path.endswith("input_tokens")]) == 1


def test_sse_fragmentation_and_multiline_framing_preserve_exact_action(monkeypatch):
    frame = json.dumps({"choices": [{"delta": {"content": ACTION}, "finish_reason": "stop"}]}, indent=2)
    material = ("\n".join("data: " + line for line in frame.splitlines()) + "\n\ndata: [DONE]\n\n").encode()
    stream = Stream([material[i:i + 7] for i in range(0, len(material), 7)])
    wire(monkeypatch, stream)
    assert asyncio.run(request()).content == ACTION


@pytest.mark.parametrize("pieces", [
    [event({"content": ACTION}, "stop")],
    [event({"content": ACTION}), b"data: [DONE]\n\n"],
    [event({"content": ACTION}, "stop"), event({"content": "late"}), b"data: [DONE]\n\n"],
    [b'data: {"error": {"message": "private error sentinel"}}\n\n'],
    [b"data: []\n\n"],
    [b"data: not-json\n\n"],
])
def test_incomplete_or_invalid_stream_never_returns_action(monkeypatch, pieces):
    stream = Stream(pieces)
    wire(monkeypatch, stream)
    with pytest.raises(ValueError) as failure:
        asyncio.run(request())
    assert "private error sentinel" not in str(failure.value)
    assert stream.closed


def test_foreground_cancellation_closes_provider_stream_without_partial_action(monkeypatch):
    async def run():
        stream = Stream([event({"content": "partial"})] * 30, delay=0.1)
        wire(monkeypatch, stream)
        pending = asyncio.create_task(request())
        await stream.entered.wait()
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert stream.closed

    asyncio.run(run())


def test_controller_response_schema_uses_existing_stream_and_token_accounting(monkeypatch):
    response = '{"task_ref":"Tasks/query"}'
    stream = Stream([event({"content": response}, "stop"), b"data: [DONE]\n\n"])
    calls = wire(monkeypatch, stream)
    schema = {"type": "object", "properties": {"task_ref": {"const": "Tasks/query"}},
              "required": ["task_ref"], "additionalProperties": False}
    reply = asyncio.run(llm.chat(
        [{"role": "user", "content": "Choose an existing outcome"}],
        model=MODELS[SPECIALIST_MODEL], reasoning_effort="none", temperature=0,
        max_tokens=192, response_schema=schema,
    ))
    assert reply.content == response and reply.prompt_tokens == 30
    assert len(calls) == 2  # One measurement and one generation, no Tool execution.
    payload = json.loads(calls[-1].content)
    assert payload["response_format"] == {
        "type": "json_schema", "json_schema": {
            "name": "obsidience_response", "strict": True, "schema": schema,
        },
    }
    assert payload["max_tokens"] == 192 and payload["temperature"] == 0
    assert payload["chat_template_kwargs"]["enable_thinking"] is False


@pytest.mark.parametrize("allowed_tools", [[], ["task.complete"]])
def test_controller_schema_cannot_share_tool_response_authority(allowed_tools):
    with pytest.raises(ValueError, match="mutually exclusive"):
        llm._chat_payload([], MODELS[SPECIALIST_MODEL], max_tokens=192,
                          temperature=0, reasoning_effort="none",
                          allowed_tools=allowed_tools, response_schema={"type": "object"})


def test_controller_schema_fails_closed_without_provider_support():
    with pytest.raises(ValueError, match="does not support"):
        llm._chat_payload([], replace(MODELS[SPECIALIST_MODEL], supports_json_schema=False),
                          max_tokens=192, temperature=0, reasoning_effort="none",
                          response_schema={"type": "object"})


def test_gemma_admission_keeps_its_controller_instructions_without_task_action_guidance():
    spec = next(spec for spec in MODELS.values() if spec.family == "gemma4" and spec.task_capable)
    messages = [{"role": "system", "content": "Select one existing Task; execute nothing."},
                {"role": "user", "content": "Current request and conversation"}]
    payload = llm._chat_payload(messages, spec, max_tokens=192, temperature=0,
                                reasoning_effort="none", response_schema={"type": "object"})
    assert payload["messages"] == messages
    assert "Thinking Packet" not in payload["messages"][0]["content"]
    assert payload["chat_template_kwargs"] == {"enable_thinking": False}

from __future__ import annotations

import asyncio
import json
from dataclasses import replace

import httpx
import pytest

from obsidience.harness.models import context, llm
from obsidience.harness.models.runtime import EXECUTIVE_MODEL, MODELS


def test_text_count_uses_runtime_and_caches_only_success(monkeypatch):
    context._TEXT_COUNTS.clear()
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"tokens": [1, 2, 3]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        monkeypatch.setattr(context, "_TOKENIZER", client)
        assert context.count_text("日本語 {}", MODELS[EXECUTIVE_MODEL]) == 3
        assert context.count_text("日本語 {}", MODELS[EXECUTIVE_MODEL]) == 3
    assert len(calls) == 1
    assert json.loads(calls[0].content)["parse_special"] is False


def test_text_count_failure_does_not_poison_cache(monkeypatch):
    context._TEXT_COUNTS.clear()
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"tokens": [1]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        monkeypatch.setattr(context, "_TOKENIZER", client)
        assert context.count_text("日本", MODELS[EXECUTIVE_MODEL]) == 6
        assert context.count_text("日本", MODELS[EXECUTIVE_MODEL]) == 1


def test_whole_request_count_preserves_template_settings():
    spec = MODELS[EXECUTIVE_MODEL]
    payload = llm._chat_payload(
        [{"role": "user", "content": "test"}], spec,
        max_tokens=128, temperature=0, reasoning_effort="low",
    )

    def handler(request):
        assert request.url.path == "/v1/chat/completions/input_tokens"
        assert json.loads(request.content) == payload
        return httpx.Response(200, json={"input_tokens": 37})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            assert await context.count_payload(payload, spec, client) == 37

    asyncio.run(run())


def test_every_chat_checks_budget_before_generation(monkeypatch):
    paths = []

    def handler(request):
        paths.append(request.url.path)
        if request.url.path.endswith("input_tokens"):
            return httpx.Response(200, json={"input_tokens": 300})
        pytest.fail("oversized request must not reach inference")

    client_type = httpx.AsyncClient
    monkeypatch.setattr(llm.httpx, "AsyncClient", lambda **kwargs: client_type(
        **kwargs, transport=httpx.MockTransport(handler)))
    spec = replace(MODELS[EXECUTIVE_MODEL], context_tokens=512, max_output_tokens=128)
    with pytest.raises(ValueError, match="Objective has not been truncated"):
        asyncio.run(llm.chat([{"role": "user", "content": "large"}], model=spec))
    assert paths == ["/v1/chat/completions/input_tokens"]


def test_private_reasoning_never_becomes_public_reply(monkeypatch):
    def handler(request):
        if request.url.path.endswith("input_tokens"):
            return httpx.Response(200, json={"input_tokens": 30})
        chunks = [
            {"choices": [{"delta": {"reasoning_content": "private test sentinel"}}]},
            {"choices": [{"delta": {"content": '{"tool":"task.complete","args":{"summary":"Done"}}'},
                          "finish_reason": "stop"}]},
            {"choices": [], "usage": {"completion_tokens": 8}},
        ]
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=(
            "".join("data: " + json.dumps(chunk) + "\n\n" for chunk in chunks)
            + "data: [DONE]\n\n"
        ))

    client_type = httpx.AsyncClient
    monkeypatch.setattr(llm.httpx, "AsyncClient", lambda **kwargs: client_type(
        **kwargs, transport=httpx.MockTransport(handler)))
    result = asyncio.run(llm.chat([{"role": "user", "content": "test"}],
                                  model=MODELS[EXECUTIVE_MODEL]))
    assert result.content == '{"tool":"task.complete","args":{"summary":"Done"}}'
    assert result.prompt_tokens == 30
    assert "private test sentinel" not in repr(result)


def test_generation_timeout_reports_model_and_phase_without_response_text(monkeypatch):
    def handler(request):
        if request.url.path.endswith("input_tokens"):
            return httpx.Response(200, json={"input_tokens": 30})
        raise httpx.ReadTimeout("private transport detail", request=request)

    client_type = httpx.AsyncClient
    monkeypatch.setattr(llm.httpx, "AsyncClient", lambda **kwargs: client_type(
        **kwargs, transport=httpx.MockTransport(handler)))
    with pytest.raises(TimeoutError, match=(
        rf"{EXECUTIVE_MODEL} generation timed out after "
        rf"{llm.CHAT_TIMEOUT_SECONDS:g} seconds"
    )) as failure:
        asyncio.run(llm.chat(
            [{"role": "user", "content": "test"}],
            model=MODELS[EXECUTIVE_MODEL],
        ))
    assert "private transport detail" not in str(failure.value)


def test_activation_packet_preserves_long_exact_objective(monkeypatch):
    from obsidience.harness.execution import executor
    from obsidience.harness.knowledge.vault import Note

    monkeypatch.setattr(executor, "resolver", lambda: None)
    monkeypatch.setattr(executor, "_skill_tools", lambda *args: [])
    task = Note("Tasks/test.md", "Test", {"kind": "task"}, "Do the requested work")
    objective = "First line\n" + "punctuation {}; 日本語\n" * 400 + "IMPORTANT final constraint"
    packet, _refs = executor._activation_packet(
        task, None, {"runbooks": [], "skills": []},
        executor.ActivationBinding(objective, {}), "", "", "",
    )
    assert "## Objective\n" + objective + "\n\n## Tools" in packet



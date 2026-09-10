from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import replace
import json

import httpx
import pytest

from obsidience.harness.models import context, llm
from obsidience.harness.models.runtime import EXECUTIVE_MODEL, MODELS


SPEC = MODELS[EXECUTIVE_MODEL]
ACTION = '{"tool":"task.complete","args":{"status":"completed","summary":"Done"}}'


@pytest.fixture(autouse=True)
def isolated_cache(monkeypatch):
    assert llm._PROVIDER_CLIENT is None
    monkeypatch.setattr(context, "_TEXT_COUNTS", OrderedDict())
    yield
    assert llm._PROVIDER_CLIENT is None


def wire(monkeypatch, handler):
    clients = []

    class Client(httpx.AsyncClient):
        close_count = 0

        async def aclose(self):
            self.close_count += 1
            await super().aclose()

    def create():
        client = Client(transport=httpx.MockTransport(handler), trust_env=False)
        clients.append(client)
        return client

    monkeypatch.setattr(llm, "_new_provider_client", create)
    return clients


def answer():
    event = {"choices": [{"delta": {"content": ACTION}, "finish_reason": "stop"}]}
    return httpx.Response(200, headers={"content-type": "text/event-stream"},
                          content="data: " + json.dumps(event) + "\n\ndata: [DONE]\n\n")


def test_lifetime_reuses_one_client_for_exact_preflight_and_generation(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        return (httpx.Response(200, json={"input_tokens": 41})
                if request.url.path.endswith("input_tokens") else answer())

    clients = wire(monkeypatch, handler)

    async def run():
        await llm.start_provider_client()
        try:
            await llm.start_provider_client()
            for text in ("first", "second"):
                reply = await llm.chat([{"role": "user", "content": text}], model=SPEC,
                                       reasoning_effort="none", max_tokens=128)
                assert reply.content == ACTION
                assert reply.prompt_tokens == 41
            assert len(clients) == 1
            assert not clients[0].is_closed
            for count_request, generation in zip(requests[::2], requests[1::2]):
                assert json.loads(count_request.content) == json.loads(generation.content)
        finally:
            await llm.close_provider_client()
        await llm.close_provider_client()

    asyncio.run(run())
    assert clients[0].is_closed
    assert clients[0].close_count == 1


def test_standalone_calls_close_clients_across_separate_event_loops(monkeypatch):
    clients = wire(monkeypatch, lambda request: (
        httpx.Response(200, json={"input_tokens": 20})
        if request.url.path.endswith("input_tokens") else answer()))
    for _ in range(2):
        assert asyncio.run(llm.chat([{"role": "user", "content": "hello"}], model=SPEC)).content == ACTION
    assert len(clients) == 2
    assert all(client.is_closed for client in clients)
    assert llm._PROVIDER_CLIENT is None


def test_foreign_loop_never_uses_or_closes_the_live_owner_client(monkeypatch):
    clients = wire(monkeypatch, lambda _: httpx.Response(200, json={"tokens": [1]}))

    async def foreign():
        with pytest.raises(RuntimeError, match="another event loop"):
            await llm.start_provider_client()
        with pytest.raises(RuntimeError, match="owner event loop"):
            await llm.close_provider_client()
        async with llm.provider_client() as local:
            assert local is not clients[0]
        assert local.is_closed

    async def run():
        await llm.start_provider_client()
        try:
            await asyncio.to_thread(lambda: asyncio.run(foreign()))
            async with llm.provider_client() as current:
                assert current is clients[0]
                assert not current.is_closed
        finally:
            await llm.close_provider_client()

    asyncio.run(run())
    assert len(clients) == 2
    assert all(client.is_closed for client in clients)


def test_cancelling_stream_closes_response_but_preserves_pool_for_next_request(monkeypatch):
    class WaitingStream(httpx.AsyncByteStream):
        def __init__(self):
            self.entered = asyncio.Event()
            self.closed = False

        async def __aiter__(self):
            self.entered.set()
            yield b': waiting\n\n'
            await asyncio.Event().wait()

        async def aclose(self):
            self.closed = True

    async def run():
        stream = WaitingStream()
        generations = 0

        def handler(request):
            nonlocal generations
            if request.url.path.endswith("input_tokens"):
                return httpx.Response(200, json={"input_tokens": 20})
            generations += 1
            if generations == 1:
                return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=stream)
            return answer()

        clients = wire(monkeypatch, handler)
        await llm.start_provider_client()
        try:
            task = asyncio.create_task(llm.chat([{"role": "user", "content": "first"}], model=SPEC))
            await asyncio.wait_for(stream.entered.wait(), 1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert stream.closed
            assert not clients[0].is_closed
            reply = await llm.chat([{"role": "user", "content": "next"}], model=SPEC)
            assert reply.content == ACTION
            assert generations == 2  # No replay of the cancelled request.
            assert len(clients) == 1
        finally:
            await llm.close_provider_client()

    asyncio.run(run())


def test_slow_tokenizer_yields_event_loop_and_uses_existing_pool(monkeypatch):
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()

        async def handler(request):
            assert json.loads(request.content) == {
                "content": "日本語", "add_special": False, "parse_special": False,
            }
            assert request.extensions["timeout"]["read"] == 0.5
            entered.set()
            await release.wait()
            return httpx.Response(200, json={"tokens": [1, 2]})

        clients = wire(monkeypatch, handler)
        await llm.start_provider_client()
        task = asyncio.create_task(context.measure_text("日本語", SPEC))
        try:
            await asyncio.wait_for(entered.wait(), 1)
            # A concurrent event-loop task runs while tokenization is pending.
            await asyncio.wait_for(asyncio.sleep(0), 1)
            assert not task.done()
            assert context.cached_text_count("日本語", SPEC) == context.PayloadCount(9, "utf8_upper_bound")
            release.set()
            assert await task == context.PayloadCount(2, "runtime")
            assert context.cached_text_count("日本語", SPEC) == context.PayloadCount(2, "runtime")
            assert len(clients) == 1
        finally:
            release.set()
            await task
            await llm.close_provider_client()

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["timeout", "http", "malformed", "shape"])
def test_count_failure_is_explicit_and_never_cached(monkeypatch, failure):
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) > 1:
            return httpx.Response(200, json={"tokens": [1]})
        if failure == "timeout":
            raise httpx.ReadTimeout("tokenizer unavailable", request=request)
        if failure == "http":
            return httpx.Response(503)
        if failure == "malformed":
            return httpx.Response(200, text="invalid json")
        return httpx.Response(200, json={"tokens": 3})

    clients = wire(monkeypatch, handler)

    async def run():
        assert await context.measure_text("日本", SPEC) == context.PayloadCount(6, "utf8_upper_bound")
        assert context.cached_text_count("日本", SPEC) == context.PayloadCount(6, "utf8_upper_bound")
        assert await context.measure_text("日本", SPEC) == context.PayloadCount(1, "runtime")
        assert await context.measure_text("日本", SPEC) == context.PayloadCount(1, "runtime")

    asyncio.run(run())
    assert len(calls) == 2
    assert all(client.is_closed for client in clients)


def test_text_cache_tracks_artifact_revision_and_remains_bounded(monkeypatch, tmp_path):
    path = tmp_path / "model.gguf"
    path.write_bytes(b"first")
    spec = replace(SPEC, model_path=path)
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"tokens": list(range(len(calls)))})

    wire(monkeypatch, handler)

    async def run():
        await llm.start_provider_client()
        try:
            assert await context.measure_text("same", spec) == context.PayloadCount(1)
            assert context.cached_text_count("same", spec) == context.PayloadCount(1)
            path.write_bytes(b"changed artifact")
            assert context.cached_text_count("same", spec) == context.PayloadCount(4, "utf8_upper_bound")
            assert await context.measure_text("same", spec) == context.PayloadCount(2)
            for index in range(130):
                await context.measure_text(str(index), spec)
            assert len(context._TEXT_COUNTS) == 128
        finally:
            await llm.close_provider_client()

    asyncio.run(run())


def test_empty_and_cached_meter_counts_do_not_create_transport(monkeypatch):
    def unexpected():
        pytest.fail("meter cache and empty input must not open a transport")

    monkeypatch.setattr(llm, "_new_provider_client", unexpected)
    assert context.cached_text_count("日本", SPEC) == context.PayloadCount(6, "utf8_upper_bound")
    assert context.cached_text_count("", SPEC) == context.PayloadCount(0)
    assert asyncio.run(context.measure_text("", SPEC)) == context.PayloadCount(0)


def test_cancelled_tokenizer_count_does_not_become_a_cached_estimate(monkeypatch):
    async def run():
        entered = asyncio.Event()

        async def handler(request):
            entered.set()
            await asyncio.Event().wait()

        clients = wire(monkeypatch, handler)
        task = asyncio.create_task(context.measure_text("cancel", SPEC))
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not context._TEXT_COUNTS
        assert clients[0].is_closed

    asyncio.run(run())

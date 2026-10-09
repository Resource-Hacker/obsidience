from __future__ import annotations

import asyncio
import copy
import json
from dataclasses import replace

import httpx
import pytest

from obsidience.harness.models import context
from obsidience.harness.models.runtime import MODELS, EXECUTIVE_MODEL


def source_page(number, body):
    citation = f"source://00000000-0000-0000-0000-{number:012d}"
    header = f"{citation} · document · 2026-09-05\nReference: https://example.com/{number}\nSHA-256: sha256:{number:064x}\n\n"
    return f"{header}Characters 2500-{2500 + len(body)} of {2500 + len(body)}. End of Source.\n\n{body}"


def observed_pages():
    messages = [
        {"role": "system", "content": "Fixed authorized procedure."},
        {"role": "user", "content": "# Thinking Packet\n## Objective\nExact\n  whitespace and constraints 日本語"},
        {"role": "assistant", "content": '{"tool":"window.place","args":{"destination":"exact"}}'},
        {"role": "user", "content": 'Observation:\n{"effect_applied":true,"must_not_replay":true}'},
    ]
    projection = context.TaskContext()
    for number in range(1, 5):
        observation = source_page(number, (f"Verified story {number}. " * 400))
        messages.append({"role": "assistant", "content": json.dumps({
            "tool": "source.read", "args": {"source": f"source://00000000-0000-0000-0000-{number:012d}", "offset": 2500},
        })})
        projection.remember_source_page(len(messages), "source.read", observation, "",
                                        source_read_allowed=True)
        messages.append({"role": "user", "content": "Observation:\n" + observation})
    return messages, projection


@pytest.mark.parametrize("change", ["objective", "latest", "wrong_message", "no_read_tool"])
def test_fixed_and_unrecoverable_context_never_gets_silently_dropped(change):
    messages, projection = observed_pages()
    if change == "objective":
        messages[1]["content"] += "must preserve " * 2000
    elif change == "latest":
        messages[-1]["content"] += "latest must preserve " * 2000
    elif change == "wrong_message":
        for page in projection.pages.values():
            messages[page.index]["content"] = "replaced " * 2000
    else:
        projection = context.TaskContext()
    original = copy.deepcopy(messages)

    def handler(request):
        return httpx.Response(200, json={"input_tokens": len(json.dumps(json.loads(request.content)["messages"]))})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(context.ContextBudgetExceeded, match="Objective has not been truncated"):
                await projection.fit_payload({"messages": messages}, MODELS[EXECUTIVE_MODEL], client, 15000)

    asyncio.run(run())
    assert messages == original


@pytest.mark.parametrize("tool", ["source.handoff", "window.place", "arbitrary"])
def test_source_shaped_mutation_result_cannot_grant_projection(tool):
    projection = context.TaskContext()
    projection.remember_source_page(3, tool, source_page(1, "x" * 10000), "", source_read_allowed=True)
    assert projection.pages == {}


@pytest.mark.parametrize("tool", ["source.read", "web.fetch", "vault.read"])
def test_pressure_preserves_individual_batch_identities_failures_and_latest_result(tool):
    projection = context.TaskContext()
    rows = []
    for number in (1, 2):
        body = f"Evidence {number}. " * 1000
        if tool == "vault.read":
            identity = json.dumps({"ref": f"Subject/{number}", "view_sha256": f"{number:064x}"})
            text = f"Article: {identity}\nCharacters 0-{len(body)} of {len(body)}. End of Article view.\n\n{body}"
        else:
            text = source_page(number, body)
            if tool == "web.fetch":
                text = text.replace(text.splitlines()[0],
                                    f"Fetched and captured https://example.com/{number} as "
                                    f"source://00000000-0000-0000-0000-{number:012d} (hash).", 1)
        rows.append({"ok": True, "result": text})
    failure = {"ok": False, "result": "Source unavailable: exact missing object; no evidence returned."}
    rows.append(failure)
    observation = json.dumps({"results": rows})
    suffix = "\nExecution budget: 8 model decisions remain."
    if tool == "vault.read":
        projection.remember_article_page(1, tool, observation, suffix, vault_read_allowed=True)
    else:
        projection.remember_source_page(1, tool, observation, suffix, source_read_allowed=True)
    messages = [{"role": "system", "content": "Preserve exact policy."},
                {"role": "user", "content": "Observation:\n" + observation + suffix},
                {"role": "assistant", "content": '{"tool":"vault.validate","args":{}}'},
                {"role": "user", "content": "Observation:\nExact latest result."}]
    projection.latest_result_index = 3
    original = copy.deepcopy(messages)
    payload = {"messages": messages}

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"input_tokens": len(json.dumps(
                json.loads(request.content)["messages"]))}),
        )) as client:
            await projection.fit_payload(payload, MODELS[EXECUTIVE_MODEL], client, 6500)

    asyncio.run(run())
    assert messages == original
    assert payload["messages"][-1] == original[-1]
    projected = payload["messages"][1]["content"]
    assert projected.endswith(suffix)
    batch = json.loads(projected.removeprefix("Observation:\n").removesuffix(suffix))
    assert batch["results"][-1] == failure
    for number, row in enumerate(batch["results"][:2], 1):
        assert row["ok"] is True
        assert "Omitted text is not in this request" in row["result"]
        if tool == "vault.read":
            assert f"Subject/{number}" in row["result"]
            assert f"{number:064x}" in row["result"]
            assert "expected_sha256" in row["result"]
        else:
            assert f"source://00000000-0000-0000-0000-{number:012d}" in row["result"]
            assert "source.read" in row["result"]
    key = "article_pages_projected" if tool == "vault.read" else "source_pages_projected"
    assert projection.last_projection[key] == 2


def test_protocol_correction_does_not_make_latest_tool_result_discardable():
    messages, projection = observed_pages()
    latest_index = len(messages) - 1
    original_latest = messages[latest_index]["content"]
    messages.extend([
        {"role": "assistant", "content": "malformed action"},
        {"role": "user", "content": "Return a valid action object."},
    ])
    payload = {"messages": messages}

    def handler(request):
        return httpx.Response(200, json={"input_tokens": len(json.dumps(json.loads(request.content)["messages"]))})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await projection.fit_payload(payload, MODELS[EXECUTIVE_MODEL], client, 15000)

    asyncio.run(run())
    assert payload["messages"][latest_index]["content"] == original_latest
    assert projection.last_projection["source_pages_projected"] == 3


@pytest.mark.parametrize("envelope", [None, [], {"input_tokens": -1}, {"input_tokens": True}, {"count": "wrong"}])
def test_failed_count_is_explicit_upper_bound_not_exact_tokens(envelope):
    def handler(_request):
        return httpx.Response(200, json=envelope)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            count = await context.measure_payload({"messages": [{"role": "user", "content": "日本"}]},
                                                   MODELS[EXECUTIVE_MODEL], client)
            assert count.method == "utf8_upper_bound"
            assert count.tokens > len("日本")

    asyncio.run(run())


def test_exact_tokens_can_fit_even_when_utf8_upper_bound_does_not():
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"input_tokens": 3}),
        )) as client:
            result = await context.TaskContext().fit_payload(
                {"messages": [{"role": "user", "content": "large " * 10000}]},
                MODELS[EXECUTIVE_MODEL], client, 100,
            )
            assert result == context.PayloadCount(3, "runtime")

    asyncio.run(run())


def test_multimodal_accounting_failure_stays_closed_and_consumption_is_explicit():
    messages = [{"role": "user", "content": [
        {"type": "text", "text": "Exact observation"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,private-image"}},
    ]}]

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(503))) as client:
            with pytest.raises(ValueError, match="multimodal"):
                await context.measure_payload({"messages": messages}, MODELS[EXECUTIVE_MODEL], client)

    asyncio.run(run())
    assert isinstance(messages[0]["content"], list)
    context.discard_consumed_images(messages)
    assert messages == [{"role": "user", "content": "Exact observation"}]



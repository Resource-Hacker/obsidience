from __future__ import annotations

import asyncio
import json
import threading
from contextlib import asynccontextmanager
from types import SimpleNamespace as NS

import pytest

from obsidience.harness.execution import executor


@pytest.fixture
def execution(monkeypatch):
    """Real executor, with no live model, Tool, retrieval, status or ledger writes."""
    task = NS(ref="Tasks/query", title="Query", kind="task", meta={})
    agent = NS(ref="Agents/Executive/Executive", title="Executive", kind="agent", meta={}, body="Isolated role")
    book = NS(ref="Runbooks/query", title="Query procedure")
    model = NS(id="isolated", label="Isolated", context_tokens=10000, max_output_tokens=1000)
    state = NS(task=task, events=[], records=[], calls=[], statuses=[], contexts=[], live_meta={}, releases=0)
    tools = ["task.complete", "window.place", *executor.MODEL_RESOURCE_TOOLS]
    state.tools = tools
    spine = dict(runbook=book, runbooks=[book], skills=[], tools=tools)

    async def compile_packet(*_args, **_kwargs):
        state.events.append(dict(phase="path", refs=[task.ref, book.ref]))
        return dict(
            packet="Isolated packet", refs=[task.ref, book.ref], spine=spine,
            provider_system="Isolated fixed instructions",
            provider_user="Move the requested application",
            retrieval_ms=1.25, objective="Move the requested application",
        )

    async def reply(*_args, **_kwargs):
        return NS(content='{"tool":"task.complete","args":{"status":"completed","summary":"Done."}}',
                  prompt_tokens=100)

    @asynccontextmanager
    async def lease(*_args, **_kwargs):
        try:
            yield model
        finally:
            state.releases += 1

    def tool(name, args, ctx):
        state.calls.append((name, args))
        state.contexts.append(ctx)
        if name == "task.complete":
            from obsidience.harness.capabilities.task.complete import execute

            return execute(args, ctx)
        return dict(status="completed", effect_applied=True, must_not_replay=True)

    def status(_task, value, fields):
        state.live_meta.update({"status": value, **fields})
        state.statuses.append(value)

    def mutate(_task, callback):
        before = dict(state.live_meta)
        callback(state.live_meta)
        if state.live_meta != before:
            state.statuses.append(state.live_meta["status"])
        return state.live_meta

    monkeypatch.setattr(executor, "resolver", lambda **_kwargs: NS(resolve=lambda _ref: agent))
    monkeypatch.setattr(executor, "resolve_spine", lambda *_args: spine)
    # Scope is tested with real accepted snapshots separately; this fixture
    # isolates cancellation after compiler authorization.
    monkeypatch.setattr(executor, "_scope_checkpoint", lambda *_args: None)
    monkeypatch.setattr(executor, "runbook_tree_hash", lambda _books: "isolated-hash")
    monkeypatch.setattr(executor, "compile_activation", compile_packet)
    monkeypatch.setattr(executor, "cached_text_count", lambda *_args: NS(tokens=100, method="runtime"))
    monkeypatch.setattr(executor, "execute_capability", tool)
    async def async_tool(name, args, ctx):
        return executor.execute_capability(name, args, ctx)
    monkeypatch.setattr(executor, "execute_capability_async", async_tool)
    monkeypatch.setattr(executor, "update_status", status)
    monkeypatch.setattr(executor, "mutate_note_metadata", mutate)
    monkeypatch.setattr(executor.model_runtime, "resolve_model", lambda *_args: model)
    monkeypatch.setattr(executor.model_runtime, "configured_spec", lambda *_args: model)
    monkeypatch.setattr(executor.model_runtime, "lease", lease)
    monkeypatch.setattr(executor.llm, "chat", reply)
    monkeypatch.setattr(executor.INDEX, "record_run", lambda **row: state.records.append(row))
    monkeypatch.setattr(executor.INDEX, "sync", lambda **_kwargs: None)
    monkeypatch.setattr(executor.action_trace, "emit", lambda *_args: None)
    monkeypatch.setattr(
        executor.knowledge_activity, "emit",
        lambda phase, refs, **fields: state.events.append(dict(phase=phase, refs=refs, **fields)),
    )

    async def run(**kwargs):
        return await executor.run_task(
            task, **{
                "emit_turn_event": False,
                "interactive": True,
                "runtime_params": {"request": "Move the requested application"},
                **kwargs,
            },
        )

    state.run = run
    state.reply = reply
    return state


@pytest.mark.parametrize("point", ["compilation", "model", "after_tool"])
def test_cancellation_finishes_activity_and_preserves_returned_effects(execution, monkeypatch, point):
    async def exercise():
        reached = asyncio.Event()
        count = 0

        async def block(*_args, **_kwargs):
            nonlocal count
            count += 1
            if point == "after_tool" and count == 1:
                return NS(content='{"tool":"window.place","args":{}}', prompt_tokens=100)
            reached.set()
            await asyncio.Event().wait()

        if point == "compilation":
            monkeypatch.setattr(executor, "compile_activation", block)
        else:
            monkeypatch.setattr(executor.llm, "chat", block)
        turn = asyncio.create_task(execution.run())
        await asyncio.wait_for(reached.wait(), 2)
        turn.cancel()
        with pytest.raises(asyncio.CancelledError):
            await turn

    asyncio.run(exercise())
    assert [e["phase"] for e in execution.events].count("query_completed") == 1
    assert execution.events[-1]["query"] == "Move the requested application"
    assert len(execution.records) == 1
    record = execution.records[0]
    assert record["status"] == "interrupted"
    assert execution.statuses == ["running", "failed"]
    trace = json.loads(record["trace"])
    if point == "after_tool":
        assert execution.calls == [("window.place", {})]
        assert trace[0]["activation_packet"] == execution.events[-1]["refs"]
        assert json.loads(trace[1]["obs"])["effect_applied"] is True
        assert json.loads(trace[1]["obs"])["must_not_replay"] is True
    else:
        assert not execution.calls


def test_cancellation_during_tool_reports_unknown_not_failed_or_replayed(execution, monkeypatch):
    async def exercise():
        loop = asyncio.get_running_loop()
        reached = asyncio.Event()
        release = threading.Event()

        def slow_tool(name, args, _ctx):
            execution.calls.append((name, args))
            loop.call_soon_threadsafe(reached.set)
            assert release.wait(3)
            return {"effect_applied": True}

        async def call_tool(*_args, **_kwargs):
            return NS(content='{"tool":"window.place","args":{}}', prompt_tokens=100)

        monkeypatch.setattr(executor, "execute_capability", slow_tool)
        monkeypatch.setattr(executor.llm, "chat", call_tool)
        turn = asyncio.create_task(execution.run())
        try:
            await asyncio.wait_for(reached.wait(), 2)
            turn.cancel()
            with pytest.raises(asyncio.CancelledError):
                await turn
        finally:
            release.set()

    asyncio.run(exercise())
    assert execution.calls == [("window.place", {})]
    call = json.loads(execution.records[0]["trace"])[1]
    assert call["interrupted"] and call["must_not_replay"]
    assert "unknown" in call["obs"]
    assert execution.events[-1]["phase"] == "query_completed"


@pytest.mark.parametrize("point", ["entry", "resource_exit"])
def test_canceled_lease_is_not_exited_twice(execution, monkeypatch, point):
    exits = []

    class Lease:
        async def __aenter__(self):
            if point == "entry":
                raise asyncio.CancelledError

        async def __aexit__(self, *_args):
            exits.append(True)
            raise asyncio.CancelledError

    async def resource_tool(*_args, **_kwargs):
        name = next(iter(executor.MODEL_RESOURCE_TOOLS))
        return NS(content=json.dumps({"tool": name, "args": {}}), prompt_tokens=100)

    monkeypatch.setattr(executor.model_runtime, "lease", lambda *_args: Lease())
    monkeypatch.setattr(executor.llm, "chat", resource_tool)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(execution.run())
    assert len(exits) == (0 if point == "entry" else 1)
    assert not execution.calls
    assert execution.records[0]["status"] == "interrupted"
    assert execution.events[-1]["phase"] == "query_completed"


@pytest.mark.parametrize("failure", [None, "compile", "ledger"])
def test_success_and_failures_emit_exactly_one_terminal_event(execution, monkeypatch, failure):
    async def broken_compile(*_args, **_kwargs):
        raise RuntimeError("isolated compilation failure")

    def broken_ledger(**_kwargs):
        raise RuntimeError("isolated ledger failure")

    if failure == "compile":
        monkeypatch.setattr(executor, "compile_activation", broken_compile)
    elif failure == "ledger":
        monkeypatch.setattr(executor.INDEX, "record_run", broken_ledger)
    if failure:
        with pytest.raises(RuntimeError, match="isolated"):
            asyncio.run(execution.run())
        if failure == "compile":
            assert execution.statuses == ["running", "failed"]
            assert execution.records[0]["status"] == "failed"
            assert execution.records[0]["overwrite"] is False
    else:
        assert asyncio.run(execution.run())["status"] == "completed"
        assert execution.records[0]["status"] == "completed"
    assert [e["phase"] for e in execution.events].count("query_completed") == 1
    assert execution.events[-1]["phase"] == "query_completed"


def test_interrupted_activation_can_be_followed_by_an_ordinary_completion(execution, monkeypatch):
    async def exercise():
        reached = asyncio.Event()

        async def block(*_args, **_kwargs):
            reached.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(executor.llm, "chat", block)
        turn = asyncio.create_task(execution.run())
        await asyncio.wait_for(reached.wait(), 2)
        turn.cancel()
        with pytest.raises(asyncio.CancelledError):
            await turn
        assert execution.records[-1]["status"] == "interrupted"

        monkeypatch.setattr(executor.llm, "chat", execution.reply)
        result = await execution.run()
        assert result["status"] == "completed"
        assert result["summary"] == "Done."
        assert "reply" not in result
        assert [row["status"] for row in execution.records] == ["interrupted", "completed"]

    asyncio.run(exercise())
    assert execution.statuses == ["running", "failed", "running", "completed"]
    assert [e["phase"] for e in execution.events].count("query_completed") == 2


@pytest.mark.parametrize("source", ["text", "realtime"])
def test_interactive_completion_uses_one_packet_tools_and_protocol(execution, monkeypatch, source):
    contract = "Keep the task.complete summary to two concise spoken sentences."

    async def complete(messages, **kwargs):
        assert executor.llm.PROTOCOL in messages[0]["content"]
        assert contract in messages[0]["content"]
        assert messages[1]["content"] == "Move the requested application"
        assert "Isolated fixed instructions" in messages[0]["content"]
        assert set(kwargs["allowed_tools"]) == {
            "task.complete", "window.place", *executor.MODEL_RESOURCE_TOOLS,
        }
        return await execution.reply()

    monkeypatch.setattr(executor.llm, "chat", complete)
    result = asyncio.run(execution.run(runtime_params={
        "source": source, "response_contract": contract,
        "request": "Move the requested application",
        "conversation_id": "conversation", "reply_to_turn_id": "user-turn",
    }))
    assert result["summary"] == "Done."
    assert execution.statuses == ["running", "completed"]
    assert execution.contexts[0]["interactive"] is True
    trace = json.loads(execution.records[0]["trace"])
    assert trace[0]["interactive_turn"] == {
        "conversation_id": "conversation", "reply_to_turn_id": "user-turn",
    }
    assert trace[-1]["tool"] == "task.complete"
    assert trace[-1]["accepted"] is True


def test_completed_run_keeps_provider_metrics_without_response_body(execution, monkeypatch):
    metrics = {"preflight_ms": 0.5, "first_public_delta_ms": 61.4,
               "generation_ms": 500.0, "cached_input_tokens": 4096}
    live_trace = []

    async def complete(*_args, **_kwargs):
        reply = await execution.reply()
        reply.provider_metrics = {**metrics, "response_body": "must not be published"}
        return reply

    monkeypatch.setattr(executor.llm, "chat", complete)
    monkeypatch.setattr(executor.action_trace, "emit", lambda *args: live_trace.append(args))
    result = asyncio.run(execution.run())
    assert result["status"] == "completed"
    trace = json.loads(execution.records[0]["trace"])
    assert [row["provider_metrics"] for row in trace if "provider_metrics" in row] == [metrics]
    assert trace[-1]["tool"] == "task.complete"
    assert trace[-1]["accepted"] is True
    model_events = [entry for entry in live_trace if entry[0] == "model"]
    assert [entry[3]["payload"]["phase"] for entry in model_events] == ["waiting", "started", "result"]
    assert model_events[-1:] == [
        ("model", "Query model result", [
            "Preflight: 0.5 ms", "Public TTFT: 61.4 ms",
            "Generation: 500.0 ms", "Cached input tokens: 4096",
        ], {"step": 1, "call_id": f"{result['run_id']}:model:1", "payload": {
            "kind": "model", "phase": "result", "model": "isolated", "model_label": "Isolated", "metrics": metrics}}),
    ]
    assert "must not be published" not in json.dumps([trace, live_trace])


def test_provider_timing_does_not_publish_invalid_numeric_fields(execution, monkeypatch):
    live_trace = []

    async def complete(*_args, **_kwargs):
        reply = await execution.reply()
        reply.provider_metrics = {
            "preflight_ms": -1, "first_public_delta_ms": float("nan"),
            "generation_ms": True, "cached_input_tokens": 2.5,
        }
        return reply

    monkeypatch.setattr(executor.llm, "chat", complete)
    monkeypatch.setattr(executor.action_trace, "emit", lambda *args: live_trace.append(args))
    assert asyncio.run(execution.run())["status"] == "completed"
    trace = json.loads(execution.records[0]["trace"])
    assert not any("provider_metrics" in row for row in trace)
    model_events = [entry for entry in live_trace if entry[0] == "model"]
    assert [entry[3]["payload"]["phase"] for entry in model_events] == ["waiting", "started", "result"]
    assert not any("metrics" in entry[3]["payload"] for entry in model_events)


@pytest.mark.parametrize("valid_action_between_groups", [False, True])
def test_invalid_action_streak_ignores_diagnostic_trace_rows(
    execution, monkeypatch, valid_action_between_groups,
):
    replies = ["No action object.", "Still no action object."]
    if valid_action_between_groups:
        replies.extend([
            '{"tool":"window.place","args":{}}',
            "Another invalid reply.", "One more invalid reply.",
            '{"tool":"task.complete","args":{"status":"completed","summary":"Done."}}',
        ])
    else:
        replies.append("Third invalid reply.")
    requests = []
    metrics = {"preflight_ms": 1.0, "first_public_delta_ms": 2.0, "generation_ms": 3.0}
    projection = {"before_input_tokens": 9000, "input_tokens": 8000, "source_pages_projected": 1}

    async def reply(*_args, **_kwargs):
        index = len(requests)
        requests.append(index)
        assert index < len(replies), "Executor requested another reply after the expected boundary"
        return NS(
            content=replies[index], prompt_tokens=100, finish_reason="stop",
            completion_tokens=5, provider_metrics=metrics, context_projection=projection,
        )

    monkeypatch.setattr(executor.llm, "chat", reply)
    result = asyncio.run(execution.run())
    trace = json.loads(execution.records[0]["trace"])
    assert len(requests) == len(replies)
    assert [row["provider_metrics"] for row in trace if "provider_metrics" in row] == [metrics] * len(replies)
    assert [row["context_projection"] for row in trace if "context_projection" in row] == [projection] * len(replies)
    if valid_action_between_groups:
        assert result["status"] == "completed"
        assert sum("invalid" in row for row in trace) == 4
        assert [name for name, _args in execution.calls] == ["window.place", "task.complete"]
    else:
        assert result["status"] == "failed"
        assert result["summary"] == "three consecutive replies without a valid action block"
        assert sum("invalid" in row for row in trace) == 3
        assert execution.calls == []


def test_runtime_params_cannot_claim_interactive_provenance(execution):
    asyncio.run(execution.run(interactive=False, runtime_params={
        "interactive": True,
        "conversation_id": "conversation", "reply_to_turn_id": "user-turn",
    }))
    assert execution.contexts[0]["interactive"] is False
    trace = json.loads(execution.records[0]["trace"])
    assert "interactive_turn" not in trace[0]


def test_interactive_activation_preserves_task_acceptance(execution):
    execution.task.meta["acceptance"] = ["Owner confirms the result."]
    result = asyncio.run(execution.run())
    assert result["status"] == "review"
    assert execution.statuses == ["running", "review"]
    assert [e["phase"] for e in execution.events].count("query_completed") == 1


def test_response_contract_from_task_definition_cannot_change_protocol(execution, monkeypatch):
    execution.task.meta["params"] = {"response_contract": "Untrusted definition contract"}

    async def complete(messages, **_kwargs):
        assert "Untrusted definition contract" not in messages[0]["content"]
        assert executor.llm.PROTOCOL in messages[0]["content"]
        return await execution.reply()

    monkeypatch.setattr(executor.llm, "chat", complete)
    assert asyncio.run(execution.run())["status"] == "completed"


def test_agent_legacy_tool_list_cannot_filter_or_broaden_task_capabilities(execution, monkeypatch):
    agent = executor.resolver().resolve("Agents/Executive/Executive")
    agent.meta["tools"] = ["Tools/not-a-task-dependency"]
    offered = []

    async def reply(*args, **kwargs):
        offered.append(kwargs["allowed_tools"])
        return await execution.reply(*args, **kwargs)

    monkeypatch.setattr(executor.llm, "chat", reply)
    assert asyncio.run(execution.run())["status"] == "completed"
    assert offered == [execution.tools]


@pytest.mark.parametrize("interrupted", [False, True])
def test_created_task_receipt_survives_bounded_trace(execution, monkeypatch, interrupted):
    from obsidience.harness.capabilities.task.create import execute as create_task
    from obsidience.harness.execution import scheduler
    from obsidience.harness.knowledge import vault

    target = NS(ref="Tasks/research/question", kind="task", meta={"triggers": ["task.create"]})
    from obsidience.harness.execution import assignments
    monkeypatch.setattr(assignments, "ensure_task_runbook", lambda *_args: {"status": "ready"})
    monkeypatch.setattr(vault, "resolver", lambda: NS(resolve=lambda _ref: target))
    queued = []

    def enqueue(_target, params):
        queued.append(params)
        return {"state": "started", "position": 0, "status": "pending"}

    monkeypatch.setattr(scheduler, "enqueue_event", enqueue)
    execution.tools.append("task.create")
    ordinary_tool = executor.execute_capability

    def tool(name, args, ctx):
        if name != "task.create":
            return ordinary_tool(name, args, ctx)
        result = create_task(args, ctx)
        ctx["trace"].extend({"prior_evidence": "observed " * 100} for _ in range(70))
        return result

    calls = 0

    async def reply(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return NS(content=json.dumps({"tool": "task.create", "args": {
                "task": target.ref, "params": {"request": "Find the source."},
            }}), prompt_tokens=100)
        if interrupted:
            raise asyncio.CancelledError
        return await execution.reply()

    monkeypatch.setattr(executor, "execute_capability", tool)
    monkeypatch.setattr(executor.llm, "chat", reply)
    runtime_params = {"conversation_id": "conversation", "reply_to_turn_id": "user-turn"}
    if interrupted:
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(execution.run(runtime_params=runtime_params))
    else:
        asyncio.run(execution.run(runtime_params=runtime_params))
    assert len(queued) == 1
    raw_trace = execution.records[0]["trace"]
    assert len(raw_trace) <= executor.MAX_RUN_TRACE_CHARS
    trace = json.loads(raw_trace)
    assert any("trace_truncated" in item for item in trace)
    assert trace[0]["interactive_turn"] == runtime_params
    assert trace[0]["created_tasks"] == [{
        "target_task_ref": target.ref, "activation_key": queued[0]["activation_key"],
    }]


def test_peer_activation_retains_exact_creator_receipt(execution):
    provenance = {
        "event": "task.create", "activation_key": "activation",
        "created_by_task_ref": "Tasks/query", "created_by_run_id": "creator-run",
    }
    asyncio.run(execution.run(interactive=False, runtime_params=provenance))
    trace = json.loads(execution.records[0]["trace"])
    assert trace[0]["task_activation"] == provenance
    assert "interactive_turn" not in trace[0]


def test_model_preflight_failure_closes_task_and_keeps_one_failed_receipt(execution, monkeypatch):
    def unavailable(*_args):
        raise RuntimeError("isolated model preflight failure")

    monkeypatch.setattr(executor.model_runtime, "resolve_model", unavailable)
    with pytest.raises(RuntimeError, match="isolated model preflight failure"):
        asyncio.run(execution.run())
    assert execution.statuses == ["running", "failed"]
    assert len(execution.records) == 1
    assert execution.records[0]["id"] == execution.live_meta["last_run"]
    assert execution.records[0]["status"] == "failed"
    assert [e["phase"] for e in execution.events] == ["query_started", "query_completed"]


def test_spine_failure_closes_task_as_blocked_with_one_terminal_event(execution, monkeypatch):
    monkeypatch.setattr(executor, "resolve_spine", lambda *_args: {"error": "missing Runbook"})
    result = asyncio.run(execution.run())
    assert result["status"] == "blocked"
    assert execution.statuses == ["running", "blocked"]
    assert len(execution.records) == 1
    assert execution.records[0]["status"] == "blocked"
    assert [e["phase"] for e in execution.events] == ["query_started", "query_completed"]


def test_late_failure_does_not_overwrite_a_newer_task_claim(execution, monkeypatch):
    async def replaced(*_args, **_kwargs):
        execution.live_meta.update({"last_run": "newer-run", "status": "running"})
        raise RuntimeError("isolated earlier activation failure")

    monkeypatch.setattr(executor, "compile_activation", replaced)
    with pytest.raises(RuntimeError, match="isolated earlier activation failure"):
        asyncio.run(execution.run())
    assert execution.statuses == ["running"]
    assert execution.live_meta["last_run"] == "newer-run"
    assert execution.live_meta["status"] == "running"
    assert execution.records[0]["id"] != "newer-run"
    assert execution.records[0]["status"] == "failed"


def test_specialist_read_activity_keeps_its_execution_graph_and_identity(execution, monkeypatch):
    agent = executor.resolver().resolve("Agents/Executive/Executive")
    agent.ref, agent.title = "Agents/Alexandria/Alexandria", "Alexandria"
    execution.tools.append("vault.read")
    actions = iter([
        {"tool": "vault.read", "args": {"ref": "Shared/fact"}},
        {"tool": "task.complete", "args": {"status": "completed", "summary": "Read the fact."}},
    ])
    ordinary = executor.execute_capability

    async def response(*_args, **_kwargs):
        return NS(content=json.dumps(next(actions)), prompt_tokens=100)

    def dispatch(name, args, context):
        if name == "vault.read":
            context["_last_context_refs"] = ["Shared/fact"]
            return "Current fact."
        return ordinary(name, args, context)

    monkeypatch.setattr(executor.llm, "chat", response)
    monkeypatch.setattr(executor, "execute_capability", dispatch)
    result = asyncio.run(execution.run())
    reads = [row for row in execution.events if "Shared/fact" in row.get("refs", [])]
    assert len(reads) == 1
    assert reads[0]["graph_id"] == "Alexandria"
    assert reads[0]["run_id"] == result["run_id"]
    assert reads[0]["retrieval_ms"] == 1.25
    lifecycle = [row for row in execution.events if row["phase"] in {"query_started", "query_completed"}]
    assert all(row["graph_id"] == "Alexandria" and row["run_id"] == result["run_id"] for row in lifecycle)


def test_completion_decoder_tracks_controller_proposal_state(execution, monkeypatch):
    execution.tools.append('vault.propose')
    monkeypatch.setattr(executor,'_maintenance_candidate_evidence',lambda *_:{'candidate_refs':['Shared/fact']})
    observed=[]
    actions=iter([
        {'tool':'vault.propose','args':{'target':'Shared/fact','body':'Inspected supported fact.'}},
        {'tool':'task.complete','args':{'status':'completed','summary':'The owner approved the update.'}},
    ])
    ordinary=executor.execute_capability
    async def response(*_args,**kwargs):
        observed.append(kwargs.get('completion_no_change',False))
        return NS(content=json.dumps(next(actions)),prompt_tokens=100)
    def dispatch(name,args,context):
        if name=='vault.propose':
            context['staged_proposals']=[{'auto_approved':True,'target':'Shared/fact.md'}]
            return 'Approved in isolated fixture.'
        return ordinary(name,args,context)
    monkeypatch.setattr(executor.llm,'chat',response)
    monkeypatch.setattr(executor,'execute_capability',dispatch)
    assert asyncio.run(execution.run())['status']=='completed'
    assert observed==[True,False]

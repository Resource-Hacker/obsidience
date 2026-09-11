"""Initial Knowledge accounting describes selection without changing its bytes."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json

import pytest

from obsidience.harness.execution import executor, trace
from obsidience.harness.knowledge import retrieval, vault
from obsidience.harness.models import llm
from obsidience.harness.models.runtime import EXECUTIVE_MODEL, MODELS, SPECIALIST_MODEL
from obsidience.tests.test_action_trace_details import stream  # noqa: F401
from obsidience.tests.test_conversation_context_bindings import graph
from obsidience.tests.test_source_retrieval_scope import _note


def nominate(monkeypatch, notes, direct):
    snapshot = vault.Resolver(notes)
    monkeypatch.setattr(retrieval, "iter_notes", lambda: pytest.fail("must use activation snapshot"))
    monkeypatch.setattr(retrieval, "_lanes_for", lambda *_args, **_kwargs: [(1, [(ref, 1) for ref in direct])])
    return snapshot


def test_no_matches_and_budget_omissions_are_distinct(monkeypatch):
    notes = [_note("Knowledge/first", body="First fact."),
             _note("Knowledge/large", body="Long content. " * 200),
             _note("Knowledge/later", body="Tiny.")]
    snapshot = nominate(monkeypatch, notes, [n.ref for n in notes])
    report = {"stale": "a previous request"}
    text, refs = retrieval.fast_context_with_refs("facts", set(), budget=90,
                                                accepted_resolver=snapshot, diagnostics=report)
    assert text == "### [[Knowledge/first]] — first (direct match)\nFirst fact.\n"
    assert refs == [notes[0].ref]
    assert report["considered_count"] == 3 and report["included_count"] == 1
    assert report["omitted_count"] == 2 and report["status"] == "selected"
    assert [entry["reason"] for entry in report["entries"]] == ["selected", "token_budget", "after_budget_stop"]
    assert report["entries"][1]["estimated_tokens"] > report["estimated_budget_tokens"]
    assert report["estimated_used_tokens"] == len(text) // 4
    assert report["entries"][2]["included_estimated_tokens"] == 0
    assert "stale" not in report
    monkeypatch.setattr(retrieval, "_lanes_for", lambda *_args, **_kwargs: [])
    assert retrieval.fast_context_with_refs("no facts", set(), accepted_resolver=snapshot,
                                            diagnostics=report) == ("", [])
    assert report["status"] == "no_matches"
    assert report["considered_count"] == report["omitted_count"] == report["included_count"] == 0
    assert report["entries"] == []


@pytest.mark.parametrize("budget", [0, 4, 20, 60, 500])
def test_first_item_clipping_reports_exact_unicode_body_range(monkeypatch, budget):
    note = _note("Knowledge/first", body=" \n日本語" * 300 + "  ")
    snapshot = nominate(monkeypatch, [note], [note.ref])
    report = {}
    legacy = retrieval.fast_context_with_refs("facts", set(), budget=budget, accepted_resolver=snapshot)
    text, refs = retrieval.fast_context_with_refs("facts", set(), budget=budget,
                                                accepted_resolver=snapshot, diagnostics=report)
    assert (text, refs) == legacy
    expected = "### [[Knowledge/first]] — first (direct match)\n" + note.body[slice(*retrieval.passage_range(note.body, "facts"))] + "\n"
    if len(expected) // 4 > budget:
        expected = expected[:budget * 4]
    assert text == expected and refs == [note.ref]
    item = report["entries"][0]
    start, end = item["body_start"], item["body_end"]
    if start is None:
        assert end is None and item["content"] == "none"
        assert item["omitted_chars"] == len(note.body)
    else:
        assert start == 2 and 2 < end <= 1200
        supplied = note.body[start:end]
        assert text.endswith(supplied) or text.endswith(supplied + "\n")
        assert item["content"] == "excerpt"
        assert item["omitted_chars"] == len(note.body) - len(supplied)
    assert report["estimated_used_tokens"] <= budget
    assert item["included_estimated_tokens"] == report["estimated_used_tokens"]


def test_full_body_classification_preserves_trimmed_boundary_offsets(monkeypatch):
    note = _note("Knowledge/whole", body=" \nFull article. \n")
    snapshot = nominate(monkeypatch, [note], [note.ref])
    report = {}
    text, _ = retrieval.fast_context_with_refs("whole", set(), accepted_resolver=snapshot, diagnostics=report)
    row = report["entries"][0]
    assert row["content"] == "full"
    assert note.body[row["body_start"]:row["body_end"]] == "Full article."
    assert row["omitted_chars"] == 4  # exact whitespace removed by existing .strip()
    assert text.endswith("\nFull article.\n")


def test_graph_origins_use_actual_round_robin_seed_and_resolved_reference(monkeypatch):
    a = _note("Knowledge/a", links=["First neighbor", "Knowledge/n2"])
    b = _note("Knowledge/b", links=["First neighbor", "Knowledge/n3"])
    c = _note("Knowledge/c")
    other = [_note(f"Knowledge/{name}") for name in ("d", "e", "f")]
    neighbors = [_note("Knowledge/n1", title="First neighbor"), _note("Knowledge/n2"), _note("Knowledge/n3")]
    direct = [a, b, c, *other]
    snapshot = nominate(monkeypatch, [*direct, *neighbors], [n.ref for n in direct])
    report = {}
    before = retrieval.fast_context_with_refs("facts", set(), accepted_resolver=snapshot)
    after = retrieval.fast_context_with_refs("facts", set(), accepted_resolver=snapshot, diagnostics=report)
    assert after == before
    assert after[1] == [a.ref, b.ref, c.ref, "Knowledge/n1", "Knowledge/n3"]
    rows = {row["ref"]: row for row in report["entries"]}
    assert rows["Knowledge/n1"]["seed_ref"] == a.ref
    assert rows["Knowledge/n3"]["seed_ref"] == b.ref
    assert rows["Knowledge/n2"]["reason"] == "graph_limit"
    assert rows["Knowledge/d"]["reason"] == "article_limit"
    assert rows[a.ref]["origin"] == "direct" and rows[a.ref]["seed_ref"] is None
    assert report["considered_count"] == 9 and report["omitted_count"] == 4


def test_preference_only_describes_the_existing_search_partition(monkeypatch):
    first, preferred = _note("Knowledge/first"), _note("Knowledge/preferred")
    snapshot = nominate(monkeypatch, [first, preferred], [first.ref, preferred.ref])
    report = {}
    _, refs = retrieval.fast_context_with_refs("facts", set(), limit=1, preferred={preferred.ref},
                                              accepted_resolver=snapshot, diagnostics=report)
    assert refs == [preferred.ref]
    assert report["entries"][0]["ref"] == preferred.ref and report["entries"][0]["preferred"] is True
    assert report["entries"][1]["reason"] == "article_limit"


def test_filtered_content_never_becomes_omission_evidence(monkeypatch):
    rejected = [
        _note("_archived/old"), _note("_staging/pending"), _note("raw/item"),
        _note("Knowledge/.private/hidden"), _note("Knowledge/stale", meta={"stale_after": "2000-01-01T00:00:00Z"}),
        _note("Knowledge/retired", meta={"article_status": "deprecated"}),
        _note("Knowledge/temporary", meta={"temporary": True}),
        _note("Knowledge/disabled", meta={"retrieval": False}),
        _note("Knowledge/excluded"), _note("Tools/tool", kind="tool"),
    ]
    accepted = _note("Knowledge/current", links=[n.ref for n in rejected])
    snapshot = nominate(monkeypatch, [accepted, *rejected], [n.ref for n in [*rejected, accepted]])
    report = {}
    _, refs = retrieval.fast_context_with_refs("facts", {"Knowledge/excluded"},
                                              accepted_resolver=snapshot, diagnostics=report)
    assert refs == [accepted.ref]
    assert report["considered_count"] == report["included_count"] == 1
    assert report["omitted_count"] == 0
    assert [item["ref"] for item in report["entries"]] == [accepted.ref]
    assert report["scope"] == "eligible_search_hits_and_seed_neighbors"


def test_shared_snapshot_rechecks_expiry_for_accounting(monkeypatch):
    class Clock:
        current = datetime(2026, 9, 9, 8, tzinfo=timezone.utc)

        @classmethod
        def now(cls, _tz):
            return cls.current

    note = _note("Knowledge/timed", meta={"stale_after": "2026-09-09T09:00:00Z"})
    snapshot = nominate(monkeypatch, [note], [note.ref])
    monkeypatch.setattr(retrieval, "datetime", Clock)
    report = {}
    retrieval.fast_context_with_refs("timed", set(), accepted_resolver=snapshot, diagnostics=report)
    assert report["included_count"] == 1
    Clock.current = datetime(2026, 9, 9, 9, tzinfo=timezone.utc)
    retrieval.fast_context_with_refs("timed", set(), accepted_resolver=snapshot, diagnostics=report)
    assert report["considered_count"] == 0 and report["entries"] == []


@pytest.mark.parametrize("query,limit,status", [(" ", 5, "empty_query"), ("facts", 0, "disabled")])
def test_skipped_search_has_explicit_accounting(monkeypatch, query, limit, status):
    monkeypatch.setattr(retrieval, "_lanes_for", lambda *_args, **_kwargs: pytest.fail("search must remain skipped"))
    report = {}
    assert retrieval.fast_context_with_refs(query, set(), limit=limit, diagnostics=report) == ("", [])
    assert report["status"] == status and report["considered_count"] == 0


def test_accounting_has_bounded_entries_and_exact_candidate_counts(monkeypatch):
    neighbors = [_note(f"Knowledge/neighbor-{i}") for i in range(100)]
    seed = _note("Knowledge/seed", links=[n.ref for n in neighbors])
    snapshot = nominate(monkeypatch, [seed, *neighbors], [seed.ref])
    report = {}
    _, refs = retrieval.fast_context_with_refs("facts", set(), accepted_resolver=snapshot, diagnostics=report)
    assert refs == [seed.ref, neighbors[0].ref, neighbors[1].ref]
    assert report["considered_count"] == 101 and report["omitted_count"] == 98
    assert len(report["entries"]) == 32 and report["entries_omitted"] == 69


def test_compiler_accounting_is_visible_but_provider_payloads_are_identical(monkeypatch, stream):
    res, agent, tasks = graph()
    note = _note("Knowledge/accepted", body="Accepted complete Knowledge.")
    agent.meta["knowledge"] = [note.ref]
    res = vault.Resolver([*res.by_ref.values(), note])
    monkeypatch.setattr(executor.source, "article_refs_for_trees", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(executor.shell_scene.SCENE, "activation_binding", lambda: {})
    monkeypatch.setattr(executor.knowledge_activity, "emit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(retrieval, "_lanes_for", lambda *_args, **_kwargs: [(1, [(note.ref, 1)])])
    kwargs = dict(agent=agent, accepted_resolver=res, params={"request": "Exact owner question"},
                  conversation_context="Owner: Earlier context.")
    activation = asyncio.run(executor.compile_activation(tasks[0], **kwargs))
    event = trace.history()[-1]
    assert event["payload"]["knowledge_accounting"] == activation["knowledge_accounting"]
    assert event["payload"]["knowledge_accounting"]["entries"][0]["ref"] == note.ref
    assert not event["truncated"]
    assert len(trace.history()) == 1 and "step" not in event
    real = retrieval.fast_context_with_refs

    def without_diagnostics(*args, **kwargs):
        kwargs.pop("diagnostics", None)
        return real(*args, **kwargs)

    monkeypatch.setattr(retrieval, "fast_context_with_refs", without_diagnostics)
    baseline = asyncio.run(executor.compile_activation(tasks[0], **kwargs))
    assert baseline["knowledge_accounting"] == {}
    for key in ("packet", "brief", "refs", "provider_system", "provider_user", "provider_conversation"):
        assert activation[key] == baseline[key]
    for model in (EXECUTIVE_MODEL, SPECIALIST_MODEL):
        requests = []
        for compiled in (baseline, activation):
            messages = [{"role": role, "content": compiled[key]} for role, key in (
                ("system", "provider_system"), ("user", "provider_conversation"), ("user", "provider_user"))]
            requests.append(llm._chat_payload(messages, MODELS[model], max_tokens=None, temperature=0,
                                              reasoning_effort="none", allowed_tools=["task.complete"]))
        assert requests[0] == requests[1]
        assert "knowledge_accounting" not in json.dumps(requests[1])


def test_packet_accounting_uses_existing_redaction_and_reports_clipping(stream):
    report = {"version": 1, "entries": [{"ref": "Knowledge/" + "大" * 9000,
        "title": "password=hidden-credential", "body_chars": 10, "reasoning": "PRIVATE"} for _ in range(32)]}
    original = json.dumps(report)
    payload = trace.packet_payload({"knowledge": "## Relevant Knowledge\nSafe context."}, [], 1.0,
                                   knowledge_accounting=report)
    trace.emit("activation", "Packet", [], {"payload": payload})
    event = trace.history()[0]
    wire = json.dumps(event, ensure_ascii=True, separators=(",", ":"))
    assert len(wire) <= trace.MAX_EVENT_CHARS and event["truncated"] is True
    assert "hidden-credential" not in wire and "PRIVATE" not in wire
    assert event["payload"]["sections"][0]["text"] == "## Relevant Knowledge\nSafe context."
    assert json.dumps(report) == original

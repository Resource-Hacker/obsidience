"""Review presentation follows actual publication, never proposed graph state."""

import asyncio
from collections import deque
import importlib
import json
from pathlib import Path
import threading

import pytest

from obsidience.harness.capabilities.vault.propose import stage_proposal
from obsidience.harness.config import CONFIG
from obsidience.harness.execution import activity
from obsidience.harness.knowledge import review
from obsidience.harness.knowledge.vault import load_note, write_note


@pytest.fixture
def link_graph(tmp_path, monkeypatch, isolated_task_ledger):
    monkeypatch.setattr(CONFIG, "vault_dir", tmp_path / "vault")
    monkeypatch.setattr(CONFIG, "git_commit", False)
    monkeypatch.setattr(activity, "_HISTORY", deque(maxlen=100))
    monkeypatch.setattr(activity, "_SUBSCRIBERS", {})
    original_sync = isolated_task_ledger.sync
    # Real note/link indexing, without an embedding model or live state.
    monkeypatch.setattr(isolated_task_ledger, "sync", lambda: original_sync(embed=False))
    write_note("Tasks/link.md", {"kind": "task", "title": "Link", "taxonomy_path": "wiki/link"}, "Relate accepted knowledge.")
    write_note("Knowledge/a.md", {"kind": "knowledge", "title": "A"}, "Original article.")
    write_note("Knowledge/b.md", {"kind": "knowledge", "title": "B"}, "Related evidence.")
    isolated_task_ledger.sync()
    return isolated_task_ledger


def stage(body="Original article. See [[Knowledge/b]].", *, task="Tasks/link", run_id="link-run"):
    result = stage_proposal(
        {"action": "update", "target": "Knowledge/a.md", "title": "A", "body": body,
         "reason": "Supporting accepted evidence."},
        {"task": task, "agent": "Alexandria", "run_id": run_id},
    )
    return Path(result["staged"]).name


def expected_edge():
    return {"source": "Knowledge/a", "target": "Knowledge/b"}


def test_stage_and_approve_project_exact_edges_after_index_commit(link_graph, monkeypatch):
    name = stage()
    event, = activity.history()
    assert event["phase"] == "review_changed"
    assert event["review"] == {
        "proposal_id": name, "run_id": "link-run", "state": "pending", "truncated": False,
    }
    assert review.link_proposals() == {
        "entries": [{"proposal_id": name, "run_id": "link-run", **expected_edge()}],
        "truncated": False,
    }
    assert expected_edge() not in link_graph.graph()["links"]
    emit = activity.emit_review_change

    def observe_publish(proposal_id, run_id, state, **kwargs):
        if state == "approved":
            assert expected_edge() in link_graph.graph()["links"]
            assert not (CONFIG.staging_dir / name).exists()
            assert link_graph.review_decision(name)["decision"] == "approved"
        return emit(proposal_id, run_id, state, **kwargs)

    monkeypatch.setattr(activity, "emit_review_change", observe_publish)
    review.approve(name)
    final = activity.history()[-1]
    decision = link_graph.review_decision(name)
    assert final["review"] == {
        "proposal_id": name, "run_id": "link-run", "state": "approved",
        "decided_at": int(decision["decided_at"] * 1000),
        "links": [expected_edge()], "truncated": False,
    }
    assert review.link_proposals() == {"entries": [], "truncated": False}
    assert activity.history()[-1] == final  # Replay retains the original decision time.
    assert "Original article" not in json.dumps(activity.history())
    assert "Supporting accepted evidence" not in json.dumps(activity.history())


def test_reject_clears_proposal_without_acceptance_or_body_text(link_graph):
    name = stage()
    review.reject(name, "Private review rationale stays outside graph events.")
    final = activity.history()[-1]
    assert final["review"] == {
        "proposal_id": name, "run_id": "link-run", "state": "rejected",
        "decided_at": int(link_graph.review_decision(name)["decided_at"] * 1000),
        "truncated": False,
    }
    assert review.link_proposals()["entries"] == []
    assert expected_edge() not in link_graph.graph()["links"]
    assert "Private review rationale" not in json.dumps(activity.history())


def test_legacy_link_review_rejection_uses_the_accepted_task_class(link_graph):
    name = stage()
    proposal = load_note(f"_staging/{name}")
    metadata = dict(proposal.meta)
    metadata.pop("review_class")
    write_note(proposal.path, metadata, proposal.body)
    assert review.link_proposals()["entries"]
    review.reject(name)
    assert activity.history()[-1]["review"]["state"] == "rejected"


def test_decided_notification_requires_the_exact_durable_binding(link_graph):
    name = stage()
    metadata = dict(load_note(f"_staging/{name}").meta)
    review.approve(name)
    activity._HISTORY.clear()
    for field in ("run_id", "task", "target"):
        review.notify_link_review(name, {**metadata, field: "different"}, "approved", links=[expected_edge()])
    review.notify_link_review(name, metadata, "rejected")
    review.notify_link_review(name, metadata, "pending")  # Removed staging cannot announce pending again.
    assert activity.history() == []


@pytest.mark.parametrize("change", ["proposal_body", "accepted_base", "endpoint_missing", "task_class", "stored_class", "duplicate"])
def test_unapprovable_link_never_appears_as_pending_or_approved(link_graph, change):
    name = stage()
    proposal = load_note(f"_staging/{name}")
    if change == "proposal_body":
        write_note(proposal.path, proposal.meta, proposal.body + "Unattested sentence.")
    elif change == "accepted_base":
        write_note("Knowledge/a.md", {"kind": "knowledge", "title": "A"}, "Owner correction.")
    elif change == "endpoint_missing":
        (CONFIG.vault_dir / "Knowledge/b.md").unlink()
    elif change == "task_class":
        write_note("Tasks/link.md", {"kind": "task", "title": "Link", "taxonomy_path": "wiki/curate"}, "Different Task.")
    elif change == "stored_class":
        write_note(proposal.path, {**proposal.meta, "review_class": "invalid"}, proposal.body)
    else:
        write_note("_staging/duplicate.md", proposal.meta, proposal.body)
    before = (CONFIG.vault_dir / "Knowledge/a.md").read_bytes()
    assert review.link_proposals() == {"entries": [], "truncated": False}
    with pytest.raises(ValueError):
        review.approve(name)
    assert (CONFIG.vault_dir / "Knowledge/a.md").read_bytes() == before
    assert [event["review"]["state"] for event in activity.history()] == ["pending"]


def test_ordinary_article_update_with_links_is_not_a_link_proposal(link_graph):
    write_note("Tasks/curate.md", {"kind": "task", "title": "Curate", "taxonomy_path": "wiki/curate"}, "Curate knowledge.")
    name = stage(task="Tasks/curate")
    assert review.link_proposals()["entries"] == []
    assert activity.history() == []
    review.approve(name)
    assert expected_edge() in link_graph.graph()["links"]
    assert activity.history() == []


def test_removed_link_has_no_pending_connection_or_acceptance_glow(link_graph):
    write_note("Knowledge/a.md", {"kind": "knowledge", "title": "A"}, "See [[Knowledge/b]].")
    link_graph.sync()
    name = stage("Original article without that relationship.")
    assert review.link_proposals()["entries"] == []
    review.approve(name)
    assert activity.history()[-1]["review"]["links"] == []
    assert expected_edge() not in link_graph.graph()["links"]


def test_endpoint_revision_warning_preserves_valid_pending_edge(link_graph):
    name = stage()
    write_note("Knowledge/b.md", {"kind": "knowledge", "title": "B"}, "An accepted revision.")
    assert review.list_proposals()[0]["evidence_warning"]
    assert review.link_proposals()["entries"] == [{"proposal_id": name, "run_id": "link-run", **expected_edge()}]
    review.approve(name)
    assert activity.history()[-1]["review"]["links"] == [expected_edge()]


def test_pending_and_approval_bounds_are_explicit_without_invented_endpoints(link_graph):
    refs = [f"Knowledge/endpoint-{number:03}" for number in range(130)]
    for ref in refs:
        write_note(ref + ".md", {"kind": "knowledge", "title": ref}, "Accepted endpoint.")
    name = stage("Original article.\n\n" + "\n".join(f"See [[{ref}]]." for ref in refs))
    pending = review.link_proposals()
    assert pending["truncated"] is True
    assert len(pending["entries"]) == 128
    assert [entry["target"] for entry in pending["entries"]] == refs[:128]
    assert all(set(entry) == {"proposal_id", "run_id", "source", "target"} for entry in pending["entries"])
    review.approve(name)
    approved = activity.history()[-1]["review"]
    assert approved["truncated"] is True
    assert len(approved["links"]) == 64
    assert {edge["target"] for edge in approved["links"]} <= set(refs)
    assert all(edge in link_graph.graph()["links"] for edge in approved["links"])


def test_index_failure_does_not_announce_an_unavailable_accepted_graph(link_graph, monkeypatch):
    name = stage()

    def unavailable():
        raise OSError("isolated index failure")

    monkeypatch.setattr(link_graph, "sync", unavailable)
    with pytest.raises(OSError, match="isolated index failure"):
        review.approve(name)
    assert link_graph.review_decision(name)["decision"] == "approved"
    assert [event["review"]["state"] for event in activity.history()] == ["pending"]


def test_graph_api_keeps_pending_overlay_separate_from_accepted_links(link_graph):
    api = importlib.import_module("obsidience.harness.interfaces.api.app")
    name = stage()
    snapshot = api.graph()
    assert snapshot["link_proposals"]["entries"] == [{"proposal_id": name, "run_id": "link-run", **expected_edge()}]
    assert expected_edge() not in snapshot["links"]
    review.approve(name)
    snapshot = api.graph()
    assert snapshot["link_proposals"]["entries"] == []
    assert expected_edge() in snapshot["links"]


@pytest.mark.parametrize("material", [b"---\ntitle: interrupted\n", b"---\ntitle: [bad\n---\n", b"\xff"])
def test_unreadable_staging_does_not_take_down_the_accepted_graph(link_graph, material):
    api = importlib.import_module("obsidience.harness.interfaces.api.app")
    before = api.graph()
    stage()
    (CONFIG.staging_dir / "interrupted.md").write_bytes(material)
    snapshot = api.graph()
    assert snapshot["nodes"] == before["nodes"]
    assert snapshot["links"] == before["links"]
    assert snapshot["link_proposals"] == {"entries": [], "truncated": True}
    assert [event["review"]["state"] for event in activity.history()] == ["pending"]


def test_review_public_payload_discards_unrecognized_fields_and_never_shortens_refs(link_graph):
    event = activity.emit_review_change("review.md", "run", "approved", decided_at=123.456,
        links=[{**expected_edge(), "body": "Private body.", "evidence": "Private excerpt."},
               expected_edge(), {"source": "x" * 513, "target": "Knowledge/b"}])
    assert event["review"]["links"] == [expected_edge()]
    assert event["review"]["truncated"] is True
    assert event["review"]["decided_at"] == 123456
    assert "Private" not in json.dumps(event)


def test_worker_thread_review_reaches_waiting_activity_subscriber(link_graph):
    async def run():
        loop = asyncio.get_running_loop()
        loop.set_debug(True)  # Cross-thread asyncio.Queue.set_result would fail here.
        queue = activity.subscribe()
        waiter = asyncio.create_task(queue.get())
        await asyncio.sleep(0)
        name = await asyncio.to_thread(stage)
        pending = await asyncio.wait_for(waiter, 2)
        assert pending["review"]["proposal_id"] == name
        assert pending["review"]["state"] == "pending"
        await asyncio.to_thread(review.approve, name)
        approved = await asyncio.wait_for(queue.get(), 2)
        assert approved["review"]["state"] == "approved"
        assert approved["review"]["links"] == [expected_edge()]
        activity.unsubscribe(queue)
        assert not activity._SUBSCRIBERS

    asyncio.run(run())


def test_existing_activity_socket_delivers_and_replays_review_changes(link_graph):
    from fastapi.testclient import TestClient

    api = importlib.import_module("obsidience.harness.interfaces.api.app")
    client = TestClient(api.app)
    with client.websocket_connect("/ws/activity") as socket:
        assert socket.receive_json() == {"type": "snapshot", "entries": []}
        name = stage()
        pending = socket.receive_json()
        assert pending["type"] == "activity"
        assert pending["review"]["state"] == "pending"
        review.approve(name)
        approved = socket.receive_json()
        assert approved["type"] == "activity"
        assert approved["review"]["links"] == [expected_edge()]
    with client.websocket_connect("/ws/activity") as socket:
        replay = socket.receive_json()
        assert replay["type"] == "snapshot"
        assert replay["entries"][-1]["review"] == approved["review"]
    assert not activity._SUBSCRIBERS


def test_activity_subscriber_and_replay_remain_bounded(link_graph):
    async def run():
        queue = activity.subscribe()
        for number in range(120):
            activity.emit("read", [f"Knowledge/{number}"])
        assert queue.qsize() == 100
        assert len(activity.history()) == 100
        assert (await queue.get())["refs"] == ["Knowledge/20"]
        activity.unsubscribe(queue)
        activity.emit("read", ["Knowledge/after-unsubscribe"])
        assert queue.qsize() == 99

    asyncio.run(run())


def test_worker_burst_uses_one_bounded_delivery_and_preserves_mixed_loop_order(link_graph, monkeypatch):
    async def run():
        queue = activity.subscribe()
        loop = asyncio.get_running_loop()
        schedule = loop.call_soon_threadsafe
        callbacks = []

        def record(callback, *args):
            callbacks.append(callback)
            return schedule(callback, *args)

        monkeypatch.setattr(loop, "call_soon_threadsafe", record)

        def burst():
            for number in range(120):
                activity.emit("read", [f"Knowledge/{number}"])

        worker = threading.Thread(target=burst)
        worker.start()
        worker.join(timeout=2)  # Hold this loop still while another thread publishes.
        assert not worker.is_alive()
        assert len(callbacks) == 1
        subscriber = activity._SUBSCRIBERS[queue]
        assert len(subscriber.pending) == 100
        activity.emit("read", ["Knowledge/120"])
        assert len(callbacks) == 1
        await asyncio.sleep(0)
        delivered = [queue.get_nowait() for _ in range(queue.qsize())]
        assert delivered == activity.history()
        assert [event["refs"] for event in delivered] == [[f"Knowledge/{n}"] for n in range(21, 121)]
        assert not subscriber.pending
        assert subscriber.scheduled is False
        activity.unsubscribe(queue)

    asyncio.run(run())


def test_disconnected_presenter_cannot_fail_a_committed_review(link_graph):
    async def connect():
        return activity.subscribe()

    queue = asyncio.run(connect())  # Its owning loop has now closed.
    name = stage()
    assert queue not in activity._SUBSCRIBERS
    result = review.approve(name)
    assert result["approved"] == "Knowledge/a.md"
    assert activity.history()[-1]["review"]["state"] == "approved"
    assert expected_edge() in link_graph.graph()["links"]


def test_auto_approval_never_announces_deleted_proposal_as_pending(link_graph, monkeypatch):
    from obsidience.harness.knowledge import curation

    def auto(result, args, context):
        approval = review.approve(Path(result["staged"]).name)
        return {**result, "auto_approved": True, "approval": approval}

    monkeypatch.setattr(curation, "try_auto_approve", auto)
    name = stage()
    assert [event["review"]["state"] for event in activity.history()] == ["approved"]
    assert activity.history()[0]["review"]["proposal_id"] == name
    assert review.link_proposals()["entries"] == []


@pytest.mark.parametrize("decided_at", [None, True, float("inf"), float("nan"), -1, 10**500])
def test_invalid_decision_time_is_not_published(link_graph, decided_at):
    assert activity.emit_review_change("review.md", "run", "approved", decided_at=decided_at) is None
    assert activity.history() == []

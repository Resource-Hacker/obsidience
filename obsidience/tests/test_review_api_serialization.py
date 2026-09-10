"""Review polling shares the API's decision lock; no live proposals are touched."""
from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
import threading

from fastapi.testclient import TestClient
import pytest

api = import_module("obsidience.harness.interfaces.api.app")


@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_listing_waits_for_inflight_review_decision(monkeypatch, decision):
    entered_decision = threading.Event()
    release_decision = threading.Event()
    read_reached_boundary = threading.Event()
    entered_listing = threading.Event()
    pending = [{"file": "isolated.md"}]

    class ObservedLock:
        """Use the real mutex, exposing only its second acquisition attempt."""
        def __init__(self):
            self.lock = threading.RLock()

        def __enter__(self):
            if entered_decision.is_set():
                read_reached_boundary.set()
            self.lock.acquire()
            return self

        def __exit__(self, *_exc):
            self.lock.release()

    def decide(name, *_args):
        assert name == "isolated.md"
        entered_decision.set()
        assert release_decision.wait(5), "test did not release the in-flight decision"
        pending.clear()
        return {"approved" if decision == "approve" else "rejected": name}

    def listing():
        entered_listing.set()
        # Before the repair this is the first boundary reached by GET. With
        # the repair GET instead reaches ObservedLock while the writer holds it.
        read_reached_boundary.set()
        return list(pending)

    monkeypatch.setattr(api, "_REVIEW_LOCK", ObservedLock())
    monkeypatch.setattr(api.review, decision, decide)
    monkeypatch.setattr(api.review, "list_proposals", listing)
    # No lifespan startup: these are real ASGI routes with inert review bodies,
    # not another running Harness, provider, microphone or Vault writer.
    client = TestClient(api.app)
    with ThreadPoolExecutor(max_workers=2) as pool:
        mutation = pool.submit(client.post, f"/api/reviews/isolated.md/{decision}")
        read = None
        try:
            assert entered_decision.wait(5)
            read = pool.submit(client.get, "/api/reviews")
            assert read_reached_boundary.wait(5)
            assert not entered_listing.is_set(), "GET read proposals during an active review decision"
            assert not read.done()
        finally:
            release_decision.set()
            result = mutation.result(timeout=5)
            if read is not None:
                snapshot = read.result(timeout=5)
            client.close()
    assert result.status_code == 200
    assert snapshot.status_code == 200 and snapshot.json() == []
    assert entered_listing.is_set()


@pytest.mark.parametrize("decision,error,status", [
    ("approve", ValueError("Stale proposal"), 400),
    ("reject", FileNotFoundError("isolated.md"), 404),
])
def test_failed_decision_releases_lock_for_next_poll(monkeypatch, decision, error, status):
    def fail(*_args):
        raise error
    monkeypatch.setattr(api, "_REVIEW_LOCK", threading.RLock())
    monkeypatch.setattr(api.review, decision, fail)
    monkeypatch.setattr(api.review, "list_proposals", lambda: [{"file": "remaining.md"}])
    client = TestClient(api.app)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            response = pool.submit(client.post, f"/api/reviews/isolated.md/{decision}").result(timeout=5)
            snapshot = pool.submit(client.get, "/api/reviews").result(timeout=5)
        assert response.status_code == status
        assert snapshot.status_code == 200 and snapshot.json() == [{"file": "remaining.md"}]
    finally:
        client.close()

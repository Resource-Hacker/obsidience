from __future__ import annotations

from types import SimpleNamespace

from obsidience.harness.interfaces.api import app as server


def test_enabling_turn_event_task_waits_for_a_real_event(monkeypatch) -> None:
    existing = SimpleNamespace(
        ref="Tasks/observations/temporary/example",
        path="Tasks/observations/temporary/example.md",
        body="Maintain the selected node.",
        meta={
            "status": "failed",
            "blocked_reason": "old failure",
            "last_run": "old-run",
            "params": {"event": "old"},
            "summary": "old summary",
            "auto_curate_target": "@agent/Temporary Observations",
        },
    )
    writes: list[tuple[str, dict, str]] = []

    monkeypatch.setattr(
        server,
        "_base_article",
        lambda _ref: {
            "ref": "@agent/Temporary Observations",
            "title": "Temporary Observations",
            "kind": "knowledge",
            "body": "Transient cache.",
        },
    )
    monkeypatch.setattr(server, "_apply_reader_override", lambda doc: doc)
    monkeypatch.setattr(server, "_auto_curate_tasks", lambda: [existing])
    monkeypatch.setattr(
        server,
        "_auto_curate_runbook",
        lambda _agent: SimpleNamespace(ref="Runbooks/observations/executive"),
    )
    monkeypatch.setattr(
        server,
        "_auto_curate_target_path",
        lambda _ref, _doc: "Agents/Executive/Observations/Temporary Observations",
    )
    monkeypatch.setattr(server, "_set_auto_curate_tag", lambda *_args: None)
    monkeypatch.setattr(server, "write_note", lambda path, meta, body: writes.append((path, meta, body)))
    monkeypatch.setattr(server.INDEX, "sync", lambda: None)

    result = server.set_article_auto_curate(
        "@agent/Temporary Observations", {"enabled": True},
    )

    assert result["enabled"] is True
    assert len(writes) == 1
    _path, meta, _body = writes[0]
    assert meta["status"] == "draft"
    assert meta["triggers"] == ["turn.complete"]
    assert "event" not in meta
    assert meta["enabled"] is True
    for runtime_field in (
        "blocked_reason", "event_queue", "last_run", "params", "summary",
        "triggered_at", "status_updated",
    ):
        assert runtime_field not in meta

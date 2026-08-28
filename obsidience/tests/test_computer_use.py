from __future__ import annotations

import pytest

from obsidience.harness.computer import runtime as computer
from obsidience.harness.execution.executor import resolve_spine
from obsidience.harness.capabilities.registry import REGISTRY
from obsidience.harness.knowledge.vault import iter_notes, resolver


ROW = {
    "pid": 100,
    "window_id": 200,
    "internal_id": "{fixture}",
    "capture_bounds": {"x": 10, "y": 20, "width": 640, "height": 480},
    "interrupt_generation": 3,
    "target_token": "kwt1_fixture",
    "app_name": "fixture.app",
    "title": "CuaTestHarness GTK3",
}


def observation(label: str = "Increment") -> dict:
    token = "element-fixture"
    result = {
        "observation": {
            "observation_id": "obs-fixture",
            "window": {
                "pid": ROW["pid"],
                "internal_id": ROW["internal_id"],
                "title": ROW["title"],
                "visible": ROW["capture_bounds"],
            },
            "elements": [{
                "token": token,
                "name": label,
                "value": label,
                "description": "",
                "role": "button",
                "bounds": {"x": 140, "y": 150, "width": 100, "height": 40},
                "source": "atspi",
                "interactable": True,
                "coordinate_attested": True,
            }],
        },
        "grounding": {
            "selected_token": token,
            "ambiguity": False,
            "candidates": [{"element_token": token, "match": "exact"}],
            "action_authorized": False,
        },
    }
    return {"result": result, "observation": result["observation"], "image": (b"rgb", 640, 480)}


def test_computer_use_spine_is_generic_and_closed() -> None:
    res = resolver()
    task = res.resolve("Tasks/executive/operate")
    assert task is not None and task.title == "Computer Use"
    spine = resolve_spine(task, res)
    assert "error" not in spine
    assert set(spine["tools"]) == {
        "application.launch", "computer.act", "computer.observe", "task.complete",
    }
    assert {skill.title for skill in spine["skills"]} == {
        "Act on the computer", "Complete task", "Launch an application",
        "Observe the computer",
    }
    assert {"computer.act", "computer.observe"} <= set(REGISTRY)
    assert not any(
        "play" in note.ref.casefold() and note.kind == "task" for note in iter_notes()
    )


def test_observe_returns_labels_without_privileged_tokens(monkeypatch) -> None:
    monkeypatch.setattr(computer, "_resolve_exact_window", lambda _application: ROW)
    monkeypatch.setattr(computer, "_observe_exact", lambda *_args, **_kwargs: observation())
    result = computer.observe_computer({
        "application": "CuaTestHarness GTK3",
        "query": "Increment",
    })
    assert result["elements"][0]["label"] == "Increment"
    assert result["action_authorized"] is False
    assert "token" not in str(result).casefold()
    assert "bounds" not in str(result).casefold()


def test_act_delivers_once_and_returns_a_fresh_post_observation(monkeypatch) -> None:
    calls: list[str] = []
    observations = iter((observation(), observation("counter=1")))
    monkeypatch.setattr(computer, "_resolve_exact_window", lambda _application: ROW)
    monkeypatch.setattr(
        computer, "_observe_exact",
        lambda *_args, **_kwargs: calls.append("observe") or next(observations),
    )
    monkeypatch.setattr(
        computer, "_validate_observation", lambda _observation_id: calls.append("validate"),
    )
    monkeypatch.setattr(computer, "_fresh_exact_row", lambda _previous: ROW)
    monkeypatch.setattr(
        computer, "_visual_witness",
        lambda *_args: {"roi": {"x": 1, "y": 1, "width": 16, "height": 16},
                        "preimage_png_base64": "fixture"},
    )

    def cua(name: str, args: dict) -> dict:
        assert name == "click"
        assert args["count"] == 1
        assert args["target_token"] == ROW["target_token"]
        calls.append("click")
        return {"structuredContent": {"effect": "delivery_acknowledged"}}

    monkeypatch.setattr(computer, "_cua_call", cua)
    context: dict = {}
    result = computer.act_computer({
        "application": "CuaTestHarness GTK3",
        "action": "click",
        "target": "Increment",
        "postcondition": "counter=1",
    }, context)
    assert calls == ["observe", "validate", "click", "observe"]
    assert result["delivery"] == "acknowledged"
    assert result["post_observation"]["query"] == "counter=1"
    assert result["must_not_replay"] is True
    with pytest.raises(computer.ComputerError, match="already attempted"):
        computer.act_computer({
            "application": "CuaTestHarness GTK3",
            "action": "click",
            "target": "Increment",
        }, context)
    assert calls.count("click") == 1


def test_inner_cua_error_is_not_success_and_is_never_replayed(monkeypatch) -> None:
    monkeypatch.setattr(computer, "_resolve_exact_window", lambda _application: ROW)
    monkeypatch.setattr(computer, "_observe_exact", lambda *_args, **_kwargs: observation())
    monkeypatch.setattr(computer, "_validate_observation", lambda _observation_id: None)
    monkeypatch.setattr(computer, "_fresh_exact_row", lambda _previous: ROW)
    monkeypatch.setattr(computer, "_visual_witness", lambda *_args: {})
    attempts = 0

    def reject(_name: str, _args: dict) -> dict:
        nonlocal attempts
        attempts += 1
        return {"isError": True, "structuredContent": {"code": "visual_witness_mismatch"}}

    monkeypatch.setattr(computer, "_cua_call", reject)
    context: dict = {}
    result = computer.act_computer({
        "application": "CuaTestHarness GTK3", "target": "Increment",
    }, context)
    assert result["delivery"] == "rejected_or_uncertain"
    assert result["must_not_replay"] is True
    with pytest.raises(computer.ComputerError, match="already attempted"):
        computer.act_computer({
            "application": "CuaTestHarness GTK3", "target": "Increment",
        }, context)
    assert attempts == 1

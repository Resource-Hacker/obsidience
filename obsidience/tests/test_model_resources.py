"""Reservation admission uses the model owner without real service operations."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from obsidience.harness import config
from obsidience.harness.capabilities.task import create as task_create
from obsidience.harness.execution import scheduler
from obsidience.harness.knowledge import vault
from obsidience.harness.models import runtime as models
from obsidience.tests.test_scheduler_interactive_provenance import ledger, record


@pytest.fixture
def allocation(monkeypatch):
    runtime = models._HardwareModelRuntime()
    settings = models._default_settings()
    monkeypatch.setattr(models, "RUNTIME", runtime)
    monkeypatch.setattr(models, "_read_settings", lambda: settings)
    monkeypatch.setattr(models, "_read_launch", lambda _model: ())
    monkeypatch.setattr(models, "_healthy", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(models, "_service_state", lambda _service: "inactive")
    monkeypatch.setattr(models, "_active", AsyncMock(return_value=False))
    monkeypatch.setattr(runtime, "_start", AsyncMock())
    monkeypatch.setattr(runtime, "_stop", AsyncMock())
    monkeypatch.setattr(runtime, "_perception", AsyncMock())
    monkeypatch.setattr(runtime, "_reconcile_defaults", AsyncMock())
    return runtime, settings


def test_pure_admission_reports_exact_reserved_layout_without_probing(allocation, monkeypatch):
    runtime, _settings = allocation
    runtime.device_reservations["realtime-speech"] = (models.RTX_4080_DEVICE,)

    def forbidden(*_args, **_kwargs):
        pytest.fail("reservation admission must not probe services or GPU utilization")

    monkeypatch.setattr(models, "_healthy", forbidden)
    monkeypatch.setattr(models, "_service_state", forbidden)
    monkeypatch.setattr(models, "gpu_snapshot", forbidden)
    with pytest.raises(models.ModelResourceUnavailable) as failure:
        models.check_resources(models.MODELS[models.QWEN_Q8_MODEL])
    assert failure.value.as_dict() == {
        "code": "model_resources_reserved",
        "model_id": models.QWEN_Q8_MODEL,
        "candidate_layouts": [list(models.GPU_DEVICES)],
        "reservations": {"realtime-speech": [models.RTX_4080_DEVICE]},
    }
    assert "realtime-speech" in str(failure.value)
    models.check_resources(models.MODELS[models.EXECUTIVE_MODEL])


def test_healthy_current_layout_cannot_bypass_reservation(allocation, monkeypatch):
    runtime, _settings = allocation
    runtime.device_reservations["realtime-speech"] = (models.RTX_4080_DEVICE,)
    monkeypatch.setattr(models, "_healthy", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(models, "_read_launch", lambda _model: models.GPU_DEVICES)
    with pytest.raises(models.ModelResourceUnavailable):
        runtime._pick_devices(models.MODELS[models.QWEN_Q8_MODEL])


def test_same_model_uses_only_another_configured_valid_layout(allocation, monkeypatch):
    runtime, settings = allocation
    settings["models"][models.SPECIALIST_MODEL]["allowed_devices"] = list(models.GPU_DEVICES)
    runtime.device_reservations["realtime-speech"] = (models.RTX_4080_DEVICE,)
    monkeypatch.setattr(models, "_healthy", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(models, "_read_launch", lambda _model: (models.RTX_4080_DEVICE,))
    assert runtime._pick_devices(models.MODELS[models.SPECIALIST_MODEL]) == (models.RTX_4000_DEVICE,)
    assert settings["models"][models.SPECIALIST_MODEL]["allowed_devices"] == list(models.GPU_DEVICES)


@pytest.mark.parametrize("devices", [
    [], "rtx4000", ["rtx4000", "unknown"], ["rtx4000", "rtx4000"],
    ["rtx4080"], ["rtx4000", None],
])
def test_explicit_device_request_is_not_silently_filtered(allocation, devices):
    runtime, _settings = allocation
    with pytest.raises(ValueError):
        runtime.check_resources(models.MODELS[models.EXECUTIVE_MODEL], devices)


def test_valid_explicit_but_reserved_layout_has_typed_resource_failure(allocation):
    runtime, _settings = allocation
    runtime.device_reservations["realtime-speech"] = (models.RTX_4080_DEVICE,)
    with pytest.raises(models.ModelResourceUnavailable):
        runtime.check_resources(models.MODELS[models.QWEN_Q8_MODEL], list(models.GPU_DEVICES))


def test_denied_lease_never_mutates_or_reconciles_hardware(allocation):
    runtime, _settings = allocation
    runtime.device_reservations["realtime-speech"] = (models.RTX_4080_DEVICE,)

    async def exercise():
        with pytest.raises(models.ModelResourceUnavailable):
            async with runtime.lease(models.MODELS[models.QWEN_Q8_MODEL]):
                pytest.fail("reserved layout cannot enter the lease")
        assert not runtime.lock.locked()
        assert not runtime.switching and runtime.running_model is None

    asyncio.run(exercise())
    runtime._start.assert_not_awaited()
    runtime._stop.assert_not_awaited()
    runtime._perception.assert_not_awaited()
    runtime._reconcile_defaults.assert_not_awaited()


def test_reservation_release_admits_exact_selected_model_and_preserves_profile(allocation):
    runtime, settings = allocation
    spec = models.configured_spec(models.QWEN_Q8_MODEL)
    before = json.dumps(settings, sort_keys=True)

    async def exercise():
        await runtime.reserve_devices("realtime-speech", (models.RTX_4080_DEVICE,))
        with pytest.raises(models.ModelResourceUnavailable):
            runtime.check_resources(spec)
        await runtime.release_devices("realtime-speech")
        async with runtime.lease(spec) as active:
            assert active == spec
            assert runtime.running_model == models.QWEN_Q8_MODEL

    asyncio.run(exercise())
    runtime._start.assert_awaited_once_with(spec, models.GPU_DEVICES)
    assert json.dumps(settings, sort_keys=True) == before


def test_duplicate_reservation_rejected_without_hardware_changes(allocation):
    runtime, _settings = allocation
    with pytest.raises(ValueError, match="exactly once"):
        asyncio.run(runtime.reserve_devices("speech", (models.RTX_4080_DEVICE,) * 2))
    assert runtime.device_reservations == {}
    runtime._stop.assert_not_awaited()


def test_user_delegation_waits_visibly_without_claim_and_resumes_same_fifo(ledger, allocation, monkeypatch):
    runtime, _settings = allocation
    runtime.device_reservations["realtime-speech"] = (models.RTX_4080_DEVICE,)
    target = vault.load_note("Tasks/research/question.md")
    vault.mutate_note_metadata(target, lambda meta: meta.update(model=models.QWEN_Q8_MODEL))
    target = vault.load_note(target.path)
    before_article = (config.CONFIG.vault_dir / target.path).read_bytes()
    conversation_id = ledger.active_conversation_id()
    turn = ledger.append_conversation_turn(
        conversation_id=conversation_id, role="user", source="realtime",
        text="Research this exact question.", run_id=None, reply_to=None, state="final",
    )
    binding = {"conversation_id": conversation_id, "reply_to_turn_id": turn["id"]}
    context = {"task": "Tasks/query", "run_id": "caller", "interactive": True, "params": binding}
    result = json.loads(task_create.execute({"task": target.ref, "wait_for_result": True}, context))
    assert result["state"] == "queued"
    assert "Waiting for model hardware" in result["reason"]
    assert "realtime-speech" in result["reason"]
    assert result["waiting_for_result"] is True
    record(ledger, "Tasks/query", "caller", {
        "created_tasks": context["_created_tasks"], "interactive_turn": binding,
    })
    current = vault.load_note(target.path)
    original = dict(current.meta["params"])
    later = {"event": "task.create", "activation_key": "later", "request": "Later exact question."}
    scheduler.enqueue_event(current, later)
    assert scheduler._realtime_allows(vault.load_note(target.path))
    assert scheduler.due_tasks() == []
    current = vault.load_note(target.path)
    assert current.meta["status"] == "pending"
    assert current.meta["blocked_reason"].startswith(scheduler.RESOURCE_WAIT_PREFIX)
    assert current.meta["params"] == original and current.meta["event_queue"] == [later]
    assert target.ref not in scheduler._running and target.ref not in scheduler._last_fired
    assert all(row["task_ref"] != target.ref for row in ledger.runs())

    asyncio.run(runtime.release_devices("realtime-speech"))
    due = scheduler.due_tasks()
    assert [note.ref for note in due] == [target.ref]
    current = vault.load_note(target.path)
    assert "blocked_reason" not in current.meta
    assert current.meta["model"] == models.QWEN_Q8_MODEL
    assert current.meta["params"] == original and current.meta["event_queue"] == [later]
    assert (config.CONFIG.vault_dir / target.path).read_bytes() == before_article


def test_claim_rechecks_resources_before_starting_or_consuming_occurrence(ledger, allocation, monkeypatch):
    runtime, _settings = allocation
    monkeypatch.setattr(scheduler, "_realtime_allows", lambda _note, _res=None: True)
    target = vault.load_note("Tasks/research/question.md")
    vault.mutate_note_metadata(target, lambda meta: meta.update(model=models.QWEN_Q8_MODEL))
    scheduler.enqueue_event(target, {"event": "task.create", "activation_key": "exact"})
    target = vault.load_note(target.path)
    scheduler._claim(target)
    runtime.device_reservations["realtime-speech"] = (models.RTX_4080_DEVICE,)
    run = AsyncMock()
    monkeypatch.setattr(scheduler, "run_task", run)
    asyncio.run(scheduler._run_claimed(target))
    run.assert_not_awaited()
    assert target.ref not in scheduler._running and target.ref not in scheduler._last_fired
    assert vault.load_note(target.path).meta["status"] == "pending"


def test_due_schedule_stays_pending_until_same_model_layout_is_released(ledger, allocation, monkeypatch):
    runtime, _settings = allocation
    monkeypatch.setattr(scheduler, "_realtime_allows", lambda _note, _res=None: True)
    target = vault.load_note("Tasks/research/question.md")
    vault.mutate_note_metadata(target, lambda meta: meta.update(
        model=models.QWEN_Q8_MODEL, schedule="* * * * *", status="completed", last_run="previous",
    ))
    scheduler._last_fired[target.ref] = 60.0
    monkeypatch.setattr(scheduler.time, "time", lambda: 121.0)
    runtime.device_reservations["realtime-speech"] = (models.RTX_4080_DEVICE,)
    assert scheduler.due_tasks() == []
    current = vault.load_note(target.path)
    assert current.meta["status"] == "pending" and current.meta["last_run"] == "previous"
    assert scheduler._last_fired[target.ref] == 60.0
    assert current.meta["model"] == models.QWEN_Q8_MODEL
    asyncio.run(runtime.release_devices("realtime-speech"))
    assert [note.ref for note in scheduler.due_tasks()] == [target.ref]
    assert scheduler._last_fired[target.ref] == 60.0
    assert ledger.runs() == []


@pytest.mark.parametrize("prior_firing", [None, 42.0])
def test_executor_resource_race_does_not_consume_scheduled_firing(ledger, allocation, monkeypatch, prior_firing):
    monkeypatch.setattr(scheduler, "_realtime_allows", lambda _note, _res=None: True)
    target = vault.load_note("Tasks/research/question.md")
    if prior_firing is not None:
        scheduler._last_fired[target.ref] = prior_firing
    monkeypatch.setattr(scheduler, "run_task", AsyncMock(return_value={
        "status": "pending", "resource_blocked": True,
    }))
    asyncio.run(scheduler._run(target))
    assert scheduler._last_fired.get(target.ref) == prior_firing
    assert ledger.runs() == []


def test_direct_unavailable_model_override_is_rejected_without_changing_saved_task(ledger, allocation, monkeypatch):
    runtime, _settings = allocation
    runtime.device_reservations["realtime-speech"] = (models.RTX_4080_DEVICE,)
    monkeypatch.setattr(scheduler, "_realtime_allows", lambda _note, _res=None: True)
    target = vault.load_note("Tasks/query.md")
    before = dict(target.meta)
    with pytest.raises(models.ModelResourceUnavailable):
        scheduler.launch(target, model=models.QWEN_Q8_MODEL)
    assert scheduler._running == set()
    assert vault.load_note(target.path).meta == before
    assert ledger.runs() == []


def test_late_conflict_does_not_requeue_ephemeral_launch_as_saved_model(ledger, allocation, monkeypatch):
    runtime, _settings = allocation
    monkeypatch.setattr(scheduler, "_realtime_allows", lambda _note, _res=None: True)
    target = vault.load_note("Tasks/query.md")
    before = dict(target.meta)
    run = AsyncMock(return_value={"status": "blocked", "resource_blocked": True})
    monkeypatch.setattr(scheduler, "run_task", run)

    async def exercise():
        pending = scheduler.launch(target, model=models.QWEN_Q8_MODEL)
        runtime.device_reservations["realtime-speech"] = (models.RTX_4080_DEVICE,)
        await pending

    asyncio.run(exercise())
    run.assert_awaited_once_with(target, model=models.QWEN_Q8_MODEL)
    assert vault.load_note(target.path).meta == before
    assert scheduler._running == set()
    assert target.ref not in scheduler._last_fired


def test_resource_failure_after_effect_does_not_replay_bound_occurrence_at_next_cron(ledger, allocation, monkeypatch):
    monkeypatch.setattr(scheduler, "_realtime_allows", lambda _note, _res=None: True)
    target = vault.load_note("Tasks/research/question.md")
    original = {"event": "task.create", "activation_key": "original"}
    later = {"event": "task.create", "activation_key": "later"}
    scheduler.enqueue_event(target, original)
    scheduler.enqueue_event(target, later)
    vault.update_status(target, "failed", {"last_run": "after-effect", "schedule": "* * * * *"})
    ledger.record_run(
        id="after-effect", task_ref=target.ref, agent="test", started=1, finished=2,
        status="failed", summary="Resource conflict after a committed effect.", trace=json.dumps([
            {"tool": "source.handoff", "obs": "Returned committed effect."},
            {"resource_blocked_after_effect": {"model_id": models.QWEN_Q8_MODEL}, "must_not_replay": True},
        ]),
    )
    scheduler._last_fired[target.ref] = 1
    assert scheduler.due_tasks() == []
    current = vault.load_note(target.path)
    assert current.meta["status"] == "failed"
    assert current.meta["params"] == original and current.meta["event_queue"] == [later]
    assert scheduler._last_fired[target.ref] == 1

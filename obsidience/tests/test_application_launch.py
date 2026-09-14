import json
import subprocess
from types import SimpleNamespace

import pytest

from obsidience.harness.capabilities.application import launch
from obsidience.harness.host.scene import EVENT_SCHEMA, SURFACE_IDS, ShellSceneCache


def test_managed_receipt_rejects_wrong_or_duplicate_identity():
    unit = "agent-gui-tft-waydroid-123-456.service"
    assert launch._managed_unit(f"Transient unit: {unit}\n", "tft-waydroid.desktop") == unit
    assert launch._managed_unit(f"Transient unit: {unit}\n", "microsoft-edge.desktop") is None
    assert launch._managed_unit(f"Transient unit: {unit}\n" * 2, "tft-waydroid.desktop") is None


def test_launch_accepted_then_collected_before_window_is_failure(monkeypatch):
    commands = []
    unit = "agent-gui-tft-waydroid-123-456.service"
    def run(command, **kwargs):
        commands.append(command)
        if command[0].endswith("agent-launch-gui"):
            return SimpleNamespace(returncode=0, stdout=f"Transient unit: {unit}\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="LoadState=not-found\nActiveState=inactive\n", stderr="")
    monkeypatch.setattr(launch, "SCENE", ShellSceneCache())
    monkeypatch.setattr(launch.subprocess, "run", run)
    result = launch._launch_application({"application": "teamfight_tactics"})
    assert result["state"] == "failed" and result["ready"] is False
    assert result["wait_status"] == "terminated_before_ready"
    assert result["dispatched"] is True and result["must_not_replay"] is True
    assert sum(command[0].endswith("agent-launch-gui") for command in commands) == 1


@pytest.mark.parametrize("lifetime", ["running", "unknown"])
def test_timeout_does_not_claim_app_is_still_loading(monkeypatch, lifetime):
    monkeypatch.setattr(launch, "SCENE", ShellSceneCache())
    monkeypatch.setattr(launch, "READINESS_TIMEOUT_SECONDS", 0)
    monkeypatch.setattr(launch, "_launch_lifetime", lambda unit: lifetime)
    result = launch._await_readiness({"application": "teamfight_tactics", "label": "TFT",
                                     "state": "starting", "ready": False}, {}, launch_unit="exact")
    assert result["state"] == "unverified" and result["launch_lifetime"] == lifetime
    assert result["must_not_replay"] is True


def test_late_window_after_live_startup_is_ready_without_replay(monkeypatch, scene):
    monkeypatch.setattr(launch, "READINESS_TIMEOUT_SECONDS", 1)
    cache = launch.SCENE
    def changed(*args):
        scene(windows=[window("tft-waydroid", "TFT")])
        return cache.change_token()
    monkeypatch.setattr(cache, "wait_for_change", changed)
    monkeypatch.setattr(launch, "_launch_lifetime", lambda unit: "running")
    result = launch._await_readiness({"application": "teamfight_tactics", "label": "TFT",
                                     "ready": False}, {}, launch_unit="exact")
    assert result["ready"] is True


def window(app_id, title, *, window_id="0xprimary", visible=True, minimized=False):
    return {
        "window_id": window_id, "app_id": app_id, "title": title, "pid": 42,
        "minimized": minimized, "visible_on_workspace": visible,
        "window_kind": "application", "pane_id": "",
        "local_rect": {"x": 0, "y": 0, "width": 800, "height": 600},
    }


@pytest.fixture(autouse=True)
def no_readiness_delay(monkeypatch):
    monkeypatch.setattr(launch, "READINESS_TIMEOUT_SECONDS", 0)


@pytest.fixture
def scene(monkeypatch):
    cache = ShellSceneCache()
    generation = cache.connect()
    assert cache.accept(generation, {
        "schema": EVENT_SCHEMA, "type": "workspace.state", "revision": 1,
        "workspace_tiling": [
            {"surface_id": surface, "columns": 1, "rows": 1, "zones": 1}
            for surface in SURFACE_IDS
        ],
    })

    def publish(surface="usb-c", windows=(), *, active="", awake=True, revision=2):
        assert cache.accept(generation, {
            "schema": EVENT_SCHEMA, "type": "application.state", "surface_id": surface,
            "revision": revision, "active_window_id": active, "surface_awake": awake,
            "windows": list(windows),
        })

    for surface in SURFACE_IDS:
        publish(surface, revision=1)
    monkeypatch.setattr(launch, "SCENE", cache)
    return publish


def test_existing_shell_window_is_ready_without_relaunch(monkeypatch, scene) -> None:
    scene(windows=[window("microsoft-edge", "Microsoft Edge - Docs", visible=False)])
    monkeypatch.setattr(
        launch.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("an existing application must not be relaunched")
        ),
    )

    result = launch._launch_application({"application": "microsoft_edge"})

    assert result["state"] == "ready"
    assert result["ready"] is True
    assert result["dispatched"] is False
    assert result["window"] == {
        "title": "Microsoft Edge - Docs",
        "app_id": "microsoft-edge",
        "surface": "usb-c",
        "focused": False,
        "visible": False,
    }


def test_unavailable_scene_preserves_managed_launch(monkeypatch) -> None:
    commands: list[list[str]] = []

    def run(command, **_kwargs):
        commands.append(command)
        if command[:3] == ["systemctl", "--user", "is-active"]:
            return SimpleNamespace(returncode=1)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(launch, "SCENE", ShellSceneCache())
    monkeypatch.setattr(launch.subprocess, "run", run)

    result = launch._launch_application({"application": "microsoft_edge"})

    assert result["state"] == "unverified"
    assert result["ready"] is False
    assert result["dispatched"] is True
    assert commands == [[
        "/home/wissenschafter/bin/agent-launch-gui", "microsoft-edge.desktop",
    ]]


@pytest.mark.parametrize("application", ["microsoft_edge", "Microsoft Edge", "edge", "microsoft-edge"])
def test_witness_resolves_shared_aliases_and_exact_app_id(scene, application):
    scene(windows=[window("microsoft-edge", "Documentation")])
    witness = launch._visible_application_window(application)
    assert witness["app_id"] == "microsoft-edge"


def test_tft_primary_window_is_not_confused_with_other_gamescope_apps(monkeypatch, scene):
    controls = window("gamescope", "gamescope", window_id="0xcontrols")
    primary = window("tft-waydroid", "gamescope")
    scene(windows=[controls, primary], active="0xprimary")
    monkeypatch.setattr(launch.subprocess, "run", lambda *_args, **_kwargs: pytest.fail("no launch effect"))
    result = launch._launch_application({"application": "teamfight_tactics"})
    assert result["dispatched"] is False
    assert result["window"] == {
        "title": primary["title"], "app_id": "tft-waydroid", "surface": "usb-c",
        "focused": True, "visible": True,
    }


@pytest.mark.parametrize("app_id,title", [
    ("emulator", "Extended controls"),
    ("emulator", "Android Emulator - TFT_4080:5554"),
    ("gamescope", "gamescope"),
    ("gamescope", "Teamfight Tactics"),
    ("org.mozilla.firefox", "Teamfight Tactics"),
])
def test_unregistered_and_retired_windows_are_not_tft_readiness(scene, app_id, title):
    scene(windows=[window(app_id, title)])
    assert launch._visible_application_window("teamfight_tactics") is None


def test_locked_scene_does_not_publish_a_launch_witness(scene):
    scene(windows=[window("microsoft-edge", "Private title")])
    cache = launch.SCENE
    snapshot = cache.snapshot()
    assert cache.accept(snapshot.generation, {
        **snapshot.workspace, "revision": 2, "session_locked": True,
    })
    assert launch._visible_application_window("microsoft_edge") is None


def test_ambiguous_windows_preserve_active_unit_guard_without_relaunch(monkeypatch, scene):
    scene(windows=[window("wow.exe", "World of Warcraft")])
    scene("samsung", [window("wow.exe", "World of Warcraft", window_id="0xsecond")])
    commands = []

    def run(command, **_kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(launch.subprocess, "run", run)
    assert launch._visible_application_window("world_of_warcraft") is None
    result = launch._launch_application({"application": "world_of_warcraft"})
    assert result["state"] == "unverified" and result["dispatched"] is False
    assert commands == [["systemctl", "--user", "is-active", "--quiet", "wow-retail-wow-drive.service"]]


def test_tft_dispatch_uses_current_managed_desktop_without_retired_unit(monkeypatch):
    commands = []

    def run(command, **_kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout="Accepted", stderr="")

    monkeypatch.setattr(launch, "SCENE", ShellSceneCache())
    monkeypatch.setattr(launch.subprocess, "run", run)
    result = launch._launch_application({"application": "teamfight_tactics"})
    assert commands == [["/home/wissenschafter/bin/agent-launch-gui", "tft-waydroid.desktop"]]
    assert result["desktop_id"] == "tft-waydroid.desktop"
    assert result["state"] == "unverified"
    assert result["dispatched"] is True and result["ready"] is False


@pytest.mark.parametrize("awake,visible,minimized", [(False, True, False), (True, False, False), (True, True, True)])
def test_witness_preserves_visibility_and_bounded_title(scene, awake, visible, minimized):
    title = "Microsoft Edge " + "Long title " * 30
    scene(windows=[window("microsoft-edge", title, visible=visible, minimized=minimized)], awake=awake)
    witness = launch._visible_application_window("microsoft_edge")
    assert witness["visible"] is False
    assert len(witness["title"]) <= 80
    assert witness["title"].endswith("…")


def test_launcher_timeout_retains_target_without_claiming_delivery(monkeypatch):
    from obsidience.harness.capabilities.task.complete import computer_completion_evidence

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("managed-launcher", 30)

    monkeypatch.setattr(launch, "_launch_application", timeout)
    result = json.loads(launch.execute({"application": "teamfight_tactics"}, {}))
    assert result["application"] == "teamfight_tactics"
    assert result["delivery"] == "uncertain" and result["must_not_replay"] is True
    evidence = computer_completion_evidence("application.launch", result)
    assert evidence["verified"] is False
    assert evidence["target"] == {"kind": "application", "name": "teamfight_tactics"}
    assert evidence["launch_outcome"] == "launcher_timeout"

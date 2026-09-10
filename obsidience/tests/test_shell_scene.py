"""Harness contracts for the shell's read-only semantic scene."""

from __future__ import annotations

import json

import pytest

from obsidience.harness.host.scene import (
    EVENT_SCHEMA,
    MAX_SEMANTIC_MANIFEST_CHARS,
    SceneManifestTooLarge,
    SceneTargetAmbiguous,
    SceneTargetNotFound,
    SceneTargetStale,
    SceneUnavailable,
    ShellSceneCache,
)


def _workspace(revision: int = 3, *, locked: bool = False) -> dict:
    return {
        "schema": EVENT_SCHEMA,
        "type": "workspace.state",
        "revision": revision,
        "session_locked": locked,
        "workspace_tiling": [
            {
                "surface_id": "samsung",
                "label": "Samsung G95SC",
                "columns": 8,
                "rows": 2,
                "zones": 16,
            },
            {
                "surface_id": "usb-c",
                "label": "USB-C",
                "columns": 3,
                "rows": 2,
                "zones": 6,
            },
            {
                "surface_id": "dp-4",
                "label": "DP-4",
                "columns": 4,
                "rows": 1,
                "zones": 4,
            },
        ],
    }


def _window(
    window_id: str,
    app_id: str,
    title: str,
    *,
    stable_id: str = "",
    visible: bool = True,
    pane_id: str = "",
) -> dict:
    return {
        "window_id": window_id,
        "stable_id": stable_id,
        "app_id": "io.obsidience.shell" if pane_id else app_id,
        "title": title,
        "pid": 42,
        "minimized": False,
        "visible_on_workspace": visible,
        "window_kind": "module" if pane_id else "application",
        "pane_id": pane_id,
        "local_rect": {"x": 10, "y": 20, "width": 800, "height": 600},
    }


def _applications(
    surface_id: str,
    revision: int,
    windows: list[dict],
    *,
    active: str = "",
    awake: bool = True,
) -> dict:
    return {
        "schema": EVENT_SCHEMA,
        "type": "application.state",
        "surface_id": surface_id,
        "revision": revision,
        "active_window_id": active,
        "surface_awake": awake,
        "windows": windows,
    }


def _hydrate(cache: ShellSceneCache) -> int:
    generation = cache.connect()
    assert cache.accept(generation, _workspace())
    for surface_id in ("samsung", "usb-c", "dp-4"):
        assert cache.accept(generation, _applications(surface_id, 1, []))
    return generation


def test_scene_requires_a_complete_current_connection() -> None:
    cache = ShellSceneCache()
    generation = cache.connect()
    assert cache.accept(generation, _workspace())
    assert cache.accept(generation, _applications("samsung", 1, []))
    assert cache.accept(generation, _applications("usb-c", 1, []))

    with pytest.raises(SceneUnavailable):
        cache.snapshot()

    assert cache.accept(generation, _applications("dp-4", 1, []))
    assert tuple(item.surface_id for item in cache.snapshot().surfaces) == (
        "samsung",
        "usb-c",
        "dp-4",
    )

    cache.disconnect(generation)
    with pytest.raises(SceneUnavailable):
        cache.snapshot()
    assert cache.activation_binding() == {
        "available": False,
        "reason": "unavailable",
    }
    assert not cache.accept(generation, _applications("samsung", 2, []))


def test_scene_resolves_unfocused_apps_and_module_panes() -> None:
    cache = ShellSceneCache()
    generation = _hydrate(cache)
    edge = _window(
        "0xedge",
        "microsoft-edge",
        "Documentation",
        stable_id="edge-stable-7",
        visible=False,
    )
    reader = _window("0xreader", "", "Reader", pane_id="reader")
    assert cache.accept(generation, _applications("samsung", 2, [edge]))
    assert cache.accept(
        generation,
        _applications("usb-c", 2, [reader], active="0xreader"),
    )

    edge_target = cache.resolve(app_id="microsoft-edge")
    assert edge_target.active is False
    assert edge_target.window.visible_on_workspace is False
    assert edge_target.window.stable_id == "edge-stable-7"

    reader_target = cache.resolve(pane_id="reader")
    assert reader_target.surface_id == "usb-c"
    assert reader_target.active is True

    manifest = cache.semantic_manifest()
    assert manifest == {
        "available": True,
        "fields": ["kind", "name", "title", "focused", "visible"],
        "tile_units": "grid_edges",
        "tile_grids": {
            "samsung": {"columns": 8, "rows": 2},
            "usb-c": {"columns": 3, "rows": 2},
            "dp-4": {"columns": 4, "rows": 1},
        },
        "surface_awake": {"samsung": True, "usb-c": True, "dp-4": True},
        "surfaces": {
            "samsung": [["application", "microsoft_edge", "Documentation", False, False]],
            "usb-c": [["pane", "reader", "Reader", True, True]],
            "dp-4": [],
        },
    }
    encoded = json.dumps(manifest, separators=(",", ":"), sort_keys=True)
    assert len(encoded) <= MAX_SEMANTIC_MANIFEST_CHARS
    for private_field in ("window_id", "stable_id", "pid", "local_rect"):
        assert private_field not in encoded


def test_scene_grid_contract_tracks_live_workspace_without_pixel_geometry() -> None:
    cache = ShellSceneCache()
    generation = _hydrate(cache)
    changed = _workspace(4)
    changed["workspace_tiling"][0].update(columns=6, rows=3, zones=18)
    assert cache.accept(generation, changed)
    binding = cache.activation_binding()
    assert binding["tile_units"] == "grid_edges"
    assert binding["tile_grids"]["samsung"] == {"columns": 6, "rows": 3}
    assert set(binding["tile_grids"]) == {"samsung", "usb-c", "dp-4"}
    assert "revision" not in json.dumps(binding)


def test_sleeping_surface_is_explicit_and_its_windows_are_not_visible() -> None:
    cache = ShellSceneCache()
    generation = _hydrate(cache)
    reader = _window("0xreader", "", "Reader", pane_id="reader")
    assert cache.accept(
        generation,
        _applications("samsung", 2, [reader], active="0xreader", awake=False),
    )

    target = cache.resolve(pane_id="reader")
    assert target.surface_awake is False
    manifest = cache.semantic_manifest()
    assert manifest["surface_awake"]["samsung"] is False
    assert manifest["surfaces"]["samsung"][0][-1] is False


def test_scene_rejects_old_revisions_and_generations() -> None:
    cache = ShellSceneCache()
    generation = _hydrate(cache)
    newest = _window("0xedge", "microsoft-edge", "Newest")
    older = _window("0xedge", "microsoft-edge", "Older")
    assert cache.accept(generation, _applications("samsung", 3, [newest]))
    assert not cache.accept(generation, _applications("samsung", 2, [older]))
    assert cache.resolve(window_id="0xedge").window.title == "Newest"

    assert not cache.accept(generation, _workspace(2, locked=True))
    # Lock state is an ordered same-revision event in the current shell protocol.
    assert cache.accept(generation, _workspace(3, locked=True))
    assert cache.snapshot().workspace["session_locked"] is True
    assert cache.activation_binding() == {"available": False, "reason": "locked"}

    replacement_generation = cache.connect()
    assert replacement_generation > generation
    assert not cache.accept(generation, _applications("samsung", 4, [newest]))
    with pytest.raises(SceneUnavailable):
        cache.snapshot()


def test_exact_resolution_is_ambiguous_and_leases_fail_stale() -> None:
    cache = ShellSceneCache()
    generation = _hydrate(cache)
    first = _window("0x1", "microsoft-edge", "One", stable_id="stable-one")
    second = _window("0x2", "microsoft-edge", "Two", stable_id="stable-two")
    assert cache.accept(generation, _applications("samsung", 2, [first]))
    assert cache.accept(generation, _applications("dp-4", 2, [second]))

    with pytest.raises(SceneTargetAmbiguous):
        cache.resolve(app_id="microsoft-edge")

    target = cache.resolve(stable_id="stable-one")
    assert cache.validate(target) == target
    assert cache.accept(
        generation,
        _applications("samsung", 3, [first], active="0x1"),
    )
    with pytest.raises(SceneTargetStale):
        cache.validate(target)


def test_oversized_scene_fails_closed_without_omitting_windows() -> None:
    cache = ShellSceneCache()
    generation = _hydrate(cache)
    windows = [
        _window(
            f"0x{index}",
            f"org.example.addressable-application-{index}-" + "x" * 60,
            f"Addressable application {index} " + "title " * 20,
        )
        for index in range(12)
    ]
    assert cache.accept(generation, _applications("samsung", 2, windows))

    with pytest.raises(SceneManifestTooLarge):
        cache.semantic_manifest()
    assert cache.activation_binding() == {
        "available": False,
        "reason": "scene_too_large",
    }


@pytest.mark.parametrize("app_id,title,not_application", [
    ("org.mozilla.firefox", "Teamfight Tactics strategy guide", "teamfight_tactics"),
    ("gamescope", "Teamfight Tactics", "teamfight_tactics"),
    ("gamescope", "gamescope", "teamfight_tactics"),
    ("emulator", "Android Emulator - TFT_4080:5554", "teamfight_tactics"),
    ("org.kde.konsole", "World of Warcraft logs", "world_of_warcraft"),
    ("org.mozilla.firefox", "Android Emulator - TFT_4080:5554", "teamfight_tactics"),
    ("org.mozilla.firefox", "Microsoft Edge download", "microsoft_edge"),
    ("org.mozilla.firefox", "Battle.net.exe troubleshooting", "battle_net"),
])
def test_display_titles_cannot_impersonate_registered_application(app_id, title, not_application):
    cache = ShellSceneCache()
    generation = _hydrate(cache)
    window = _window("0xtest", app_id, title)
    cache.accept(generation, _applications("samsung", 2, [window]))
    assert cache.semantic_manifest()["surfaces"]["samsung"][0][1] == app_id
    assert cache.resolve_semantic("application", app_id).window.app_id == app_id
    with pytest.raises(SceneTargetNotFound):
        cache.resolve_semantic("application", not_application)

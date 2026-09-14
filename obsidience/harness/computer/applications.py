"""Shared allow-listed identities for launch, grounding, and window effects."""

from __future__ import annotations

from collections.abc import Iterator

APPLICATIONS = {
    "battle_net": {
        "label": "Battle.net",
        "aliases": ("battle net", "battlenet"),
        "desktop_id": "battlenet-wow-drive.desktop",
        "window_app_ids": ("battle.net.exe",),
        "window_needles": ("battle.net",),
    },
    "world_of_warcraft": {
        "label": "World of Warcraft",
        "aliases": ("wow",),
        "desktop_id": "wow-retail-wow-drive-smooth-motion.desktop",
        "window_app_ids": ("steam_app_0", "wow.exe"),
        "window_needles": ("world of warcraft", "wow.exe"),
        "unit": "wow-retail-wow-drive.service",
    },
    "teamfight_tactics": {
        "label": "Teamfight Tactics",
        "aliases": ("tft", "team fight tactics"),
        "desktop_id": "tft-waydroid.desktop",
        "window_app_ids": ("tft-waydroid",),
        "window_needles": ("tft-waydroid",),
    },
    "microsoft_edge": {
        "label": "Microsoft Edge",
        "aliases": ("edge",),
        "desktop_id": "microsoft-edge.desktop",
        "window_app_ids": ("microsoft-edge",),
        "window_needles": ("microsoft edge", "microsoft-edge"),
    },
}


def _normalized(value: object) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def canonical_application_id(value: object) -> str | None:
    """Resolve one public application name to its allow-listed registry key."""

    requested = _normalized(value)
    for application, spec in APPLICATIONS.items():
        names = (application, spec["label"], *spec.get("aliases", ()))
        if requested in {_normalized(name) for name in names}:
            return application
    return None


def application_aliases() -> Iterator[tuple[str, str]]:
    """Yield public names longest-first for bounded request mention matching."""

    aliases = (
        (_normalized(name), application)
        for application, spec in APPLICATIONS.items()
        for name in (application, spec["label"], *spec.get("aliases", ()))
    )
    yield from sorted(set(aliases), key=lambda item: (-len(item[0]), item[0]))


def application_window_needles(value: object) -> tuple[str, ...]:
    """Return registered window identity fragments, preserving unknown exact names."""

    application = canonical_application_id(value)
    if application is None:
        requested = _normalized(value)
        return (requested,) if requested else ()
    return tuple(
        _normalized(needle) for needle in APPLICATIONS[application]["window_needles"]
    )


def matches_application_window(value: object, app_id: str, title: str) -> bool:
    """Match a registered application name to one live semantic window identity."""

    application = canonical_application_id(value)
    if application is None:
        return False
    spec = APPLICATIONS[application]
    if _normalized(app_id) not in spec["window_app_ids"]:
        return False
    prefixes = spec.get("window_title_prefixes", ())
    return not prefixes or _normalized(title).startswith(prefixes)


def application_window_name(app_id: str, title: str) -> str:
    """Project a registered application identity, never a free-form window title."""

    matches = [
        name for name in APPLICATIONS if matches_application_window(name, app_id, title)
    ]
    return matches[0] if len(matches) == 1 else app_id

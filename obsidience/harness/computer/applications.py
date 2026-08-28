"""Shared allow-listed application identities for launch and computer grounding."""

APPLICATIONS = {
    "battle_net": {
        "label": "Battle.net",
        "desktop_id": "battlenet-wow-drive.desktop",
        "window_needles": ("battle.net",),
    },
    "world_of_warcraft": {
        "label": "World of Warcraft",
        "desktop_id": "wow-retail-wow-drive-smooth-motion.desktop",
        "window_needles": ("world of warcraft", "wow.exe"),
        "unit": "wow-retail-wow-drive.service",
    },
    "teamfight_tactics": {
        "label": "Teamfight Tactics",
        "desktop_id": "tft-mobile-waydroid.desktop",
        "window_needles": ("android emulator - tft_4080", "teamfight tactics"),
        "unit": "tft-4080-emulator.service",
    },
    "microsoft_edge": {
        "label": "Microsoft Edge",
        "desktop_id": "microsoft-edge.desktop",
        "window_needles": ("microsoft edge", "microsoft-edge"),
    },
}

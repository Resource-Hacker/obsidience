from __future__ import annotations

import json
from pathlib import Path

import pytest

from obsidience.shell.theme import apply as shell_theme


def test_palette_projects_one_surface_into_edge_and_openbox() -> None:
    theme = shell_theme.load_palette()

    assert json.loads(shell_theme.render_edge_policy(theme)) == {
        "BrowserThemeColor": "#030a10",
        "BrowserColorScheme": "device",
    }
    openbox = shell_theme.render_openbox_theme(theme)
    assert "window.active.title.bg.color: #030a10" in openbox
    assert "window.inactive.title.bg.color: #02080e" in openbox
    assert "window.active.border.color: #67e8f9" in openbox
    assert "window.inactive.border.color: #294b54" in openbox
    assert "window.active.label.text.color: #cffafe" in openbox


def test_palette_rejects_an_unknown_or_malformed_color(tmp_path: Path) -> None:
    record = shell_theme.load_palette()
    record["colors"]["surface"] = "transparent"
    path = tmp_path / "palette.json"
    path.write_text(json.dumps(record), encoding="utf-8")

    with pytest.raises(ValueError, match="theme colors"):
        shell_theme.load_palette(path)

    record["colors"]["surface"] = "#030a10"
    record["colors"]["extra"] = "#ffffff"
    path.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ValueError, match="color contract"):
        shell_theme.load_palette(path)


def test_opaque_projection_understands_qml_argb() -> None:
    assert shell_theme.opaque("#eb030a10") == "#030a10"
    assert shell_theme.opaque("#67E8F9") == "#67e8f9"
    with pytest.raises(ValueError, match="invalid theme color"):
        shell_theme.opaque("#12345")


def test_openbox_config_changes_only_its_theme_block(tmp_path: Path) -> None:
    path = tmp_path / "rc.xml"
    path.write_text(
        "<openbox_config>\n"
        "<theme><name>Clearlooks</name>"
        "<font><name>sans</name></font></theme>\n"
        "<application><name>sans</name></application>\n"
        "</openbox_config>\n",
        encoding="utf-8",
    )

    shell_theme._configure_openbox(path, "JetBrains Mono")

    content = path.read_text(encoding="utf-8")
    assert "<theme><name>Obsidience</name>" in content
    assert "<font><name>JetBrains Mono</name></font>" in content
    assert "<application><name>sans</name></application>" in content


def test_theme_boundary_does_not_embed_or_mutate_application_windows() -> None:
    source = Path(shell_theme.__file__).read_text(encoding="utf-8")
    forbidden = ("XReparent", "WindowContainer", "xdg-foreign", "XComposite")

    assert not any(term in source for term in forbidden)
    assert str(shell_theme.EDGE_POLICY_PATH) == (
        "/etc/opt/edge/policies/managed/obsidience-theme.json"
    )
    assert "--refresh-platform-policy" in source
    assert "--no-startup-window" in source

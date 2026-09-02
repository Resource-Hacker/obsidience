from __future__ import annotations

import json
import subprocess

import pytest

from obsidience.shell.applications import packagekit


def result(command: list[str], rows: list[dict], returncode: int = 0):
    return subprocess.CompletedProcess(
        command,
        returncode,
        "\n".join(json.dumps(row) for row in rows),
        "",
    )


def test_installed_apps_come_from_real_desktop_entries(tmp_path, monkeypatch) -> None:
    root = tmp_path / "applications"
    root.mkdir()
    visible = root / "demo.desktop"
    visible.write_text(
        "[Desktop Entry]\nType=Application\nName=Demo\nComment=Real app\nIcon=demo\n",
        encoding="utf-8",
    )
    (root / "hidden.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Hidden\nNoDisplay=true\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(packagekit, "DESKTOP_ROOTS", (root,))
    monkeypatch.setattr(
        packagekit,
        "backend_status",
        lambda: {"available": True, "name": "PackageKit", "backend": "alpm"},
    )
    monkeypatch.setattr(
        packagekit,
        "_installed_packages",
        lambda: {"demo": {"version": "1.0", "repo": "installed"}},
    )
    monkeypatch.setattr(
        packagekit,
        "_package_owners",
        lambda paths: {str(visible): ("demo", "1.0")},
    )

    payload = packagekit.installed_applications()

    assert payload["count"] == 1
    assert payload["applications"][0] == {
        "id": "native:demo:demo.desktop",
        "desktop_id": "demo.desktop",
        "label": "Demo",
        "description": "Real app",
        "icon": "demo",
        "package": "demo",
        "version": "1.0",
        "repository": "installed",
        "backend": "package",
        "installed": True,
        "manageable": True,
    }


def test_package_search_deduplicates_installed_and_repository_rows(monkeypatch) -> None:
    monkeypatch.setattr(
        packagekit,
        "backend_status",
        lambda: {"available": True, "name": "PackageKit", "backend": "alpm"},
    )
    monkeypatch.setattr(
        packagekit,
        "_installed_packages",
        lambda: {"demo": {"name": "demo", "version": "1.0", "repo": "installed"}},
    )

    def fake_run(command, *, timeout=30):
        del timeout
        if "search" in command:
            return result(
                command,
                [
                    {"name": "demo", "version": "1.0", "repo": "installed", "state": "installed"},
                    {"name": "demo", "version": "1.1", "repo": "extra", "state": "available"},
                    {"name": "demo-tools", "version": "2.0", "repo": "extra", "state": "available"},
                ],
            )
        return result(
            command,
            [
                {"name": "demo", "description": "Installed demo"},
                {"name": "demo-tools", "description": "Optional demo tools"},
            ],
        )

    monkeypatch.setattr(packagekit, "_run", fake_run)

    payload = packagekit.search_packages("demo")

    assert [row["package"] for row in payload["results"]] == ["demo", "demo-tools"]
    assert payload["results"][0]["installed"] is True
    assert payload["results"][1]["installed"] is False


def test_remove_rejects_packages_outside_installed_app_inventory(monkeypatch) -> None:
    monkeypatch.setattr(
        packagekit,
        "installed_applications",
        lambda: {"applications": [], "count": 0},
    )

    with pytest.raises(ValueError, match="not an installed desktop application"):
        packagekit.remove_application({"package": "demo"})


def test_install_uses_one_exact_packagekit_argv(monkeypatch) -> None:
    calls: list[list[str]] = []
    installed = iter(({}, {"demo": {"state": "installed"}}))
    monkeypatch.setattr(packagekit, "_installed_packages", lambda: next(installed))

    def fake_run(command, *, timeout=30):
        del timeout
        calls.append(command)
        if "resolve" in command:
            return result(command, [{"name": "demo", "state": "available"}])
        return result(command, [{"status": "finished"}])

    monkeypatch.setattr(packagekit, "_run", fake_run)

    payload = packagekit.install_package({"package": "demo"})

    assert calls == [
        ["pkgcli", "--json", "resolve", "demo"],
        ["pkgcli", "--json", "--yes", "install", "demo"],
    ]
    assert payload["installed"] is True

"""Thin PackageKit boundary for the native Applications pane."""

from __future__ import annotations

import configparser
import json
import os
import re
import shutil
import subprocess
import threading
from pathlib import Path


DESKTOP_ROOTS = (
    Path("/usr/share/applications"),
    Path("/usr/local/share/applications"),
    Path.home() / ".local/share/applications",
)
PACKAGE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9@._+-]{0,127}$")
OWNER_LINE = re.compile(r"^(.*?) is owned by ([^ ]+) ([^ ]+)$")
_OPERATION_LOCK = threading.Lock()


def _run(command: list[str], *, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "LC_ALL": "C", "LANG": "C"}
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"software manager failed: {exc}") from exc


def _json_lines(output: str) -> list[dict]:
    rows: list[dict] = []
    for line in output.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _command_error(result: subprocess.CompletedProcess[str]) -> str:
    rows = _json_lines(result.stdout)
    for row in rows:
        if row.get("error"):
            return str(row["error"])[:500]
    return (result.stderr or result.stdout or "PackageKit request failed").strip()[:500]


def backend_status() -> dict:
    executable = shutil.which("pkgcli")
    if not executable:
        return {
            "available": False,
            "name": "PackageKit",
            "backend": "",
            "message": "PackageKit is not installed.",
        }
    result = _run([executable, "--json", "backend"])
    rows = _json_lines(result.stdout)
    row = rows[0] if rows else {}
    backend = row.get("backend") if isinstance(row.get("backend"), dict) else {}
    roles = {item for item in str(row.get("roles", "")).split(";") if item}
    available = result.returncode == 0 and {
        "install-packages",
        "remove-packages",
    } <= roles
    return {
        "available": available,
        "name": "PackageKit",
        "backend": str(backend.get("name", "")),
        "message": "CachyOS software management is ready."
        if available else _command_error(result),
    }


def _installed_packages() -> dict[str, dict]:
    executable = shutil.which("pkgcli")
    if not executable:
        return {}
    result = _run([executable, "--json", "--filter", "installed", "list"])
    if result.returncode != 0:
        return {}
    return {
        str(row["name"]): row
        for row in _json_lines(result.stdout)
        if row.get("name") and row.get("state") == "installed"
    }


def _desktop_files() -> list[Path]:
    # Later XDG roots replace an identically named system entry.
    by_id: dict[str, Path] = {}
    for root in DESKTOP_ROOTS:
        if root.is_dir():
            for path in sorted(root.glob("*.desktop")):
                by_id[path.name] = path
    return list(by_id.values())


def _package_owners(paths: list[Path]) -> dict[str, tuple[str, str]]:
    system_paths = [path for path in paths if path.is_relative_to("/usr")]
    if not system_paths:
        return {}
    result = _run(["pacman", "-Qo", *(str(path) for path in system_paths)])
    owners: dict[str, tuple[str, str]] = {}
    for line in result.stdout.splitlines():
        match = OWNER_LINE.match(line.strip())
        if match:
            owners[match.group(1)] = (match.group(2), match.group(3))
    return owners


def _desktop_entry(path: Path) -> dict | None:
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    try:
        parser.read(path, encoding="utf-8")
        entry = parser["Desktop Entry"]
    except (OSError, configparser.Error, KeyError):
        return None
    if entry.get("Type", "Application") != "Application":
        return None
    if entry.getboolean("Hidden", fallback=False) or entry.getboolean(
        "NoDisplay", fallback=False
    ):
        return None
    label = entry.get("Name", "").strip()
    if not label:
        return None
    return {
        "desktop_id": path.name,
        "label": label[:160],
        "description": entry.get("Comment", "").strip()[:300],
        "icon": entry.get("Icon", "application-x-executable").strip()
        or "application-x-executable",
    }


def installed_applications() -> dict:
    backend = backend_status()
    packages = _installed_packages()
    paths = _desktop_files()
    owners = _package_owners(paths)
    applications = []
    for path in paths:
        entry = _desktop_entry(path)
        if not entry:
            continue
        owner = owners.get(str(path))
        package = owner[0] if owner else ""
        package_row = packages.get(package, {})
        applications.append(
            {
                "id": f"native:{package or path.name}:{path.name}",
                **entry,
                "package": package,
                "version": str(package_row.get("version", owner[1] if owner else "")),
                "repository": str(package_row.get("repo", "local")),
                "backend": "package",
                "installed": True,
                "manageable": bool(package and package in packages),
            }
        )
    applications.sort(key=lambda row: (row["label"].casefold(), row["desktop_id"]))
    return {
        "backend": backend,
        "applications": applications,
        "count": len(applications),
    }


def search_packages(query: str) -> dict:
    query = str(query).strip()
    if len(query) < 2:
        raise ValueError("Enter at least two characters to find software.")
    if len(query) > 80:
        raise ValueError("Software search is limited to 80 characters.")
    status = backend_status()
    if not status["available"]:
        return {"backend": status, "results": [], "count": 0, "query": query}

    result = _run(["pkgcli", "--json", "search", "details", query], timeout=45)
    if result.returncode != 0:
        raise RuntimeError(_command_error(result))
    installed = _installed_packages()
    selected: dict[str, dict] = {}
    for row in _json_lines(result.stdout):
        name = str(row.get("name", ""))
        if not PACKAGE_NAME.fullmatch(name):
            continue
        previous = selected.get(name)
        if previous is None or (
            previous.get("state") != "installed" and row.get("state") == "installed"
        ):
            selected[name] = row
        if len(selected) >= 60:
            break

    names = list(selected)[:40]
    details: dict[str, dict] = {}
    if names:
        shown = _run(["pkgcli", "--json", "show", *names], timeout=45)
        details = {
            str(row["name"]): row
            for row in _json_lines(shown.stdout)
            if row.get("name")
        }

    rows = []
    for name in names:
        package = installed.get(name) or selected[name]
        detail = details.get(name, {})
        rows.append(
            {
                "id": f"package:{name}",
                "label": name,
                "package": name,
                "description": str(
                    detail.get("description") or detail.get("summary") or ""
                )[:300],
                "icon": "system-software-install",
                "version": str(package.get("version", "")),
                "repository": str(package.get("repo", "")),
                "backend": "package",
                "installed": name in installed,
                "manageable": True,
            }
        )
    return {"backend": status, "results": rows, "count": len(rows), "query": query}


def _validated_package(value: object) -> str:
    package = str(value or "").strip()
    if not PACKAGE_NAME.fullmatch(package):
        raise ValueError("A valid exact package name is required.")
    return package


def _run_operation(command: list[str], package: str, action: str) -> dict:
    with _OPERATION_LOCK:
        result = _run(command, timeout=1800)
    if result.returncode != 0:
        raise RuntimeError(_command_error(result))
    installed = package in _installed_packages()
    expected = action == "install"
    if installed != expected:
        raise RuntimeError(f"PackageKit did not verify {action} for {package}.")
    return {
        "package": package,
        "action": action,
        "installed": installed,
        "message": f"{package} was {'installed' if installed else 'removed'}.",
    }


def install_package(payload: dict) -> dict:
    package = _validated_package(payload.get("package"))
    resolved = _run(["pkgcli", "--json", "resolve", package])
    candidates = [
        row for row in _json_lines(resolved.stdout) if row.get("name") == package
    ]
    if not candidates:
        raise ValueError(f"PackageKit could not resolve {package}.")
    if package in _installed_packages():
        return {
            "package": package,
            "action": "install",
            "installed": True,
            "message": f"{package} is already installed.",
        }
    return _run_operation(
        ["pkgcli", "--json", "--yes", "install", package], package, "install"
    )


def remove_application(payload: dict) -> dict:
    package = _validated_package(payload.get("package"))
    removable = {
        row["package"]
        for row in installed_applications()["applications"]
        if row["manageable"]
    }
    if package not in removable:
        raise ValueError(f"{package} is not an installed desktop application.")
    return _run_operation(
        [
            "pkgcli",
            "--json",
            "--yes",
            "remove",
            "--no-autoremove",
            package,
        ],
        package,
        "remove",
    )

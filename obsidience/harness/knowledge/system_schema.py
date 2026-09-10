"""One bounded projection of physical System descriptors and their hierarchy.

Descriptor data describes registered collectors; it never imports or executes
them. Source presentation and deterministic Knowledge publication share this
catalog instead of defining parallel folder and Article maps.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..config import CONFIG

MAX_SYSTEM_ENTRIES = 256
MAX_DESCRIPTOR_BYTES = 64_000
MAX_CATALOG_BYTES = 1_000_000
MAX_SYSTEM_DEPTH = 8
ROOT_REF = "ADMECH Workstation/ADMECH Workstation"


def _safe(path: Path) -> None:
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError("System descriptors cannot follow symlinks")


def _part(value: str) -> str:
    if len(value) > 100 or re.fullmatch(r"[a-z0-9][a-z0-9-]*", value) is None:
        raise ValueError("System path cannot form an exact Article reference")
    return value.replace("-", " ").title()


def _invalid_number(value: str) -> None:
    raise ValueError("System descriptors require finite JSON numbers")


def system_schema() -> list[dict]:
    """Return the real root, Hardware/Applications folders, and descriptors."""
    root = CONFIG.system_dir
    _safe(root)
    if not root.is_dir():
        raise ValueError("System descriptor directory is unavailable")
    directories = {root}
    paths = [root / "system.json"]
    count = 3

    def walk(directory: Path, depth: int) -> None:
        nonlocal count
        _safe(directory)
        if depth > MAX_SYSTEM_DEPTH:
            raise ValueError("System descriptor hierarchy exceeds its depth bound")
        # iterdir preserves access errors; glob could silently omit a subtree.
        for path in directory.iterdir():
            count += 1
            if count > MAX_SYSTEM_ENTRIES:
                raise ValueError("System descriptor inventory exceeds its entry bound")
            _safe(path)
            _part(path.stem if path.is_file() else path.name)
            if path.is_dir():
                directories.add(path)
                walk(path, depth + 1)
            elif path.suffix == ".json":
                paths.append(path)

    for name in ("hardware", "applications"):
        directory = root / name
        if not directory.is_dir():
            raise ValueError("System Hardware and Applications directories are required")
        directories.add(directory)
        walk(directory, 1)

    descriptors = {}
    total = 0
    for path in sorted(paths):
        _safe(path)
        if not path.is_file():
            raise ValueError("System descriptor must be a regular JSON file")
        with path.open("rb") as stream:
            material = stream.read(MAX_DESCRIPTOR_BYTES + 1)
        total += len(material)
        if len(material) > MAX_DESCRIPTOR_BYTES or total > MAX_CATALOG_BYTES:
            raise ValueError("System descriptor content exceeds its byte bound")
        descriptor = json.loads(material, parse_constant=_invalid_number)
        if (not isinstance(descriptor, dict) or descriptor.get("schema") != "obsidience.system-node.v1"
                or descriptor.get("read_only") is not True
                or any(not isinstance(descriptor.get(field), str) or not descriptor[field].strip()
                       or len(descriptor[field]) > 200 or any(ord(char) < 32 for char in descriptor[field])
                       for field in ("id", "label", "category"))
                or any(field in descriptor and (not isinstance(descriptor[field], str)
                       or not descriptor[field].strip() or len(descriptor[field]) > 200
                       or any(ord(char) < 32 for char in descriptor[field]))
                       for field in ("collector", "selector"))):
            raise ValueError("Invalid read-only System descriptor")
        descriptors[path] = descriptor

    def directory_ref(path: Path) -> str:
        if path == root:
            return ROOT_REF
        parts = [_part(part) for part in path.relative_to(root).parts]
        return "/".join(("ADMECH Workstation", *parts, parts[-1]))

    rows = []
    absorbed = set()
    for directory in sorted(directories, key=lambda path: (len(path.parts), path.as_posix())):
        descriptor_path = root / "system.json" if directory == root else directory / "application.json"
        if directory != root and not directory.is_relative_to(root / "applications"):
            descriptor_path = None
        descriptor = descriptors.get(descriptor_path)
        if descriptor is not None:
            absorbed.add(descriptor_path)
        rows.append({"key": "system" if directory == root else directory.relative_to(root).as_posix(),
            "title": "ADMECH Workstation" if directory == root else descriptor["label"] if descriptor else _part(directory.name),
            "ref": directory_ref(directory),
            "parent_ref": None if directory == root else directory_ref(directory.parent),
            "path": directory.relative_to(CONFIG.project_root).as_posix(),
            "descriptor_path": descriptor_path.relative_to(CONFIG.project_root).as_posix() if descriptor else None,
            "descriptor": descriptor})
    for path, descriptor in sorted(descriptors.items()):
        if path in absorbed:
            continue
        parent_ref = directory_ref(path.parent)
        rows.append({"key": path.relative_to(root).with_suffix("").as_posix(), "title": descriptor["label"],
            "ref": parent_ref.rsplit("/", 1)[0] + "/" + _part(path.stem), "parent_ref": parent_ref,
            "path": path.relative_to(CONFIG.project_root).as_posix(),
            "descriptor_path": path.relative_to(CONFIG.project_root).as_posix(), "descriptor": descriptor})
    if len({row["ref"].casefold() for row in rows}) != len(rows):
        raise ValueError("System descriptors map to ambiguous Article references")
    if any(len("schema." + row["key"]) > 200 for row in rows):
        raise ValueError("System descriptor path exceeds its evidence identity bound")
    return rows


def system_source_metadata(rows: list[dict] | None = None) -> dict[str, dict]:
    """Exact descriptor display labels and physical containing breadcrumbs."""
    catalog = system_schema() if rows is None else rows
    folders = {row["path"]: row for row in catalog if row["descriptor_path"] != row["path"]}
    result = {}
    for row in catalog:
        path = row["descriptor_path"]
        if path is None:
            continue
        breadcrumbs = [{"path": key, "title": "System" if value["key"] == "system" else value["title"]}
            for key, value in folders.items() if Path(path).is_relative_to(key)]
        breadcrumbs.sort(key=lambda value: (len(Path(value["path"]).parts), value["path"]))
        result[path] = {"system_label": row["title"], "system_breadcrumbs": breadcrumbs}
    return result

"""Physical contract for the Harness module and its direct subsystems."""

from __future__ import annotations

import importlib
import tomllib
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
PRODUCT_ROOT = PROJECT_ROOT / "obsidience"
HARNESS_ROOT = PRODUCT_ROOT / "harness"


def test_harness_manifest_names_the_real_module() -> None:
    manifest = tomllib.loads((HARNESS_ROOT / "module.toml").read_text(encoding="utf-8"))
    assert manifest == {
        "schema": "obsidience.module.v1",
        "id": "harness",
        "name": "Harness",
        "summary": (
            "Activates and executes Tasks using the graph, local models, "
            "capabilities, and system services."
        ),
        "package": "obsidience.harness",
        "entrypoints": [
            "obsidience.harness.__main__",
            "obsidience.harness.interfaces.api.app",
        ],
        "source_roots": ["obsidience/harness"],
        "projections": ["obsidience/state/system"],
    }
    assert importlib.import_module(manifest["package"])
    for entrypoint in manifest["entrypoints"]:
        assert importlib.util.find_spec(entrypoint) is not None


def test_first_party_tree_has_no_modules_directory() -> None:
    offenders = [
        path.relative_to(PROJECT_ROOT).as_posix()
        for path in PRODUCT_ROOT.rglob("modules")
        if path.is_dir() and "node_modules" not in path.parts
    ]
    assert offenders == []


def test_old_python_and_source_roots_are_absent() -> None:
    forbidden = (
        "obsidience.modules",
        "obsidience.capabilities",
        "obsidience.interfaces",
        "harness/obsidience",
    )
    offenders: list[str] = []
    for root in (HARNESS_ROOT, PRODUCT_ROOT / "tests"):
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in {".py", ".toml"}:
                continue
            if path == Path(__file__):
                continue
            text = path.read_text(encoding="utf-8")
            if any(value in text for value in forbidden):
                offenders.append(path.relative_to(PROJECT_ROOT).as_posix())
    assert offenders == []

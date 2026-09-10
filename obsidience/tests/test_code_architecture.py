"""Executable checks for Obsidience's code-side ontology."""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

from obsidience.harness.capabilities.registry import (
    ADAPTERS,
    REGISTRY,
    contract_error,
    resolve,
    source,
)
from obsidience.harness.knowledge.vault import iter_notes, resolver
from obsidience.harness.web.runtime import WEB_WORKER_MODULE


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = PROJECT_ROOT / "obsidience" / "harness"


def test_package_tree_exposes_the_runtime_shape() -> None:
    assert {
        "capabilities",
        "computer",
        "connections",
        "conversation",
        "execution",
        "host",
        "interfaces",
        "knowledge",
        "models",
        "realtime",
        "web",
    } <= {
        path.name for path in PACKAGE_ROOT.iterdir() if path.is_dir()
    }
    assert {path.name for path in PACKAGE_ROOT.glob("*.py")} == {
        "__init__.py", "__main__.py", "config.py",
    }
    assert (PACKAGE_ROOT / "module.toml").is_file()
    assert not any(path.name == "modules" for path in PACKAGE_ROOT.rglob("*"))
    assert not any(
        (PACKAGE_ROOT / name).exists() for name in ("common", "core", "utils")
    )


def test_packages_are_explicit_and_initializers_are_side_effect_free() -> None:
    for directory in (
        path
        for path in PACKAGE_ROOT.rglob("*")
        if path.is_dir()
        and "__pycache__" not in path.parts
        and any(child.suffix == ".py" for child in path.iterdir() if child.is_file())
    ):
        initializer = directory / "__init__.py"
        assert initializer.is_file(), f"Python package lacks __init__.py: {directory}"
        body = ast.parse(initializer.read_text(encoding="utf-8")).body
        executable = [
            node
            for node in body
            if not (
                isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            )
        ]
        assert not executable, f"Package initializer has behavior: {initializer}"


def test_internal_layers_do_not_import_the_interface_layer() -> None:
    for root in (
        path for path in PACKAGE_ROOT.iterdir()
        if path.is_dir() and path.name != "interfaces"
    ):
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imported = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.append(node.module)
            assert not any(
                name == "obsidience.harness.interfaces"
                or name.startswith("obsidience.harness.interfaces.")
                for name in imported
            ), f"Internal code imports an interface: {path}"


def test_leaf_tool_skill_capability_contract_is_exactly_one_to_one() -> None:
    notes = iter_notes()
    res = resolver()
    leaf_tools = [note for note in notes if note.kind == "tool" and not note.children]
    leaf_skills = [note for note in notes if note.kind == "skill" and not note.children]

    assert Counter(tool.title for tool in leaf_tools) == Counter(REGISTRY)
    pairings: Counter[str] = Counter()
    for skill in leaf_skills:
        assert not skill.meta.get("tools"), skill.ref
        tool = res.resolve(str(skill.meta.get("tool", "")))
        assert tool is not None and tool.kind == "tool" and not tool.children, skill.ref
        pairings[tool.ref] += 1

    for tool in leaf_tools:
        assert "sources" not in tool.meta, tool.ref
        assert contract_error(
            tool.title,
            tool.meta.get("binding"),
            tool.meta.get("source"),
        ) is None, tool.ref
        assert pairings[tool.ref] == 1, tool.ref
        assert (PROJECT_ROOT / source(tool.title)).is_file(), tool.ref
        expected_module = (
            source(tool.title)
            .removesuffix(".py")
            .replace("/", ".")
        )
        assert ADAPTERS[tool.title] == expected_module, tool.ref
        assert callable(resolve(tool.title)), tool.ref


def test_private_worker_entrypoints_follow_the_module_tree() -> None:
    assert WEB_WORKER_MODULE == "obsidience.harness.web.worker"


def test_system_owns_hardware_inventory_and_telemetry() -> None:
    model_tree = ast.parse(
        (PACKAGE_ROOT / "models" / "runtime.py").read_text(
            encoding="utf-8"
        )
    )
    model_functions = {
        node.name for node in model_tree.body if isinstance(node, ast.FunctionDef)
    }
    assert not {
        "gpu_snapshot",
        "hardware_sensor_snapshot",
        "_cpu_sensor_snapshot",
        "_igpu_sensor_snapshot",
    } & model_functions

    inventory = PACKAGE_ROOT / "host" / "inventory.py"
    inventory_functions = {
        node.name
        for node in ast.parse(inventory.read_text(encoding="utf-8")).body
        if isinstance(node, ast.FunctionDef)
    }
    assert {
        "application_snapshot", "gpu_snapshot", "hardware_sensor_snapshot",
        "network_snapshot", "storage_snapshot", "system_snapshot",
    } <= inventory_functions

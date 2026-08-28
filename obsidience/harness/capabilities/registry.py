"""Static bridge from accepted Tool Articles to executable Capabilities.

Tool metadata is descriptive.  It must exactly match this registry, but it can
never choose an import path or executable at runtime.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
from importlib import import_module
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Any

CAPABILITY_PREFIX = "capability:"
CAPABILITY_SOURCE_ROOT = PurePosixPath("obsidience/harness/capabilities")
ALWAYS_ALLOWED = ("task.complete",)
MODEL_RESOURCE_TOOLS = frozenset({"model.configure", "model.benchmark"})

_CAPABILITY_NAMES = (
    "application.launch",
    "computer.act",
    "computer.observe",
    "harness.status",
    "model.benchmark",
    "model.configure",
    "model.inspect",
    "model.source",
    "observations.temporary.append",
    "observations.temporary.archive",
    "source.handoff",
    "source.ingest",
    "source.read",
    "task.complete",
    "task.create",
    "vault.list",
    "vault.maintenance",
    "vault.propose",
    "vault.read",
    "vault.search",
    "vault.validate",
    "web.fetch",
    "web.search",
)
ADAPTERS = MappingProxyType({
    name: f"obsidience.harness.capabilities.{name}" for name in _CAPABILITY_NAMES
})
REGISTRY = tuple(ADAPTERS)
SOURCES = MappingProxyType({
    name: str(CAPABILITY_SOURCE_ROOT.joinpath(*name.split("."))).replace("\\", "/")
    + ".py"
    for name in ADAPTERS
})


def binding(name: str) -> str:
    """Return the one canonical Article binding for a registered Capability."""
    if name not in ADAPTERS:
        raise KeyError(f"Unknown tool: {name}")
    return CAPABILITY_PREFIX + name


def source(name: str) -> str:
    """Return the one canonical Source projection for a registered Capability."""
    try:
        return SOURCES[name]
    except KeyError as exc:
        raise KeyError(f"Unknown tool: {name}") from exc


def contract_error(title: object, article_binding: object, article_source: object) -> str | None:
    """Describe an exact Tool Article contract mismatch, or return ``None``."""
    name = str(title or "").strip()
    if name not in ADAPTERS:
        return f"no registered Capability exists for Tool title {name or '(missing)'}"
    expected_binding = binding(name)
    if article_binding != expected_binding:
        return (
            f"binding must be {expected_binding}, got "
            f"{str(article_binding or '(missing)').strip()}"
        )
    expected_source = source(name)
    if not isinstance(article_source, str) or article_source.strip() != expected_source:
        return (
            f"source must be the singular path {expected_source}, got "
            f"{article_source if article_source else '(missing)'}"
        )
    try:
        resolve(name)
    except (ImportError, AttributeError, TypeError) as exc:
        return f"Capability entrypoint is unavailable: {exc}"
    return None


@lru_cache(maxsize=None)
def resolve(name: str) -> Callable[[dict, dict], Any]:
    """Resolve one explicitly registered adapter only when it is invoked."""
    module_path = ADAPTERS.get(name)
    if module_path is None:
        raise KeyError(f"Unknown tool: {name}")
    adapter = getattr(import_module(module_path), "execute", None)
    if not callable(adapter):
        raise TypeError(f"Capability adapter has no execute function: {module_path}")
    return adapter


def execute(name: str, args: dict | None, context: dict | None) -> Any:
    """Invoke one registered Capability adapter."""
    return resolve(name)(args or {}, context or {})

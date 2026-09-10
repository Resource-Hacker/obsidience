"""Static bridge from accepted Tool Articles to executable Capabilities.

Tool metadata is descriptive.  It must exactly match this registry, but it can
never choose an import path or executable at runtime.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from functools import lru_cache
from importlib import import_module
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Any

CAPABILITY_PREFIX = "capability:"
CAPABILITY_SOURCE_ROOT = PurePosixPath("obsidience/harness/capabilities")
ALWAYS_ALLOWED = ("task.complete",)
MODEL_RESOURCE_TOOLS = frozenset({"model.configure", "model.benchmark", "harness.evaluate"})
# Reviewed implementation policy; Article prose cannot declare an effect safe.
READ_ONLY_CAPABILITIES = frozenset({
    "source.read", "vault.read", "vault.search", "vault.validate", "harness.status",
})

_CAPABILITY_NAMES = (
    "application.launch",
    "computer.act",
    "computer.observe",
    "harness.evaluate",
    "harness.repair",
    "harness.status",
    "model.benchmark",
    "model.configure",
    "model.inspect",
    "model.source",
    "observations.temporary.append",
    "observations.temporary.archive",
    "review.inspect",
    "source.handoff",
    "source.ingest",
    "source.read",
    "task.complete",
    "task.create",
    "task.inspect",
    "vault.list",
    "vault.maintenance",
    "vault.propose",
    "vault.read",
    "vault.search",
    "vault.validate",
    "web.fetch",
    "web.feed",
    "web.search",
    "window.activate",
    "window.place",
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
    """Invoke a synchronous adapter; async operations require joined dispatch."""
    adapter = resolve(name)
    if inspect.iscoroutinefunction(adapter):
        raise TypeError(f"Capability {name} requires execute_async")
    return adapter(args or {}, context if context is not None else {})


async def execute_async(name: str, args: dict | None, context: dict | None) -> Any:
    """Await native async operations without a detached HTTP or worker request.

    Synchronous adapters retain their existing worker and cooperative cancellation
    event. Authorization remains the caller's accepted Task/Tool contract check.
    """
    adapter = resolve(name)
    context = context if context is not None else {}
    cancel = context.get("_capability_cancel_event")
    if cancel is not None and cancel.is_set():
        raise asyncio.CancelledError
    try:
        if inspect.iscoroutinefunction(adapter):
            return await adapter(args or {}, context)
        return await asyncio.to_thread(execute, name, args, context)
    except asyncio.CancelledError:
        if cancel is not None:
            cancel.set()
        raise

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


def _schema_object(properties: dict, required: tuple[str, ...] = ()) -> dict:
    return {"type": "object", "properties": properties,
            "required": list(required), "additionalProperties": False}


def _schema_text(maximum: int = 512, *, empty: bool = False) -> dict:
    return {"type": "string", "minLength": 0 if empty else 1, "maxLength": maximum}


def _schema_array(item: dict, maximum: int, minimum: int = 0) -> dict:
    return {"type": "array", "items": item, "minItems": minimum, "maxItems": maximum}


@lru_cache(maxsize=1)
def _argument_schemas() -> dict[str, dict]:
    """The registry's decoder-facing interface; adapters still validate effects."""
    from ..computer.applications import APPLICATIONS
    from ..host.scene import SURFACE_IDS
    text = _schema_text
    obj = _schema_object
    array = _schema_array
    integer = {"type": "integer", "minimum": 0}
    surface = {"type": "string", "enum": list(SURFACE_IDS)}
    target = {"anyOf": [obj({"kind": {"const": kind}, "name": text(256 if kind == "application" else 48),
                             "surface": surface}, ("kind", "name")) for kind in ("application", "pane")]}
    observe_target = {"anyOf": [*target["anyOf"], obj({"kind": {"const": "focused"}, "surface": surface}, ("kind",))]}
    tile = obj({key: integer for key in ("left", "top", "right", "bottom")}, ("left", "top", "right", "bottom"))
    bounded_scope = obj({"kind": {"enum": ["knowledge", "task", "runbook", "tool", "skill", "agent"]},
        "current_only": {"type": "boolean"}, "exclude_subtrees": array(text(300),10)})
    schemas = {
        "application.launch": obj({"application": {"type":"string","enum":sorted(APPLICATIONS)}},("application",)),
        "computer.observe": obj({"target":observe_target,"query":text(500)},("target","query")),
        "computer.act": obj({"application":text(256),"action":{"const":"click"},"target":text(128),
            "point":obj({axis:{"type":"integer","minimum":0,"maximum":999} for axis in ("x","y")},("x","y")),
            "postcondition":text(500)},("application","target","point")),
        "window.activate": obj({"target":target},("target",)),
        "window.place": obj({"target":target,"destination":obj({"surface":surface,"tile":tile},("surface",))},("target","destination")),
        "vault.search": {"anyOf":[obj({"query":text(300),"scope":bounded_scope},("query",)),
                                  obj({"queries":array(text(300),10,1),"scope":bounded_scope},("queries",))]},
        "vault.read": {"anyOf":[obj({key:value,"offset":integer,"expected_sha256":{"type":"string","pattern":"^[0-9a-f]{64}$"}},(key,))
            for key,value in (("ref",text(500)),("refs",array(text(500),10,1)))]},
        "vault.list":obj({"folder":text(512,empty=True),"offset":integer}),
        "vault.propose":obj({"target":text(512),"action":{"enum":["create","update","archive"]},
            "title":text(300),"body":text(96000,empty=True),"reason":text(400,empty=True),
            "source":text(512),"metadata":{"type":"object","additionalProperties":True}},("target",)),
        "vault.maintenance":obj({}), "vault.validate":obj({}), "harness.status":obj({}),
        "harness.repair":obj({"task":text(512),"run_id":text(128)},("task","run_id")),
        "harness.evaluate":obj({"proposal":text(512)},("proposal",)),
        "task.inspect":obj({"task":text(512),"run_id":text(128)},("task",)),
        "review.inspect":obj({"task":text(512),"proposal":text(512)}),
        "task.create":obj({"task":text(512),"params":{"type":"object","additionalProperties":True,"maxProperties":8},
            "wait_for_result":{"type":"boolean"},"await_publication":{"type":"boolean"}},("task",)),
        "task.complete":obj({"status":{"enum":["completed","failed","review"]},"summary":text(2000,empty=True),
            "reclassify":{"type":"boolean"},
            "outcome":text(100,empty=True),"evidence":array(text(500),8),
            "verification":obj({"status":{"enum":["established","not_established"]},"observation":text(1000)},("status","observation"))},("status","summary")),
        "observations.temporary.append":obj({"text":text(2000),"related_refs":array(text(512),3)},("text",)),
        "observations.temporary.archive":obj({}),
        "source.read":{"anyOf":[obj({key:value,"offset":integer,"limit":{"type":"integer","minimum":1,"maximum":12000}},(key,))
            for key,value in (("source",text(128)),("sources",array(text(128),10,1)))]},
        "source.ingest":obj({"source_type":text(32),"source_ref":text(2048,empty=True),"media_type":text(128),
            "captured_at":text(80),"content":text(500000)},("content",)),
        "source.handoff":obj({"title":text(300),"content":text(500000)},("title","content")),
        "web.search":obj({"query":text(2000),"limit":{"type":"integer","minimum":1,"maximum":20}},("query",)),
        "web.fetch":{"anyOf":[obj({"url":text(8192)},("url",)),obj({"urls":array(text(8192),10,1)},("urls",))]},
        "web.feed":obj({"url":text(8192),"limit":{"type":"integer","minimum":1,"maximum":100}},("url",)),
        "model.inspect":obj({"model_id":text(200)},("model_id",)),
        "model.source":obj({"model_id":text(200)},("model_id",)),
        "model.benchmark":obj({"model_id":text(200),"devices":array(text(100),8,1)},("model_id",)),
        "model.configure":obj({"model_id":text(200),"allowed_devices":array(text(100),8,1),
            "context_tokens":{"type":"integer","minimum":1},"max_output_tokens":{"type":"integer","minimum":1},
            "gpu_memory_utilization":{"type":"number","exclusiveMinimum":0,"maximum":1},
            "max_num_seqs":{"type":"integer","minimum":1}},("model_id",)),
    }
    if set(schemas) != set(REGISTRY):
        raise ValueError("Every registered Tool requires an argument schema")
    return schemas


def argument_schema(name: str) -> dict:
    from copy import deepcopy
    return deepcopy(_argument_schemas()[name])


def action_schema(allowed: list[str]) -> dict:
    """Constrain each permitted Tool together with its own argument shape."""
    if not allowed or set(allowed) - set(REGISTRY):
        raise ValueError("Action schema requires exact registered capabilities")
    return {"anyOf": [_schema_object({"tool":{"type":"string","enum":[name]},
                                     "args":argument_schema(name)},("tool","args"))
                      for name in sorted(set(allowed))]}


def decoder_action_schema(allowed: list[str]) -> dict:
    """Keep exact argument structure without exponential grammar repetitions.

    llama.cpp expands nested finite string/array bounds into grammar rules.
    Canonical contracts and adapters retain those bounds; the decoding grammar
    enforces types, required keys, enums and closed property sets. The request's
    output-token limit bounds generation before adapter validation.
    """
    def structural(value):
        if isinstance(value, dict):
            return {key: structural(item) for key, item in value.items()
                    if key not in {"maxLength", "maxItems", "maxProperties"}}
        if isinstance(value, list):
            return [structural(item) for item in value]
        return value
    return structural(action_schema(allowed))

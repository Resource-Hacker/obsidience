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
MODEL_RESOURCE_TOOLS = frozenset({"model.configure", "model.benchmark", "harness.evaluate", "harness.optimize"})
# Reviewed implementation policy; Article prose cannot declare an effect safe.
READ_ONLY_CAPABILITIES = frozenset({
    "source.read", "vault.read", "vault.search", "vault.list", "vault.validate", "harness.status",
    "task.inspect", "review.inspect", "vault.maintenance", "observations.recall",
})

_CAPABILITY_NAMES = (
    "application.launch",
    "camera.observe",
    "lights.set",
    "tv.control",
    "media.pause",
    "computer.act",
    "computer.observe",
    "harness.evaluate",
    "harness.optimize",
    "harness.repair",
    "harness.status",
    "model.benchmark",
    "model.configure",
    "model.inspect",
    "model.source",
    "observations.recall",
    "observations.retain",
    "review.inspect",
    "session.unlock",
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
    from ..host.scene import HANDLE_PATTERN, SURFACE_IDS
    text = _schema_text
    obj = _schema_object
    array = _schema_array
    integer = {"type": "integer", "minimum": 0}
    surface = {"type": "string", "enum": list(SURFACE_IDS)}
    handle = {"type": "string", "pattern": HANDLE_PATTERN,
              "description": "One window's handle, e.g. w3, from the current Scene or an ambiguity menu."}
    target = {"anyOf": [obj({"kind": {"const": kind}, "name": text(256 if kind == "application" else 48),
                             "surface": surface}, ("kind", "name")) for kind in ("application", "pane")]
              + [obj({"handle": handle}, ("handle",))]}
    observe_target = {"anyOf": [
        obj({"kind": {"const": "application"}, "name": text(256), "surface": surface,
             "title": text(200)}, ("kind", "name")),
        target["anyOf"][1], obj({"kind": {"enum": ["attention", "focused"]}, "surface": surface}, ("kind",)),
        obj({"handle": {**handle, "description": (
            "For what the owner is looking at now, omit target: it resolves as kind attention, the most "
            "recently focused application (focused does too while an Obsidience pane has focus). Otherwise "
            "use a handle, e.g. w3, from the current Scene or an ambiguity menu.")}}, ("handle",))]}
    tile = obj({key: integer for key in ("left", "top", "right", "bottom")}, ("left", "top", "right", "bottom"))
    bounded_scope = obj({"kind": {"enum": ["knowledge", "task", "runbook", "tool", "skill", "agent"]},
        "current_only": {"type": "boolean"}, "exclude_subtrees": array(text(300),10)})
    schemas = {
        "application.launch": obj({"application": {"type":"string","enum":sorted(APPLICATIONS)},
            "url":text(2000)},("application",)),
        "camera.observe": obj({"query":text(500), "wake":{"type":"boolean"}},("query",)),
        "media.pause": obj({"query":text(128, empty=True)}),
        "computer.observe": obj({"target":observe_target,"query":text(500)},("query",)),
        # The adapter requires application or handle and checks both against the observation.
        "computer.act": obj({"scope":{"enum":["input","state"]},"application":text(256),"handle":handle,
            "action":{"const":"click"},
            "target":{**text(128),"description":"Short clicked-control label, 1-128 characters, e.g. Play/Pause button. Do not copy the browser window title."},
            "point":obj({axis:{"type":"integer","minimum":0,"maximum":999} for axis in ("x","y")},("x","y")),
            "postcondition":text(500)},("scope","target","point")),
        "window.activate": obj({"target":target},("target",)),
        "window.place": obj({"target":target,"destination":obj({"surface":surface,"tile":tile},("surface",))},("target","destination")),
        "vault.search": {"anyOf":[obj({"query":text(300),"scope":bounded_scope},("query",)),
                                  obj({"queries":array(text(300),10,1),"scope":bounded_scope},("queries",))]},
        "vault.read": {"anyOf":[obj({key:value,"offset":integer,"expected_sha256":{"type":"string","pattern":"^[0-9a-f]{64}$"}},(key,))
            for key,value in (("ref",text(500)),("refs",array(text(500),10,1)))]},
        "vault.list":obj({"folder":text(512,empty=True),"offset":integer}),
        "vault.propose":{"anyOf":[
            obj({"target":text(512),"action":{"enum":["create","update"]},
                "title":text(300),"body":text(96000),"source":text(512),"reason":text(400,empty=True),
                "metadata":{"type":"object","additionalProperties":True}},("target","body")),
            obj({"target":text(512),"action":{"const":"archive"},"title":text(300),
                "body":text(96000,empty=True),"source":text(512),"reason":text(400,empty=True),
                "metadata":{"type":"object","additionalProperties":True}},("target","action")),
        ]},
        "vault.maintenance":obj({}), "vault.validate":obj({}), "harness.status":obj({}),
        "harness.repair":{"anyOf":[obj({"task":text(512),"run_id":text(128)},("task","run_id")),
                                    obj({"component":{"const":"hindsight"}},("component",))]},
        "harness.evaluate":obj({"proposal":text(512)},("proposal",)),
        "harness.optimize":obj({"case_id":text(64)},("case_id",)),
        "task.inspect":obj({"task":text(512),"run_id":text(128)},("task",)),
        "review.inspect":obj({"task":text(512),"proposal":text(512)}),
        "session.unlock":obj({}),
        "tv.control":{"anyOf":[obj({"action":{"enum":["on","off","observe"]}},("action",)),
            obj({"action":{"const":"launch"},"app":text(32)},("action","app")),
            obj({"action":{"const":"key"},"key":{"enum":["up","down","left","right","select","back","home","menu","play","pause","rewind","fast_forward","volume_up","volume_down","mute","enter","delete"]}},("action","key")),
            obj({"action":{"const":"keys"},"keys":{"type":"array","minItems":1,"maxItems":8,"items":{"enum":["up","down","left","right","select","back","home","menu","enter","delete"]}}},("action","keys")),
            obj({"action":{"const":"text"},"text":text(120)},("action","text")),
            obj({"action":{"const":"find"},"query":text(120),"app":text(32)},("action","query")),
            obj({"action":{"const":"open"},"id":text(8)},("action","id")),
            obj({"action":{"const":"open"},"url":text(300)},("action","url"))]},
        "lights.set":obj({"target":{"enum":["all", "window_lamp", "woven_pendant", "north_lamp",
            "tv_floor_lamp", "desk_lantern", "room_lantern"]},"state":{"enum":["on","off"]}},("target","state")),
        "task.create":obj({"task":text(512),"params":{"type":"object","additionalProperties":True,"maxProperties":8},
            "wait_for_result":{"type":"boolean"},"await_publication":{"type":"boolean"}},("task",)),
        "task.complete":obj({"status":{"enum":["completed","failed","review"],
                "description":"Defaults to completed. Use failed for a blocker or review for pending proposals."},"summary":text(2000,empty=True),
            "outcome":{"enum":["changed","no_change",""],
                "description":"Optional change classification; omit for ordinary answers. no_change requires completed status and explicit evidence."},
            "evidence":array(text(500),8),
            "verification":{**obj({"status":{"enum":["established","not_established"]},"observation":text(1000)},("status","observation")),
                "description":"Required to establish page or playback state after opening a URL, or application state after computer.act. Requires the current image and its visible evidence."}},("summary",)),
        "observations.retain":obj({"text":text(2000),"related_refs":array(text(512),3)},("text",)),
        "observations.recall":obj({"query":text(3000)},("query",)),
        "source.read":{"anyOf":[obj({key:value,"offset":integer,"limit":{"type":"integer","minimum":1,"maximum":12000}},(key,))
            for key,value in (("source",text(128)),("sources",array(text(128),10,1)))]},
        "source.ingest":obj({"source_type":text(32),"source_ref":text(2048,empty=True),"media_type":text(128),
            "captured_at":text(80),"content":text(500000)},("content",)),
        "source.handoff":obj({"title":text(300),"content":text(500000)},("title","content")),
        "web.search":obj({"query":text(2000),"limit":{"type":"integer","minimum":1,"maximum":20}},("query",)),
        "web.fetch":{"anyOf":[obj({"url":text(8192)},("url",)),obj({"urls":array(text(8192),10,1)},("urls",))]},
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
    schema = deepcopy(_argument_schemas()[name])
    if name == "computer.observe":
        from ..host.scene import SCENE

        # Copying a long Unicode title is unreliable. Constrain this optional
        # observation filter to exact public labels from the current Scene.
        # Native target resolution still rejects wrong-app and duplicate labels.
        scene = SCENE.activation_binding()
        fields = scene.get("fields", [])
        titles = set()
        if scene.get("available") is True and "kind" in fields and "title" in fields:
            kind_index, title_index = fields.index("kind"), fields.index("title")
            titles = {row[title_index] for rows in scene.get("surfaces", {}).values() for row in rows
                      if len(row) > max(kind_index, title_index) and row[kind_index] == "application"
                      and isinstance(row[title_index], str) and row[title_index]}
        properties = schema["properties"]["target"]["anyOf"][0]["properties"]
        if titles:
            properties["title"] = {"type": "string", "enum": sorted(titles)}
        else:
            properties.pop("title", None)
    return schema


def action_schema(allowed: list[str], *, completion_no_change: bool = False, completion_blocked: bool = False,
                  proposal_mode: str = "") -> dict:
    """Constrain Tool arguments and the active completion contract, not its evidence."""
    if not allowed or set(allowed) - set(REGISTRY):
        raise ValueError("Action schema requires exact registered capabilities")
    choices = []
    for name in sorted(set(allowed)):
        args = argument_schema(name)
        if name == "vault.propose" and proposal_mode == "link":
            args = args["anyOf"][0]
            args["properties"]["action"] = {"const": "update"}
            args["required"].append("action")
            for key in ("metadata", "source"):
                args["properties"].pop(key, None)
        elif name == "vault.propose" and proposal_mode == "ingest":
            # General Inbox ingestion authors Knowledge. Retirement belongs to
            # Archive; documentary metadata is compiled by the publication owner.
            args = args["anyOf"][0]
            args["required"].append("action")
            for key in ("metadata", "source"):
                args["properties"].pop(key, None)
        if name == "task.complete" and completion_blocked:
            args["properties"]["status"] = {"const": "failed"}
            args["required"] = list(dict.fromkeys([*args["required"], "status"]))
            args["properties"]["outcome"]["enum"] = ["changed", ""]
        elif name == "task.complete" and completion_no_change:
            from copy import deepcopy
            successful = deepcopy(args)
            successful["properties"]["status"] = {"const": "completed"}
            successful["properties"]["outcome"] = {"const": "no_change"}
            successful["properties"]["evidence"]["minItems"] = 1
            # llama.cpp emits required fields before optional fields. Both
            # branches must allow status first, or that prefix forces failure.
            successful["required"] = list(dict.fromkeys([*successful["required"], "status", "outcome", "evidence"]))
            args["properties"]["status"] = {"const": "failed"}
            # Without an explicit status this branch would bypass the successful
            # contract, then default to completed in the capability adapter.
            args["required"] = list(dict.fromkeys([*args["required"], "status"]))
            args["properties"]["outcome"]["enum"] = ["changed", ""]
            args = {"anyOf": [successful, args]}
        choices.append(_schema_object({"tool": {"type": "string", "enum": [name]},
                                       "args": args}, ("tool", "args")))
    return {"anyOf": choices}


def decoder_action_schema(allowed: list[str], *, completion_no_change: bool = False, completion_blocked: bool = False,
                          proposal_mode: str = "") -> dict:
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
    return structural(action_schema(allowed, completion_no_change=completion_no_change,
                                    completion_blocked=completion_blocked,
                                    proposal_mode=proposal_mode))

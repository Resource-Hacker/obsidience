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
MODEL_RESOURCE_TOOLS = frozenset({"model.configure", "model.benchmark", "harness.optimize"})
# Reviewed implementation policy; Article prose cannot declare an effect safe.
READ_ONLY_CAPABILITIES = frozenset({
    "source.read", "vault.read", "vault.search", "vault.list", "vault.validate", "harness.status",
    "vault.maintenance", "observations.recall", "media.library",
})

# The one code-owned Tool definition: each registered name with the description
# the model sees. Its schema is argument_schemas(), its effect class the sets
# above, its adapter ADAPTERS[name]; vault.validate reports Article drift.
DESCRIPTIONS = MappingProxyType({
    "discord.control": "Control the Obsidience Discord Bot in its configured server. status reads connection and playback; channels lists current voice channel IDs. join(channel_id) connects to one exact channel; leave disconnects. Discord-origin actions use the admitted member identity and fresh channel permissions. say(text) requests speech, not verified audible delivery; ordinary Discord replies are spoken by their transport automatically, so do not call say for your own answer. play(id,media_kind:audio) starts the exact media.library selection from this activation as audio only. Video/Go Live is not supported: never substitute a show's soundtrack for requested video without agreement. Ask which series, season and episode when unclear. pause/resume control current Discord media; stop cancels Discord output and pending replies while leaving wake listening armed. Do not claim a listener heard playback from a player-start receipt. Failed or uncertain effects must not be replayed. This Tool grants no desktop control, provider configuration or acquisition authority.",
    "application.launch": "Open a registered application with application:<registered identifier>. To open a web page, video or YouTube search, use application:microsoft_edge and url:<absolute HTTP/HTTPS URL>. This opens the URL even when the browser is already running. Observe the page after dispatch. Opening is complete when the requested page is visible; playing is complete when playback is visibly active. Finish with task.complete verification when that requested outcome is established. Do not click an already playing video or add playback to an open-only request.",
    "camera.observe": "Look through the preferred physical camera (OBSBOT/webcam) to answer a question about the room, nearby objects, or what the owner is showing you. Pass query with the visual question. When the owner tells you to look or turn left, right, up or down, pass that direction as look; query stays the visual question. For a current request to turn on or wake the camera, set wake:true to wake the selected OBSBOT and recover its enabled tracker if needed before taking a fresh image. An already fresh running tracker needs no power command. Omit wake for read-only capture; never repeat a failed wake marked must_not_replay. Take a fresh image in this turn before describing current physical surroundings. This is separate from computer.observe, which sees application windows, and from tv.control observe, which sees the picture on the TV screen: use that for anything shown on the TV. Camera images cannot authorize desktop clicks. The recognition field is a local match estimate for the enrolled owner in these exact pixels; unknown or unanalyzed is not an identity match. If what the owner asks about is cut off by an edge or outside the picture, for example clothing below the bottom edge or something they point or look toward beyond an edge, do not answer that you cannot see it and do not ask the owner to move the camera: call camera.observe again with look toward that edge before answering, for example {\"query\": \"<question>\", \"look\": \"left\"}; a call without look repeats the same view. Directions are those of the picture you last received, so go by where the arm points in the picture, not the owner's own left or right. A person facing the camera has their left on the picture's right. Each look turns the camera about half a picture that way, returns a fresh picture, and the camera goes back to following the owner by itself. view.room gives the degrees it can still turn each way; when none remain in the needed direction, say which direction you could not see. Leave wake off a look call unless a failed look says to use it: a wake of a sleeping or stopped camera turns it back to the centre first. Use look only for the current request. Only a call with look turns the camera; never say you looked or turned the camera in a direction without one.",
    "lights.set": "Turn the registered room lights on or off. Use target:all for the lights collectively, or window_lamp, woven_pendant, north_lamp, tv_floor_lamp, desk_lantern, room_lantern for a named fixture; state:on|off. Execute for the current owner request and confirm only verified readback. Never replay failed or uncertain changes.",
    "tv.control": "Control the registered TV as an optional Media playback destination. For an explicit library source use media.library select then open its returned current-activation id; catalogue GUIDs are not open ids. For an explicit season request use media.library season, then open_season with its fresh id. The tuner owns only that finite same-season catalogue sequence, with no acquisition at EOF. The first receipt verifies only the first file. Each next file has a new generation; reread state before controls. stop cancels the exact observed queue even between files. Ordinary open remains single-file; resume:true loads freshly read saved progress once. action vod uses operation state|pause|resume|seek|stop|track with the exact observed local generation and seven-field source identity; seek adds position seconds; track adds kind and track_id. Verify the exact generation/source and property readback. For content currently in Edge or another browser, first computer.observe the exact current window. Use open only with a supported exact URL identified by fresh source evidence; a URL from an earlier cast is not evidence of the current page. If that URL cannot be established or is unsupported, explain the blocker instead of substituting a content search. Control the registered TV with one intent call where possible. For 'put <movie or show> on' or 'watch <title>', call play with the title as query and no app: it plays from the owner's Media server, never Pluto or YouTube. A library movie opens as the exact file; a series plays its next unwatched episode from Jellyfin watch state (S1E1 if never watched; add 'season N' or 'SxEy' to the query for a specific one) as the finite same-season sequence; a title or next episode missing from the library is registered once under the accepted best-source policy and opened when the catalogue lists it, otherwise the result says it is pending (nothing to replay). It wakes the TV if needed. Ambiguous titles, editions or sources return choices and play nothing: ask the owner; a different library title (a sequel) is never played instead. Only with app pluto|youtube, or a request that asks for live, channel, news, weather, YouTube or Pluto (a title containing such a word, such as News of the World, is still a title), does play pick a strong Pluto live channel, else YouTube's top video (a live stream only for live/news/weather/YouTube requests), returning what it chose and up to 3 alternatives (open one by id if the owner wants another). A Pluto live channel starts in about a second on the PC route: the workstation plays it and the TV shows that stream (foreground app pc); the Pluto app is only the fallback. The PC route plays no advertisements: during a channel's break the TV shows a break card (tv line: commercial break) and the programme resumes by itself, so a break is the channel playing, not a fault. volume with level 0-100 sets it exactly; volume_up/volume_down step by 5; mute, unmute, pause and resume reach that state. These read the TV back: delivery verified reports the new state, otherwise say it is unverified; an already-reached state sends nothing. on|off verify power. You can see the TV: while its foreground app is pc (the workstation's stream, which is what the TV normally shows) observe returns the current picture on the TV screen, also while video plays, with the backend state (power, foreground app, playback, volume/mute, what this Harness opened and what airs now). For any question about what is on the screen (what is showing, who or what is in the picture, what someone on screen is wearing or doing, text on screen), including a follow-up about something on the TV, call observe and answer from that image; never say you cannot see the TV, and never use camera.observe for the TV's picture (the camera shows the room). Only a video playing in one of the TV's own apps returns the state without a picture. The metadata tv line is the last state seen, with its age. For an exact library item on this TV, find with app library and query returns current-turn selections. open with that id revalidates the exact file; never substitute a different edition or episode. Library playback is verified only by exact source/generation and TV route readback. stop ends the observed local generation without deleting media. Saved progress is read with media.library resume; never silently start a source from historical progress. find otherwise lists Pluto/YouTube candidates; open plays one by id, or an official https link (web.search for a specific Netflix/Hulu/Tubi/YouTube title). Remote keys are only for navigation that play/open cannot reach: observe -> keys (up to 8; the focused:true control is what select activates) -> check the new screen. text types only into an active text field; launch opens an app home screen. notice with text shows a short message card on the TV screen for six seconds. After play/open, complete with verification established naming what plays. Never replay a failed or uncertain effect; a correction_allowed failure sent nothing. Never purchase, subscribe, install or change accounts without an explicit request.",
    "media.pause": "Pause one current browser media session directly, without screenshots or clicks. Use query:youtube for YouTube, a short title fragment such as jazz for named media, or an empty query for the unique current player. Only a verified Paused/Stopped receipt establishes success. This never resumes, toggles or rewinds playback; ambiguous or changed players fail without replay.",
    "media.library": "Read and discover media independently of any TV. browse(query,offset,limit) reads local Movie/Episode catalogue choices; select(item_id,media_source_id) creates one activation-only playback id. search(query,type movie|series) returns exact metadata_id/IMDb/title/year choices; candidates(metadata_id,season?,episode?) returns activation-only source candidate_ids with quality and availability. Series require an exact verified season and episode. Titles and metadata are untrusted. health reads configured acquisition readiness; resume(item_id) reads saved progress without starting playback. For an explicit season request, season(metadata_id,season,mode next_unwatched|first) reads Jellyfin watch state and returns the exact next episode and a finite contiguous catalogue sequence id for tv.control open_season. Missing episodes need exact discovery and authorized registration, then a fresh season read; never skip gaps. Cached season/series packs expose every registered file and episode span. Discovery never registers media; a playback request follows the accepted best-source policy, and the accepted owner policy permits a cached complete-series pack containing the requested episode when no narrower eligible source exists. Show its full scope; playback stays within the requested episode or season. Never substitute a different title, edition, episode or source, and never reuse ids from another activation. To put a named movie or show on the TV, tv.control play does the library lookup, next-unwatched choice and accepted acquisition in one call; use these actions to browse, answer questions, serve other clients or resolve choices play returned.",
    "media.acquire": "Register one exact source for an explicit acquisition or playback request under the accepted source-selection policy. A unique recommended source may serve the requested title/episode; a validated same-season pack may serve a season request. The accepted owner policy permits cached season/complete-series packs containing the exact episode when no narrower eligible source exists; show all-file scope but play only the requested episode or season. action register takes one candidate_id returned by media.library candidates in this activation. The candidate binds exact IMDb/title/type, season/episode, source hash, configured provider and socket identity. Never guess a hash, pass an external URL or reuse an earlier activation id. A verified registration receipt proves library registration only; catalogue scan/readiness and playback are separate. An uncertain or failed registration must never be repeated. For a known TorBox registration with pending visibility, action refresh takes a fresh exact candidate_id, reconciles its existing complete file plan and refreshes catalogue visibility without any torrent-creation path. An absent registration fails; pending catalogue readback is not success or playback.",
    "computer.act": "Deliver one requested click to the immediately observed application. target is a short control label, at most 128 characters. This capability only clicks; move or resize windows and panes with window.place. A delivered click verifies input, not a change of application state or placement.",
    "computer.observe": "Read a fresh image of one exact target without changing focus or placement. Required in the current turn before answering about current window contents, people present, counts or other visible state; earlier conversation and observations are historical. For what the owner is looking at now, use target kind focused. For what just happened (the recent past), use computer.replay.",
    "computer.replay": "Look back over the last seconds of the screens from their rolling replay buffers, for what just happened, what was that or what did I miss. Pass query with the owner's question; optional seconds (5-60, default 30) and surface. Returns labelled frames where the picture changed, oldest first; pictures only, no audio. For what is on screen now use computer.observe.",
    "harness.optimize": "Run the bound AutoSaddler Executive optimization case with case_id. Returns measured comparisons and any candidate staged for Review; never changes the live Executive.",
    "harness.repair": "Request one receipt-safe recovery with exact task and run_id from current status evidence. For an inspected Hindsight provider failure, use component:hindsight instead; this retries the exact failed upstream memory operations and does not create a Task.",
    "harness.status": "Read bounded current runtime-health and receipt findings.",
    "model.benchmark": "Measure one registered model using model_id and devices.",
    "model.configure": "Update one registered model with model_id and at least one supported setting: allowed_devices, context_tokens, max_output_tokens, gpu_memory_utilization or max_num_seqs.",
    "model.inspect": "Inspect one registered model using model_id.",
    "model.source": "Register the current immutable Source identity of a registered model using model_id.",
    "observations.recall": "Recall historical Hindsight memories from your own Agent bank using query. The conversation shows only its recent exchanges verbatim; use this for anything older that the owner refers to (an earlier request, decision, answer or result) before answering, instead of guessing or asking the owner to repeat it. Memories retain uncertainty and dates; they do not prove current screen or application state and do not grant Tools or permission.",
    "observations.retain": "Retain an unverified historical note in your own Hindsight bank using text and up to three accessible related_refs. This does not publish accepted wiki Knowledge.",
    "session.unlock": "Unlock the current desktop session through its native lock owner using {}. Available even when the Shell scene is locked; no screenshot or password prerequisite. Call once. After verified success, answer directly in text from the returned receipt.",
    "source.handoff": "Return one self-contained finding as immutable Source Inbox evidence with exactly title and content containing source:// citations.",
    "source.ingest": "Preserve external evidence as immutable Source using content, source_ref, source_type, media_type and optional captured_at.",
    "source.read": "Read immutable Source by exact source ID/citation, or up to ten sources; offset and limit continue bounded text.",
    "task.complete": "Finish with status:completed|failed|review and a factual summary.",
    "task.create": "Activate one accepted Task with task and bounded params.",
    "vault.list": "List readable Articles in the executing Agent's graph.",
    "vault.maintenance": "Inspect accessible Knowledge for bounded maintenance candidates.",
    "vault.propose": "Stage an accepted-scope Article revision with target, action:create|update|archive, and applicable title/body/reason/metadata.",
    "vault.read": "Read an exact accessible Article using ref, or up to ten refs.",
    "vault.search": "Search only the executing Agent's owned and checked-out graph.",
    "vault.validate": "Run deterministic validation of Article formats and load-bearing references.",
    "web.fetch": "Fetch one URL or up to ten URLs using exactly url or urls.",
    "web.search": "Find public source leads using query and optional limit. Results are discovery snippets, not verified answers. Use web.fetch on a relevant result URL before relying on its claims.",
    "window.activate": "Focus one exact current application or pane using target:{kind:application|pane,name:<exact name>,surface?:<surface>}.",
    "window.place": "Move or resize a current application window or Obsidience pane. Call directly with target:{kind:application|pane,name:<exact Scene name>} and destination:{surface:<destination Surface>,tile?:{left,top,right,bottom}}. External apps use kind:application, even when called panes. Omit tile to move to another Surface. No screenshot, click, close, detach or prior activation is needed. Completion requires the returned destination and observed placement to agree."
})
ADAPTERS = MappingProxyType({
    name: f"obsidience.harness.capabilities.{name}" for name in DESCRIPTIONS
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
def argument_schemas() -> dict[str, dict]:
    """The registry's decoder-facing interface; adapters still validate effects."""
    from ..computer.applications import APPLICATIONS
    from ..shell_port.scene import HANDLE_PATTERN, SURFACE_IDS
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
    media_identity_fields = ('provider', 'root_id', 'revision', 'catalogue_instance',
                             'item_id', 'media_source_id', 'source_revision')
    media_identity = obj({key: text(256) for key in media_identity_fields}, media_identity_fields)
    vod_binding = {"action":{"const":"vod"}, "generation":{"type":"string","pattern":"^[0-9a-f]{32}$"},
                   "source":media_identity}
    # An update body once carried only its new section and replaced the whole Article.
    proposal_body = ("The complete Article body, never only the new or changed part. An update replaces "
                     "the entire current body: keep every section you are not changing.")
    schemas = {
        "discord.control": {"anyOf": [
            obj({"action":{"enum":["status","channels","leave","pause","resume","stop"]}}, ("action",)),
            obj({"action":{"const":"join"},"channel_id":{"type":"string","pattern":"^[0-9]{17,20}$"}}, ("action","channel_id")),
            obj({"action":{"const":"say"},"text":text(4000)}, ("action","text")),
            obj({"action":{"const":"play"},"id":text(64),"media_kind":{"const":"audio"}}, ("action","id","media_kind"))]},
        "application.launch": obj({"application": {"type":"string","enum":sorted(APPLICATIONS)},
            "url":text(2000)},("application",)),
        "camera.observe": obj({"query":{**text(500), "description":
                "The visual question to answer from the picture, not a camera command."},
            "wake":{"type":"boolean"},
            "look":{"type":"string","enum":["left","right","up","down"], "description":
                "Turn the camera one step toward this edge of the last picture before capturing: a spoken "
                "direction, or the edge that cuts off what was asked about."}},("query",)),
        "media.pause": obj({"query":text(128, empty=True)}),
        "media.library": {"anyOf": [
            obj({"action":{"const":"browse"}, "query":text(120,empty=True),
                 "offset":{"type":"integer","minimum":0,"maximum":100000},
                 "limit":{"type":"integer","minimum":1,"maximum":20}}, ("action",)),
            obj({"action":{"const":"select"},"item_id":text(64),"media_source_id":text(128)},
                ("action","item_id","media_source_id")),
            obj({"action":{"const":"search"},"query":text(120),"type":{"enum":["movie","series"]}},
                ("action","query","type")),
            obj({"action":{"const":"candidates"},"metadata_id":text(64),
                 "season":{"type":"integer","minimum":0,"maximum":1000},
                 "episode":{"type":"integer","minimum":1,"maximum":10000}}, ("action","metadata_id")),
            obj({"action":{"const":"season"},"metadata_id":text(64),
                 "season":{"type":"integer","minimum":1,"maximum":99},
                 "mode":{"enum":["first","next_unwatched"]}}, ("action","metadata_id","season")),
            obj({"action":{"const":"health"}},("action",)),
            obj({"action":{"const":"resume"},"item_id":text(64)},("action","item_id"))]},
        "media.acquire": obj({"action":{"enum":["register", "refresh"]},"candidate_id":text(64)},
                             ("action","candidate_id")),
        "computer.observe": obj({"target":observe_target,"query":text(500)},("query",)),
        "computer.replay": obj({"query":text(500),"seconds":{"type":"integer","minimum":5,"maximum":60},
            "surface":surface},("query",)),
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
        "vault.read": {"anyOf":[obj({key:value,
                "offset":{**integer,"description":"Continuation only: the end character of this Article's previous page. Write ref first, then offset, then expected_sha256. Omit for the first page."},
                "expected_sha256":{"type":"string","pattern":"^[0-9a-f]{64}$",
                    "description":"Continuation only: the view_sha256 returned with the previous page. Required with an offset above 0."}},(key,))
            for key,value in (("ref",text(500)),("refs",array(text(500),10,1)))]},
        "vault.list":obj({"folder":text(512,empty=True),"offset":integer}),
        # The adapter refuses an authored source; Sources are cited in the body.
        "vault.propose":{"anyOf":[
            obj({"target":text(512),"action":{"enum":["create","update"]},
                "title":text(300),"body":{**text(96000),"description":proposal_body},"reason":text(400,empty=True),
                "metadata":{"type":"object","additionalProperties":True}},("target","body")),
            obj({"target":text(512),"action":{"const":"archive"},"title":text(300),
                "body":{**text(96000,empty=True),"description":proposal_body},"reason":text(400,empty=True),
                "metadata":{"type":"object","additionalProperties":True}},("target","action")),
        ]},
        "vault.maintenance":obj({}), "vault.validate":obj({}), "harness.status":obj({}),
        "harness.repair":{"anyOf":[obj({"task":text(512),"run_id":text(128)},("task","run_id")),
                                    obj({"component":{"const":"hindsight"}},("component",))]},
        "harness.optimize":obj({"case_id":text(64)},("case_id",)),
        "session.unlock":obj({}),
        "tv.control":{"anyOf":[obj({"action":{"enum":["on","off","observe","volume_up","volume_down","mute","unmute","pause","resume","stop"]}},("action",)),
            obj({**vod_binding,"operation":{"enum":["state","pause","resume","stop"]}},
                ("action","operation","generation","source")),
            obj({**vod_binding,"operation":{"const":"seek"},"position":{"type":"number","minimum":0,"maximum":1000000000}},
                ("action","operation","generation","source","position")),
            obj({**vod_binding,"operation":{"const":"track"},"kind":{"enum":["audio","subtitle"]},
                 "track_id":{"type":["integer","null"],"minimum":1,"maximum":2147483647}},
                ("action","operation","generation","source","kind","track_id")),
            obj({"action":{"const":"volume"},"level":{"type":"integer","minimum":0,"maximum":100,
                "description":"Exact TV volume level 0-100."}},("action","level")),
            obj({"action":{"const":"play"},"query":text(120),"app":text(32)},("action","query")),
            obj({"action":{"const":"launch"},"app":text(32)},("action","app")),
            obj({"action":{"const":"key"},"key":{"enum":["up","down","left","right","select","back","home","menu","enter","delete","rewind","fast_forward"]}},("action","key")),
            obj({"action":{"const":"keys"},"keys":{"type":"array","minItems":1,"maxItems":8,"items":{"enum":["up","down","left","right","select","back","home","menu","enter","delete"]}}},("action","keys")),
            obj({"action":{"const":"text"},"text":text(120)},("action","text")),
            obj({"action":{"const":"find"},"query":text(120),"app":text(32)},("action","query")),
            obj({"action":{"const":"open_season"},"id":text(8)},("action","id")),
            obj({"action":{"const":"open"},"id":text(8),"resume":{"type":"boolean"}},("action","id")),
            obj({"action":{"const":"open"},"url":text(300),"start":{"type":"integer","minimum":0,"maximum":86400,
                "description":"YouTube video start position in seconds."}},("action","url")),
            obj({"action":{"const":"notice"},"text":text(200)},("action","text"))]},
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
    schema = deepcopy(argument_schemas()[name])
    if name == "computer.observe":
        from ..shell_port.scene import SCENE

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


def tool_parameters(name: str, *, completion_no_change: bool = False, completion_blocked: bool = False,
                    proposal_mode: str = "", repair_rows: list[dict] | tuple = ()) -> dict:
    """One Tool's parameter schema under the active step contract, not its evidence."""
    if name not in ADAPTERS:
        raise ValueError(f"Unknown tool: {name}")
    args = argument_schema(name)
    if name == "harness.repair" and repair_rows:
        # Declare only the call the inspected plan permits: a Task row takes
        # task and run_id, the Hindsight row takes component. A plan holding
        # both kinds declares the Task call first: their union cannot complete
        # it once run_id is written, and every attempt needs a fresh plan.
        args = args["anyOf"][0 if any("component" not in row for row in repair_rows) else 1]
    if name == "vault.propose" and proposal_mode == "link":
        args = args["anyOf"][0]
        args["properties"]["action"] = {"const": "update"}
        args["required"].append("action")
        args["properties"].pop("metadata", None)
    elif name == "vault.propose" and proposal_mode == "ingest":
        # General Inbox ingestion authors Knowledge. Retirement belongs to
        # Archive; documentary metadata is compiled by the publication owner.
        args = args["anyOf"][0]
        args["required"].append("action")
        args["properties"].pop("metadata", None)
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
    return args

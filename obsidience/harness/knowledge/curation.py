"""Owner-selected, source-backed Ingest publication through ordinary review.

The branch's accepted metadata is the policy; Source text cannot grant it.
Other proposals remain in the same review queue. No second wiki writer.
"""

from __future__ import annotations

import hashlib
from contextlib import contextmanager
import json
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

import yaml

from .auto_curate import enabled, policy_for, selection
from .source import SourceError, _SOURCE_CITATION, get_source, validate_source_citations
from .vault import Resolver, folder_article_path, is_folder_article, iter_notes, load_note
from .links import body_links

FEED_GENERATOR = "obsidience/harness/knowledge/curation.py#feed"


def feed_article_target(binding: dict) -> str:
    """The owner-selected folder and native item identity determine placement."""
    from ..connections.destinations import destination as selected_destination

    node = selected_destination(str(binding.get("destination_ref", "")))
    destination = PurePosixPath(node["ref"])
    identity = hashlib.sha256((binding["feed_id"] + ":" + binding["item_key"]).encode()).hexdigest()[:24]
    return str(destination.parent / ("item--" + identity + ".md"))


def _feed_article(handoff: dict, binding: dict) -> dict:
    """Compile Darwin's complete handoff without a second summary pass."""
    from .vault import normalize_article_body

    citations = [handoff["citation"], *[item["citation"] for item in
                  validate_source_citations(handoff["content"], required=True)]]
    if "source://" + binding["source_id"] not in citations:
        raise SourceError("Feed handoff omits its original item citation")
    title = handoff["source_ref"]
    return {
        "target": feed_article_target(binding), "title": title,
        "body": normalize_article_body(handoff["content"], title).strip() + "\n",
        "metadata": {"type": "knowledge", "resource": binding["reporting_url"] or "source://" + binding["source_id"],
            "sources": [{"resource": citation} for citation in dict.fromkeys(citations)],
            "generated": {"by": FEED_GENERATOR, "at": handoff["captured_at"]}},
    }


def _accepted_feed_origin(note, binding: dict) -> dict | None:
    """Recover publication identity from its native documentary Inbox citation."""
    from .source import feed_source_binding

    for item in note.meta.get("sources") or []:
        ref = item.get("resource") if isinstance(item, dict) else item
        if not isinstance(ref, str) or _SOURCE_CITATION.fullmatch(ref) is None:
            continue
        doc = get_source(ref)
        if not doc["path"].startswith("inbox/"):
            continue
        origin = feed_source_binding(doc["id"])
        if (origin and origin["feed_id"] == binding["feed_id"]
                and origin["item_key"] == binding["item_key"]
                and origin["destination_ref"] == binding["destination_ref"]):
            return origin
    return None


def prepare_feed_article(args: dict, context: dict) -> dict:
    """Require the exact admitted Inbox and read receipt before ordinary Review."""
    from .source import feed_binding_matches, feed_source_binding, research_handoff_origin

    params = context.get("params") or {}
    if (context.get("task") != "Tasks/ingest" or context.get("agent") != "Alexandria"
            or context.get("event") != "source.inbox" or not context.get("run_id")
            or not isinstance(params, dict) or params.get("research_task") != "Tasks/research/distill"
            or research_handoff_origin(params) is None):
        raise SourceError("Feed publication requires its exact Distill to Ingest occurrence")
    handoff = get_source(str(params.get("source_citation", "")))
    binding = feed_source_binding(handoff["id"])
    if binding is None or not feed_binding_matches(params.get("feed_binding"), binding):
        raise SourceError("Feed Inbox destination binding does not match its admitted occurrence")
    receipt = context.get("_source_reads", {}).get(handoff["citation"], {})
    length = len(handoff["content"])
    if (receipt.get("content_sha256") != handoff["content_sha256"]
            or receipt.get("total_characters") != length or [0, length] not in receipt.get("ranges", [])):
        raise SourceError("Feed publication requires source.read of the complete exact Inbox")
    if (set(args) - {"target", "source", "action", "reason", "metadata"}
            or args.get("source") != handoff["citation"]
            or args.get("metadata", {}) not in ({}, {"type": "knowledge"})
            or args.get("action", "create") not in {"create", "update"}):
        raise SourceError("Feed publication accepts exact source and target, without body or authored metadata")
    article = _feed_article(handoff, binding)
    if str(args.get("target", "")).removesuffix(".md") != article["target"].removesuffix(".md"):
        raise SourceError("Feed publication target must be " + article["target"])
    existing = load_note(article["target"])
    if existing and (existing.kind != "knowledge" or existing.runtime_observation
                     or existing.meta.get("generated", {}).get("by") != FEED_GENERATOR):
        raise SourceError("Feed destination conflicts with an independently maintained Article")
    already_current = False
    if existing:
        accepted = _accepted_feed_origin(existing, binding)
        if accepted is None:
            raise SourceError("Existing Feed Article has no attested matching Inbox origin")
        already_current = accepted["source_id"] == binding["source_id"]
        if not already_current and get_source(accepted["source_id"])["captured_at"] >= get_source(binding["source_id"])["captured_at"]:
            raise SourceError("An equal or newer Feed item version is already published; preserve that accepted Article")
    article["action"] = "update" if existing else "create"
    article["reason"] = str(args.get("reason") or "Ingest the complete bound Feed summary")
    envelope = {"feed_id": binding["feed_id"], "destination_ref": binding["destination_ref"],
                "origin_source_id": binding["source_id"], "source_id": handoff["id"],
                "source_sha256": handoff["content_sha256"], "target": article["target"]}
    return {"article": article, "binding": binding, "envelope": envelope,
            "already_current": already_current}


@contextmanager
def feed_review_guard(envelope: dict | None):
    """Definition lock precedes the Article lock for staging and later approval."""
    if envelope is None:
        yield None
        return
    from ..connections.runtime import feed_destination_guard

    if (not isinstance(envelope, dict) or set(envelope) != {
            "feed_id", "destination_ref", "origin_source_id", "source_id", "source_sha256", "target"}):
        raise SourceError("Feed proposal controller receipt is invalid")
    with feed_destination_guard(envelope["feed_id"], expected_ref=envelope["destination_ref"]) as destination:
        yield destination


def validate_feed_proposal(meta: dict, body: str, *, destination=None) -> None:
    """Reattest pinned bytes, placement and metadata through the ordinary owner."""
    from .source import feed_source_binding
    from .links import canonical_body

    envelope = meta["feed_publication"]
    handoff = get_source(str(envelope["source_id"]))
    binding = feed_source_binding(handoff["id"])
    if (binding is None or handoff["content_sha256"] != envelope["source_sha256"]
            or binding["feed_id"] != envelope["feed_id"]
            or binding["destination_ref"] != envelope["destination_ref"]
            or binding["source_id"] != envelope["origin_source_id"]):
        raise SourceError("Feed proposal Source or destination receipt changed")
    expected = _feed_article(handoff, binding)
    expected_body = canonical_body(expected["body"].strip(), expected["target"]) + "\n"
    authored = {"kind": "knowledge", **{key: value for key, value in expected["metadata"].items() if key != "type"}}
    expected_action = "update" if load_note(expected["target"]) else "create"
    if (meta.get("target") != expected["target"] or envelope["target"] != expected["target"]
            or meta.get("action") != expected_action or meta.get("review_group") or meta.get("review_building")
            or meta.get("title") != expected["title"] or body != expected_body
            or set(meta.get("authored_fields", [])) != set(authored)
            or any(meta.get(key) != value for key, value in authored.items())):
        raise SourceError("Feed proposal must preserve the exact compiled handoff and documentary metadata")
    if destination is not None:
        count = len(_feed_members().get(envelope["feed_id"], [])) + int(expected_action == "create")
        if count > _retention_cap(destination.get("max_active_articles", 10)):
            raise SourceError("Feed active Article limit requires a complete publication and retention group; restage this Inbox")


def _retention_cap(value) -> int:
    if type(value) is not int or not 1 <= value <= 1000:
        raise SourceError("Feed active Article limit must be an integer from 1 to 1000")
    return value


def _feed_members(*, notes=None, index=None) -> dict[str, list[dict]]:
    """One fresh, read-only inventory; shared folders never imply ownership."""
    from .index import INDEX
    from .source import _material_sha256, _row_doc, feed_source_binding
    from ..config import CONFIG

    ledger = INDEX if index is None else index
    notes = iter_notes() if notes is None else notes
    output, documents = {}, {}
    for note in notes:
        if (note.kind != "knowledge" or note.runtime_observation
                or note.meta.get("article_status") == "deprecated"
                or not isinstance(note.meta.get("generated"), dict)
                or note.meta["generated"].get("by") != FEED_GENERATOR):
            continue
        origins = {}
        for item in note.meta.get("sources") or []:
            ref = item.get("resource") if isinstance(item, dict) else item
            if not isinstance(ref, str) or _SOURCE_CITATION.fullmatch(ref) is None:
                continue
            source_id = ref.removeprefix("source://")
            if source_id not in documents:
                row = ledger.source(source_id)
                if row is None or _material_sha256(bytes(row["material"])) != row["material_sha256"]:
                    raise SourceError("Feed Article documentary Source is missing or changed")
                documents[source_id] = (row, _row_doc(row, include_content=True))
            row, doc = documents[source_id]
            if not doc["path"].startswith("inbox/") or not row.get("origin_source_id"):
                continue
            binding = feed_source_binding(doc["id"], index=ledger, restore=False)
            if binding is None:
                continue
            identity = hashlib.sha256((binding["feed_id"] + ":" + binding["item_key"]).encode()).hexdigest()[:24]
            expected = str(PurePosixPath(binding["destination_ref"]).parent / ("item--" + identity + ".md"))
            raw = ledger.source(binding["source_id"])
            captured = datetime.fromisoformat(raw["captured_at"].replace("Z", "+00:00"))
            if captured.utcoffset() is None:
                raise SourceError("Feed Article capture time must include a timezone")
            origin = {"ref": note.ref, "source_id": binding["source_id"], "inbox_id": doc["id"],
                      "feed_id": binding["feed_id"], "item_key": binding["item_key"],
                      "destination_ref": binding["destination_ref"],
                      "captured_at": captured.astimezone(timezone.utc).isoformat(),
                      "base_sha256": hashlib.sha256((CONFIG.vault_dir / note.path).read_bytes()).hexdigest()}
            if note.path != expected or is_folder_article(note) or note.children:
                origin["retention_protection"] = "owner-reorganized placement"
            origins[(binding["feed_id"], binding["item_key"], binding["source_id"])] = origin
        if len(origins) > 1:
            raise SourceError("Feed Article has ambiguous published item ownership")
        if origins:
            origin = next(iter(origins.values()))
            output.setdefault(origin["feed_id"], []).append(origin)
    for members in output.values():
        by_item = {}
        for member in members:
            by_item.setdefault(member["item_key"], []).append(member)
        for copies in by_item.values():
            if len(copies) > 1 and any(row.get("retention_protection") for row in copies):
                for row in copies:
                    row["retention_protection"] = "duplicate item with owner-reorganized placement"
        members.sort(key=lambda row: (row["captured_at"], row["ref"]))
    return output


def _membership_hash(members: list[dict]) -> str:
    return hashlib.sha256(json.dumps(members, sort_keys=True).encode()).hexdigest()


def _retention_placement_blocker(members: list[dict]) -> str:
    protected = [row for row in members if row.get("retention_protection")]
    if not protected:
        return ""
    return ("Feed retirement requires owner resolution of " + protected[0]["retention_protection"]
            + ": " + ", ".join(row["ref"] for row in protected[:6]))


def _retention_link_blocker(refs: set[str], notes: list) -> str:
    if not refs:
        return ""
    res = Resolver(notes)
    inbound = [note.ref for note in notes if note.ref not in refs
               and any((target := res.resolve(raw)) is not None and target.ref in refs for raw in note.links)]
    return ("Feed retirement is blocked by accepted inbound references from " + ", ".join(inbound[:6])) if inbound else ""


def feed_retention_states(caps_by_id: dict[str, int], *, index=None) -> dict[str, dict]:
    """Read-only projection: never materialize Source or start retention work."""
    from ..config import CONFIG
    from . import format as codec
    from .vault import _NOTE_WRITE_LOCK

    if not caps_by_id:
        return {}
    caps_by_id = {feed_id: _retention_cap(cap) for feed_id, cap in caps_by_id.items()}
    with _NOTE_WRITE_LOCK:
        try:
            notes = iter_notes()
            inventory = _feed_members(notes=notes, index=index)
        except (ValueError, OSError, yaml.YAMLError) as exc:
            return {feed_id: {"active_article_count": None, "max_active_articles": cap,
                             "excess_articles": None, "retention_status": "unavailable",
                             "retention_detail": "Accepted Feed inventory is unavailable: " + str(exc)[:200]}
                    for feed_id, cap in caps_by_id.items()}
        pending = {}
        for path in sorted(CONFIG.staging_dir.glob("*.md")):
            try:
                meta, _body = codec.loads(path.read_text())
            except (ValueError, OSError, yaml.YAMLError):
                return {feed_id: {"active_article_count": len(inventory.get(feed_id, [])), "max_active_articles": cap,
                                 "excess_articles": max(0, len(inventory.get(feed_id, [])) - cap),
                                 "retention_status": "unavailable", "retention_detail": "Pending Review metadata is unreadable; retention cannot be assessed"}
                        for feed_id, cap in caps_by_id.items()}
            envelope = meta.get("feed_retention")
            if isinstance(envelope, dict) and not meta.get("review_building"):
                if (not isinstance(envelope.get("feed_id"), str)
                        or not isinstance(envelope.get("membership_sha256"), str)
                        or type(envelope.get("max_active_articles")) is not int):
                    return {feed_id: {"active_article_count": len(inventory.get(feed_id, [])), "max_active_articles": cap,
                                     "excess_articles": max(0, len(inventory.get(feed_id, [])) - cap),
                                     "retention_status": "unavailable", "retention_detail": "Pending Feed Review metadata is invalid"}
                            for feed_id, cap in caps_by_id.items()}
                row = pending.setdefault(envelope.get("feed_id"), {"envelope": envelope, "archives": set()})
                if meta.get("action") == "archive":
                    row["archives"].add(str(meta.get("target", "")).removesuffix(".md"))
        from .review import _transaction_feed_continuation
        for path in sorted(CONFIG.staging_dir.glob(".review-transaction-*.json")):
            try:
                retained = _transaction_feed_continuation(json.loads(path.read_text()))
                if retained:
                    envelope = retained["envelope"]
                    if not isinstance(envelope.get("feed_id"), str):
                        raise ValueError("invalid Feed identity")
                    pending[envelope["feed_id"]] = {"envelope": envelope, "archives": set(), "continuation": True}
            except (ValueError, OSError, yaml.YAMLError):
                return {feed_id: {"active_article_count": len(inventory.get(feed_id, [])), "max_active_articles": cap,
                                 "excess_articles": max(0, len(inventory.get(feed_id, [])) - cap),
                                 "retention_status": "unavailable", "retention_detail": "Retained Review continuation is unreadable"}
                        for feed_id, cap in caps_by_id.items()}
        states = {}
        for feed_id, value in caps_by_id.items():
            cap = _retention_cap(value)
            members = inventory.get(feed_id, [])
            excess = max(0, len(members) - cap)
            state, detail = ("over_limit", f"{excess} active Articles need retirement") if excess else ("within_limit", "Active Article limit is satisfied")
            waiting = pending.get(feed_id)
            retiring = {row["ref"] for row in members[:excess]}
            if waiting:
                envelope = waiting["envelope"]
                retiring = waiting["archives"]
                state, detail = "review_required", "A complete Feed retention change awaits Review"
                if waiting.get("continuation"):
                    state, detail = "blocked", "A committed Feed batch has retained continuation; reconcile this Feed to stage its remaining work"
                elif (envelope.get("max_active_articles") != cap
                        or envelope.get("membership_sha256") != _membership_hash(members)):
                    state, detail = "blocked", "The pending Feed change has stale policy or Article inputs; reject it before replanning"
            if block := _retention_link_blocker(retiring, notes):
                state, detail = "blocked", block
            if block := _retention_placement_blocker([row for row in members if row["ref"] in retiring]):
                state, detail = "blocked", block
            states[feed_id] = {"active_article_count": len(members), "max_active_articles": cap,
                               "excess_articles": excess, "retention_status": state, "retention_detail": detail}
        return states


def feed_retention_state(feed_id: str, cap: int, *, index=None) -> dict:
    return feed_retention_states({feed_id: cap}, index=index)[feed_id]


def _retention_plan(feed_id: str, destination: dict, members: list[dict], publication=None) -> dict:
    """Keep the incoming leaf and retire only the oldest attested prior leaves."""
    from .review import MAX_REVIEW_MEMBERS

    cap = _retention_cap(destination.get("max_active_articles", 10))
    incoming = None
    if publication is not None:
        from .source import feed_source_binding

        handoff = get_source(publication["source_id"])
        binding = feed_source_binding(handoff["id"])
        if (binding is None or binding["feed_id"] != feed_id
                or binding["destination_ref"] != destination["destination_ref"]
                or handoff["content_sha256"] != publication["source_sha256"]
                or binding["source_id"] != publication["origin_source_id"]):
            raise SourceError("Feed publication no longer matches its exact Inbox and destination")
        incoming = _feed_article(handoff, binding)
        if incoming["target"] != publication["target"]:
            raise SourceError("Feed publication target changed")
        existing = load_note(incoming["target"])
        incoming["action"] = "update" if existing else "create"
        if existing:
            generated = existing.meta.get("generated")
            if (existing.kind != "knowledge" or existing.runtime_observation
                    or not isinstance(generated, dict) or generated.get("by") != FEED_GENERATOR):
                raise SourceError("Feed destination conflicts with an independently maintained Article")
            accepted = _accepted_feed_origin(existing, binding)
            if accepted is None:
                raise SourceError("Existing Feed Article has no attested matching Inbox origin")
            if accepted["source_id"] == binding["source_id"]:
                incoming = None  # Already published; preserve the owner's current bytes.
            else:
                previous = datetime.fromisoformat(get_source(accepted["source_id"])["captured_at"].replace("Z", "+00:00"))
                captured = datetime.fromisoformat(get_source(binding["source_id"])["captured_at"].replace("Z", "+00:00"))
                if previous >= captured:
                    raise SourceError("An equal or newer Feed item version is already published; preserve that accepted Article")
    incoming_ref = publication["target"].removesuffix(".md") if publication else None
    count = len(members) + int(incoming is not None and incoming["action"] == "create")
    overflow = max(0, count - cap)
    include_incoming = incoming is not None and overflow < MAX_REVIEW_MEMBERS
    victims = [row for row in members if row["ref"] != incoming_ref][:min(overflow, MAX_REVIEW_MEMBERS)]
    if overflow and not victims:
        raise SourceError("Feed active limit cannot be met without retiring the incoming Article")
    if block := _retention_placement_blocker(victims):
        raise SourceError(block)
    changes = [incoming] if include_incoming else []
    for victim in victims:
        note = load_note(victim["ref"] + ".md")
        changes.append({"action": "archive", "target": note.path, "title": note.title, "body": "", "metadata": {}})
    envelope = {"feed_id": feed_id, "destination_ref": destination["destination_ref"],
                "max_active_articles": cap, "membership_sha256": _membership_hash(members),
                "publication": publication, "include_incoming": include_incoming}
    return {"changes": changes, "envelope": envelope,
            "batch_key": hashlib.sha256(json.dumps(envelope, sort_keys=True).encode()).hexdigest(),
            "archived_count": len(victims), "include_incoming": include_incoming}


@contextmanager
def feed_retention_guard(envelope, *, definition_guard=None):
    """Only Feed group decisions acquire configuration before Article state."""
    if envelope is None:
        yield None
        return
    if (not isinstance(envelope, dict) or set(envelope) != {
            "feed_id", "destination_ref", "max_active_articles", "membership_sha256", "publication", "include_incoming"}):
        raise SourceError("Feed retention group has an invalid controller envelope")
    from ..connections.runtime import feed_destination_guard

    guard = definition_guard() if definition_guard else feed_destination_guard(envelope["feed_id"], expected_ref=envelope["destination_ref"])
    with guard as destination:
        if (destination["destination_ref"] != envelope["destination_ref"]
                or destination.get("max_active_articles", 10) != envelope["max_active_articles"]):
            raise SourceError("Feed destination or active Article limit changed before Review")
        yield destination


def validate_feed_retention_group(members, accepted=None, destination=None) -> None:
    """Pin the entire owned set, not just the particular outgoing revisions."""
    envelope = members[0][1].get("feed_retention")
    if envelope is None:
        if any(meta.get("feed_retention") is not None for _path, meta, _body in members):
            raise SourceError("Feed retention group members disagree about their controller envelope")
        return
    if (not isinstance(envelope, dict) or set(envelope) != {
            "feed_id", "destination_ref", "max_active_articles", "membership_sha256", "publication", "include_incoming"}
            or any(meta.get("feed_retention") != envelope or meta.get("feed_publication") is not None
                   for _path, meta, _body in members)):
        raise SourceError("Feed retention group members disagree about their controller envelope")
    inventory = _feed_members(notes=accepted).get(envelope["feed_id"], [])
    if _membership_hash(inventory) != envelope["membership_sha256"]:
        raise SourceError("Feed Article membership or accepted bytes changed before Review")
    expected = _retention_plan(envelope["feed_id"], destination or envelope, inventory, envelope["publication"])
    if expected["envelope"] != envelope or len(expected["changes"]) != len(members):
        raise SourceError("Feed retention policy or exact member set changed before Review")
    from .links import canonical_body
    for spec, (_path, meta, body) in zip(expected["changes"], members):
        fields = {"kind": "knowledge", **{key: value for key, value in spec["metadata"].items() if key != "type"}} if spec["action"] != "archive" else {}
        expected_body = canonical_body(spec["body"].strip(), spec["target"]) + "\n"
        if (meta.get("target") != spec["target"] or meta.get("action") != spec["action"]
                or meta.get("title") != spec["title"] or body != expected_body
                or set(meta.get("authored_fields", [])) != set(fields)
                or any(meta.get(key) != value for key, value in fields.items())):
            raise SourceError("Feed retention group must preserve its compiled summary and exact archive set")


def stage_feed_retention(feed_id: str, destination: dict, context: dict, *, publication=None) -> dict:
    """Stage the next bounded change; the Review owner retains any continuation."""
    from .review import stage_group

    members = _feed_members().get(feed_id, [])
    plan = _retention_plan(feed_id, destination, members, publication)
    if not plan["changes"]:
        return {"archived_count": 0, "retention_status": "within_limit"}
    private = {**context, "_feed_compiling": True, "_feed_retention": plan["envelope"], "staged_proposals": []}
    result = stage_group(plan["changes"], private,
                         reason=f"Keep at most {plan['envelope']['max_active_articles']} active Articles for this Feed",
                         batch_key=plan["batch_key"])
    result.update(feed_publication=publication is not None, policy=destination["destination_ref"], archived_count=0)
    return result


def apply_feed_retention(feed_id: str, destination: dict, context: dict, *, publication=None, definition_guard=None) -> dict:
    """One publication owner approves permitted groups and retains the next Review."""
    from .review import approve_group, _recover_pending_publications

    _recover_pending_publications()
    result = stage_feed_retention(feed_id, destination, context, publication=publication)
    if not result.get("staged"):
        return result
    if all(enabled(spec["target"]) for spec in result["members"]):
        try:
            approval = approve_group(Path(result["staged"]).name, definition_guard=definition_guard)
            result["approval"] = approval
            result["archived_count"] = approval.get("archived_count", 0)
            if approval.get("retention_pending"):
                result.update(approval["retention_pending"])
                result["archived_count"] = approval.get("archived_count", 0)
            elif approval.get("retention_blocked"):
                result.update(auto_curate_blocked=approval["retention_blocked"], retention_status="blocked")
            else:
                result.update(auto_approved=True, retention_status="within_limit")
        except (ValueError, OSError) as exc:
            result["auto_curate_blocked"] = str(exc)[:300]
    else:
        result["auto_curate_blocked"] = "Auto-curate is disabled on an affected Article; the complete Feed change requires Review."
    context.setdefault("staged_proposals", []).append(result)
    if not result.get("auto_approved"):
        result.setdefault("retention_status", "review_required")
        result["pending_review"] = True
    return result


def reconcile_feed_retention(feed_id: str, *, definition_guard=None) -> dict:
    """Explicit owner Save uses the same Review owner, without a synthetic Task."""
    from ..connections.runtime import feed_destination_guard
    from .vault import _NOTE_WRITE_LOCK
    from .review import resume_feed_retention

    guard = definition_guard() if definition_guard else feed_destination_guard(feed_id)
    with guard as destination, _NOTE_WRITE_LOCK:
        cap = _retention_cap(destination.get("max_active_articles", 10))
        try:
            resumed = resume_feed_retention(feed_id, definition_guard=definition_guard)
            if resumed and (resumed.get("retention_pending") or resumed.get("retention_blocked")):
                result = resumed.get("retention_pending", resumed)
                state = feed_retention_state(feed_id, cap)
                if resumed.get("retention_blocked"):
                    state.update(retention_status="blocked", retention_detail=resumed["retention_blocked"])
                return {**result, **state}
            result = apply_feed_retention(feed_id, destination, {"agent": "owner", "task": "", "run_id": ""}, definition_guard=definition_guard)
        except (ValueError, OSError) as exc:
            return {**feed_retention_state(feed_id, cap), "retention_status": "blocked", "blocked_reason": str(exc)[:300], "retention_detail": str(exc)[:300]}
        return {**result, **feed_retention_state(feed_id, cap)}


def publication_policy(target: str):
    path = PurePosixPath(target.removesuffix(".md"))
    for parent in path.parents:
        if str(parent) == ".":
            break
        note = load_note(folder_article_path(str(parent)))
        if note and note.meta.get("curation_task"):
            return note
    return None


def try_auto_approve(result: dict, args: dict, context: dict) -> dict:
    from ..capabilities.vault.propose import _authored_metadata

    try:
        args = {**args, "metadata": _authored_metadata(args.get("metadata") or {})}
    except ValueError:
        return result
    if not enabled(str(result["target"])):
        return result
    policy = publication_policy(str(result["target"]))
    if not policy:
        return _approve_scoped_knowledge(result, args, context)
    curation_task = str(policy.meta.get("curation_task", "")).strip("[]")
    research_task = str(policy.meta.get("research_task", "")).strip("[]")
    active_task = load_note(curation_task + ".md")
    if (
        context.get("task") != curation_task
        or context.get("agent") != "Alexandria"
        or context.get("event") != "source.inbox"
        or not context.get("run_id")
        or not active_task
        or active_task.kind != "task"
        or active_task.meta.get("status") != "running"
        or active_task.meta.get("last_run") != context.get("run_id")
        or result["action"] not in {"create", "update"}
        or result["target"] == policy.path
    ):
        return result
    # Tool proposals may not author permission, trigger, provenance, or role
    # metadata. The ordinary review remains available if this check fails.
    metadata = args.get("metadata") or {}
    existing = load_note(result["target"])
    if (
        not isinstance(metadata, dict)
        or set(metadata) - {"kind"}
        or metadata.get("kind", "knowledge") != "knowledge"
        or existing
        and (existing.kind != "knowledge" or existing.runtime_observation)
    ):
        return result
    params = context.get("params") or {}
    if not isinstance(params, dict) or params.get("research_task") != research_task:
        return result
    try:
        from .index import INDEX
        from .review import approve
        from .source import _research_owner

        handoff = get_source(str(params.get("source_citation", "")))
        row = INDEX.source(handoff["id"])
        task = str(params["research_task"])
        run_id = str(params.get("research_run_id", ""))
        expected = f"source.inbox:research:{run_id}:{task}:"
        row_path = str(row.get("path", "")) if row else ""
        event_key = str(row.get("event_key", "")) if row else ""
        expected_params = {
            "activation_key": event_key,
            "source_id": handoff["id"],
            "source_citation": handoff["citation"],
            "source_path": f"obsidience/evidence/{row_path}",
            "source_type": handoff["source_type"],
            "source_ref": handoff["source_ref"],
            "source_media_type": handoff["media_type"],
            "source_captured_at": handoff["captured_at"],
            "source_sha256": handoff["content_sha256"],
        }
        if (
            not row
            or not row_path.startswith("inbox/")
            or not event_key.startswith(expected)
            or any(params.get(key) != value for key, value in expected_params.items())
            or handoff["source_type"] != "research"
            or handoff["media_type"] != "text/markdown"
            or not _research_owner(task, run_id)
        ):
            return result
        evidence = validate_source_citations(handoff["content"], required=True)
        evidence_citations = [item["citation"] for item in evidence]
        if params.get("source_citations") != evidence_citations:
            return result
        allowed = set(evidence_citations)
        allowed.add(handoff["citation"])
        body = str(args.get("body", ""))
        citations = {item["citation"] for item in validate_source_citations(body, required=True)}
        if handoff["citation"] not in citations or not citations <= allowed:
            return {**result, "auto_curate_blocked": "Proposal citations exceed the current research handoff or omit its Inbox citation."}
        accepted = Resolver(iter_notes())
        if any(not accepted.resolve(match) for match in body_links(body, str(result["target"]))):
            return result
        approved = approve(Path(result["staged"]).name)
        return {
            **result,
            "auto_approved": True,
            "approval": approved,
            "policy": policy.ref,
        }
    except (ValueError, OSError) as exc:
        return {**result, "auto_curate_blocked": str(exc)[:300]}


def _approve_scoped_knowledge(result: dict, args: dict, context: dict) -> dict:
    """Publish ordinary Knowledge through the same validator and review ledger.

    The author may maintain its own knowledge; the Curator may maintain an
    owner-enabled destination. Permission never permits authoring authority,
    modifying runtime observations, or silently accepting unsupported claims.
    """
    from .review import approve

    target = str(result["target"])
    policy = policy_for(target)
    existing = load_note(target)
    task = load_note(str(context.get("task", "")) + ".md")
    agent = str(context.get("agent", ""))
    metadata = args.get("metadata") or {}
    if (
        selection(policy) is not True
        or result["action"] not in {"create", "update"}
        or not task or task.kind != "task"
        or task.meta.get("status") != "running"
        or not context.get("run_id")
        or task.meta.get("last_run") != context["run_id"]
        or str(task.meta.get("assignee", "")).strip("[]") != f"Agents/{agent}/{agent}"
        or (agent != "Alexandria" and not target.startswith(f"Agents/{agent}/"))
        or target.split("/", 1)[0] in {"Tools", "Skills", "Tasks", "Runbooks"}
        or not isinstance(metadata, dict) or set(metadata) - {"kind", "type"}
        or metadata.get("type", metadata.get("kind", "knowledge")) != "knowledge"
        or existing and (existing.kind != "knowledge" or existing.runtime_observation)
    ):
        return result
    try:
        body = str(args.get("body", ""))
        sources = validate_source_citations(body)
        accepted = Resolver(iter_notes())
        links = body_links(body, target)
        if any(not accepted.resolve(link) for link in links) or not (sources or links):
            return result
        approval = approve(Path(result["staged"]).name)
        return {**result, "auto_approved": True, "approval": approval, "policy": policy.ref}
    except (ValueError, OSError) as exc:
        return {**result, "auto_curate_blocked": str(exc)[:300]}

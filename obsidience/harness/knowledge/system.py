"""Deterministic System inventory Articles from immutable System evidence.

The System schema supplies this publisher's paths. The receipt retains identities
and hashes, never a second copy of the facts. Authored contracts live in Observations.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from datetime import datetime, timezone
from pathlib import PurePosixPath
from urllib.parse import quote, unquote

from ..config import CONFIG
from . import format as article_format
from .vault import _NOTE_WRITE_LOCK, _atomic_write, canonical_body, load_note, write_note


def system_articles() -> dict[str, dict]:
    """Shallow Knowledge hierarchy; raw System descriptors keep their paths.

    Hardware is a Source grouping, not a Knowledge node. Each application is
    one Article with its registered sub-descriptors included as cited details.
    """
    from .system_schema import ROOT_REF, system_schema
    rows = system_schema()
    catalog = {}
    prefix = ROOT_REF.rsplit("/", 1)[0] + "/"
    hardware = prefix + "Hardware/"
    for row in rows:
        key = row["key"]
        if key == "hardware" or (key.startswith("applications/") and key.count("/") > 1):
            continue
        item = dict(row)
        if key.startswith("hardware/"):
            item["ref"] = row["ref"].replace(hardware, prefix, 1)
            item["parent_ref"] = (ROOT_REF if row["parent_ref"] == hardware + "Hardware"
                else row["parent_ref"].replace(hardware, prefix, 1))
        elif key.startswith("applications/") and row["path"] != row["descriptor_path"]:
            item["ref"] = row["ref"].rsplit("/", 1)[0]
            item["components"] = [child for child in rows if child["key"].startswith(key + "/")]
        catalog[key] = item
    if len({item["ref"].casefold() for item in catalog.values()}) != len(catalog):
        raise ValueError("System descriptors map to ambiguous application Articles")
    return catalog


def _source_category(key: str) -> str:
    return "schema." + key.replace("/", ".")


_REFRESH_LOCK = threading.Lock()
_INDEX_ERROR = ""
_MAX_ROWS = 200
_MAX_ARTICLE_CHARS = 96_000
_OWNERSHIP_ERROR = "System inventory is read-only and follows its schema; write authored workstation knowledge under Workstation Observations"


def _ref(value: str) -> str:
    value = unquote(str(value)).removeprefix("@branch/").strip("/")
    return str(PurePosixPath(value)).removesuffix(".md")


def is_system_article(ref_or_path: str) -> bool:
    ref = _ref(ref_or_path).casefold()
    if not ref.startswith("admech workstation/"):
        return False
    if str(ref_or_path).startswith("@branch/"):
        ref += "/" + ref.rsplit("/", 1)[-1]
    return any(ref == item["ref"].casefold() for item in system_articles().values())


def assert_system_article_writable(ref_or_path: str) -> None:
    ref = _ref(ref_or_path).casefold()
    observations = "admech workstation/workstation observations"
    if (ref == "admech workstation" or ref.startswith("admech workstation/")) and not (
            ref == observations or ref.startswith(observations + "/")):
        raise ValueError(_OWNERSHIP_ERROR)


def assert_system_move_allowed(source: str, destination: str | None = None) -> None:
    origin = _ref(source).casefold()
    assert_system_article_writable(origin)
    if destination is not None:
        assert_system_article_writable(destination)


def _state_path():
    return CONFIG.runtime_dir / "system-knowledge.json"


def _safe_path(path) -> None:
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise ValueError("System Knowledge cannot follow symlinks")


def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read_state() -> dict:
    path = _state_path()
    _safe_path(path)
    if not path.exists():
        return {"schema_version": 2, "updated_at": None, "categories": {}}
    if path.stat().st_size > 512_000:
        raise ValueError("System Knowledge receipt exceeds its bound")
    state = json.loads(path.read_text())
    if (not isinstance(state, dict) or state.get("schema_version") != 2
            or not isinstance(state.get("categories"), dict)
            or set(state["categories"]) - system_articles().keys()):
        raise ValueError("Invalid System Knowledge receipt")
    for row in state["categories"].values():
        if (not isinstance(row, dict) or set(row) - {"published", "pending", "status", "detail"}
                or row.get("status", "uninitialized") not in {"current", "unavailable", "conflict", "uninitialized"}
                or not isinstance(row.get("detail", ""), str)):
            raise ValueError("Invalid System Knowledge category receipt")
        for key in ("published", "pending"):
            if key in row and (not isinstance(row[key], dict)
                    or set(row[key]) != {"article_sha256", "source_id", "content_sha256", "captured_at"}
                    or not re.fullmatch(r"[a-f0-9]{64}", str(row[key].get("article_sha256", "")))
                    or not re.fullmatch(r"[a-f0-9-]{36}", str(row[key].get("source_id", "")))
                    or not re.fullmatch(r"sha256:[a-f0-9]{64}", str(row[key].get("content_sha256", "")))
                    or not isinstance(row[key].get("captured_at"), str)):
                raise ValueError("Invalid System Knowledge publication receipt")
    return state


def _save_state(state: dict) -> None:
    path = _state_path()
    _safe_path(path)
    text = json.dumps(state, sort_keys=True, indent=2) + "\n"
    if not path.exists() or path.read_text() != text:
        _atomic_write(path, text)


def _cell(value) -> str:
    if value is None:
        return "Not recorded"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    text = str(value).replace("\n", " ").replace("\r", " ")
    if len(text) > 400:
        text = text[:400] + " … [excerpt; see Source]"
    for char in ("\\", "`", "*", "_", "[", "]", "<", ">", "|"):
        text = text.replace(char, "\\" + char)
    return text


def _label(value: str) -> str:
    return _cell(str(value).replace("_", " ").capitalize())


def _sections(facts: dict, depth: int = 2) -> list[str]:
    sections = []
    scalars = [(key, value) for key, value in sorted(facts.items()) if not isinstance(value, (dict, list))]
    if scalars:
        sections.append("| Field | Recorded value |\n| --- | --- |\n" + "\n".join(
            f"| {_label(key)} | {_cell(value)} |" for key, value in scalars))
    for key, value in sorted(facts.items()):
        if not isinstance(value, (dict, list)):
            continue
        sections.append("#" * min(depth, 6) + " " + _label(key))
        if isinstance(value, dict):
            sections.extend(_sections(value, depth + 1) if value else ["No values recorded."])
        elif not value:
            sections.append("No entries recorded in this capture.")
        elif all(isinstance(row, dict) and all(not isinstance(cell, (dict, list)) for cell in row.values())
                 for row in value):
            columns = sorted({column for row in value for column in row})
            sections.append("| " + " | ".join(_label(column) for column in columns) + " |\n| "
                + " | ".join("---" for _ in columns) + " |\n" + "\n".join(
                    "| " + " | ".join(_cell(row.get(column)) for column in columns) + " |"
                    for row in value[:_MAX_ROWS]))
        else:
            for row in value[:_MAX_ROWS]:
                if isinstance(row, dict):
                    sections.extend(_sections(row, depth + 1))
                elif isinstance(row, list):
                    sections.append("Nested entries are available in the complete Source.")
                else:
                    sections.append("- " + _cell(row))
        if isinstance(value, list) and len(value) > _MAX_ROWS:
            sections.append(f"Showing {_MAX_ROWS} of {len(value)} recorded entries. The Source retains the complete capture.")
    return sections


def _render(item: dict, facts: dict, source: dict) -> tuple[dict, str]:
    category = _source_category(item["key"])
    if (not isinstance(source.get("id"), str) or source.get("citation") != "source://" + source["id"]
            or source.get("immutable") is not True or not source.get("content_sha256")
            or json.loads(source["content"]) != {"schema": "obsidience.system-evidence.v1",
                                                 "category": category, "facts": facts}):
        raise ValueError("System capture does not attest the supplied inventory")
    meta = {"kind": "knowledge", "title": item["title"], "tags": ["system-inventory"],
            "generated": {"by": "Obsidience System inventory", "at": source["captured_at"]},
            "sources": [{"resource": source["citation"]}]}
    for component in (item, *item.get("components", [])):
        if component["descriptor_path"]:
            meta["sources"].append({"resource": component["descriptor_path"]})
    body = ("System schema and observed inventory, populated automatically by the Harness.\n\n"
            f"Captured: {source['captured_at']}. [Immutable evidence]({source['citation']}) "
            f"({source['content_sha256']}).\n\n"
            + "\n\n".join(_sections(facts)))
    if len(body) > _MAX_ARTICLE_CHARS:
        body = body[:_MAX_ARTICLE_CHARS].rsplit("\n", 1)[0] + "\n\nArticle excerpt; the Source retains the complete capture."
    if item["parent_ref"]:
        body += f"\n\n[Parent](/{quote(item['parent_ref'] + '.md', safe='/')}).\n"
    # The schema's children table is descriptive. Folder placement owns
    # hierarchy, so unavailable first captures cannot create dangling links.
    if item["key"] == "system":
        observations = "ADMECH Workstation/Workstation Observations/Workstation Observations"
        if load_note(observations + ".md"):
            body += f"\n\n[Workstation Observations](/{quote(observations + '.md', safe='/')}).\n"
    return meta, canonical_body(body, item["ref"] + ".md")


def _public_status(state: dict, *, error: str = "") -> dict:
    categories = []
    try:
        catalog = system_articles()
    except (OSError, ValueError) as exc:
        return {"status": "degraded", "detail": "System schema unavailable: " + str(exc)[:200],
                "categories": [], "current_count": 0, "article_count": 0, "updated_at": state.get("updated_at")}
    for category, item in catalog.items():
        row = state["categories"].get(category, {})
        published = row.get("published", {})
        status = "conflict" if error else row.get("status", "uninitialized")
        detail = error or row.get("detail", "")
        path = CONFIG.vault_dir / (item["ref"] + ".md")
        try:
            _safe_path(path)
            exists = path.is_file()
            if published and (not exists or _hash(path.read_bytes()) != published["article_sha256"]):
                status, detail = "conflict", "Published inventory Article was changed or removed; owner content was preserved"
        except OSError:
            exists = False
            status, detail = "unavailable", "Published inventory Article could not be read"
        except ValueError as exc:
            exists = False
            status, detail = "conflict", str(exc)
        categories.append({"category": category, "ref": item["ref"], "title": item["title"],
            "status": status, "detail": detail[:300], "source_id": published.get("source_id"),
            "source_citation": "source://" + published["source_id"] if published else None,
            "observed_at": published.get("captured_at"), "article_exists": exists})
    count = sum(row["status"] == "current" for row in categories)
    result = {"status": "ready" if count == len(categories) else "uninitialized" if all(
                row["status"] == "uninitialized" for row in categories) else "degraded",
            "updated_at": state.get("updated_at"), "categories": categories, "current_count": count,
            "article_count": sum(row["article_exists"] and bool(row["source_id"]) for row in categories)}
    if _INDEX_ERROR:
        result.update(status="degraded", detail=_INDEX_ERROR)
    return result


def system_knowledge_status() -> dict:
    """Read bounded schema receipts and Article hashes; never collect or publish."""
    with _NOTE_WRITE_LOCK:
        try:
            return _public_status(_read_state())
        except (OSError, ValueError, TypeError, KeyError) as exc:
            return _public_status({"categories": {}}, error="System Knowledge receipt unavailable: " + str(exc)[:200])


def refresh_system_knowledge(*, sync: bool = True) -> dict:
    """Capture through the existing Source owner and publish only attested facts."""
    from ..host.system_evidence import collect_system_evidence, system_node_facts
    from .source import capture_system_evidence
    global _INDEX_ERROR

    with _REFRESH_LOCK:
        try:
            catalog = system_articles()
        except (OSError, ValueError):
            return {**_public_status({"categories": {}}), "changed": 0}
        try:
            inventory = collect_system_evidence()
        except Exception as exc:
            inventory = {category: {"status": "unavailable", "detail": type(exc).__name__}
                         for category in system_articles()}
        changed = 0
        with _NOTE_WRITE_LOCK:
            try:
                state = _read_state()
            except (OSError, ValueError, TypeError, KeyError) as exc:
                return {**_public_status({"categories": {}}, error="System Knowledge receipt unavailable: " + str(exc)[:200]), "changed": 0}
            state["updated_at"] = datetime.now(timezone.utc).isoformat()
        for category, item in catalog.items():
            try:
                facts = system_node_facts(item, inventory)
                if item.get("components"):
                    facts["details"] = {component["key"].removeprefix(category + "/"):
                        system_node_facts(component, inventory) for component in item["components"]}
                facts["children"] = [{"title": child["title"], "ref": child["ref"]} for child in catalog.values() if child["parent_ref"] == item["ref"]]
                source = capture_system_evidence(_source_category(category), facts)
                meta, body = _render(item, facts, source)
                material = article_format.dumps(meta, body).encode()
                intended = {"article_sha256": _hash(material), "source_id": source["id"],
                            "content_sha256": source["content_sha256"], "captured_at": source["captured_at"]}
                with _NOTE_WRITE_LOCK:
                    row = state["categories"].setdefault(category, {})
                    path = CONFIG.vault_dir / (item["ref"] + ".md")
                    _safe_path(path)
                    parent = load_note(item["parent_ref"] + ".md") if item["parent_ref"] else None
                    if item["parent_ref"] and (parent is None or parent.kind != "knowledge"):
                        raise ValueError("The System schema parent Article is unavailable")
                    actual = _hash(path.read_bytes()) if path.exists() else None
                    if row.get("pending") and actual == row["pending"]["article_sha256"]:
                        row["published"] = row.pop("pending")
                        changed += 1  # Recovery may need to index the already-written Article.
                    previous = row.get("published", {}).get("article_sha256")
                    if (actual is not None and actual != previous) or (actual is None and previous is not None):
                        row.update(status="conflict", detail="Inventory path contains changed or authored content; it was preserved")
                        continue
                    if actual != intended["article_sha256"]:
                        row["pending"] = intended
                        _save_state(state)  # Intent precedes the atomic Article replacement.
                        write_note(item["ref"] + ".md", meta, body)
                        changed += 1
                    row.pop("pending", None)
                    row.update(published=intended, status="current", detail="")
                    _save_state(state)
            except Exception as exc:
                with _NOTE_WRITE_LOCK:
                    row = state["categories"].setdefault(category, {})
                    row.update(status="unavailable", detail=str(exc)[:300] or type(exc).__name__)
        receipt_error = ""
        with _NOTE_WRITE_LOCK:
            try:
                _save_state(state)
                result = _public_status(state)
            except (OSError, ValueError, TypeError, KeyError) as exc:
                receipt_error = "System Knowledge receipt unavailable: " + str(exc)[:200]
                result = _public_status(state, error=receipt_error)
        if sync:
            from .index import INDEX
            try:
                INDEX.sync()
                _INDEX_ERROR = ""
                result = _public_status(state, error=receipt_error)
            except Exception as exc:
                _INDEX_ERROR = "Knowledge index update failed: " + str(exc)[:200]
                result.update(status="degraded", detail=_INDEX_ERROR)
        return {**result, "changed": changed}

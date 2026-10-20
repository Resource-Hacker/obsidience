# Portions Copyright 2026 Google LLC
# SPDX-License-Identifier: Apache-2.0
# Adapted for Obsidience: functional codec with CRLF/body preservation, strict
# mapping check for falsy frontmatter, and conformance findings from SPEC.md.
"""Open Knowledge Format v0.2: the portable document contract.

This module is the one owner of OKF document framing and conformance. It
parses and serializes YAML-frontmatter Markdown, names the reserved
``index.md``/``log.md`` documents, and reports how a document or bundle
meets the specification. It knows nothing about Article types, the
``obsidience`` namespace, Task state, trust, review or execution; the
Obsidience Article profile in ``format`` is layered on top.

The framing and timestamp-preserving loader follow the Apache-2.0 reference
codec; the conformance rules follow SPEC.md at the same revision:
https://github.com/GoogleCloudPlatform/open-knowledge-format/blob/
ad30107c31c06aec8a7d5636e0d1058118604e6f/src/reference_agent/bundle/document.py
"""

from __future__ import annotations

import posixpath
import re
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote, urlsplit

import yaml
from markdown_it import MarkdownIt


RESERVED_FILENAMES = frozenset({"index.md", "log.md"})
LIFECYCLE_STATUSES = ("draft", "stable", "deprecated")
# Root keys the specification defines; producers may add any others (SPEC 4.1).
SPEC_FIELDS = frozenset({
    "type", "title", "description", "resource", "tags", "sources", "usage_window",
    "generated", "verified", "status", "stale_after", "runtime", "parameters",
    "computation", "executor", "attester",
})

_ACTOR = re.compile(r"(?:human|process):\S+|[A-Za-z0-9_.-]+/\S+")
_LOG_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_FOOTNOTE = re.compile(r"\[\^([^\]\s]+)\](?!:)")
_WIKILINK = re.compile(r"\[\[[^\]\n]+\]\]")
_MARKDOWN = MarkdownIt("commonmark").enable("table")


class _Loader(getattr(yaml, "CSafeLoader", yaml.SafeLoader)):
    """Keep authored timestamp spellings, including offsets, as strings."""


_Loader.yaml_implicit_resolvers = {
    key: [(tag, pattern) for tag, pattern in values
          if tag != "tag:yaml.org,2002:timestamp"]
    for key, values in _Loader.yaml_implicit_resolvers.items()
}


def parse(text: str) -> tuple[dict[str, Any], str]:
    """Split one OKF document into its frontmatter mapping and exact body.

    A document without frontmatter is returned whole as the body. Body line
    endings, including CRLF, are preserved byte for byte.
    """
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return {}, text
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        raise ValueError("Unterminated YAML frontmatter")
    raw = yaml.load("".join(lines[1:end]), Loader=_Loader)
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError("YAML frontmatter must be a mapping")
    body = "".join(lines[end + 1:])
    if body.startswith("\r\n"):
        body = body[2:]
    elif body.startswith("\n"):
        body = body[1:]
    return raw, body


def serialize(raw: Mapping[str, Any], body: str) -> str:
    """Serialize metadata and body; unknown fields and types are not discarded."""
    header = yaml.safe_dump(dict(raw), sort_keys=False, allow_unicode=True)
    return f"---\n{header}---\n\n{body}" + ("" if body.endswith("\n") else "\n")


def is_reserved(path: str | Path) -> bool:
    """Reserved navigation/history documents are never concepts (SPEC 3.1).

    The comparison is case-insensitive so a case-folding filesystem cannot
    turn ``Index.md`` into a concept beside a reserved listing.
    """
    return PurePosixPath(str(path)).name.casefold() in RESERVED_FILENAMES


def resolve(href: str, path: str) -> str | None:
    """Bundle-relative target of a link or path (SPEC 6); None when it leaves the bundle.

    A leading ``/`` is bundle-relative; anything else is relative to ``path``.
    """
    target = unquote(urlsplit(href).path)
    if not target:
        return None
    target = target.lstrip("/") if target.startswith("/") else posixpath.join(posixpath.dirname(path), target)
    target = posixpath.normpath(target)
    return None if target in {".", ".."} or target.startswith("../") else target


def is_timestamp(value: Any) -> bool:
    """An ISO 8601 datetime with an explicit UTC offset (SPEC 5)."""
    if not isinstance(value, str) or "T" not in value:
        return False
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).utcoffset() is not None
    except ValueError:
        return False


def timestamp(value: str) -> datetime:
    """Parse a value already accepted by ``is_timestamp``."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def is_actor(value: Any) -> bool:
    """``<producer>/<version>``, ``human:<id>`` or ``process:<id>`` (SPEC 7)."""
    return isinstance(value, str) and _ACTOR.fullmatch(value) is not None


def normalize_verified(raw: Mapping[str, Any]) -> list[Any]:
    """A bare ``verified`` mapping is a one-element list (SPEC 5.2 MUST)."""
    verified = raw.get("verified")
    if isinstance(verified, Mapping):
        return [verified]
    return verified if isinstance(verified, list) else []


@dataclass(frozen=True, slots=True)
class Finding:
    """One conformance observation.

    ``error`` breaks SPEC 11 conformance; ``warning`` departs from SHOULD
    guidance in SPEC 4-10; ``info`` is a condition consumers must tolerate,
    such as a broken link.
    """

    path: str
    level: str
    rule: str
    message: str


def check_text(text: str, path: str, *, exists: Callable[[str], bool] | None = None,
               bundle_root: bool = False) -> list[Finding]:
    """Check one document's text; ``path`` is bundle-relative POSIX."""
    try:
        raw, body = parse(text)
    except (ValueError, yaml.YAMLError) as error:
        return [Finding(path, "error", "11", f"frontmatter is not parseable: {error}".splitlines()[0])]
    first = text.splitlines()[:1]
    findings = check_document(raw, body, path, exists=exists,
                              framed=bool(first) and first[0].strip() == "---",
                              bundle_root=bundle_root)
    if "\r\n" in text:
        findings.append(Finding(path, "info", "4", "uses CRLF line endings; the body round-trips unchanged"))
    return findings


def check_document(raw: Mapping[str, Any], body: str, path: str, *,
                   exists: Callable[[str], bool] | None = None, framed: bool = True,
                   bundle_root: bool = False) -> list[Finding]:
    """Check a parsed document against SPEC 3-11.

    ``exists`` answers whether a bundle-relative file exists, enabling the
    tolerated broken-link and unresolved-path observations.
    """
    name = PurePosixPath(path).name.casefold()
    if name == "index.md":
        return _check_index(raw, body, path, framed, bundle_root)
    if name == "log.md":
        return _check_log(body, path)
    findings: list[Finding] = []

    def add(level: str, rule: str, message: str) -> None:
        findings.append(Finding(path, level, rule, message))

    if not framed:
        add("error", "11", "concept document has no YAML frontmatter block")
        return findings
    kind = raw.get("type")
    if not isinstance(kind, str) or not kind.strip():
        add("error", "11", "frontmatter needs a non-empty string type")
    for key in ("title", "description", "resource"):
        if key in raw and not isinstance(raw[key], str):
            add("warning", "4.1", f"{key} should be a string")
    if "tags" in raw and (not isinstance(raw["tags"], list)
                          or any(not isinstance(tag, str) for tag in raw["tags"])):
        add("warning", "4.1", "tags should be a YAML list of strings")
    if "status" in raw and raw["status"] not in LIFECYCLE_STATUSES:
        add("warning", "5.4", "status should be draft, stable or deprecated")
    if "stale_after" in raw and not is_timestamp(raw["stale_after"]):
        add("warning", "5.5", "stale_after should be an ISO 8601 datetime with an offset")
    if "generated" in raw:
        generated = raw["generated"]
        if not isinstance(generated, Mapping) or "by" not in generated:
            add("warning", "5.2", "generated should be a mapping with by")
        else:
            if not is_actor(generated["by"]):
                add("warning", "7", f"generated.by is not an actor: {generated['by']!r}")
            if "at" in generated and not is_timestamp(generated["at"]):
                add("warning", "5", "generated.at should be an ISO 8601 datetime with an offset")
    if "verified" in raw and not isinstance(raw["verified"], (Mapping, list)):
        add("warning", "5.2", "verified should be a mapping or a list of mappings")
    else:
        for i, event in enumerate(normalize_verified(raw)):
            if not isinstance(event, Mapping):
                add("warning", "5.2", f"verified[{i}] should be a mapping with by and at")
                continue
            if not is_actor(event.get("by")):
                add("warning", "7", f"verified[{i}].by is not an actor: {event.get('by')!r}")
            if not is_timestamp(event.get("at")):
                add("warning", "5", f"verified[{i}].at should be an ISO 8601 datetime with an offset")
    findings.extend(Finding(path, *item) for item in _check_window(raw.get("usage_window"), "usage_window"))

    def path_value(value: Any, label: str, *, scope: bool = False) -> None:
        if not isinstance(value, str) or not value.strip():
            add("warning", "6.2", f"{label} should be a non-empty path or URI")
            return
        if len(urlsplit(value).scheme) > 1:  # An absolute URI; one letter is a drive.
            return
        target = resolve(value, path)
        if exists is not None and (target is None or not exists(target)):
            kind_text = "an unresolvable relative path or a scope descriptor" if scope else "an unresolvable relative path"
            add("info", "6.2", f"{label} {value!r} is not a file in this bundle; consumers read it as {kind_text}")

    if "resource" in raw and isinstance(raw["resource"], str):
        path_value(raw["resource"], "resource")
    if "computation" in raw:
        path_value(raw["computation"], "computation")
    for key in ("executor", "attester"):
        if key in raw:
            if not isinstance(raw[key], Mapping) or "resource" not in raw[key]:
                add("warning", "10.2", f"{key} should be a mapping with resource")
            else:
                path_value(raw[key]["resource"], f"{key}.resource")
    if kind == "Attested Computation" and "runtime" not in raw:
        add("warning", "10.2", "an Attested Computation requires runtime")

    source_ids: set[str] = set()
    if "sources" in raw:
        sources = raw["sources"]
        if not isinstance(sources, list):
            add("warning", "5.1", "sources should be a list of mappings")
            sources = []
        for i, source in enumerate(sources):
            label = f"sources[{i}]"
            if not isinstance(source, Mapping):
                add("warning", "5.1", f"{label} should be a mapping with resource")
                continue
            if "resource" not in source:
                add("warning", "5.1", f"{label}.resource is required")
            else:
                path_value(source["resource"], f"{label}.resource", scope=True)
            if "id" in source:
                if not isinstance(source["id"], str) or not source["id"].strip():
                    add("warning", "5.1", f"{label}.id should be a non-empty string")
                elif source["id"] in source_ids:
                    add("warning", "5.1", f"{label}.id {source['id']!r} repeats; ids are attribution keys")
                else:
                    source_ids.add(source["id"])
            if "usage_count" in source and (not isinstance(source["usage_count"], int)
                                            or isinstance(source["usage_count"], bool)
                                            or source["usage_count"] < 0):
                add("warning", "5.1", f"{label}.usage_count should be a non-negative integer")
            if "last_modified" in source and not is_timestamp(source["last_modified"]):
                add("warning", "5", f"{label}.last_modified should be an ISO 8601 datetime with an offset")
            findings.extend(Finding(path, *item)
                            for item in _check_window(source.get("usage_window"), f"{label}.usage_window"))
    findings.extend(_check_body(body, path, source_ids, exists))
    return findings


def check_bundle(root: Path, *, exclude: Collection[str] = ()) -> list[Finding]:
    """Check every Markdown file of a bundle directory.

    Hidden entries and top-level names in ``exclude`` are skipped; the caller
    decides which application directories are not part of the bundle.
    """
    root = Path(root)
    files: set[str] = set()
    documents: list[str] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if (any(part.startswith(".") for part in relative.parts)
                or relative.parts[0] in exclude or not path.is_file()):
            continue
        files.add(relative.as_posix())
        if path.suffix == ".md":
            documents.append(relative.as_posix())
    findings: list[Finding] = []
    for relative in documents:
        try:
            text = (root / relative).read_text(encoding="utf-8")
        except UnicodeError:
            findings.append(Finding(relative, "error", "4", "document is not UTF-8"))
            continue
        findings.extend(check_text(text, relative, exists=files.__contains__,
                                   bundle_root="/" not in relative))
    if "index.md" not in files:
        findings.append(Finding("index.md", "info", "12", "no bundle-root index.md declares okf_version"))
    return findings


def _check_window(window: Any, label: str) -> list[tuple[str, str, str]]:
    if window is None:
        return []
    if not isinstance(window, Mapping):
        return [("warning", "5.1", f"{label} should be a mapping with from and to")]
    return [("warning", "5", f"{label}.{key} should be an ISO 8601 datetime with an offset")
            for key in ("from", "to") if not is_timestamp(window.get(key))]


def _check_body(body: str, path: str, source_ids: set[str],
                exists: Callable[[str], bool] | None) -> list[Finding]:
    findings = []
    cited: set[str] = set()
    if exists is None and "[[" not in body and "[^" not in body:
        return findings  # Nothing to observe without a file catalog.
    for block in _MARKDOWN.parse(body):
        if block.type != "inline":
            continue  # Code blocks and fences are examples, not links.
        line = (block.map or [0])[0] + 1
        depth = 0
        for token in block.children or []:
            if token.type == "link_open":
                depth += 1
                href = token.attrGet("href") or ""
                url = urlsplit(href)
                if url.scheme or url.netloc or not url.path.lower().endswith(".md"):
                    continue
                target = resolve(href, path)
                if target is None:
                    findings.append(Finding(path, "info", "6.1", f"line {line}: link {href!r} leaves the bundle"))
                elif exists is not None and not exists(target):
                    findings.append(Finding(path, "info", "6.1", f"line {line}: link {href!r} has no target yet"))
            elif token.type == "link_close":
                depth -= 1
            elif token.type == "text" and not depth:
                for match in _WIKILINK.finditer(token.content):
                    findings.append(Finding(path, "warning", "6.1",
                        f"line {line}: {match.group(0)} is not a Markdown link; OKF consumers do not follow it"))
                cited.update(_FOOTNOTE.findall(token.content))
    for label in sorted(cited - source_ids):
        findings.append(Finding(path, "warning", "5.1", f"footnote [^{label}] has no matching sources[].id"))
    return findings


def _check_index(raw: Mapping[str, Any], body: str, path: str, framed: bool,
                 bundle_root: bool) -> list[Finding]:
    findings = []
    if framed and (not bundle_root or set(raw) - {"okf_version"}):
        findings.append(Finding(path, "error", "8",
            "index.md carries no frontmatter except okf_version at the bundle root"))
    for number, line in enumerate(body.splitlines(), 1):
        text = line.strip()
        if text and not text.startswith(("#", "* ", "- ")):
            findings.append(Finding(path, "warning", "8",
                f"line {number}: index entries should be headings or link list items"))
            break
    return findings


def _check_log(body: str, path: str) -> list[Finding]:
    findings = []
    dates = []
    for number, line in enumerate(body.splitlines(), 1):
        if line.startswith("## "):
            heading = line[3:].strip()
            if not _LOG_DATE.fullmatch(heading):
                findings.append(Finding(path, "error", "9", f"line {number}: date heading {heading!r} is not YYYY-MM-DD"))
            else:
                dates.append(heading)
    if dates != sorted(dates, reverse=True):
        findings.append(Finding(path, "warning", "9", "log entries should be newest first"))
    return findings

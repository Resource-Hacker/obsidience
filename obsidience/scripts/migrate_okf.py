"""One-time native Article conversion; run with the Harness stopped.

Preview is read-only. The operator snapshots the Vault and SQLite before apply.
Immutable Source, archived Articles and historical execution evidence stay intact.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from obsidience.harness.knowledge import format as codec
from obsidience.harness.knowledge.links import body_links, canonical_body
from obsidience.harness.knowledge.vault import SOURCE_DIRS, _atomic_write, _rewrite_refs


@dataclass
class Change:
    old: Path
    new: Path
    before: str
    after: str
    meta: dict


def prepare(vault: Path, project: Path) -> tuple[list[Change], dict[str, str]]:
    documents = []
    renames = {}
    aliases = defaultdict(set)
    for path in sorted(vault.rglob("*.md")):
        relative = path.relative_to(vault)
        if relative.parts[0] in SOURCE_DIRS or any(part.startswith(("_", ".")) for part in relative.parts):
            continue
        before = path.read_text()
        raw, body = codec.parse(before)
        # Untyped reserved listings are already valid OKF navigation, not Articles.
        if path.name.lower() in {"index.md", "log.md"} and not (raw.get("kind") or raw.get("type")):
            continue
        meta = codec.decode_metadata(raw)
        meta.setdefault("kind", "knowledge")
        new = path.with_name(path.parent.name + ".md") if path.name.lower() == "index.md" else path
        if path.name.lower() == "log.md":
            raise ValueError(f"Choose an ordinary Article name before migration: {relative}")
        if new != path and new.exists():
            raise ValueError(f"Article collision: {new.relative_to(vault)}")
        old_ref = relative.with_suffix("").as_posix()
        new_ref = new.relative_to(vault).with_suffix("").as_posix()
        if new != path:
            renames[old_ref] = new_ref
        for alias in (old_ref, path.stem, str(meta.get("title", ""))):
            if alias:
                aliases[alias.casefold()].add(new_ref)
        documents.append((path, new, before, meta, body))
    # Resolve only exact unique names; ambiguity must stay an admission failure.
    link_map = {key: next(iter(refs)) for key, refs in aliases.items() if len(refs) == 1}
    link_map.update(renames)
    changes = []
    for path, new, before, meta, body in documents:
        for ref in body_links(body, path.relative_to(vault).as_posix()):
            if len(aliases.get(ref.casefold(), ())) > 1:
                raise ValueError(f"Ambiguous Article link in {path.relative_to(vault)}: {ref}")
        meta = _rewrite_refs(meta, renames)
        if isinstance(meta.get("sources"), list):
            meta["sources"] = [
                {"resource": (value if urlsplit(value).scheme else (project / value).resolve().as_uri())}
                if isinstance(value, str) else value for value in meta["sources"]
            ]
        body = canonical_body(body, path.relative_to(vault).as_posix(), link_map)
        raw = codec.encode_metadata(meta)
        errors = codec.validate_profile(raw, new)
        if errors:
            raise ValueError(f"{path.relative_to(vault)}: {'; '.join(errors)}")
        changes.append(Change(path, new, before, codec.serialize(raw, body), meta))
    return changes, renames


def apply(changes: list[Change], vault: Path, ledger) -> None:
    for item in changes:
        if item.old.read_text() != item.before:
            raise ValueError(f"Article changed since preview: {item.old.relative_to(vault)}")
        if item.old != item.new and item.new.exists():
            raise ValueError(f"Article collision since preview: {item.new.relative_to(vault)}")
    ledger.remap_task_runtime({
        item.old.relative_to(vault).with_suffix("").as_posix():
        item.new.relative_to(vault).with_suffix("").as_posix()
        for item in changes if item.old != item.new and item.meta.get("kind") == "task"
    })
    for item in changes:
        if item.meta.get("kind") == "task":
            ref = item.new.relative_to(vault).with_suffix("").as_posix()
            ledger.seed_task_runtime(ref, item.meta)
    for item in changes:
        if item.before == item.after and item.old == item.new:
            continue
        _atomic_write(item.new, item.after)
        if item.old != item.new:
            item.old.unlink()


def main() -> None:
    from obsidience.harness.config import CONFIG

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    changes, renames = prepare(CONFIG.vault_dir, CONFIG.project_root)
    if args.apply:
        state = subprocess.run(
            ["systemctl", "--user", "is-active", "obsidience-harness-dev.service"],
            capture_output=True, text=True, check=False,
        ).stdout.strip()
        if state not in {"inactive", "failed"}:
            raise SystemExit("Stop the Harness and snapshot Vault + SQLite before applying")
        from obsidience.harness.knowledge.index import INDEX

        apply(changes, CONFIG.vault_dir, INDEX)
    print(json.dumps({
        "applied": args.apply, "articles": len(changes), "renamed": len(renames),
        "rewritten": sum(item.before != item.after or item.old != item.new for item in changes),
        "task_states": sum(item.meta.get("kind") == "task" for item in changes),
    }))


if __name__ == "__main__":
    main()

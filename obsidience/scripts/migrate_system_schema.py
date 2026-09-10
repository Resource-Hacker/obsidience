"""Move the original ADMECH contracts beneath Observations; preview by default.

Run with the Harness stopped and a complete Vault/SQLite/receipt backup before
applying. Source files and historical Review/execution receipts are not migrated
here. The ordinary move owner repairs accepted references; no model is called.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

from obsidience.harness.config import CONFIG
from obsidience.harness.knowledge import format as codec
from obsidience.harness.knowledge import vault
from obsidience.harness.knowledge.system_schema import system_schema


ROOT = "ADMECH Workstation"
OBSERVATIONS = ROOT + "/Workstation Observations"
AUTHORED = (
    "ADMECH Workstation",
    "Hardware/Hardware",
    "Hardware/Displays/Displays",
    "Hardware/Displays/display-topology-and-isolation-strategy--a8755cfa",
    "Hardware/Displays/Samsung Odyssey OLED G9/Samsung Odyssey OLED G9",
    "Hardware/Displays/Samsung Odyssey OLED G9/samsung-display-vrr-and-edid-configuration--96ccfd7b",
    "Hardware/Input/Input",
    "Hardware/Input/input-mapping-and-mouse-configuration--5579dfc0",
    "Software/Software",
    "Software/Desktop and Windowing/Desktop and Windowing",
    "Software/Desktop and Windowing/agent-launch-and-gui-application-management--339f2788",
    "Software/Games/Games",
    "Software/Games/gaming-performance-and-visual-quality-priorities--595700d3",
    "Software/Games/Teamfight Tactics/Teamfight Tactics",
    "Software/Games/Teamfight Tactics/tft-launch-via-rtx-4080-android-avd--3e5726a8",
    "Software/Games/World of Warcraft/World of Warcraft",
    "Software/Games/World of Warcraft/world-of-warcraft-launch-policy--3e5e73cc",
    "Software/Terminal and tmux/Terminal and tmux",
    "Software/Terminal and tmux/terminal-persistence-and-tmux-configuration--e868685d",
)
RETAINED = (
    "Workstation Observations/Workstation Observations",
    "Workstation Observations/workstation-observation-if-vrr-dsc-blackouts-return-use-the-validated-14--c05b5d51",
    "Workstation Observations/Incident/Incident",
    "Workstation Observations/Incident/incident-samsung-vrr-blackscreen-and-nvidia-610-regression--bcacd849",
    "Workstation Observations/Incident/samsung-total-display-loss-incident-and-failover-contract--5c280a8c",
)
# old category -> (old relative Article, schema-v2 key, new relative Article)
GENERATED = {
    "identity": ("System Identity", "system", "ADMECH Workstation"),
    "compute": ("Hardware/Compute/Compute", "hardware/compute", "Hardware/Compute/Compute"),
    "storage": ("Hardware/Drives/Drives", "hardware/drives", "Hardware/Drives/Drives"),
    "devices": ("Hardware/Devices/Devices", "hardware/devices", "Hardware/Devices/Devices"),
    "network": ("Hardware/Network/Network", "hardware/network", "Hardware/Network/Network"),
    "applications": ("Software/Applications/Applications", "applications", "Applications/Applications"),
    "runtime": ("Software/Obsidience/Obsidience", "applications/obsidience", "Applications/Obsidience/Obsidience"),
}


def migration_mapping() -> dict[str, str]:
    # Preserve every authored title; only the old root overview needs a new
    # filename to leave the same-named root Article to the System mirror.
    mapping = {ROOT + "/" + ref: OBSERVATIONS + "/" + (
        "Workstation Contracts" if ref == "ADMECH Workstation" else ref
    ) for ref in AUTHORED}
    mapping.update({ROOT + "/" + old: ROOT + "/" + new
                    for old, _key, new in GENERATED.values() if old != new})
    return mapping


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _receipt_path() -> Path:
    return CONFIG.runtime_dir / "system-knowledge.json"


def _snapshot() -> dict[str, bytes]:
    result = {}
    for path in sorted(CONFIG.vault_dir.rglob("*.md")):
        if any(parent.is_symlink() for parent in (path, *path.parents)):
            raise ValueError("Migration cannot follow a Vault symlink")
        result[path.relative_to(CONFIG.vault_dir).as_posix()] = path.read_bytes()
    return result


def _accepted(path: str) -> bool:
    return Path(path).parts[0] not in (
        *vault.IMMUTABLE_DIRS, *vault.SYSTEM_DIRS, *vault.HIDDEN_DIRS,
    )


def _document(files: dict[str, bytes], ref: str) -> tuple[dict, str]:
    raw = files.get(ref + ".md")
    if raw is None:
        raise ValueError("Missing expected Article: " + ref)
    meta, body = codec.loads(raw.decode("utf-8"))
    if meta.get("kind", "knowledge") != "knowledge":
        raise ValueError("Migration accepts only Knowledge Articles: " + ref)
    return meta, body


def _publication(files: dict[str, bytes], ref: str, row: dict) -> dict:
    meta, _ = _document(files, ref)
    published = row.get("published") if isinstance(row, dict) else None
    generated = meta.get("generated")
    if (not isinstance(published, dict) or row.get("pending")
            or row.get("status") not in {"current", "unavailable", "conflict"}
            or not isinstance(row.get("detail", ""), str)
            or set(published) != {"article_sha256", "source_id", "content_sha256", "captured_at"}
            or published.get("article_sha256") != _sha(files[ref + ".md"])
            or not re.fullmatch(r"[a-f0-9-]{36}", str(published.get("source_id", "")))
            or not re.fullmatch(r"sha256:[a-f0-9]{64}", str(published.get("content_sha256", "")))
            or not isinstance(published.get("captured_at"), str) or not published["captured_at"]
            or not isinstance(generated, dict) or generated.get("by") != "Obsidience System inventory"
            or {"resource": "source://" + published["source_id"]} not in meta.get("sources", [])):
        raise ValueError("Generated Article is not covered by its exact publication receipt: " + ref)
    return published


def prepare() -> dict:
    """Preflight every move, accepted reference and publication before mutation."""
    files = _snapshot()
    receipt_path = _receipt_path()
    if any(parent.is_symlink() for parent in (receipt_path, *receipt_path.parents)):
        raise ValueError("Migration cannot follow a receipt symlink")
    receipt_raw = receipt_path.read_bytes()
    state = json.loads(receipt_raw)
    if not isinstance(state, dict) or not isinstance(state.get("categories"), dict):
        raise ValueError("Invalid System Knowledge receipt")
    mapping = migration_mapping()
    catalog = system_schema()
    schema_refs = {row["ref"] for row in catalog}
    schema_by_key = {row["key"]: row["ref"] for row in catalog}
    schema_keys = {row["ref"]: row["key"] for row in catalog}
    if any(schema_by_key.get(key) != ROOT + "/" + new for _old, key, new in GENERATED.values()):
        raise ValueError("System schema no longer matches the reviewed migration destinations")
    already = state.get("schema_version") == 2
    if state.get("schema_version") not in {1, 2}:
        raise ValueError("Unsupported System Knowledge receipt version")
    if not already and set(state["categories"]) != set(GENERATED):
        raise ValueError("Expected exactly seven legacy System publication receipts")
    for old, new in mapping.items():
        ref = new if already and old not in {ROOT + "/" + r[0] for r in GENERATED.values()} else old
        if not already or old not in {ROOT + "/" + r[0] for r in GENERATED.values()}:
            meta, _ = _document(files, ref)
            if old in {ROOT + "/" + item for item in AUTHORED} and meta.get("generated"):
                raise ValueError("Authored contract unexpectedly became generated: " + ref)
        if already:
            if old + ".md" in files and old not in schema_refs:
                raise ValueError("Legacy Article still exists after migration: " + old)
            if old + ".md" in files and old in schema_refs:
                _publication(files, old, state["categories"].get(schema_keys[old]))
        elif new + ".md" in files and new not in mapping:
            raise ValueError("Migration destination already exists: " + new)
        target = CONFIG.vault_dir / (new + ".md")
        if any(parent.is_symlink() or (parent.exists() and not parent.is_dir())
               for parent in target.parents):
            raise ValueError("Invalid migration destination parent: " + new)
        if target.parent.exists() and any(
            sibling.name.casefold() == target.name.casefold() and sibling != target
            for sibling in target.parent.iterdir()
        ):
            raise ValueError("Case-insensitive migration destination collision: " + new)
    for ref in RETAINED:
        _document(files, ROOT + "/" + ref)
    for old_key, (old, key, new) in GENERATED.items():
        _publication(files, ROOT + "/" + (new if already else old),
                     state["categories"].get(key if already else old_key))
    if not already:
        expected = {ROOT + "/" + ref + ".md" for ref in (*AUTHORED, *RETAINED)}
        expected.update(ROOT + "/" + row[0] + ".md" for row in GENERATED.values())
        actual = {path for path in files if path.startswith(ROOT + "/")}
        if actual != expected:
            raise ValueError("ADMECH inventory changed; review extra or missing Articles before migration")
    inbound = []
    for path, raw in files.items():
        if not _accepted(path):
            continue
        parse = codec.parse if Path(path).name.casefold() in {"index.md", "log.md"} else codec.loads
        meta, body = parse(raw.decode("utf-8"))
        # Use the exact same native transformations as move_vault_item for
        # preflight only. The migration never implements its own link writer.
        if (vault._rewrite_refs(meta, mapping) != meta
                or vault.canonical_body(body, path, mapping) != body):
            inbound.append(path)
    fingerprint = _sha(json.dumps({
        "files": {path: _sha(raw) for path, raw in files.items()},
        "receipt": _sha(receipt_raw), "mapping": mapping, "system_schema": catalog,
    }, sort_keys=True, separators=(",", ":")).encode())
    return {"status": "already_migrated" if already else "ready",
            "plan_sha256": fingerprint, "authored_moves": 0 if already else len(AUTHORED),
            "generated_moves": 0 if already else 3,
            "moves": [] if already else [{"source": old + ".md", "destination": new + ".md"}
                                           for old, new in mapping.items()],
            "retained_observations": [ROOT + "/" + ref for ref in RETAINED],
            "accepted_reference_updates": [] if already else inbound,
            "receipt_version": state["schema_version"]}


def apply(expected_plan_sha256: str) -> dict:
    """Apply one exact inspected plan; restore the whole batch on failure."""
    with vault._NOTE_WRITE_LOCK:
        plan = prepare()
        if plan["plan_sha256"] != expected_plan_sha256:
            raise ValueError("Vault or receipt changed since preview; inspect a fresh dry run")
        if plan["status"] == "already_migrated":
            return {**plan, "applied": False}
        from obsidience.harness.knowledge.index import INDEX

        mapping = migration_mapping()
        if any(INDEX.task_runtime(ref) is not None for ref in {*mapping, *mapping.values()}):
            raise ValueError("Knowledge migration cannot move a reference owning Task runtime")
        files = _snapshot()
        receipt_raw = _receipt_path().read_bytes()
        state = json.loads(receipt_raw)
        directories = {path for path in CONFIG.vault_dir.rglob("*") if path.is_dir()}
        created = []
        try:
            for item in plan["moves"]:
                source = CONFIG.vault_dir / item["source"]
                destination = CONFIG.vault_dir / item["destination"]
                destination.parent.mkdir(parents=True, exist_ok=True)
                vault.move_vault_item(
                    item["source"], destination.parent.relative_to(CONFIG.vault_dir).as_posix(),
                    _system_migration=(_sha(source.read_bytes()), item["destination"]),
                )
                created.append(destination)
            categories = {}
            for old_key, (_old, key, new) in GENERATED.items():
                published = dict(state["categories"][old_key]["published"])
                published["article_sha256"] = _sha((CONFIG.vault_dir / (ROOT + "/" + new + ".md")).read_bytes())
                prior = state["categories"][old_key]
                categories[key] = {"published": published, "status": prior["status"],
                                   "detail": prior.get("detail", "")}
            vault._atomic_write(_receipt_path(), json.dumps({
                "schema_version": 2, "updated_at": state.get("updated_at"), "categories": categories,
            }, sort_keys=True, indent=2) + "\n")
            if prepare()["status"] != "already_migrated":
                raise ValueError("Migration postcondition did not verify")
        except BaseException:
            # Individual moves own their rollback; this restores all earlier
            # successful moves and their accepted inbound edits as one batch.
            for path in reversed(created):
                if path.relative_to(CONFIG.vault_dir).as_posix() not in files:
                    path.unlink(missing_ok=True)
            for relative, raw in files.items():
                path = CONFIG.vault_dir / relative
                if not path.exists() or path.read_bytes() != raw:
                    vault._atomic_write(path, raw.decode("utf-8"))
            vault._atomic_write(_receipt_path(), receipt_raw.decode("utf-8"))
            for path in sorted(set(CONFIG.vault_dir.rglob("*")) - directories,
                               key=lambda item: len(item.parts), reverse=True):
                if path.is_dir() and not any(path.iterdir()):
                    path.rmdir()
            raise
        return {**plan, "status": "migrated", "receipt_version": 2, "applied": True}


def _flatten_mapping() -> tuple[dict[str, str], dict[str, dict]]:
    from obsidience.harness.knowledge.system import system_articles
    catalog = system_articles()
    mapping = {}
    for row in system_schema():
        owner = "system" if row["key"] == "hardware" else row["key"]
        if owner.startswith("applications/"):
            owner = "/".join(owner.split("/")[:2])
        target = catalog[owner]["ref"]
        if row["ref"] != target:
            mapping[row["ref"]] = target
    return mapping, catalog


def prepare_flatten() -> dict:
    """Preflight the shallow System layout against exact publication receipts."""
    files = _snapshot()
    receipt_path = _receipt_path()
    if any(path.is_symlink() for path in (receipt_path, *receipt_path.parents)):
        raise ValueError("Migration cannot follow a receipt symlink")
    receipt_raw = receipt_path.read_bytes()
    state = json.loads(receipt_raw)
    if state.get("schema_version") != 2 or not isinstance(state.get("categories"), dict):
        raise ValueError("Flattening requires the existing schema-v2 publisher")
    mapping, catalog = _flatten_mapping()
    physical = {row["key"]: row for row in system_schema()}
    done = set(state["categories"]) == set(catalog)
    expected = catalog if done else physical
    if set(state["categories"]) != set(expected):
        raise ValueError("System publication coverage changed; inspect before migrating")
    for key, row in expected.items():
        _publication(files, row["ref"], state["categories"][key])
    moves = [{"source": row["ref"] + ".md", "destination": catalog[key]["ref"] + ".md"}
             for key, row in physical.items() if key in catalog and row["ref"] != catalog[key]["ref"]]
    archives = [{"source": row["ref"] + ".md", "successor": mapping[row["ref"]],
                 "destination": "_archived/system-hierarchy/" + row["ref"] + ".md"}
                for key, row in physical.items() if key not in catalog]
    for item in moves + archives:
        source, destination = item["source"], item["destination"]
        if done:
            if source in files:
                raise ValueError("Retired System Article still exists: " + source)
            continue
        if destination in files:
            raise ValueError("Migration destination already exists: " + destination)
        target = CONFIG.vault_dir / destination
        if any(p.is_symlink() or (p.exists() and not p.is_dir()) for p in target.parents):
            raise ValueError("Invalid migration destination parent: " + destination)
        if target.parent.exists() and any(p.name.casefold() == target.name.casefold()
                                         for p in target.parent.iterdir()):
            raise ValueError("Case-insensitive migration destination collision: " + destination)
    # Never remove a generated grouping that still contains unregistered content.
    for folder in (ROOT + "/Hardware/", ROOT + "/Applications/"):
        actual = {path for path in files if path.startswith(folder)}
        registered = {row["ref"] + ".md" for row in expected.values() if (row["ref"] + ".md").startswith(folder)}
        if actual != registered:
            raise ValueError("System subtree contains unregistered Articles: " + folder)
    digest = _sha(json.dumps({"files": {p: _sha(raw) for p, raw in files.items()},
        "receipt": _sha(receipt_raw), "catalog": catalog, "mapping": mapping}, sort_keys=True).encode())
    return {"status": "already_migrated" if done else "ready", "plan_sha256": digest,
            "moves": [] if done else moves, "archives": [] if done else archives,
            "article_count": len(catalog)}


def apply_flatten(expected_plan_sha256: str) -> dict:
    """Move exact generated Articles, archive wrappers and repair accepted refs."""
    from datetime import datetime, timezone
    from obsidience.harness.knowledge.index import INDEX

    with vault._NOTE_WRITE_LOCK:
        plan = prepare_flatten()
        if plan["plan_sha256"] != expected_plan_sha256:
            raise ValueError("Vault or receipt changed since preview; inspect a fresh dry run")
        if plan["status"] == "already_migrated":
            return {**plan, "applied": False}
        mapping, catalog = _flatten_mapping()
        if any(INDEX.task_runtime(ref) is not None for ref in {*mapping, *mapping.values()}):
            raise ValueError("Knowledge migration cannot move a reference owning Task runtime")
        files, receipt_raw = _snapshot(), _receipt_path().read_bytes()
        state = json.loads(receipt_raw)
        directories = {path for path in CONFIG.vault_dir.rglob("*") if path.is_dir()}
        completed = False
        obsolete = {parent for item in plan["moves"] + plan["archives"]
                    for parent in (CONFIG.vault_dir / item["source"]).parents
                    if parent.is_relative_to(CONFIG.vault_dir) and parent != CONFIG.vault_dir}
        try:
            for item in plan["archives"]:
                meta, body = codec.loads(files[item["source"]].decode())
                meta.update(article_status="deprecated", superseded_by="[[" + item["successor"] + "]]",
                    archived_at=datetime.now(timezone.utc).isoformat(),
                    archive_reason="System hierarchy simplified; details retained in the successor Article and immutable Source.")
                vault._atomic_write(CONFIG.vault_dir / item["destination"], codec.dumps(meta, body))
                (CONFIG.vault_dir / item["source"]).unlink()
            for item in plan["moves"]:
                source = CONFIG.vault_dir / item["source"]
                destination = CONFIG.vault_dir / item["destination"]
                destination.parent.mkdir(parents=True, exist_ok=True)
                vault.move_vault_item(item["source"], destination.parent.relative_to(CONFIG.vault_dir).as_posix(),
                    _system_migration=(_sha(source.read_bytes()), item["destination"]))
            # Native accepted-link transformations also rebase references to
            # absorbed wrappers. Archive editions and raw Source remain untouched.
            for relative in files:
                path = CONFIG.vault_dir / relative
                if not _accepted(relative) or not path.is_file():
                    continue
                reserved = path.name.casefold() in {"index.md", "log.md"}
                parse, serialize = (codec.parse, codec.serialize) if reserved else (codec.loads, codec.dumps)
                meta, body = parse(path.read_text())
                updated = vault._rewrite_refs(meta, mapping)
                rebased = vault.canonical_body(body, relative, mapping)
                if updated != meta or rebased != body:
                    vault._atomic_write(path, serialize(updated, rebased))
            # Include moved Articles in the same reference repair and receipt update.
            categories = {}
            for key, item in catalog.items():
                path = CONFIG.vault_dir / (item["ref"] + ".md")
                meta, body = codec.loads(path.read_text())
                if key == "system":
                    meta["title"] = "System"
                vault._atomic_write(path, codec.dumps(vault._rewrite_refs(meta, mapping),
                    vault.canonical_body(body, item["ref"] + ".md", mapping)))
                row = state["categories"][key]
                row["published"]["article_sha256"] = _sha(path.read_bytes())
                categories[key] = row
            state["categories"] = categories
            vault._atomic_write(_receipt_path(), json.dumps(state, sort_keys=True, indent=2) + "\n")
            if prepare_flatten()["status"] != "already_migrated":
                raise ValueError("System flattening postcondition did not verify")
            completed = True
        except BaseException:
            for path in CONFIG.vault_dir.rglob("*.md"):
                if path.relative_to(CONFIG.vault_dir).as_posix() not in files:
                    path.unlink()
            for relative, raw in files.items():
                vault._atomic_write(CONFIG.vault_dir / relative, raw.decode())
            vault._atomic_write(_receipt_path(), receipt_raw.decode())
            raise
        finally:
            # Empty historical wrapper folders must not reappear as graph hubs.
            for path in sorted(CONFIG.vault_dir.rglob("*"), key=lambda p: len(p.parts), reverse=True):
                if path.is_dir() and not any(path.iterdir()) and (
                    path not in directories or (completed and path in obsolete)):
                    path.rmdir()
        return {**plan, "status": "migrated", "applied": True}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--flatten", action="store_true", help="Publish System without Hardware or application-detail wrappers")
    parser.add_argument("--expected-plan-sha256", help="Exact plan_sha256 from the reviewed dry run")
    args = parser.parse_args()
    if args.apply:
        if not args.expected_plan_sha256:
            parser.error("--apply requires --expected-plan-sha256 from the dry run")
        state = subprocess.run(["systemctl", "--user", "is-active", "obsidience-harness-dev.service"],
                               capture_output=True, text=True, check=False).stdout.strip()
        if state not in {"inactive", "failed"}:
            raise SystemExit("Stop the Harness and retain the Vault/SQLite/receipt backup before apply")
        result = (apply_flatten if args.flatten else apply)(args.expected_plan_sha256)
    else:
        result = {**(prepare_flatten() if args.flatten else prepare()), "applied": False}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

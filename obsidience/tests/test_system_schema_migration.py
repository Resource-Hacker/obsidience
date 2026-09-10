"""One-off System schema migration uses native moves and exact preflight pins."""

import json
import uuid

import pytest

from obsidience.harness import config
from obsidience.harness.knowledge import format as codec
from obsidience.harness.knowledge import vault
from obsidience.scripts import migrate_system_schema as migration


@pytest.fixture
def original_inventory(tmp_path, monkeypatch, isolated_task_ledger):
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config.CONFIG, "vault_dir", tmp_path / "vault")
    root = config.CONFIG.vault_dir
    system = config.CONFIG.system_dir
    system.mkdir(parents=True)
    (system / "system.json").write_text(json.dumps({
        "schema": "obsidience.system-node.v1", "id": "system", "label": "System",
        "category": "system", "read_only": True,
    }))
    for folder in ("hardware/compute", "hardware/drives", "hardware/devices",
                   "hardware/network", "applications/obsidience"):
        (system / folder).mkdir(parents=True)
    old_display = migration.ROOT + "/Hardware/Displays/display-topology-and-isolation-strategy--a8755cfa"
    for relative in (*migration.AUTHORED, *migration.RETAINED):
        ref = migration.ROOT + "/" + relative
        vault.write_note(ref + ".md", {"kind": "knowledge", "title": "Authored " + relative,
                         "obsidience": {"auto_curate": True}, "tags": ["invariant"]},
                         "Owner contract.\n\n[Display](/" + old_display.replace(" ", "%20") + ".md#Facts)")
    categories = {}
    for category, (old, _key, _new) in migration.GENERATED.items():
        source_id = str(uuid.uuid4())
        ref = migration.ROOT + "/" + old
        vault.write_note(ref + ".md", {"kind": "knowledge", "title": "Generated " + category,
                         "generated": {"by": "Obsidience System inventory", "at": "2026-09-10"},
                         "sources": [{"resource": "source://" + source_id}]},
                         "Captured facts. [Root](/ADMECH%20Workstation/ADMECH%20Workstation.md)")
        categories[category] = {"status": "current", "detail": "", "published": {
            "article_sha256": migration._sha((root / (ref + ".md")).read_bytes()),
            "source_id": source_id, "content_sha256": "sha256:" + "a" * 64,
            "captured_at": "2026-09-10T03:00:00Z",
        }}
    migration._receipt_path().write_text(json.dumps({
        "schema_version": 1, "updated_at": "2026-09-10T03:00:00Z", "categories": categories,
    }))
    vault.write_note("Outside.md", {"kind": "knowledge", "title": "External",
                     "related_refs": ["[[" + old_display + "]]"],
                     "sources": [{"resource": "source://unchanged-source"}]},
                     "[Display](/" + old_display.replace(" ", "%20") + ".md#Facts)\n\n"
                     "`[Example](/" + old_display.replace(" ", "%20") + ".md)`")
    for name in ("_archived/prior.md", "_staging/pending.md"):
        path = root / name
        path.parent.mkdir(parents=True)
        path.write_text("---\nproposal: pinned\n---\n[Display](/" + old_display + ".md)\n")
    return root, isolated_task_ledger


def snapshot():
    return migration._snapshot(), migration._receipt_path().read_bytes()


def test_dry_run_is_complete_and_read_only(original_inventory, monkeypatch):
    before = snapshot()
    monkeypatch.setattr(vault, "move_vault_item", lambda *args, **kwargs: pytest.fail("dry run moved"))
    plan = migration.prepare()
    assert plan["status"] == "ready"
    assert len(plan["moves"]) == 22
    assert plan["authored_moves"] == 19
    assert plan["generated_moves"] == 3
    assert len(plan["retained_observations"]) == 5
    assert "Outside.md" in plan["accepted_reference_updates"]
    assert not any(path.startswith("_") for path in plan["accepted_reference_updates"])
    assert snapshot() == before


def test_apply_preserves_authored_metadata_source_ids_and_history(original_inventory):
    root, ledger = original_inventory
    files, old_receipt = snapshot()
    plan = migration.prepare()
    result = migration.apply(plan["plan_sha256"])
    assert result["status"] == "migrated"
    mapping = migration.migration_mapping()
    for relative in (*migration.AUTHORED, *migration.RETAINED):
        old = migration.ROOT + "/" + relative
        new = mapping.get(old, old)
        old_meta, old_body = codec.loads(files[old + ".md"].decode())
        note = vault.load_note(new + ".md")
        assert note.meta == vault._rewrite_refs(old_meta, mapping)
        assert note.body == vault.canonical_body(old_body, old + ".md", mapping)
    for old, new in mapping.items():
        assert (root / (new + ".md")).is_file()
        if old not in mapping.values():
            assert not (root / (old + ".md")).exists()
    outside = vault.load_note("Outside.md")
    assert "/Workstation%20Observations/Hardware/Displays/" in outside.body
    assert "/Workstation Observations/Hardware/Displays/" in outside.meta["related_refs"][0]
    assert "`[Example](/ADMECH%20Workstation/Hardware/Displays/" in outside.body
    assert outside.meta["sources"] == [{"resource": "source://unchanged-source"}]
    for name in ("_archived/prior.md", "_staging/pending.md"):
        assert (root / name).read_bytes() == files[name]
    old_state = json.loads(old_receipt)
    state = json.loads(migration._receipt_path().read_bytes())
    assert state["schema_version"] == 2
    for old_key, (_old, key, new) in migration.GENERATED.items():
        receipt = state["categories"][key]["published"]
        previous = old_state["categories"][old_key]["published"]
        assert {k: v for k, v in receipt.items() if k != "article_sha256"} == {
            k: v for k, v in previous.items() if k != "article_sha256"}
        assert receipt["article_sha256"] == migration._sha((root / (migration.ROOT + "/" + new + ".md")).read_bytes())
    assert ledger.db.execute("SELECT COUNT(*) FROM task_runtime").fetchone()[0] == 0
    after = snapshot()
    repeated = migration.prepare()
    assert repeated["status"] == "already_migrated"
    assert migration.apply(repeated["plan_sha256"])["applied"] is False
    assert snapshot() == after


@pytest.mark.parametrize("changed", ["article", "inbound", "historical", "receipt", "schema"])
def test_change_since_preview_rejected_before_any_move(original_inventory, monkeypatch, changed):
    root, _ = original_inventory
    plan = migration.prepare()
    if changed == "receipt":
        path = migration._receipt_path()
    elif changed == "schema":
        path = config.CONFIG.system_dir / "system.json"
    else:
        path = root / {"article": migration.ROOT + "/Hardware/Hardware.md",
                       "inbound": "Outside.md", "historical": "_staging/pending.md"}[changed]
    if changed == "schema":
        data = json.loads(path.read_text()); data["label"] = "Changed System"
        path.write_text(json.dumps(data))
    else:
        path.write_text(path.read_text() + "\n")
    before = snapshot()
    monkeypatch.setattr(vault, "move_vault_item", lambda *args, **kwargs: pytest.fail("stale plan moved"))
    with pytest.raises(ValueError, match="changed since preview"):
        migration.apply(plan["plan_sha256"])
    assert snapshot() == before


@pytest.mark.parametrize("issue", ["collision", "extra", "receipt", "type"])
def test_preflight_rejects_invalid_inventory(original_inventory, issue):
    root, _ = original_inventory
    if issue == "collision":
        vault.write_note(migration.OBSERVATIONS + "/Hardware/Hardware.md",
                         {"kind": "knowledge", "title": "Collision"}, "Unrelated")
    elif issue == "extra":
        vault.write_note(migration.ROOT + "/New Article.md", {"kind": "knowledge", "title": "New"}, "New")
    elif issue == "receipt":
        path = root / (migration.ROOT + "/System Identity.md")
        path.write_text(path.read_text() + "Owner edit")
    else:
        path = root / (migration.ROOT + "/Hardware/Hardware.md")
        path.write_text(path.read_text().replace("type: knowledge", "type: task"))
    before = snapshot()
    with pytest.raises(ValueError):
        migration.prepare()
    assert snapshot() == before


@pytest.mark.parametrize("failure", ["move", "receipt", "postcondition"])
def test_batch_failure_rolls_back_prior_moves_and_all_inbound_edits(original_inventory, monkeypatch, failure):
    root, _ = original_inventory
    before = snapshot()
    plan = migration.prepare()
    real_move = vault.move_vault_item
    calls = []

    def move(*args, **kwargs):
        calls.append(args[0])
        if failure == "move" and len(calls) == 4:
            raise OSError("injected move failure")
        return real_move(*args, **kwargs)

    monkeypatch.setattr(vault, "move_vault_item", move)
    real_write = vault._atomic_write
    failed = False

    def write(path, content):
        nonlocal failed
        if failure == "receipt" and path == migration._receipt_path() and not failed:
            failed = True
            raise OSError("injected receipt failure")
        real_write(path, content)

    monkeypatch.setattr(vault, "_atomic_write", write)
    real_prepare = migration.prepare

    def prepare():
        if failure == "postcondition" and len(calls) == 22:
            raise OSError("injected postcondition failure")
        return real_prepare()

    monkeypatch.setattr(migration, "prepare", prepare)
    with pytest.raises(OSError, match="injected"):
        migration.apply(plan["plan_sha256"])
    assert calls
    assert snapshot() == before
    assert not (root / "ADMECH Workstation/Applications").exists()


def test_repeated_apply_rejects_incomplete_v2_receipt(original_inventory):
    plan = migration.prepare()
    migration.apply(plan["plan_sha256"])
    state = json.loads(migration._receipt_path().read_text())
    state["categories"].pop("system")
    migration._receipt_path().write_text(json.dumps(state))
    with pytest.raises(ValueError, match="publication receipt"):
        migration.prepare()


def test_noop_after_publisher_adds_schema_hardware_hub(original_inventory):
    plan = migration.prepare()
    migration.apply(plan["plan_sha256"])
    state = json.loads(migration._receipt_path().read_text())
    receipt = dict(state["categories"]["hardware/compute"]["published"])
    path = migration.ROOT + "/Hardware/Hardware.md"
    vault.write_note(path, {
        "kind": "knowledge", "title": "Hardware",
        "generated": {"by": "Obsidience System inventory"},
        "sources": [{"resource": "source://" + receipt["source_id"]}],
    }, "The new publisher's Hardware condensation.")
    receipt["article_sha256"] = migration._sha((config.CONFIG.vault_dir / path).read_bytes())
    state["categories"]["hardware"] = {"published": receipt, "status": "current", "detail": ""}
    migration._receipt_path().write_text(json.dumps(state))
    assert migration.prepare()["status"] == "already_migrated"


def test_private_move_seam_requires_exact_current_hash(original_inventory):
    root, _ = original_inventory
    source = migration.ROOT + "/System Identity.md"
    target = migration.OBSERVATIONS + "/Wrong.md"
    before = snapshot()
    with pytest.raises(ValueError, match="System migration"):
        vault.move_vault_item(source, migration.OBSERVATIONS,
                              _system_migration=("0" * 64, target))
    assert snapshot() == before


def test_unavailable_last_capture_keeps_its_status(original_inventory):
    state = json.loads(migration._receipt_path().read_text())
    state["categories"]["devices"].update(status="unavailable", detail="Capture was unavailable")
    migration._receipt_path().write_text(json.dumps(state))
    plan = migration.prepare()
    migration.apply(plan["plan_sha256"])
    state = json.loads(migration._receipt_path().read_text())
    assert state["categories"]["hardware/devices"]["status"] == "unavailable"
    assert state["categories"]["hardware/devices"]["detail"] == "Capture was unavailable"


def test_runtime_collision_is_rejected_before_changes(original_inventory):
    _root, ledger = original_inventory
    ledger.seed_task_runtime(migration.ROOT + "/ADMECH Workstation", {"status": "pending"})
    plan = migration.prepare()
    before = snapshot()
    with pytest.raises(ValueError, match="owning Task runtime"):
        migration.apply(plan["plan_sha256"])
    assert snapshot() == before

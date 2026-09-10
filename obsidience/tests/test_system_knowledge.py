"""System facts publish deterministically without replacing authored Knowledge."""

from copy import deepcopy
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from obsidience.harness import config
from obsidience.harness.capabilities.vault import maintenance, propose
from obsidience.harness.config import CONFIG
from obsidience.harness.knowledge import format as article_format, review, source, system, vault


@pytest.fixture
def inventory(tmp_path, monkeypatch, isolated_task_ledger):
    from obsidience.harness.host import system_evidence

    descriptors = Path(__file__).resolve().parents[2] / "obsidience/state/system"
    copied = list(descriptors.rglob("*.json"))
    assert len(copied) == 17
    for original in copied:
        target = tmp_path / "obsidience/state/system" / original.relative_to(descriptors)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, target)
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(CONFIG, "vault_dir", tmp_path / "obsidience/vault")
    monkeypatch.setattr(CONFIG, "git_commit", False)
    monkeypatch.setattr(system, "_INDEX_ERROR", "")
    facts = {
        "identity": {"hostname": "fixture-host", "operating_system": "Fixture OS", "kernel": "test-1"},
        "compute": {"cpu": {"model": "Fixture CPU", "logical_cpus": 8}, "memory": {"total_bytes": 8192},
                    "gpus": [{"label": "Fixture RTX 4000 Ada", "vendor_id": "0x10de", "memory_bytes": 4000},
                             {"label": "Fixture RTX 4080 SUPER", "vendor_id": "0x10de", "memory_bytes": 4080},
                             {"label": "Fixture AMD", "vendor_id": "0x1002", "memory_bytes": 1002}]},
        "storage": {"locations": [{"id": "obsidience", "total_bytes": 1024, "quota_bytes": None},
                                   {"id": "models", "total_bytes": 2048, "quota_bytes": None}],
                    "drives": [
                        {"id": "serial:" + serial, "serial": serial, "model": model, "wwn": wwn,
                         "device": "/dev/nvme" + str(index) + "n1", "total_bytes": 1000 * (index + 1),
                         "transport": "nvme", "read_only": index == 3, "filesystem": "", "uuid": "", "partuuid": "",
                         "mount_points": [], "partitions": [
                             {"device": "/dev/nvme" + str(index) + "n1p1", "type": "part", "total_bytes": 900,
                              "read_only": index == 3, "filesystem": "btrfs", "uuid": "fixture-" + str(index),
                              "partuuid": "part-" + str(index), "mount_points": ["/fixture/" + str(index)], "children": []}]}
                        for index, (serial, model, wwn) in enumerate([
                            ("2407E897AB30", "CT1000T705SSD5", "uuid.e6533516-bf6a-44b3-a940-c039b54f34dd"),
                            ("S73WNU0XB11863P", "Samsung SSD 990 PRO 2TB", "eui.0025384b41a2c2c7"),
                            ("S7KHNU0X757355N", "Samsung SSD 990 PRO 2TB", "eui.0025384741a25c94"),
                            ("S73WNU0XB11923L", "Samsung SSD 990 PRO 2TB", "eui.0025384b41a2c303"),
                        ])]},
        "devices": {"microphones": [{"id": "fixture-mic", "label": "Microphone"}],
                    "cameras": [{"id": "fixture-camera", "label": "Camera"}],
                    "speakers": [{"id": "fixture-speaker", "label": "Speaker"}]},
        "network": {"interfaces": [{"id": "fixture-net", "type": "ethernet"}]},
        "applications": {"applications": [{"desktop_id": "test.desktop", "label": "Test app"}]},
        "runtime": {"speech": {"asr": "fixture-asr", "tts": "fixture-tts"},
                    "hardware_assignments": {"fixture-model": "rtx4000"},
                    "media_selections": {"camera": "fixture-camera", "microphone": "fixture-mic",
                                         "speaker": "fixture-speaker"}},
    }
    collected = {category: {"status": "complete", "facts": values, "detail": ""}
                 for category, values in facts.items()}
    monkeypatch.setattr(system_evidence, "collect_system_evidence", lambda: deepcopy(collected))
    def no_event(_row):
        pytest.fail("System inventory must not emit an agent Source event")
    monkeypatch.setattr(source, "_source_event", no_event)
    from obsidience.harness.models import llm
    def no_model(*_args, **_kwargs):
        pytest.fail("System publication must not call a model")
    monkeypatch.setattr(llm, "chat", no_model)
    syncs = []
    monkeypatch.setattr(isolated_task_ledger, "sync", lambda: syncs.append(True))
    return collected, isolated_task_ledger, syncs


def _article(category="system"):
    return CONFIG.vault_dir / (system.system_articles()[category]["ref"] + ".md")


def _row(report, category):
    return next(row for row in report["categories"] if row["category"] == category)


def _files(root):
    return {str(path.relative_to(root)): (path.read_bytes(), path.stat().st_mtime_ns)
            for path in root.rglob("*.md")}


def test_initial_refresh_populates_native_knowledge_from_immutable_source_without_tasks(inventory):
    _facts, ledger, syncs = inventory
    assert system.system_knowledge_status()["status"] == "uninitialized"
    report = system.refresh_system_knowledge()
    assert report["status"] == "ready" and report["article_count"] == report["current_count"] == 22
    assert report["changed"] == 22 and len(syncs) == 1  # Every real schema node is generated.
    accepted = vault.iter_notes()
    assert len(accepted) == 22
    resolver = vault.Resolver(accepted)
    assert all(resolver.resolve(link) for note in accepted for link in note.links)
    for category, item in system.system_articles().items():
        note = vault.load_note(_article(category).relative_to(CONFIG.vault_dir))
        assert note.kind == "knowledge" and not note.runtime_observation
        raw, _body = article_format.parse(_article(category).read_text())
        assert not article_format.validate_profile(raw, note.path)
        assert raw["generated"]["by"] == "Obsidience System inventory"
        assert raw["tags"] == ["system-inventory"]
        citation = raw["sources"][0]["resource"]
        evidence = source.get_source(citation)
        assert evidence["immutable"] and evidence["source_ref"] == "system://schema." + category.replace("/", ".")
        assert evidence["content_sha256"] in note.body
        assert evidence["captured_at"] in note.body
        captured = json.loads(evidence["content"])
        assert captured["category"] == "schema." + category.replace("/", ".")
        assert captured["facts"]["system_path"] == (item["descriptor_path"] or item["path"])
        assert captured["facts"].get("descriptor") == item["descriptor"]
        assert captured["facts"]["children"] == [
            {"title": child["title"], "ref": child["ref"]}
            for child in system.system_articles().values() if child["parent_ref"] == item["ref"]]
        assert evidence["source_path"].startswith("obsidience/evidence/system/" + captured["category"] + "/")
        assert (CONFIG.project_root / evidence["source_path"]).is_file()
        assert source.validate_source_citations(note.body, required=True)[0]["id"] == evidence["id"]
    assert ledger.db.execute("SELECT count(*) FROM runs").fetchone()[0] == 0
    assert ledger.db.execute("SELECT count(*) FROM task_runtime").fetchone()[0] == 0
    assert not list(CONFIG.staging_dir.glob("*.md"))
    assert ledger.db.execute("SELECT count(*) FROM source_evidence WHERE event_key IS NOT NULL").fetchone()[0] == 0
    receipt = system._state_path().read_text()
    assert json.loads(receipt)["schema_version"] == 2
    assert "Fixture CPU" not in receipt and "fixture-host" not in receipt


def test_publication_has_exact_physical_schema_parity_and_no_invented_branches(inventory):
    expected = {
        "system", "applications", "hardware", "applications/obsidience", "applications/web-browser",
        "hardware/compute", "hardware/devices", "hardware/drives", "hardware/network",
        "applications/obsidience/model-assignments",
        "applications/obsidience/speech-runtime", "hardware/compute/amd-igpu", "hardware/compute/cpu",
        "hardware/compute/rtx-4000-ada", "hardware/compute/rtx-4080-super", "hardware/devices/camera",
        "hardware/devices/microphone", "hardware/devices/speaker", "hardware/drives/crucial-t705",
        "hardware/drives/samsung-990-pro-games", "hardware/drives/samsung-990-pro-storage",
        "hardware/drives/samsung-990-pro-windows",
    }
    catalog = system.system_articles()
    assert set(catalog) == expected
    assert catalog["hardware/network"]["parent_ref"] == catalog["hardware"]["ref"]
    assert catalog["hardware/network"]["ref"] == "ADMECH Workstation/Hardware/Network"
    assert catalog["applications/web-browser"]["ref"] == "ADMECH Workstation/Applications/Web Browser"
    assert catalog["applications/web-browser"]["parent_ref"] == catalog["applications"]["ref"]
    report = system.refresh_system_knowledge()
    assert {row["category"] for row in report["categories"]} == expected
    assert {note.ref for note in vault.iter_notes()} == {row["ref"] for row in catalog.values()}
    assert len({row["source_id"] for row in report["categories"]}) == len(expected)
    # The registered Web Browser descriptor is the only browser branch;
    # enumerating an unrelated installed application creates no new Article.
    assert not any("test.desktop" in note.body for note in vault.iter_notes())


def test_descriptor_selectors_publish_only_their_exact_observed_inventory(inventory):
    facts = {key: row["facts"] for key, row in inventory[0].items()}
    runtime = facts["runtime"]
    expected = {
        "system": facts["identity"],
        "hardware/compute/cpu": {"cpu": facts["compute"]["cpu"], "memory": facts["compute"]["memory"]},
        "hardware/compute/rtx-4000-ada": facts["compute"]["gpus"][0],
        "hardware/compute/rtx-4080-super": facts["compute"]["gpus"][1],
        "hardware/compute/amd-igpu": facts["compute"]["gpus"][2],
        "applications/obsidience": {"storage_locations": facts["storage"]["locations"]},
        "hardware/drives/crucial-t705": facts["storage"]["drives"][0],
        "hardware/drives/samsung-990-pro-games": facts["storage"]["drives"][1],
        "hardware/drives/samsung-990-pro-storage": facts["storage"]["drives"][2],
        "hardware/drives/samsung-990-pro-windows": facts["storage"]["drives"][3],
        "hardware/network": facts["network"],
        "applications/obsidience/model-assignments": {"hardware_assignments": runtime["hardware_assignments"]},
        "applications/obsidience/speech-runtime": {
            "speech": runtime["speech"], "media_selections": runtime["media_selections"]},
    }
    for selector, plural in (("camera", "cameras"), ("microphone", "microphones"), ("speaker", "speakers")):
        expected["hardware/devices/" + selector] = {
            "endpoints": facts["devices"][plural],
            "configured_selection": runtime["media_selections"][selector],
        }
    report = system.refresh_system_knowledge()
    assert report["status"] == "ready"
    for row in report["categories"]:
        captured = json.loads(source.get_source(row["source_id"])["content"])["facts"]
        if row["category"] in expected:
            assert captured["observed"] == expected[row["category"]]
        else:
            assert "observed" not in captured


@pytest.mark.parametrize("failure", ["missing", "serial", "model", "wwn", "ambiguous"])
def test_physical_drive_identity_failure_preserves_accepted_article(inventory, failure):
    category = "hardware/drives/samsung-990-pro-games"
    original = system.refresh_system_knowledge()
    original_row = _row(original, category)
    before = _files(CONFIG.vault_dir)
    drives = inventory[0]["storage"]["facts"]["drives"]
    if failure == "missing":
        del drives[1]
    elif failure == "ambiguous":
        drives.append(deepcopy(drives[1]))
    else:
        drives[1][failure] = "wrong-identity"

    report = system.refresh_system_knowledge()
    row = _row(report, category)
    assert report["status"] == "degraded" and report["changed"] == 0
    assert row["status"] == "unavailable" and row["detail"]
    assert row["source_id"] == original_row["source_id"]
    assert row["source_citation"] == original_row["source_citation"]
    assert _files(CONFIG.vault_dir) == before
    assert all(item["status"] == "current" for item in report["categories"] if item["category"] != category)


def test_storage_locations_belong_to_obsidience_without_invented_drive_nodes(inventory):
    report = system.refresh_system_knowledge()
    app = _row(report, "applications/obsidience")
    facts = json.loads(source.get_source(app["source_citation"])["content"])["facts"]
    assert facts["observed"] == {"storage_locations": inventory[0]["storage"]["facts"]["locations"]}
    catalog = system.system_articles()
    assert {key for key in catalog if key.startswith("hardware/drives/")} == {
        "hardware/drives/crucial-t705", "hardware/drives/samsung-990-pro-games",
        "hardware/drives/samsung-990-pro-storage", "hardware/drives/samsung-990-pro-windows",
    }
    before = _article("applications/obsidience").read_bytes()
    inventory[0]["storage"] = {"status": "unavailable", "facts": {}, "detail": "Storage collector offline"}
    degraded = system.refresh_system_knowledge()
    unavailable = _row(degraded, "applications/obsidience")
    assert degraded["status"] == "degraded" and unavailable["status"] == "unavailable"
    assert unavailable["source_id"] == app["source_id"]
    assert _article("applications/obsidience").read_bytes() == before


def test_identical_refresh_preserves_source_and_article_bytes_and_retries_index(inventory):
    system.refresh_system_knowledge()
    before_articles, before_sources = _files(CONFIG.vault_dir), _files(CONFIG.source_dir)
    before = system.system_knowledge_status()
    result = system.refresh_system_knowledge()
    assert result["changed"] == 0 and result["status"] == "ready"
    assert _files(CONFIG.vault_dir) == before_articles
    assert _files(CONFIG.source_dir) == before_sources
    assert result["categories"] == before["categories"]
    assert len(inventory[2]) == 2


def test_legacy_receipt_requires_explicit_migration_and_preserves_existing_bytes(inventory):
    system.refresh_system_knowledge()
    before = _files(CONFIG.vault_dir), _files(CONFIG.source_dir)
    receipt = json.loads(system._state_path().read_text())
    receipt["schema_version"] = 1
    system._state_path().write_text(json.dumps(receipt))
    report = system.refresh_system_knowledge()
    assert report["status"] == "degraded" and report["changed"] == 0
    assert all(row["status"] == "conflict" for row in report["categories"])
    assert (_files(CONFIG.vault_dir), _files(CONFIG.source_dir)) == before
    assert json.loads(system._state_path().read_text())["schema_version"] == 1


def test_existing_authored_hubs_and_contracts_remain_exact(inventory):
    for ref in {"ADMECH Workstation/Workstation Observations/Workstation Observations",
                "ADMECH Workstation/Workstation Observations/Displays/Displays"}:
        vault.write_note(ref + ".md", {"kind": "knowledge", "title": "Owner title", "custom": "preserve"},
                         "Exact owner instructions. No changes.")
    vault.write_note("ADMECH Workstation/Workstation Observations/Owner policy.md", {"title": "Owner policy"}, "Owner display policy.")
    before = _files(CONFIG.vault_dir)
    result = system.refresh_system_knowledge(sync=False)
    assert result["changed"] == 22 and not inventory[2]
    after = _files(CONFIG.vault_dir)
    assert all(after[path] == content for path, content in before.items())


def test_changed_facts_have_new_evidence_and_keep_old_source(inventory):
    before = system.refresh_system_knowledge()
    original = _row(before, "system")["source_citation"]
    old_evidence = source.get_source(original)
    inventory[0]["identity"]["facts"]["kernel"] = "test-2"
    result = system.refresh_system_knowledge()
    assert result["changed"] == 1
    assert _row(result, "system")["source_citation"] != original
    assert source.get_source(original)["content"] == old_evidence["content"]
    assert "test-2" in _article().read_text()


def test_unavailable_category_preserves_last_good_article_and_citation(inventory):
    before = system.refresh_system_knowledge()
    article = _article().read_bytes()
    inventory[0]["identity"] = {"status": "unavailable", "facts": {}, "detail": "Inventory command failed"}
    result = system.refresh_system_knowledge()
    assert result["status"] == "degraded" and result["changed"] == 0
    assert _row(result, "system")["status"] == "unavailable"
    assert _row(result, "system")["source_id"] == _row(before, "system")["source_id"]
    assert _article().read_bytes() == article
    assert system.system_knowledge_status()["status"] == "degraded"


@pytest.mark.parametrize("failure", ["missing", "unavailable"])
def test_first_refresh_without_collector_has_no_dangling_links_and_recovers(inventory, failure):
    collected = inventory[0]
    available_compute = collected.pop("compute")
    if failure == "unavailable":
        collected["compute"] = {"status": "unavailable", "facts": {}, "detail": "Collector offline"}
    descriptors = {path: (path.read_bytes(), path.stat().st_mtime_ns)
                   for path in CONFIG.system_dir.rglob("*.json")}
    catalog = system.system_articles()
    missing = {row["ref"] for category, row in catalog.items() if category.startswith("hardware/compute/")}

    report = system.refresh_system_knowledge()
    assert report["status"] == "degraded"
    accepted = vault.iter_notes()
    assert {note.ref for note in accepted} == {row["ref"] for row in catalog.values()} - missing
    resolver = vault.Resolver(accepted)
    assert all(resolver.resolve(link) for note in accepted for link in note.links)
    assert all((path.read_bytes(), path.stat().st_mtime_ns) == before for path, before in descriptors.items())
    before_articles = _files(CONFIG.vault_dir)

    collected["compute"] = available_compute
    recovered = system.refresh_system_knowledge()
    assert recovered["status"] == "ready" and recovered["current_count"] == recovered["article_count"] == 22
    assert recovered["changed"] == len(missing)
    accepted = vault.iter_notes()
    assert {note.ref for note in accepted} == {row["ref"] for row in catalog.values()}
    resolver = vault.Resolver(accepted)
    assert all(resolver.resolve(link) for note in accepted for link in note.links)
    after_articles = _files(CONFIG.vault_dir)
    assert all(after_articles[path] == before for path, before in before_articles.items())
    assert all((path.read_bytes(), path.stat().st_mtime_ns) == before for path, before in descriptors.items())


def test_collector_failure_degrades_without_live_mutation(inventory, monkeypatch):
    from obsidience.harness.host import system_evidence
    system.refresh_system_knowledge()
    before = _files(CONFIG.vault_dir)
    monkeypatch.setattr(system_evidence, "collect_system_evidence", lambda: (_ for _ in ()).throw(OSError("offline")))
    result = system.refresh_system_knowledge()
    assert result["status"] == "degraded" and result["changed"] == 0
    assert _files(CONFIG.vault_dir) == before


@pytest.mark.parametrize("existing", ["authored", "edited", "removed"])
def test_conflicting_article_is_never_overwritten_or_recreated(inventory, existing):
    if existing == "authored":
        vault.write_note(str(_article().relative_to(CONFIG.vault_dir)), {"title": "Owner content"}, "Keep this.")
    else:
        system.refresh_system_knowledge()
        if existing == "edited":
            _article().write_text(_article().read_text() + "Owner correction.\n")
        else:
            _article().unlink()
    before = _article().read_bytes() if _article().exists() else None
    inventory[0]["identity"]["facts"]["hostname"] = "different-host"
    result = system.refresh_system_knowledge()
    assert _row(result, "system")["status"] == "conflict"
    assert (_article().read_bytes() if _article().exists() else None) == before


@pytest.mark.parametrize("boundary", ["before_write", "after_write"])
def test_publication_intent_recovers_crash_without_duplicate_source_or_effect(inventory, monkeypatch, boundary):
    class Crash(BaseException):
        pass
    real_write = system.write_note
    calls = []
    def interrupted(path, meta, body):
        if path == str(_article().relative_to(CONFIG.vault_dir)):
            calls.append(path)
            if boundary == "after_write":
                real_write(path, meta, body)
            raise Crash()
        return real_write(path, meta, body)
    monkeypatch.setattr(system, "write_note", interrupted)
    with pytest.raises(Crash):
        system.refresh_system_knowledge()
    state = json.loads(system._state_path().read_text())
    pending = state["categories"]["system"]["pending"]
    source_id = pending["source_id"]
    if boundary == "after_write":
        assert hashlib.sha256(_article().read_bytes()).hexdigest() == pending["article_sha256"]
    writes = []
    def resumed(path, meta, body):
        writes.append(path)
        return real_write(path, meta, body)
    monkeypatch.setattr(system, "write_note", resumed)
    result = system.refresh_system_knowledge()
    assert result["status"] == "ready"
    assert _row(result, "system")["source_id"] == source_id
    identity_written = str(_article().relative_to(CONFIG.vault_dir)) in writes
    assert identity_written is (boundary == "before_write")
    assert inventory[1].db.execute("SELECT count(*) FROM source_evidence").fetchone()[0] == 22


def test_failed_index_is_visible_and_identical_refresh_retries(inventory, monkeypatch):
    _facts, ledger, syncs = inventory
    monkeypatch.setattr(ledger, "sync", lambda: (_ for _ in ()).throw(OSError("index unavailable")))
    report = system.refresh_system_knowledge()
    assert report["status"] == "degraded" and "index" in report["detail"]
    assert system.system_knowledge_status()["status"] == "degraded"
    before = _files(CONFIG.vault_dir)
    monkeypatch.setattr(ledger, "sync", lambda: syncs.append(True))
    result = system.refresh_system_knowledge()
    assert result["status"] == "ready" and result["changed"] == 0
    assert system.system_knowledge_status()["status"] == "ready"
    assert _files(CONFIG.vault_dir) == before and syncs == [True]


@pytest.mark.parametrize("action", ["create", "update", "archive"])
def test_model_proposals_cannot_claim_reserved_paths_even_without_marker(inventory, action):
    with pytest.raises(ValueError, match="System inventory"):
        propose.stage_proposal({"target": system.system_articles()["hardware/compute/cpu"]["ref"], "action": action,
                               "title": "Fake", "body": "Invented facts", "metadata": {"generated": {"by": "owner"}}}, {})


def test_single_and_group_approval_cannot_bypass_reserved_path(inventory):
    path = CONFIG.staging_dir / "forged.md"
    meta = {"title": "Invented", "kind": "knowledge", "action": "create", "task": "", "agent": "model",
            "run_id": "forged", "target": system.system_articles()["hardware/compute/cpu"]["ref"] + ".md", "review_class": "article", "authored_fields": []}
    vault.write_note(str(path.relative_to(CONFIG.vault_dir)), meta, "Invented facts.")
    row, = review.list_proposals()
    assert not row["approvable"] and "System inventory" in row["blocked_reason"]
    with pytest.raises(ValueError, match="System inventory"):
        review.approve(path.name)
    with pytest.raises(ValueError, match="System inventory"):
        review._validate_group([(path, meta, "Invented facts.")])
    assert not _article("hardware/compute/cpu").exists()


@pytest.mark.parametrize("ref", ["ADMECH Workstation", "ADMECH Workstation/Hardware",
                                  "ADMECH Workstation/Hardware/Compute", "ADMECH Workstation/System Identity.md"])
def test_move_of_generated_article_or_ancestor_is_rejected(inventory, ref):
    system.refresh_system_knowledge()
    before = _files(CONFIG.vault_dir)
    with pytest.raises(ValueError, match="System inventory"):
        vault.move_vault_item(ref, "", "Other")
    assert _files(CONFIG.vault_dir) == before


def test_generated_paths_and_branch_aliases_are_protected_without_blocking_observations(inventory):
    for item in system.system_articles().values():
        assert system.is_system_article(item["ref"])
        assert system.is_system_article(item["ref"] + ".md")
    assert system.is_system_article("@branch/ADMECH Workstation/Hardware/Compute")
    assert system.is_system_article("ADMECH Workstation/Hardware/Hardware")
    assert not system.is_system_article("ADMECH Workstation/Workstation Observations/Workstation Observations")
    system.assert_system_article_writable("ADMECH Workstation/Workstation Observations/Owner policy")
    with pytest.raises(ValueError, match="System inventory"):
        system.assert_system_article_writable("ADMECH Workstation/Hardware/Unregistered/Injected")


def test_managed_facts_are_not_maintenance_candidates_but_remain_link_targets(inventory):
    system.refresh_system_knowledge()
    target = system.system_articles()["hardware/compute/cpu"]["ref"]
    vault.write_note("ADMECH Workstation/Workstation Observations/Owner contract.md", {"title": "Owner contract"},
                     f"The compute inventory is recorded [here](/{target.replace(' ', '%20')}.md).")
    res = vault.resolver()
    assert res.resolve(res.resolve("ADMECH Workstation/Workstation Observations/Owner contract").links[0]).ref == target
    for candidate in maintenance._maintenance_candidates()["candidates"]:
        assert not any(system.is_system_article(ref) for ref in candidate["refs"])


def test_large_inventory_is_explicit_excerpt_and_source_stays_complete(inventory):
    inventory[0]["devices"]["facts"]["microphones"] = [
        {"id": f"mic-{i}", "label": f"Microphone {i}"} for i in range(205)]
    result = system.refresh_system_knowledge()
    assert result["status"] == "ready"
    key = "hardware/devices/microphone"
    assert "Showing 200 of 205" in _article(key).read_text()
    evidence = source.get_source(_row(result, key)["source_id"])
    assert len(json.loads(evidence["content"])["facts"]["observed"]["endpoints"]) == 205

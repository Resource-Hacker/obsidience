"""One read-only System catalog supplies exact physical and Knowledge identities."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from obsidience.harness import config
from obsidience.harness.knowledge import system_schema as schema


def descriptor(label="CPU", **extra):
    return {"schema": "obsidience.system-node.v1", "id": "observed-cpu",
            "label": label, "category": "compute", "read_only": True, **extra}


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    root = config.CONFIG.system_dir
    (root / "hardware/compute").mkdir(parents=True)
    (root / "applications/browser").mkdir(parents=True)
    (root / "system.json").write_text(json.dumps(descriptor("SYSTEM")))
    (root / "hardware/compute/cpu.json").write_text(json.dumps(descriptor("Ryzen 9")))
    (root / "applications/browser/application.json").write_text(json.dumps(descriptor("Web Browser")))
    (root / "applications/browser/runtime.json").write_text(json.dumps(descriptor("Current runtime")))
    return root


def test_real_folders_are_hubs_root_and_application_are_absorbed(catalog):
    rows = schema.system_schema()
    by_key = {row["key"]: row for row in rows}
    assert set(by_key) == {"system", "hardware", "hardware/compute", "hardware/compute/cpu",
                           "applications", "applications/browser", "applications/browser/runtime"}
    assert by_key["system"]["ref"] == "ADMECH Workstation/ADMECH Workstation"
    assert by_key["system"]["parent_ref"] is None
    assert by_key["system"]["title"] == "System"
    app = by_key["applications/browser"]
    assert app["title"] == "Web Browser"
    assert app["ref"] == "ADMECH Workstation/Applications/Browser/Browser"
    assert app["parent_ref"] == "ADMECH Workstation/Applications/Applications"
    assert app["path"] == "obsidience/state/system/applications/browser"
    assert app["descriptor_path"] == app["path"] + "/application.json"
    cpu = by_key["hardware/compute/cpu"]
    assert cpu["title"] == "Ryzen 9"
    assert cpu["ref"] == "ADMECH Workstation/Hardware/Compute/Cpu"
    assert cpu["parent_ref"] == "ADMECH Workstation/Hardware/Compute/Compute"
    assert cpu["path"] == cpu["descriptor_path"] == "obsidience/state/system/hardware/compute/cpu.json"
    for row in rows:
        assert (config.CONFIG.project_root / row["path"]).exists()
        assert row["parent_ref"] is None or row["parent_ref"] in {item["ref"] for item in rows}


def test_labels_can_change_without_changing_stable_file_references(catalog):
    before = {row["key"]: row["ref"] for row in schema.system_schema()}
    (catalog / "hardware/compute/cpu.json").write_text(json.dumps(descriptor("Replacement CPU")))
    after = schema.system_schema()
    assert {row["key"]: row["ref"] for row in after} == before
    assert next(row for row in after if row["key"] == "hardware/compute/cpu")["title"] == "Replacement CPU"


def test_flat_inventory_leaves_do_not_create_duplicate_wrapper_hubs(catalog):
    (catalog / "hardware/network.json").write_text(json.dumps(descriptor("Network", category="network")))
    (catalog / "applications/web-browser.json").write_text(json.dumps(descriptor("Web Browser", category="application")))
    rows = {row["key"]: row for row in schema.system_schema()}
    for key, parent, title in (("hardware/network", "hardware", "Network"),
                               ("applications/web-browser", "applications", "Web Browser")):
        row = rows[key]
        assert row["title"] == title
        assert row["parent_ref"] == rows[parent]["ref"]
        assert row["ref"] == rows[parent]["ref"].rsplit("/", 1)[0] + "/" + title
        assert row["path"] == row["descriptor_path"] == "obsidience/state/system/" + key + ".json"
        assert not any(other.startswith(key + "/") for other in rows)
        breadcrumbs = schema.system_source_metadata()[row["path"]]["system_breadcrumbs"]
        assert [crumb["path"] for crumb in breadcrumbs] == [
            "obsidience/state/system", "obsidience/state/system/" + parent]


def test_exact_source_metadata_reuses_folder_labels_without_claiming_virtual_paths(catalog):
    metadata = schema.system_source_metadata()
    key = "obsidience/state/system/applications/browser/runtime.json"
    assert metadata[key] == {"system_label": "Current runtime", "system_breadcrumbs": [
        {"path": "obsidience/state/system", "title": "System"},
        {"path": "obsidience/state/system/applications", "title": "Applications"},
        {"path": "obsidience/state/system/applications/browser", "title": "Web Browser"},
    ]}
    assert len(metadata) == 4
    assert all((config.CONFIG.project_root / path).is_file() for path in metadata)


def test_reading_is_deterministic_and_never_executes_descriptive_collector(catalog):
    cpu = catalog / "hardware/compute/cpu.json"
    cpu.write_text(json.dumps(descriptor(collector="nonexistent.module.would_mutate")))
    # Evidence captures and unrelated runtime state are outside this schema.
    (catalog / "snapshots").mkdir()
    (catalog / "snapshots/corrupt.json").write_text("not a descriptor")
    files = list(catalog.rglob("*"))
    before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in files if path.is_file()}
    first = json.dumps(schema.system_schema(), sort_keys=True)
    assert json.dumps(schema.system_schema(), sort_keys=True) == first
    assert {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in before} == before
    assert all("snapshots" not in row["key"] for row in schema.system_schema())


@pytest.mark.parametrize("change", [
    {"schema": "other"}, {"read_only": False}, {"read_only": 1},
    {"id": ""}, {"label": "Bad\nlabel"}, {"category": None}, {"selector": []},
])
def test_invalid_descriptors_fail_the_catalog_instead_of_omitting_rows(catalog, change):
    (catalog / "hardware/compute/cpu.json").write_text(json.dumps(descriptor(**change)))
    with pytest.raises(ValueError, match="Invalid read-only"):
        schema.system_schema()


@pytest.mark.parametrize("content", ["{broken", '{"schema": NaN}', '{"schema": Infinity}'])
def test_malformed_json_is_explicit(catalog, content):
    (catalog / "hardware/compute/cpu.json").write_text(content)
    with pytest.raises(ValueError):
        schema.system_schema()


@pytest.mark.parametrize("relative", ["hardware/compute/cpu.json", "hardware/compute", "system.json"])
def test_symlinks_are_never_followed(catalog, tmp_path, relative):
    target = catalog / relative
    outside = tmp_path / "external"
    target.rename(outside)
    target.symlink_to(outside, target_is_directory=outside.is_dir())
    with pytest.raises(ValueError, match="symlinks"):
        schema.system_schema()


@pytest.mark.parametrize("filename", ["CPU.json", "cpu_test.json", "cpu.extra.json", "bad:name.json"])
def test_ambiguous_evidence_key_syntax_is_rejected(catalog, filename):
    (catalog / "hardware/compute" / filename).write_text(json.dumps(descriptor()))
    with pytest.raises(ValueError, match="exact Article"):
        schema.system_schema()


def test_leaf_cannot_collide_with_existing_folder_article(catalog):
    (catalog / "hardware/compute/compute.json").write_text(json.dumps(descriptor()))
    with pytest.raises(ValueError, match="ambiguous Article"):
        schema.system_schema()


@pytest.mark.parametrize("bound,value,message", [
    ("MAX_SYSTEM_ENTRIES", 4, "entry bound"),
    ("MAX_SYSTEM_DEPTH", 1, "depth bound"),
    ("MAX_DESCRIPTOR_BYTES", 20, "byte bound"),
    ("MAX_CATALOG_BYTES", 20, "byte bound"),
])
def test_bounds_fail_explicitly_instead_of_returning_partial_schema(catalog, monkeypatch, bound, value, message):
    monkeypatch.setattr(schema, bound, value)
    with pytest.raises(ValueError, match=message):
        schema.system_schema()


def test_missing_required_root_descriptor_and_branch_fail(catalog):
    (catalog / "system.json").unlink()
    with pytest.raises(ValueError, match="regular JSON file"):
        schema.system_schema()
    (catalog / "system.json").write_text(json.dumps(descriptor()))
    (catalog / "applications").rename(catalog / "retired-applications")
    with pytest.raises(ValueError, match="Hardware and Applications"):
        schema.system_schema()


def test_category_identity_length_is_bounded_before_capture(catalog):
    directory = catalog / "hardware" / ("a" * 100) / ("b" * 100)
    directory.mkdir(parents=True)
    with pytest.raises(ValueError, match="evidence identity bound"):
        schema.system_schema()

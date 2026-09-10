from __future__ import annotations

from types import SimpleNamespace

import pytest

from obsidience.harness import config
from obsidience.harness.knowledge import source, vault


@pytest.fixture
def source_tree(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config.CONFIG, "vault_dir", tmp_path / "obsidience/vault")
    notes = []
    monkeypatch.setattr(vault, "iter_notes", lambda: iter(notes))

    def write(key, body="example"):
        path = tmp_path / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
        return path

    return tmp_path, notes, write


def test_inventory_pages_cover_all_sources_without_starving_system(source_tree):
    root, notes, write = source_tree
    expected = [f"obsidience/evidence/raw/{index}.txt" for index in range(5)]
    expected += ["obsidience/harness/Stage.py", "obsidience/harness/stage.py",
                 "obsidience/state/system/system.json", "obsidience/vault/Knowledge/page.md"]
    for key in expected:
        write(key)
    notes.append(SimpleNamespace(ref="Knowledge/page", path="Knowledge/page.md", body="", meta={}))
    before = {key: ((root / key).read_bytes(), (root / key).stat().st_mtime_ns) for key in expected}

    found, cursor = [], None
    while True:
        page = source.list_source_files(after=cursor, limit=2)
        assert page["issues"] == []
        assert page["coverage"]["returned"] == len(page["files"]) <= 2
        assert page["coverage"]["consistency"] == "live"
        assert page["coverage"]["scope"] is None
        found.extend(row["key"] for row in page["files"])
        cursor = page["coverage"]["next_cursor"]
        if page["coverage"]["complete"]:
            assert cursor is None
            break
        assert cursor == page["files"][-1]["key"]
    assert found == sorted(expected, key=lambda key: (key.casefold(), key))
    assert len(set(found)) == len(expected)
    assert before == {key: ((root / key).read_bytes(), (root / key).stat().st_mtime_ns) for key in expected}


def test_exact_reader_and_scope_exist_outside_first_page(source_tree):
    _root, _notes, write = source_tree
    for index in range(5):
        write(f"obsidience/evidence/raw/{index}.txt")
    key = "obsidience/state/system/system.json"
    write(key, '{"read_only":true}')
    assert key not in [row["key"] for row in source.list_source_files(limit=2)["files"]]
    assert source.get_source_file(key)["content"] == '{"read_only":true}'
    page = source.list_source_files(scope="obsidience/state/system", limit=2)
    assert [row["key"] for row in page["files"]] == [key]
    assert page["files"][0]["storage"] == "system"
    assert page["coverage"]["complete"] is True
    assert source.source_tree_exists("obsidience/state/system") is True
    assert source.source_tree_exists("obsidience/state/syste") is False
    assert source.source_tree_exists(key, folder_only=False) is True
    assert source.source_tree_exists(key) is False


def test_exact_capacity_does_not_mistake_skipped_entries_for_another_page(source_tree):
    root, _notes, write = source_tree
    write("obsidience/evidence/a.txt")
    write("obsidience/evidence/b.txt")
    write("obsidience/evidence/.hidden.txt")
    write("obsidience/evidence/.hidden/other.txt")
    (root / "obsidience/evidence/empty").mkdir()
    (root / "obsidience/evidence/link.txt").symlink_to(root / "obsidience/evidence/a.txt")
    page = source.list_source_files(limit=2)
    assert page["coverage"]["complete"] is True
    assert page["coverage"]["next_cursor"] is None
    assert page["issues"] == []
    write("obsidience/evidence/c.txt")
    assert source.list_source_files(limit=2)["coverage"]["complete"] is False


def test_linked_files_share_page_bound_and_missing_links_are_audited_outside_scope(source_tree):
    _root, notes, write = source_tree
    for index in range(3):
        write(f"obsidience/evidence/{index}.txt")
    key = "support/linked.txt"
    write(key, "Accepted explicit Source")
    notes.append(SimpleNamespace(ref="Knowledge/example", path="Knowledge/example.md", body="", meta={
        "sources": [key, "support/missing.txt"],
    }))
    page = source.list_source_files(scope="obsidience/evidence", limit=1)
    assert len(page["files"]) == 1
    assert page["coverage"]["complete"] is False
    assert page["issues"][0]["path"] == "support/missing.txt"
    assert page["issues"][0]["status"] == "missing"
    exact = source.get_source_file(key)
    assert exact["articles"] == ["Knowledge/example"]
    assert exact["content"] == "Accepted explicit Source"


def test_page_selection_bounds_content_and_stat_projection(source_tree, monkeypatch):
    _root, _notes, write = source_tree
    for index in range(20):
        write(f"obsidience/evidence/{index:02}.txt")
    projected = []
    original = source._source_record

    def project(*args):
        projected.append(args[0])
        return original(*args)

    monkeypatch.setattr(source, "_source_record", project)
    source.list_source_files(limit=2)
    assert projected == ["obsidience/evidence/00.txt", "obsidience/evidence/01.txt"]


def test_scoped_checkout_associations_follow_all_pages(source_tree, monkeypatch):
    _root, notes, write = source_tree
    for index in range(5):
        key = f"obsidience/evidence/{index}.txt"
        write(key)
        notes.append(SimpleNamespace(ref=f"Knowledge/{index}", path=f"Knowledge/{index}.md", body="", meta={"source": key}))
    original = source.list_source_files
    monkeypatch.setattr(source, "list_source_files", lambda **kwargs: original(**kwargs, limit=2))
    assert source.article_refs_for_trees(["obsidience/evidence"]) == [f"Knowledge/{index}" for index in range(5)]


def test_fixed_project_files_are_not_repeated_across_pages(source_tree):
    _root, _notes, write = source_tree
    keys = [".gitignore", "AGENTS.md", "obsidience/shell/session/greetd.toml",
            "obsidience/shell/session/install-session"]
    for key in keys:
        write(key)
    page = source.list_source_files(limit=10)
    assert len(page["files"]) == len(keys)
    assert {row["key"] for row in page["files"]} == set(keys)
    assert source.get_source_file(".gitignore")["path"] == ".gitignore"


@pytest.mark.parametrize("args", [{"limit": 0}, {"limit": 2001}, {"limit": True},
                                 {"scope": "../private"}, {"after": "/etc/passwd"},
                                 {"after": "obsidience/../private"},
                                 {"scope": "obsidience/evidence", "after": "docs/a.md"}])
def test_invalid_listing_boundaries_are_rejected(source_tree, args):
    with pytest.raises(source.SourceError):
        source.list_source_files(**args)


@pytest.mark.parametrize("key", ["../private.txt", "/etc/passwd", "obsidience/state/private.txt",
                                "obsidience/evidence/.hidden.txt", "@view/system"])
def test_direct_reader_does_not_broaden_source_authority(source_tree, key):
    _root, _notes, write = source_tree
    write("obsidience/state/private.txt", "private")
    write("obsidience/evidence/.hidden.txt", "private")
    with pytest.raises(source.SourceError, match="not found"):
        source.get_source_file(key)


def test_listing_and_direct_reader_reject_symlinked_scopes(source_tree):
    root, _notes, write = source_tree
    write("private/secret.txt")
    link = root / "obsidience/evidence/linked"
    link.parent.mkdir(parents=True)
    link.symlink_to(root / "private", target_is_directory=True)
    assert source.list_source_files(scope="obsidience/evidence/linked")["files"] == []
    with pytest.raises(source.SourceError, match="not found"):
        source.get_source_file("obsidience/evidence/linked/secret.txt")


def test_empty_inventory_does_not_create_source_directories(source_tree):
    root, _notes, _write = source_tree
    before = set(root.rglob("*"))
    page = source.list_source_files()
    assert page["files"] == []
    assert page["issues"] == []
    assert page["coverage"]["complete"] is True
    assert set(root.rglob("*")) == before

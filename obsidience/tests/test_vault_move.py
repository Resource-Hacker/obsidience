import pytest

from obsidience.harness.config import CONFIG
from obsidience.harness.knowledge import format as article_format
from obsidience.harness.knowledge import vault


@pytest.fixture
def move_vault(tmp_path, monkeypatch, isolated_task_ledger):
    root = tmp_path / "vault"
    root.mkdir()
    monkeypatch.setattr(CONFIG, "vault_dir", root)
    return root, isolated_task_ledger


def _article(path, title, body="", **meta):
    vault.write_note(path, {"kind": "knowledge", "title": title, "article_status": "stable", **meta}, body)


def _snapshot(root):
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_folder_rename_moves_own_hub_and_preserves_nested_hubs_runtime_and_links(move_vault):
    root, ledger = move_vault
    _article("Collection/Collection.md", "Collection", "[Work](task.md#Outcome)")
    _article("Collection/Nested/Nested.md", "Nested", "[Parent](/Collection/Collection.md)")
    state = {
        "status": "review", "last_run": "review-run", "summary": "Awaiting owner.",
        "params": {"event": "task.create", "activation_key": "current", "target": "Collection/task"},
        "event_queue": [{"activation_key": "next", "request": "exact waiting input"}],
    }
    _article("Collection/task.md", "Task", kind="task", **state)
    ledger.record_run(id="review-run", task_ref="Collection/task", started=1, finished=2,
                      agent="test", status="review", summary="Awaiting owner.", trace="[]")
    _article("Outside.md", "Outside", "[Hub](/Collection/Collection.md#Facts)\n\n"
             "[Work][task]\n\n[task]: /Collection/task.md\n\n"
             "`[example](/Collection/task.md)`", related_refs=["[[Collection/Collection]]"])
    vault._atomic_write(root / "index.md", "# Listing\n\n[Collection](/Collection/Collection.md)\n")

    result = vault.move_vault_item("Collection", "", "Renamed")

    assert result["refs"]["Collection/Collection"] == "Renamed/Renamed"
    assert result["refs"]["Collection/Nested/Nested"] == "Renamed/Nested/Nested"
    assert not (root / "Collection").exists()
    assert not (root / "Renamed/Collection.md").exists()
    hub = vault.load_note("Renamed/Renamed.md")
    assert hub.title == "Renamed"
    assert hub.links == ["Renamed/task"]
    assert vault.is_folder_article(hub)
    assert vault.is_folder_article(vault.load_note("Renamed/Nested/Nested.md"))
    assert ledger.task_runtime("Collection/task") is None
    assert {k:v for k,v in ledger.task_runtime("Renamed/task").items() if k != "activation_id"} == state
    assert vault.load_note("Renamed/task.md").meta["status"] == "review"
    assert ledger.run("review-run")["task_ref"] == "Collection/task"
    outside = vault.load_note("Outside.md")
    assert "[Hub](/Renamed/Renamed.md#Facts)" in outside.body
    assert "[task]: /Renamed/task.md" in outside.body
    assert "`[example](/Collection/task.md)`" in outside.body
    assert outside.meta["related_refs"] == ["[[Renamed/Renamed]]"]
    listing_meta, listing_body = article_format.parse((root / "index.md").read_text())
    assert listing_meta == {}
    assert "[Collection](/Renamed/Renamed.md)" in listing_body
    assert vault.load_note("index.md") is None


def test_folder_move_without_rename_preserves_hub_name(move_vault):
    root, _ledger = move_vault
    _article("Collection/Collection.md", "Collection")
    (root / "Destination").mkdir()

    result = vault.move_vault_item("Collection", "Destination")

    assert result["refs"]["Collection/Collection"] == "Destination/Collection/Collection"
    assert vault.is_folder_article(vault.load_note("Destination/Collection/Collection.md"))


def test_article_rename_keeps_exact_pending_state_and_rewrites_links(move_vault):
    root, ledger = move_vault
    _article("Tasks/work.md", "Work", kind="task", status="pending",
             params={"activation_key": "current"}, event_queue=[{"activation_key": "next"}])
    _article("Outside.md", "Outside", "[Work](/Tasks/work.md#Outcome)")
    state = ledger.task_runtime("Tasks/work")

    result = vault.move_vault_item("Tasks/work.md", "Tasks", "New Work")

    assert result["destination"] == "Tasks/new-work.md"
    assert vault.load_note("Tasks/new-work.md").title == "New Work"
    assert ledger.task_runtime("Tasks/new-work") == state
    assert ledger.task_runtime("Tasks/work") is None
    assert "/Tasks/new-work.md#Outcome" in vault.load_note("Outside.md").body
    assert not (root / "Tasks/work.md").exists()


def test_folder_hub_collision_is_rejected_before_any_changes(move_vault):
    root, ledger = move_vault
    _article("Collection/Collection.md", "Collection")
    _article("Collection/renamed.md", "Unrelated")
    _article("Collection/task.md", "Task", kind="task", status="pending")
    before = _snapshot(root)

    with pytest.raises(ValueError, match="hub already exists"):
        vault.move_vault_item("Collection", "", "Renamed")

    assert _snapshot(root) == before
    assert ledger.task_runtime("Collection/task") == {"status": "pending"}


def test_failed_rename_restores_hub_links_and_only_moved_runtime_state(move_vault, monkeypatch):
    root, ledger = move_vault
    _article("Collection/Collection.md", "Collection")
    _article("Collection/task.md", "Task", kind="task", status="pending",
             params={"activation_key": "active"}, event_queue=[{"activation_key": "next"}])
    _article("Outside.md", "Outside", "[Hub](/Collection/Collection.md)")
    ledger.seed_task_runtime("Unrelated/task", {"status": "failed"})
    before = _snapshot(root)
    state = ledger.task_runtime("Collection/task")
    write = vault._atomic_write
    failed = False

    def fail_one_write(path, content):
        nonlocal failed
        if path == root / "Outside.md" and not failed:
            failed = True
            raise OSError("injected write failure")
        write(path, content)

    monkeypatch.setattr(vault, "_atomic_write", fail_one_write)
    with pytest.raises(OSError, match="injected"):
        vault.move_vault_item("Collection", "", "Renamed")

    assert _snapshot(root) == before
    assert not (root / "Renamed").exists()
    assert ledger.task_runtime("Collection/task") == state
    assert ledger.task_runtime("Renamed/task") is None
    assert ledger.task_runtime("Unrelated/task") == {"status": "failed"}


def test_move_cannot_adopt_stale_destination_state_when_source_has_no_row(move_vault):
    root, ledger = move_vault
    _article("Tasks/work.md", "Work", kind="task")
    ledger.seed_task_runtime("Tasks/renamed", {"status": "review", "last_run": "unrelated"})
    before = _snapshot(root)

    with pytest.raises(ValueError, match="destination already owns"):
        vault.move_vault_item("Tasks/work.md", "Tasks", "Renamed")

    assert _snapshot(root) == before
    assert ledger.task_runtime("Tasks/work") is None
    assert {k:v for k,v in ledger.task_runtime("Tasks/renamed").items() if k != "activation_id"} == {"status": "review", "last_run": "unrelated"}


@pytest.mark.parametrize("name", ["Index", "Log"])
def test_article_rename_cannot_create_reserved_listing_name(move_vault, name):
    root, _ledger = move_vault
    _article("Article.md", "Article")
    before = _snapshot(root)
    with pytest.raises(ValueError, match="reserved"):
        vault.move_vault_item("Article.md", "", name)
    assert _snapshot(root) == before


def test_move_preserves_review_and_archive_evidence_including_legacy_envelopes(move_vault):
    root, _ledger = move_vault
    vault.write_note('News/Top 10.md', {'kind': 'knowledge', 'title': 'Top 10'}, 'Existing edition.')
    vault.write_note('News/News.md', {'kind': 'knowledge', 'title': 'News'}, '[Edition](/News/Top%2010.md)')
    (root / 'News/Top 10').mkdir()
    historical = {}
    for relative in ['_staging/pending.md', '_staging/_rejected/old.md', '_archived/News/retired.md']:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        content = '---\nproposal: true\ntarget: News/Top 10.md\n---\n\n[[News/Top 10]]\n'
        path.write_text(content)
        historical[path] = path.read_bytes()
    result = vault.move_vault_item('News/Top 10.md', 'News/Top 10')
    assert result['destination'] == 'News/Top 10/Top 10.md'
    assert not (root / 'News/Top 10.md').exists()
    assert '/News/Top%2010/Top%2010.md' in vault.load_note('News/News.md').body
    assert all(path.read_bytes() == content for path, content in historical.items())

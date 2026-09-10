"""One Knowledge edition is accepted or rejected as one Review disposition."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import threading

import pytest

from obsidience.harness.config import CONFIG
from obsidience.harness.knowledge import curation, format as article_format, review, vault


@pytest.fixture
def edition(tmp_path, monkeypatch, isolated_task_ledger):
    root = tmp_path / "vault"
    root.mkdir()
    monkeypatch.setattr(CONFIG, "vault_dir", root)
    monkeypatch.setattr(CONFIG, "git_commit", False)
    synced = []
    monkeypatch.setattr(isolated_task_ledger, "sync", lambda: synced.append(True))
    monkeypatch.setattr(review, "reconcile_origin_review_task", lambda ref: "review")
    def keep_staged(result, args, context):
        assert context.get("_group_staging") is True
        return result
    monkeypatch.setattr(curation, "try_auto_approve", keep_staged)
    vault.write_note("News/News.md", {"title": "News", "kind": "knowledge", "auto_curate": False},
                     "[Current edition](/News/Top/Top.md)")
    vault.write_note("News/Top/Top.md", {"title": "Top", "kind": "knowledge"},
                     "[Old story](old.md)")
    vault.write_note("News/Top/old.md", {"title": "Old", "kind": "knowledge", "sources": ["source://old"],
                                      "description": "Preserve documentary metadata", "local_field": "keep"},
                     "Original dated reporting.")
    context = {"agent": "Alexandria", "task": "Tasks/ingest", "run_id": "edition-run"}
    specs = [
        {"action": "update", "target": "News/Top/Top.md", "title": "Top",
         "body": "[First](first.md)\n\n[Second](second.md)", "metadata": {"kind": "knowledge"}},
        {"action": "create", "target": "News/Top/first.md", "title": "First",
         "body": "First distinct summary. [Index](Top.md)", "metadata": {"kind": "knowledge"}},
        {"action": "create", "target": "News/Top/second.md", "title": "Second",
         "body": "Second distinct summary. [Index](Top.md)", "metadata": {"kind": "knowledge"}},
        {"action": "archive", "target": "News/Top/old.md", "title": "Old", "body": ""},
    ]
    return root, isolated_task_ledger, context, specs, synced


def snapshot(root):
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*.md")}


def stage(edition):
    return review.stage_group(edition[3], edition[2], "Replace current edition", "source-edition-key")


def test_policy_off_stages_one_card_and_manual_approval_publishes_complete_graph(edition):
    root, ledger, context, specs, synced = edition
    before = snapshot(root)
    result = stage(edition)
    assert {path: data for path, data in snapshot(root).items() if not path.startswith("_staging/")} == before
    assert len(context["staged_proposals"]) == 1
    rows = review.list_proposals()
    assert len(rows) == 1 and rows[0]["approvable"]
    assert rows[0]["file"] == Path(result["staged"]).name
    assert [member["action"] for member in rows[0]["members"]] == ["update", "create", "create", "archive"]
    assert "First distinct summary" in rows[0]["body_preview"]
    assert "ARCHIVE: Old" in rows[0]["body_preview"]
    outcome = review.approve(result["members"][2]["file"])
    assert outcome["approved"] == "News/Top/Top.md"
    assert outcome["review_outcome"]["approved_count"] == 4
    assert len(synced) == 1 and not review.list_proposals()
    assert not (root / "News/Top/old.md").exists()
    archived = vault.load_note("_archived/News/Top/old.md")
    assert archived.meta["article_status"] == "deprecated"
    assert archived.meta["archive_reason"] == "Replace current edition"
    assert archived.meta["archived_at"].endswith("Z")
    assert archived.meta["sources"] == ["source://old"] and archived.meta["local_field"] == "keep"
    assert archived.body == "Original dated reporting.\n"
    assert all(ledger.review_decision(member["file"])["decision"] == "approved" for member in result["members"])
    resolver = vault.resolver()
    assert all(resolver.resolve(link) for note in vault.iter_notes() for link in note.links)


@pytest.mark.parametrize("failure", ["base", "body", "metadata", "missing", "inbound"])
def test_stale_or_invalid_member_blocks_entire_card_without_partial_writes(edition, failure):
    root, ledger, _, _, synced = edition
    result = stage(edition)
    if failure == "base":
        (root / "News/Top/old.md").write_text((root / "News/Top/old.md").read_text() + "Owner revision.\n")
    elif failure == "missing":
        (root / "News/Top/old.md").unlink()
    elif failure == "inbound":
        vault.write_note("Other.md", {"title": "Other", "kind": "knowledge"}, "[Still needed](/News/Top/old.md)")
    else:
        path = CONFIG.staging_dir / result["members"][1]["file"]
        meta, body = article_format.loads(path.read_text())
        if failure == "body":
            body += "Changed proposal.\n"
        else:
            meta["title"] = "Changed title"
        path.write_text(article_format.dumps(meta, body))
    before = snapshot(root)
    rows = review.list_proposals()
    assert len(rows) == 1 and not rows[0]["approvable"]
    with pytest.raises(ValueError):
        review.approve(Path(result["staged"]).name)
    assert snapshot(root) == before and not synced
    assert ledger.review_outcome("edition-run")["approved_count"] == 0


@pytest.mark.parametrize("failure", ["file", "decision"])
def test_approval_failure_restores_all_targets_staging_and_receipts(edition, monkeypatch, failure):
    root, ledger, _, _, synced = edition
    result = stage(edition)
    before = snapshot(root)
    if failure == "file":
        original = review._atomic_write
        failed = []
        def write(path, text):
            if path == root / "News/Top/second.md" and not failed:
                failed.append(True)
                raise OSError("simulated disk failure")
            return original(path, text)
        monkeypatch.setattr(review, "_atomic_write", write)
    else:
        original = ledger.record_review_decisions
        def decisions(rows, **kwargs):
            original(rows[:2], **kwargs)
            raise ValueError("simulated decision conflict")
        monkeypatch.setattr(ledger, "record_review_decisions", decisions)
    with pytest.raises((OSError, ValueError), match="simulated"):
        review.approve(Path(result["staged"]).name)
    assert snapshot(root) == before and not synced
    assert ledger.review_outcome("edition-run")["approved_count"] == 0


def test_rejection_disposes_whole_stale_group_and_records_every_member(edition):
    root, ledger, _, _, synced = edition
    before = snapshot(root)
    result = stage(edition)
    # Owner can reject a stale proposal; rejection never accepts its changed content.
    changed = CONFIG.staging_dir / result["members"][1]["file"]
    changed.write_text(changed.read_text() + "Changed proposal.\n")
    outcome = review.reject(result["members"][-1]["file"], "Keep previous edition")
    assert outcome["review_outcome"]["rejected_count"] == 4
    assert not review.list_proposals() and not synced
    assert {path: data for path, data in snapshot(root).items() if not path.startswith("_staging/")} == before
    assert len(list((CONFIG.staging_dir / "_rejected").glob("*.md"))) == 4
    assert all(ledger.review_decision(member["file"])["decision"] == "rejected" for member in result["members"])


def test_rejection_receipt_failure_restores_all_pending_members(edition, monkeypatch):
    root, ledger, _, _, _ = edition
    result = stage(edition)
    before = snapshot(root)
    original = ledger.record_review_decisions
    def fail(rows, **kwargs):
        original(rows[:1], **kwargs)
        raise ValueError("simulated rejection failure")
    monkeypatch.setattr(ledger, "record_review_decisions", fail)
    with pytest.raises(ValueError, match="simulated rejection failure"):
        review.reject(Path(result["staged"]).name)
    assert snapshot(root) == before
    assert ledger.review_outcome("edition-run")["rejected_count"] == 0


def test_staging_failure_removes_only_its_own_proposals(edition, monkeypatch):
    from obsidience.harness.capabilities.vault import propose
    root, _, _, _, _ = edition
    vault.write_note("_staging/unrelated.md", {"title": "Unrelated", "target": "Elsewhere.md", "proposal": True}, "Keep.")
    before = snapshot(root)
    original = propose.stage_proposal
    calls = []
    def interrupted(args, context):
        calls.append(args)
        if len(calls) == 3:
            raise ValueError("staging interrupted")
        return original(args, context)
    monkeypatch.setattr(propose, "stage_proposal", interrupted)
    with pytest.raises(ValueError, match="staging interrupted"):
        stage(edition)
    assert snapshot(root) == before


def test_same_batch_reattaches_without_rewriting_and_different_content_fails(edition):
    root, _, context, specs, _ = edition
    first = stage(edition)
    before = snapshot(root)
    second = stage(edition)
    assert second["existing"] and second["staged"] == first["staged"]
    assert snapshot(root) == before
    changed = deepcopy(specs)
    changed[1]["body"] = "Changed reporting."
    with pytest.raises(ValueError, match="batch key"):
        review.stage_group(changed, context, "Same source", "source-edition-key")
    assert snapshot(root) == before


def test_regenerated_audit_timestamp_reattaches_original_pinned_group(edition):
    root, _, context, specs, _ = edition
    specs[1]["metadata"]["generated"] = {"by": "Alexandria", "at": "2026-09-06T08:00:00Z"}
    first = stage(edition)
    before = snapshot(root)
    specs[1]["metadata"]["generated"]["at"] = "2026-09-06T09:00:00Z"
    second = review.stage_group(specs, {**context, "run_id": "later-run"}, "Same source", "source-edition-key")
    assert second["existing"] and second["staged"] == first["staged"]
    assert snapshot(root) == before


@pytest.mark.parametrize("change", ["limit", "authority", "duplicate"])
def test_group_size_and_knowledge_only_boundary(edition, change):
    root, _, context, specs, _ = edition
    before = snapshot(root)
    if change == "limit":
        specs = specs * 7
    elif change == "authority":
        specs[1]["metadata"]["binding"] = "capability:invented"
    else:
        specs.append(deepcopy(specs[1]))
    with pytest.raises(ValueError):
        review.stage_group(specs, context, "Invalid group", "invalid-key")
    assert snapshot(root) == before


def test_invalid_candidate_links_are_rejected_before_retaining_staging(edition):
    root, _, context, specs, _ = edition
    before = snapshot(root)
    specs[1]["body"] = "[Absent article](/Missing/Article.md)"
    with pytest.raises(ValueError, match="unresolved Article links"):
        review.stage_group(specs, context, "Invalid input", "invalid-key")
    assert snapshot(root) == before


def test_unrelated_existing_dangling_link_does_not_block_edition(edition):
    root, _, _, _, _ = edition
    vault.write_note("Unrelated.md", {"title": "Older unrelated Article", "kind": "knowledge"},
                     "[Preexisting unresolved reference](/Absent.md)")
    result = stage(edition)
    assert review.list_proposals()[0]["approvable"]
    review.approve(Path(result["staged"]).name)
    assert "Absent.md" in (root / "Unrelated.md").read_text()


def test_sync_and_group_reader_lock_order_completes_concurrently(tmp_path, monkeypatch, isolated_task_ledger):
    """A normal sync cannot hold flock while waiting for group Review's note lock."""
    ledger = isolated_task_ledger
    root = tmp_path / "vault"
    root.mkdir()
    monkeypatch.setattr(CONFIG, "vault_dir", root)
    vault.write_note("Topic.md", {"title": "Topic", "kind": "knowledge"}, "Accepted Article.")
    entered, release, group_entered = threading.Event(), threading.Event(), threading.Event()
    original = ledger._sync
    errors, results = [], []
    first = [True]
    def synchronized(embed):
        assert vault._NOTE_WRITE_LOCK._is_owned()
        if first[0]:
            first[0] = False
            entered.set()
            assert release.wait(3)
        return original(embed)
    monkeypatch.setattr(ledger, "_sync", synchronized)
    def ordinary():
        try:
            results.append(ledger.sync(embed=False))
        except BaseException as exc:
            errors.append(exc)
            entered.set()
    def group():
        try:
            with vault._NOTE_WRITE_LOCK:
                group_entered.set()
                results.append(ledger.sync(embed=False))
        except BaseException as exc:
            errors.append(exc)
    normal = threading.Thread(target=ordinary, daemon=True)
    grouped = threading.Thread(target=group, daemon=True)
    normal.start()
    try:
        assert entered.wait(3)
        assert not errors
        grouped.start()
        assert not group_entered.wait(0.05)
    finally:
        release.set()
        normal.join(3)
        if grouped.ident:
            grouped.join(3)
    assert not normal.is_alive() and not grouped.is_alive()
    assert not errors and len(results) == 2


def test_group_reader_cannot_observe_partially_written_edition(edition, monkeypatch):
    root, _, _, _, _ = edition
    result = stage(edition)
    written, release, reader_started, reader_finished = [threading.Event() for _ in range(4)]
    original = review._atomic_write
    snapshots, errors = [], []
    def write(path, material):
        original(path, material)
        if path == root / "News/Top/first.md":
            written.set()
            assert release.wait(3)
    monkeypatch.setattr(review, "_atomic_write", write)
    def approve():
        try:
            review.approve(Path(result["staged"]).name)
        except BaseException as exc:
            errors.append(exc)
    def read():
        reader_started.set()
        snapshots.append({note.ref for note in vault.iter_notes()})
        reader_finished.set()
    writer = threading.Thread(target=approve, daemon=True)
    reader = threading.Thread(target=read, daemon=True)
    writer.start()
    try:
        assert written.wait(3)
        reader.start()
        assert reader_started.wait(3)
        assert not reader_finished.wait(0.05)
    finally:
        release.set()
        writer.join(3)
        if reader.ident:
            reader.join(3)
    assert not writer.is_alive() and not reader.is_alive() and not errors
    assert len(snapshots) == 1
    assert "News/Top/first" in snapshots[0] and "News/Top/second" in snapshots[0]
    assert "News/Top/old" not in snapshots[0]


def crash_publication(edition, result, boundary):
    root, ledger, _, _, _ = edition
    script = r'''
import os,sys
from pathlib import Path
from obsidience.harness.config import CONFIG
CONFIG.vault_dir=Path(sys.argv[1])
CONFIG.db_path=Path(sys.argv[2])
CONFIG.git_commit=False
from obsidience.harness.knowledge import review
boundary=sys.argv[4]
original_write=review._atomic_write
def write(path,material):
    original_write(path,material)
    if boundary == 'before_commit' and path == CONFIG.vault_dir/'News/Top/first.md':
        os._exit(91)
review._atomic_write=write
original_unlink=Path.unlink
def unlink(path,*args,**kwargs):
    if boundary == 'after_commit' and path.parent == CONFIG.staging_dir and path.suffix == '.md':
        os._exit(92)
    return original_unlink(path,*args,**kwargs)
Path.unlink=unlink
review.approve(sys.argv[3])
'''
    child = subprocess.run([sys.executable, "-c", script, str(root), str(ledger.db_path),
                            Path(result["staged"]).name, boundary],
                           cwd=Path(__file__).parents[2], capture_output=True, text=True, timeout=15)
    assert child.returncode == (91 if boundary == "before_commit" else 92), child.stderr
    assert len(list(CONFIG.staging_dir.glob(".review-transaction-*.json"))) == 1


def test_process_death_before_commit_restores_previous_edition_and_pending_group(edition):
    root, ledger, _, _, _ = edition
    result = stage(edition)
    before = snapshot(root)
    crash_publication(edition, result, "before_commit")
    assert (root / "News/Top/first.md").exists()
    assert all((CONFIG.staging_dir / member["file"]).exists() for member in result["members"])
    assert ledger.review_outcome("edition-run")["approved_count"] == 0
    assert review.recover_groups() == {"rolled_back": 1, "finalized": 0}
    assert snapshot(root) == before
    assert not list(CONFIG.staging_dir.glob(".review-transaction-*.json"))
    assert review.list_proposals()[0]["approvable"]


def test_process_death_after_commit_finishes_disposition_without_replaying_writes(edition):
    root, ledger, _, _, _ = edition
    result = stage(edition)
    crash_publication(edition, result, "after_commit")
    assert ledger.review_outcome("edition-run")["approved_count"] == 4
    canonical = {path: data for path, data in snapshot(root).items() if not path.startswith("_staging/")}
    mtimes = {path: (root / path).stat().st_mtime_ns for path in canonical}
    assert review.recover_groups() == {"rolled_back": 0, "finalized": 1}
    assert {path: data for path, data in snapshot(root).items() if not path.startswith("_staging/")} == canonical
    assert {path: (root / path).stat().st_mtime_ns for path in canonical} == mtimes
    assert not review.list_proposals()
    assert not list(CONFIG.staging_dir.glob(".review-transaction-*.json"))


def test_recovery_preserves_newer_owner_bytes_and_refuses_partial_rollback(edition):
    root, _, _, _, _ = edition
    result = stage(edition)
    crash_publication(edition, result, "before_commit")
    (root / "News/Top/Top.md").write_text("Owner edited after process death.\n")
    current = snapshot(root)
    with pytest.raises(ValueError, match="unexpected current Article bytes"):
        review.recover_groups()
    assert snapshot(root) == current
    assert list(CONFIG.staging_dir.glob(".review-transaction-*.json"))


def test_returning_story_can_be_retired_again_without_overwriting_prior_history(edition):
    root, _, context, _, _ = edition
    first = stage(edition)
    review.approve(Path(first["staged"]).name)
    original_archive = root / "_archived/News/Top/old.md"
    original_bytes = original_archive.read_bytes()
    return_specs = [
        {"action": "update", "target": "News/Top/Top.md", "title": "Top",
         "body": "[Returned story](old.md)\n\n[Second](second.md)", "metadata": {"kind": "knowledge"}},
        {"action": "create", "target": "News/Top/old.md", "title": "Old",
         "body": "Updated reporting from the returning source. [Index](Top.md)", "metadata": {"kind": "knowledge"}},
    ]
    returned = review.stage_group(return_specs, context, "Story returns", "edition-two")
    review.approve(Path(returned["staged"]).name)
    assert (root / "News/Top/old.md").exists()
    retire_specs = [
        {"action": "update", "target": "News/Top/Top.md", "title": "Top",
         "body": "[First](first.md)\n\n[Second](second.md)", "metadata": {"kind": "knowledge"}},
        {"action": "archive", "target": "News/Top/old.md", "title": "Old", "body": ""},
    ]
    retired = review.stage_group(retire_specs, context, "Next edition", "edition-three")
    review.approve(Path(retired["staged"]).name)
    assert not (root / "News/Top/old.md").exists()
    archives = list((root / "_archived/News/Top").glob("old*.md"))
    assert len(archives) == 2 and original_archive.read_bytes() == original_bytes
    newer = next(path for path in archives if path != original_archive)
    assert "Updated reporting" in newer.read_text()
    assert article_format.loads(newer.read_text())[0]["article_status"] == "deprecated"


@pytest.mark.parametrize("boundary", ["initial", "finalizing"])
def test_process_death_while_staging_never_exposes_independent_proposals(edition, boundary):
    root, ledger, context, specs, _ = edition
    before = snapshot(root)
    script = r'''
import os,sys,json
from pathlib import Path
from obsidience.harness.config import CONFIG
CONFIG.vault_dir=Path(sys.argv[1]);CONFIG.db_path=Path(sys.argv[2]);CONFIG.git_commit=False
from obsidience.harness.knowledge import review,vault,format
boundary=sys.argv[3]
original=vault._atomic_write
def write(path,material):
    original(path,material)
    if path.parent == CONFIG.staging_dir and path.suffix == '.md':
        meta,_=format.loads(material)
        if boundary == 'initial' and meta.get('review_building') and meta.get('title') == 'First':
            os._exit(93)
        if boundary == 'finalizing' and meta.get('review_group') and not meta.get('review_building'):
            os._exit(94)
vault._atomic_write=write;review._atomic_write=write
review.stage_group(json.loads(sys.argv[4]),json.loads(sys.argv[5]),'Complete edition','staging-crash-key')
'''
    child = subprocess.run([sys.executable, "-c", script, str(root), str(ledger.db_path), boundary,
                            json.dumps(specs), json.dumps(context)], cwd=Path(__file__).parents[2],
                           capture_output=True, text=True, timeout=15)
    assert child.returncode == (93 if boundary == "initial" else 94), child.stderr
    rows = review.list_proposals()
    assert not rows or not rows[0]["approvable"]
    for path in CONFIG.staging_dir.glob("*.md"):
        with pytest.raises(ValueError, match="staged"):
            review.approve(path.name)
    recovered = review.recover_groups()
    assert {path: data for path, data in snapshot(root).items() if not path.startswith("_staging/")} == before
    if boundary == "initial":
        assert recovered["discarded_builds"] == 1
        assert recovered["discarded_tasks"] == ["Tasks/ingest"]
        assert not review.list_proposals()
        assert len(list((CONFIG.staging_dir / "_rejected").glob("*.md"))) == 2
    else:
        rows = review.list_proposals()
        assert len(rows) == 1 and rows[0]["approvable"] and rows[0]["member_count"] == 4
    assert ledger.review_outcome("edition-run")["approved_count"] == 0


@pytest.mark.parametrize("component", ["index", "reconciliation", "audit"])
def test_postcommit_error_returns_actual_eleven_article_publication(edition, monkeypatch, component):
    _, ledger, context, _, _ = edition
    specs = [{"action": "update", "target": "News/Top/Top.md", "title": "Top",
              "body": "\n\n".join(f"[Story {number}](story-{number}.md)" for number in range(10)),
              "metadata": {"kind": "knowledge"}}] + [
        {"action": "create", "target": f"News/Top/story-{number}.md", "title": f"Story {number}",
         "body": f"Individual summary {number}. [Index](Top.md)", "metadata": {"kind": "knowledge"}}
        for number in range(10)
    ]
    result = review.stage_group(specs, context, "Ten stories", "ten-story-edition")
    def fail(*_args):
        raise OSError(f"simulated {component} failure")
    if component == "index":
        monkeypatch.setattr(ledger, "sync", fail)
    elif component == "reconciliation":
        monkeypatch.setattr(review, "reconcile_origin_review_task", fail)
    else:
        monkeypatch.setattr(review, "git_commit", fail)
    outcome = review.approve(Path(result["staged"]).name)
    assert outcome["committed"] and outcome["approved"] == "News/Top/Top.md"
    assert outcome["review_outcome"]["approved_count"] == 11
    assert f"simulated {component} failure" in outcome["publication_warning"]
    assert not review.list_proposals()
    assert len(list(CONFIG.staging_dir.glob(".review-transaction-*.json"))) == 1
    assert all(vault.load_note(f"News/Top/story-{number}.md") for number in range(10))


def test_later_edition_finishes_old_committed_journal_before_superseding_bytes(edition, monkeypatch):
    root, ledger, context, _, _ = edition
    first = stage(edition)
    original_sync = ledger.sync
    monkeypatch.setattr(ledger, "sync", lambda: (_ for _ in ()).throw(OSError("index unavailable")))
    outcome = review.approve(Path(first["staged"]).name)
    assert outcome["committed"] and outcome["publication_warning"]
    assert list(CONFIG.staging_dir.glob(".review-transaction-*.json"))
    monkeypatch.setattr(ledger, "sync", original_sync)
    later = review.stage_group([
        {"action": "update", "target": "News/Top/Top.md", "title": "Top",
         "body": "Later edition. [First](first.md)\n\n[Second](second.md)",
         "metadata": {"kind": "knowledge"}},
    ], {**context, "run_id": "later-run"}, "New edition", "later-edition-key")
    assert not list(CONFIG.staging_dir.glob(".review-transaction-*.json"))
    review.approve(Path(later["staged"]).name)
    assert "Later edition" in vault.load_note("News/Top/Top.md").body
    before = snapshot(root)
    assert review.recover_groups() == {"rolled_back": 0, "finalized": 0}
    assert snapshot(root) == before
    assert ledger.review_outcome("edition-run")["approved_count"] == 4
    assert ledger.review_outcome("later-run")["approved_count"] == 1


def test_ordinary_approval_also_finishes_older_group_publication(edition, monkeypatch):
    from obsidience.harness.capabilities.vault.propose import stage_proposal

    root, ledger, context, _, _ = edition
    first = stage(edition)
    original_sync = ledger.sync
    monkeypatch.setattr(ledger, "sync", lambda: (_ for _ in ()).throw(OSError("index unavailable")))
    review.approve(Path(first["staged"]).name)
    monkeypatch.setattr(ledger, "sync", original_sync)
    later = stage_proposal({"action": "update", "target": "News/Top/Top.md", "title": "Top",
                           "body": "Owner correction. [First](first.md)\n\n[Second](second.md)",
                           "reason": "Correct the published edition", "metadata": {"kind": "knowledge"}},
                          {**context, "run_id": "correction-run", "_group_staging": True})
    review.approve(Path(later["staged"]).name)
    assert not list(CONFIG.staging_dir.glob(".review-transaction-*.json"))
    assert "Owner correction" in vault.load_note("News/Top/Top.md").body
    before = snapshot(root)
    assert review.recover_groups() == {"rolled_back": 0, "finalized": 0}
    assert snapshot(root) == before


def test_committed_decision_survives_failed_final_outcome_projection(edition, monkeypatch):
    _, ledger, _, _, _ = edition
    result = stage(edition)
    original_outcome = ledger.review_outcome
    monkeypatch.setattr(ledger, "review_outcome", lambda _run: (_ for _ in ()).throw(OSError("ledger read unavailable")))
    outcome = review.approve(Path(result["staged"]).name)
    assert outcome["committed"] and outcome["approved"] == "News/Top/Top.md"
    assert "decision projection: ledger read unavailable" in outcome["publication_warning"]
    assert "review_outcome" not in outcome
    assert original_outcome("edition-run")["approved_count"] == 4
    assert not review.list_proposals()


def test_failed_postcommit_file_cleanup_is_decided_history_not_pending_work(edition, monkeypatch):
    _, ledger, _, _, _ = edition
    result = stage(edition)
    stuck = Path(result["staged"])
    original_unlink = Path.unlink
    def fail_one(path, *args, **kwargs):
        if path == stuck:
            raise OSError("simulated proposal cleanup failure")
        return original_unlink(path, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", fail_one)
    outcome = review.approve(stuck.name)
    assert outcome["committed"] and outcome["review_outcome"]["approved_count"] == 4
    assert "simulated proposal cleanup failure" in outcome["publication_warning"]
    assert stuck.exists() and not review.list_proposals()
    assert ledger.review_outcome("edition-run")["approved_count"] == 4
    monkeypatch.setattr(Path, "unlink", original_unlink)
    assert review.recover_groups() == {"rolled_back": 0, "finalized": 1}
    assert not stuck.exists() and not review.list_proposals()

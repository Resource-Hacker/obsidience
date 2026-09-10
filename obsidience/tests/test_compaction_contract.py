from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timezone

import pytest

from obsidience.harness.conversation import observations
from obsidience.harness.conversation.store import ConversationStore
from obsidience.harness.knowledge.vault import load_note, write_note


VALID = (
    "Goal: Preserve the question.\n\nConstraints and corrections: The owner corrected the name.\n\n"
    "Verified state: No external state was observed.\n\nOutstanding: Answer the original question."
)
INCOMPLETE = "Goal: Preserve the question.\n\nConstraints and corrections: The owner corrected the name and"


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    monkeypatch.setattr(observations.CONFIG, "vault_dir", tmp_path / "vault")
    monkeypatch.setattr(observations, "auto_curate_enabled", lambda _target: True)
    return {
        "curation_mode": "compaction", "origin_task_ref": observations.IMMEDIATE_COMPACT_TASK_REF,
        "target_path": str(observations.EXECUTIVE_TEMPORARY_PATH), "turn_id": "compact-contract",
        "conversation_id": "conversation-contract", "through_sequence": 53,
    }


@pytest.mark.parametrize("text", [
    INCOMPLETE,
    VALID.replace("Outstanding: Answer the original question.", "Outstanding:"),
    VALID.replace("Verified state:", "Goal:"),
    VALID.replace("Goal:", "Outstanding:", 1),
    "An unauthored preface.\n" + VALID,
])
def test_incomplete_compaction_never_writes_or_advances_context(runtime, text):
    with pytest.raises(ValueError, match="four nonempty sections"):
        observations.append_temporary_observation({"text": text}, runtime)
    assert not list(observations.CONFIG.vault_dir.rglob("*.md"))
    assert observations.latest_context_compaction(runtime["conversation_id"]) is None


@pytest.mark.parametrize("style", ["colon", "markdown"])
def test_complete_sections_preserve_content_above_ordinary_200_character_limit(runtime, style):
    text = VALID.replace("Preserve the question.", "Preserve the exact original question, its context and the owner's correction without treating assistant claims as verified facts.")
    if style == "markdown":
        for section in observations._COMPACTION_SECTIONS:
            text = text.replace(section + ": ", "## " + section + "\n")
    assert 200 < len(text) < 2000
    result = observations.append_temporary_observation({"text": text}, runtime)
    assert load_note(result["ref"] + ".md").body.strip() == text


def test_commit_revalidates_pending_summary_and_preserves_invalid_artifact(runtime):
    result = observations.append_temporary_observation({"text": VALID}, runtime)
    note = load_note(result["ref"] + ".md")
    write_note(note.path, note.meta, INCOMPLETE)
    path = observations.CONFIG.vault_dir / note.path
    before = path.read_bytes()
    with pytest.raises(RuntimeError, match="complete four-section"):
        observations.commit_context_compaction(
            conversation_id=runtime["conversation_id"], through_sequence=53, turn_id=runtime["turn_id"],
        )
    assert path.read_bytes() == before
    assert load_note(note.path).meta["compaction_committed"] is False


def _legacy_summary(runtime, *, text, sequence, pending=False):
    path = observations.EXECUTIVE_TEMPORARY_PATH / f"legacy-{sequence}.md"
    write_note(str(path), {
        "kind": "knowledge", "title": "Historical compaction", "temporary": True,
        "observation_scope": "temporary", "compaction": True, "compaction_committed": True,
        "source_conversation_id": runtime["conversation_id"], "through_sequence": sequence,
        "source_turn_id": f"compact-{sequence}", "observed_at": datetime.now(timezone.utc).isoformat(),
        **({"promotion_pending": "a" * 20} if pending else {}),
    }, text)
    return observations.CONFIG.vault_dir / path


def test_invalid_newer_summary_cannot_replace_prior_valid_anchor_or_promotion_watermark(runtime):
    good = _legacy_summary(runtime, text=VALID, sequence=2)
    bad = _legacy_summary(runtime, text=INCOMPLETE, sequence=53, pending=True)
    before = bad.read_bytes()
    latest = observations.latest_context_compaction(runtime["conversation_id"], active=True)
    assert latest.path == str(good.relative_to(observations.CONFIG.vault_dir))
    assert observations.promoted_context_sequence(runtime["conversation_id"]) == 0
    assert [note.ref for note in observations._committed_context_compactions(runtime["conversation_id"])] == [latest.ref]
    assert bad.read_bytes() == before


def test_invalid_only_compaction_falls_back_to_exact_sqlite_dialogue(runtime, isolated_task_ledger):
    store = ConversationStore(isolated_task_ledger)
    runtime["conversation_id"] = store.conversation_id

    async def append():
        user = await store.append(role="user", source="realtime", text="What level is the character?")
        await store.append(role="user", source="realtime", text="I meant Squancher.")
        return user

    asyncio.run(append())
    bad = _legacy_summary(runtime, text=INCOMPLETE, sequence=53, pending=True)
    before = hashlib.sha256(bad.read_bytes()).hexdigest()
    projected = observations.project_immediate_observations(
        store, conversation_id=store.conversation_id, materialize=False,
    )
    assert projected["compacted_through"] == 0
    assert "What level is the character?" in projected["body"]
    assert "I meant Squancher." in projected["body"]
    assert INCOMPLETE not in projected["body"]
    assert hashlib.sha256(bad.read_bytes()).hexdigest() == before

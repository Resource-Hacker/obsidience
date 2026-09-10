from pathlib import Path

import pytest
from fastapi import HTTPException

from obsidience.harness.config import CONFIG
from obsidience.harness.interfaces.api import app as server
from obsidience.harness.knowledge import index, review
from obsidience.harness.knowledge.vault import move_vault_item, write_note


@pytest.mark.parametrize("agent, alias", [
    ("Executive", "@agent/Observations"),
    ("Darwin", "@sat/Darwin/observations"),
])
def test_reader_children_use_their_physical_index_identity(monkeypatch, tmp_path, agent, alias):
    monkeypatch.setattr(CONFIG, "vault_dir", tmp_path)
    root = f"Agents/{agent}/Observations"
    child = root + "/Temporary Observations/Temporary Observations"
    write_note(f"Agents/{agent}/{agent}.md", {"kind": "agent", "title": agent}, "Identity.")
    write_note(root + "/Observations.md", {"kind": "knowledge", "title": "Observations"}, "Parent.")
    write_note(child + ".md", {"kind": "knowledge", "title": "Temporary Observations"}, "Child.")
    article = server.get_article(alias)
    assert article["ref"] == root + "/Observations"
    assert article["children"] == [child]
    assert server.get_article(child)["title"] == "Temporary Observations"


def test_physical_observation_hierarchy_has_one_readable_hub(monkeypatch, tmp_path):
    monkeypatch.setattr(CONFIG, "vault_dir", tmp_path)
    monkeypatch.setattr(CONFIG, "db_path", tmp_path / "test.sqlite")
    write_note("Agents/Executive/Executive.md", {"kind": "agent", "title": "JARVIS", "role": "executive"}, "Executive.")
    root = "Agents/Executive/Observations"
    for folder in (root, root + "/Immediate Observations", root + "/Temporary Observations", root + "/Preferences"):
        write_note(folder + "/" + Path(folder).name + ".md", {"kind": "knowledge", "title": Path(folder).name}, "Authored condensation.")
    immediate = root + "/Immediate Observations/current-conversation"
    write_note(immediate + ".md", {"kind": "knowledge", "title": "Current conversation", "immediate": True, "retrieval": False}, "A completed conversation.")
    temporary = root + "/Temporary Observations/summary"
    write_note(temporary + ".md", {"kind": "knowledge", "title": "Conversation summary", "temporary": True, "retrieval": False}, "A compacted summary.")
    test_index = index.Index()
    monkeypatch.setattr(server, "INDEX", test_index)
    test_index.sync(embed=False)
    graph = server.graph()
    subjects = next(group["subjects"] for group in graph["navigation"]["groups"] if group["id"] == "executive")
    immediate_subject = next(subject for subject in subjects if subject.get("path") == root + "/Immediate Observations")
    assert immediate_subject["title"] == "Immediate Observations"
    assert immediate_subject["parent_id"] == "@agent/Observations"
    assert immediate_subject["article_ref"] == root + "/Immediate Observations/Immediate Observations"
    by_ref = {node["id"]: node for node in graph["nodes"]}
    assert by_ref[immediate]["parent_id"] == immediate_subject["id"]
    assert by_ref[immediate_subject["article_ref"]]["navigation_ref"] == immediate_subject["id"]
    assert by_ref[temporary]["parent_id"] == "@agent/Temporary Observations"
    assert len([subject for subject in subjects if subject["title"] == "Temporary Observations"]) == 1
    for ref in (immediate_subject["id"], immediate_subject["article_ref"]):
        article = server.get_article(ref)
        assert article["body"].strip() == "Authored condensation."
        assert article["children"] == [immediate]
        assert article["ref"] == immediate_subject["article_ref"]
    observations = server.get_article("@agent/Observations")
    assert len(observations["children"]) == 3
    assert immediate not in observations["children"]
    assert server._auto_curate_target_path(root + "/Temporary Observations/Temporary Observations", {}) == root + "/Temporary Observations"
    original_iter = server.iter_notes
    calls = []
    def counted_notes():
        calls.append(True)
        return original_iter()
    monkeypatch.setattr(server, "iter_notes", counted_notes)
    server._navigation_manifest({})
    assert len(calls) == 1
    test_index.db.close()


@pytest.mark.parametrize("flag", ["immediate", "temporary"])
def test_wiki_maintenance_cannot_rewrite_runtime_observations(monkeypatch, tmp_path, flag):
    from obsidience.harness.capabilities.vault import maintenance, propose

    monkeypatch.setattr(CONFIG, "vault_dir", tmp_path)
    target = "Agents/Executive/Observations/live.md"
    write_note(target, {"kind": "knowledge", "title": "Live observation", flag: True}, "Private runtime context.")
    assert maintenance._maintenance_candidates()["checked_articles"] == 0
    with pytest.raises(ValueError, match="Compact and Promote"):
        propose.stage_proposal({"target": target, "action": "update", "title": "Live observation", "body": "Edited."}, {})
    write_note("_staging/old.md", {"proposal": True, "action": "update", "target": target, "kind": "knowledge", "title": "Live observation"}, "Edited.")
    with pytest.raises(ValueError, match="Compact and Promote"):
        review.approve("old.md")
    with pytest.raises(HTTPException, match="Compact and Promote"):
        server.update_article(target.removesuffix(".md"), {"title": "Edited", "body": "Edited."})
    with pytest.raises(ValueError, match="Compact and Promote"):
        move_vault_item(target, "Agents/Executive", "Renamed")
    with pytest.raises(ValueError, match="Compact and Promote"):
        move_vault_item("Agents/Executive/Observations", "Agents/Executive", "Renamed")

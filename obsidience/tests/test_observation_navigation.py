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

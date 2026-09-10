"""Owner API preserves the boundary between System evidence and authored wiki."""

import pytest
from fastapi import HTTPException

from obsidience.harness.config import CONFIG
from obsidience.harness.interfaces.api import app as api
from obsidience.harness.knowledge import vault


NETWORK = "ADMECH Workstation/Hardware/Network"
HARDWARE = "ADMECH Workstation/Hardware/Hardware"


def test_system_status_is_read_only_and_refresh_has_one_owner(monkeypatch):
    calls = []
    report = {"status": "ready", "categories": [], "current_count": 22, "article_count": 22}
    monkeypatch.setattr(api.system_knowledge, "system_knowledge_status", lambda: report)
    monkeypatch.setattr(api.system_knowledge, "refresh_system_knowledge",
                        lambda: calls.append("refresh") or {**report, "changed": 0})
    assert api.system_knowledge_status() == report
    assert calls == []
    assert api.refresh_system_knowledge()["changed"] == 0
    assert calls == ["refresh"]


@pytest.mark.parametrize("note_ref,ref", [
    (NETWORK, NETWORK), (HARDWARE, HARDWARE), (HARDWARE, "@branch/ADMECH Workstation/Hardware"),
])
def test_system_reader_is_read_only_through_article_and_folder_routes(tmp_path, monkeypatch, note_ref, ref):
    monkeypatch.setattr(CONFIG, "vault_dir", tmp_path / "vault")
    vault.write_note(note_ref + ".md", {"title": "System inventory", "kind": "knowledge"},
                     "Recorded interface inventory.")
    before = (CONFIG.vault_dir / (note_ref + ".md")).read_bytes()

    doc = api.get_article(ref)
    assert doc["read_only"] is True
    assert doc["managed_by"] == "system"
    assert doc["auto_curate_supported"] is False
    with pytest.raises(HTTPException) as caught:
        api.update_article(ref, {"title": "Edited", "body": "Unattested changes"})
    assert caught.value.status_code == 409
    with pytest.raises(HTTPException):
        api.set_article_auto_curate(ref, {"enabled": True})
    assert (CONFIG.vault_dir / (note_ref + ".md")).read_bytes() == before


def test_authored_workstation_article_remains_editable(tmp_path, monkeypatch):
    monkeypatch.setattr(CONFIG, "vault_dir", tmp_path / "vault")
    monkeypatch.setattr(api.INDEX, "sync", lambda: None)
    ref = "ADMECH Workstation/Workstation Observations/Hardware/Input/Mouse policy"
    vault.write_note(ref + ".md", {"title": "Mouse policy", "kind": "knowledge"}, "Original")
    assert not api.get_article(ref).get("read_only", False)
    result = api.update_article(ref, {"title": "Mouse policy", "body": "Owner correction"})
    assert result == {"article": ref, "updated": True}
    assert vault.load_note(ref + ".md").body == "Owner correction\n"

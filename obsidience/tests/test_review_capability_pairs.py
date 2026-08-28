from __future__ import annotations

import pytest

from obsidience.harness.capabilities.registry import binding, source
from obsidience.harness.config import CONFIG
from obsidience.harness.knowledge import index, review
from obsidience.harness.knowledge.vault import write_note


def _proposal(target: str, title: str, kind: str, **metadata) -> dict:
    return {
        "proposal": True,
        "action": "create",
        "target": target,
        "title": title,
        "kind": kind,
        "agent": "test",
        "task": "",
        "review_class": "article",
        **metadata,
    }


def test_new_tool_and_skill_are_approved_as_one_pair(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(CONFIG, "vault_dir", tmp_path)
    monkeypatch.setattr(CONFIG, "git_commit", False)
    monkeypatch.setattr(index.INDEX, "sync", lambda: None)

    tool_name = "application.launch"
    write_note(
        "_staging/tool.md",
        _proposal(
            f"Tools/{tool_name}.md",
            tool_name,
            "tool",
            binding=binding(tool_name),
            source=source(tool_name),
        ),
        "Executable application launch contract.",
    )
    write_note(
        "_staging/skill.md",
        _proposal(
            "Skills/launching-an-application.md",
            "Launch an application",
            "skill",
            tool=f"[[Tools/{tool_name}]]",
        ),
        "How to invoke and verify application launch.",
    )

    result = review.approve("tool.md")

    assert result["approved"] == f"Tools/{tool_name}.md"
    assert result["paired_skill"] == "Skills/launching-an-application.md"
    assert (tmp_path / f"Tools/{tool_name}.md").is_file()
    assert (tmp_path / "Skills/launching-an-application.md").is_file()
    assert not list((tmp_path / "_staging").glob("*.md"))


def test_new_tool_without_one_pending_skill_is_rejected(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(CONFIG, "vault_dir", tmp_path)
    monkeypatch.setattr(CONFIG, "git_commit", False)
    monkeypatch.setattr(index.INDEX, "sync", lambda: None)

    tool_name = "application.launch"
    write_note(
        "_staging/tool.md",
        _proposal(
            f"Tools/{tool_name}.md",
            tool_name,
            "tool",
            binding=binding(tool_name),
            source=source(tool_name),
        ),
        "Executable application launch contract.",
    )

    with pytest.raises(ValueError, match="exactly one accepted or pending paired Skill"):
        review.approve("tool.md")

    assert not (tmp_path / f"Tools/{tool_name}.md").exists()
    assert (tmp_path / "_staging/tool.md").is_file()

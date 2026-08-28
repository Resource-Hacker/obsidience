from __future__ import annotations

from obsidience.harness.interfaces.api import app as api_app
from obsidience.harness import config
from obsidience.harness.knowledge import source, vault


def _agent(path, title: str, role: str) -> None:
    vault.write_note(
        path,
        {"title": title, "kind": "agent", "status": "accepted", "role": role},
        f"# {title}\n",
    )


def test_source_tree_checkout_is_independent_per_agent(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config.CONFIG, "vault_dir", tmp_path / "vault")
    monkeypatch.setattr(api_app.INDEX, "sync", lambda: None)

    _agent("Agents/Executive/Executive.md", "Executive", "executive")
    _agent("Agents/Heimdall/Heimdall.md", "Heimdall", "guardian")
    _agent("Agents/Alexandria/Alexandria.md", "Alexandria", "curator")
    _agent("Agents/Darwin/Darwin.md", "Darwin", "researcher")
    implementation = (
        tmp_path / "obsidience" / "harness" / "knowledge" / "source.py"
    )
    implementation.parent.mkdir(parents=True)
    implementation.write_text("READ_ONLY = True\n")

    tree = "obsidience/harness"
    executive = api_app.set_source_checkout(
        tree, {"agent": "executive", "checked_out": True}
    )
    curator = api_app.set_source_checkout(
        tree, {"agent": "curator", "checked_out": True}
    )
    assert executive["checkout_changed"] is True
    assert curator["checkout_changed"] is True

    repeated = api_app.set_source_checkout(
        tree, {"agent": "executive", "checked_out": True}
    )
    assert repeated["checkout_changed"] is False
    assignments = {
        (row["agent"], row["tree"])
        for row in api_app.source_checkouts()["assignments"]
    }
    assert assignments == {("executive", tree), ("curator", tree)}

    api_app.set_source_checkout(tree, {"agent": "executive", "checked_out": False})
    assignments = {
        (row["agent"], row["tree"])
        for row in api_app.source_checkouts()["assignments"]
    }
    assert assignments == {("curator", tree)}
    curator_note = vault.load_note("Agents/Alexandria/Alexandria.md")
    assert curator_note is not None
    assert curator_note.meta["source_trees"] == [tree]


def test_source_checkout_rejects_files_and_traversal(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config.CONFIG, "vault_dir", tmp_path / "vault")
    monkeypatch.setattr(api_app.INDEX, "sync", lambda: None)
    _agent("Agents/Executive/Executive.md", "Executive", "executive")
    implementation = tmp_path / "obsidience" / "harness" / "only.py"
    implementation.parent.mkdir(parents=True)
    implementation.write_text("VALUE = 1\n")

    for tree in (
        "obsidience/harness/only.py",
        "@view/system",
        "../system",
        "harness/missing",
    ):
        try:
            api_app.set_source_checkout(
                tree, {"agent": "executive", "checked_out": True}
            )
        except Exception as cause:
            assert getattr(cause, "status_code", None) == 404
        else:
            raise AssertionError(f"invalid Source checkout was accepted: {tree}")

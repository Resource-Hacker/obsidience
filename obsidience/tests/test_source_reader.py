from __future__ import annotations

from types import SimpleNamespace

import pytest

from obsidience.harness import config
from obsidience.harness.knowledge import source, vault


def test_okf_documentary_resources_use_exact_local_files_without_fetch(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config.CONFIG, "vault_dir", tmp_path / "obsidience/vault")
    backing = tmp_path / "DESIGN.md"
    backing.write_text("Architecture.")
    note = SimpleNamespace(ref="Knowledge/design", path="Knowledge/design.md", body="Design.", meta={
        "sources": [{"resource": backing.as_uri()}, {"resource": "https://example.org/manual"}],
    })
    monkeypatch.setattr(vault, "iter_notes", lambda: [note])
    result = source.list_source_files()
    assert result["issues"] == []
    assert next(item for item in result["files"] if item["path"] == "DESIGN.md")["articles"] == [note.ref]
    with pytest.raises(source.SourceError, match="escapes"):
        source._safe_linked_source((tmp_path.parent / "outside.md").as_uri())


def test_source_reader_projects_knowledge_code_system_and_capability_links(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        config.CONFIG, "vault_dir", tmp_path / "obsidience" / "vault"
    )

    article = tmp_path / "obsidience" / "vault" / "Tools" / "task.complete.md"
    article.parent.mkdir(parents=True)
    article.write_text("---\ntitle: task.complete\nkind: tool\n---\n\n# task.complete\n")
    staged = tmp_path / "obsidience" / "vault" / "_staging" / "proposal.md"
    staged.parent.mkdir(parents=True)
    staged.write_text("# Pending proposal\n")
    archived = tmp_path / "obsidience" / "vault" / "_archived" / "retired.md"
    archived.parent.mkdir(parents=True)
    archived.write_text("# Retired article\n")
    implementation = (
        tmp_path / "obsidience" / "harness" / "capabilities" / "task" / "complete.py"
    )
    implementation.parent.mkdir(parents=True)
    implementation.write_text("OBJECTIVE = 'before'\n")
    module = (
        tmp_path / "obsidience" / "harness" / "execution" / "scheduler.py"
    )
    module.parent.mkdir(parents=True)
    module.write_text("TICK = 20\n")
    interface = (
        tmp_path / "obsidience" / "ui" / "src" / "renderer" / "src" / "App.tsx"
    )
    interface.parent.mkdir(parents=True)
    interface.write_text("export const APP = 'Obsidience';\n")
    shell_host = tmp_path / "obsidience" / "shell" / "host.py"
    shell_host.parent.mkdir(parents=True)
    shell_host.write_text("OUTPUT = 'HDMI-A-1'\n")
    shell_stage = tmp_path / "obsidience" / "shell" / "qml" / "Stage.qml"
    shell_stage.parent.mkdir(parents=True)
    shell_stage.write_text("import QtQuick\n\nItem {}\n")
    shell_texture = (
        tmp_path / "obsidience" / "shell" / "qml" / "assets" / "edge.svg"
    )
    shell_texture.parent.mkdir(parents=True)
    shell_texture.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>\n')
    idle_policy = tmp_path / "obsidience" / "shell" / "idle" / "hypridle.conf"
    idle_policy.parent.mkdir(parents=True)
    idle_policy.write_text("listener { timeout = 300 }\n")
    inbox = (
        tmp_path / "obsidience" / "evidence" / "inbox" / "research--example.md"
    )
    inbox.parent.mkdir(parents=True)
    inbox.write_text("# Cited research handoff\n")

    note = SimpleNamespace(
        ref="Tools/task.complete",
        path="Tools/task.complete.md",
        body="# task.complete",
        meta={
            "source": "obsidience/harness/capabilities/task/complete.py",
            "sources": ["obsidience/state/system/hardware/compute/cpu.json"],
        },
    )
    monkeypatch.setattr(vault, "iter_notes", lambda: iter([note]))
    system_file = (
        tmp_path / "obsidience" / "state" / "system" / "hardware" /
        "compute" / "cpu.json"
    )
    system_file.parent.mkdir(parents=True)
    system_file.write_text('{"schema":"test","read_only":true}\n')

    manifest = source.list_source_files()
    assert manifest["issues"] == []
    assert not any(
        item["key"].startswith("@view/") for item in manifest["files"]
    )
    assert all((tmp_path / item["key"]).is_file() for item in manifest["files"])
    assert not any(
        item["key"].startswith(("code/", "knowledge/", "blobs/"))
        for item in manifest["files"]
    )
    assert [item["key"] for item in manifest["files"]] == [
        "obsidience/evidence/inbox/research--example.md",
        "obsidience/harness/capabilities/task/complete.py",
        "obsidience/harness/execution/scheduler.py",
        "obsidience/shell/host.py",
        "obsidience/shell/idle/hypridle.conf",
        "obsidience/shell/qml/assets/edge.svg",
        "obsidience/shell/qml/Stage.qml",
        "obsidience/state/system/hardware/compute/cpu.json",
        "obsidience/ui/src/renderer/src/App.tsx",
        "obsidience/vault/_archived/retired.md",
        "obsidience/vault/_staging/proposal.md",
        "obsidience/vault/Tools/task.complete.md",
    ]
    by_key = {item["key"]: item for item in manifest["files"]}
    assert by_key["obsidience/vault/Tools/task.complete.md"]["articles"] == [
        "Tools/task.complete"
    ]
    assert by_key["obsidience/vault/Tools/task.complete.md"]["storage"] == "knowledge"
    assert by_key["obsidience/vault/_staging/proposal.md"]["articles"] == []
    assert by_key["obsidience/vault/_archived/retired.md"]["articles"] == []
    assert by_key[
        "obsidience/harness/capabilities/task/complete.py"
    ]["articles"] == ["Tools/task.complete"]
    assert by_key["obsidience/harness/execution/scheduler.py"][
        "articles"
    ] == []
    assert by_key["obsidience/ui/src/renderer/src/App.tsx"]["articles"] == []
    assert by_key["obsidience/shell/host.py"]["articles"] == []
    assert by_key["obsidience/shell/qml/Stage.qml"]["media_type"] == "text/x-qml"
    assert by_key["obsidience/shell/qml/assets/edge.svg"]["media_type"] == "image/svg+xml"
    assert by_key["obsidience/evidence/inbox/research--example.md"]["articles"] == []
    assert by_key["obsidience/evidence/inbox/research--example.md"]["storage"] == "blob"
    assert by_key["obsidience/state/system/hardware/compute/cpu.json"]["articles"] == [
        "Tools/task.complete"
    ]
    assert by_key["obsidience/state/system/hardware/compute/cpu.json"]["read_only"] is True

    texture = source.get_source_file("obsidience/shell/qml/assets/edge.svg")
    assert texture["content"] == shell_texture.read_text()

    markdown = source.get_source_file("obsidience/vault/Tools/task.complete.md")
    assert markdown["content"] == article.read_text()
    assert markdown["path"] == "obsidience/vault/Tools/task.complete.md"

    key = "obsidience/harness/capabilities/task/complete.py"
    before = source.get_source_file(key)
    implementation.write_text("OBJECTIVE = 'after'\n")
    after = source.get_source_file(key)
    assert before["content"] == "OBJECTIVE = 'before'\n"
    assert after["content"] == "OBJECTIVE = 'after'\n"
    assert after["sha256"] != before["sha256"]

    system_doc = source.get_source_file(
        "obsidience/state/system/hardware/compute/cpu.json"
    )
    assert system_doc["content"] == system_file.read_text()
    assert system_doc["storage"] == "system"
    assert system_doc["modified_at"] == system_file.stat().st_mtime

    handoff = source.get_source_file(
        "obsidience/evidence/inbox/research--example.md"
    )
    assert handoff["content"] == inbox.read_text()
    assert handoff["path"] == "obsidience/evidence/inbox/research--example.md"

    qml = source.get_source_file("obsidience/shell/qml/Stage.qml")
    assert qml["content"] == shell_stage.read_text()

    idle = source.get_source_file("obsidience/shell/idle/hypridle.conf")
    assert idle["content"] == idle_policy.read_text()

    with pytest.raises(source.SourceError, match="source file not found"):
        source.get_source_file("@view/system")


def test_source_tree_mapping_prefers_related_knowledge_without_exposing_files(monkeypatch) -> None:
    from obsidience.harness.knowledge import system_schema

    gpu_ref = "ADMECH Workstation/Hardware/Compute/Rtx 4080 Super"
    shell_ref = "ADMECH Workstation/Applications/Obsidience/Obsidience"
    gpu_path = "obsidience/state/system/hardware/compute/rtx-4080-super.json"
    shell_path = "obsidience/state/system/applications/obsidience"
    from obsidience.harness.knowledge import system
    monkeypatch.setattr(system, "system_articles", lambda: {
        "gpu": {"ref": gpu_ref, "path": gpu_path, "descriptor_path": gpu_path},
        "shell": {"ref": shell_ref, "path": shell_path,
                  "descriptor_path": shell_path + "/application.json"},
    })
    notes = [
        SimpleNamespace(
            ref=gpu_ref,
            path=gpu_ref + ".md",
            body="GPU facts",
            meta={},
        ),
        SimpleNamespace(
            ref=shell_ref,
            path=shell_ref + ".md",
            body="Shell facts",
            meta={},
        ),
        SimpleNamespace(
            ref="ADMECH Workstation/Workstation Observations/Hardware/GPU",
            path="ADMECH Workstation/Workstation Observations/Hardware/GPU.md",
            body="Authored hardware observation outside the System mirror",
            meta={},
        ),
        SimpleNamespace(
            ref="Personal/Unrelated",
            path="Personal/Unrelated.md",
            body="Other",
            meta={},
        ),
    ]
    monkeypatch.setattr(vault, "iter_notes", lambda: iter(notes))
    monkeypatch.setattr(vault, "load_note", lambda *args: pytest.fail("read outside accepted snapshot"))
    monkeypatch.setattr(
        source,
        "list_source_files",
        lambda **kwargs: {
            "files": [
                {
                    "key": "obsidience/harness/capabilities/task/complete.py",
                    "articles": ["Tools/task.complete"],
                },
                {
                    "key": "obsidience/vault/Personal/Unrelated.md",
                    "articles": ["Personal/Unrelated"],
                },
            ],
            "issues": [],
        },
    )

    assert source.article_refs_for_trees(
        ["obsidience/state/system/hardware"]
    ) == [
        gpu_ref
    ]
    assert source.article_refs_for_trees(["obsidience/harness"]) == [
        "Tools/task.complete"
    ]
    assert source.article_refs_for_trees(
        ["obsidience/state/system/applications"]
    ) == [
        shell_ref
    ]
    assert source.article_refs_for_trees(["obsidience/state/system"]) == [
        shell_ref,
        gpu_ref,
    ]
    assert source.article_refs_for_trees([gpu_path]) == [gpu_ref]
    assert source.article_refs_for_trees([shell_path + "/application.json"]) == [shell_ref]
    assert source.article_refs_for_trees([shell_path]) == [shell_ref]
    assert source.article_refs_for_trees(["obsidience/vault/Personal"]) == [
        "Personal/Unrelated"
    ]
    notes.remove(next(note for note in notes if note.ref == shell_ref))
    assert source.article_refs_for_trees(["obsidience/state/system"]) == [gpu_ref]


def test_source_tree_scope_rejects_traversal() -> None:
    for value in ("", ".", "../system", "/system", ".hidden"):
        try:
            source.normalize_source_tree(value)
        except source.SourceError:
            pass
        else:
            raise AssertionError(f"unsafe Source scope was accepted: {value}")
    assert source.normalize_source_tree("unknown/tree") == "unknown/tree"

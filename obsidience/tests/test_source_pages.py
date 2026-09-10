from types import SimpleNamespace

from obsidience.harness.capabilities.source import read
from obsidience.harness.capabilities.vault import list as list_capability
from obsidience.harness.knowledge import source, vault


def test_source_paging_reaches_exact_end(monkeypatch):
    content = "a" * 12_000 + "THE END"
    monkeypatch.setattr(source, "get_source", lambda _: {
        "citation": "source://example", "source_type": "document", "captured_at": "now",
        "source_ref": "file.txt", "content_sha256": "hash", "content": content,
    })
    first = read.execute({"source": "example"}, {})
    assert "Next offset: 12000" in first and "THE END" not in first
    last = read.execute({"source": "example", "offset": 12000}, {})
    assert "End of Source" in last and last.endswith("THE END")
    assert "Invalid offset" in read.execute({"source": "example", "offset": -1}, {})


def test_vault_pages_include_knowledge_but_not_private(monkeypatch):
    rows = [SimpleNamespace(ref=f"News & Research/{n:03}", title=f"Story {n}") for n in range(65)]
    rows.append(SimpleNamespace(ref="_staging/private", title="secret"))
    monkeypatch.setattr(vault, "iter_notes", lambda: rows)
    first = list_capability.execute({"folder": "News & Research"}, {})
    assert "Next offset: 60" in first and "Story 64" not in first
    last = list_capability.execute({"folder": "News & Research", "offset": 60}, {})
    assert "End of folder" in last and "Story 64" in last
    assert "secret" not in list_capability.execute({}, {})
    assert "Invalid folder" in list_capability.execute({"folder": "_staging"}, {})
    assert "Invalid folder" in list_capability.execute({"folder": "News/../Tasks"}, {})


def test_xml_source_roundtrip_preserves_downloaded_whitespace():
    xml = '<?xml version="1.0"?>\r\n<rss>  <channel/> </rss>\r\n'
    captured = source.RawSource.create(source_type="tool", source_ref="https://example.com/feed",
                                      media_type="application/rss+xml", captured_at=None, content=xml)
    restored = source.parse_raw_source(source.render_raw_source(captured))
    assert restored.content.encode() == xml.encode()
    assert restored.content_sha256 == captured.content_sha256


def test_supporting_research_capture_identity_comes_from_execution():
    context = {"agent": "Darwin", "task": "Tasks/research/news", "run_id": "abc"}
    assert source.research_activation_key(context) == "source.added:research:abc:Tasks/research/news"
    assert source.research_activation_key({**context, "agent": "Alexandria"}) is None
    assert source.research_activation_key({"params": {"handled_by_run_id": "fake"}}) is None

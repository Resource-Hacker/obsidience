from __future__ import annotations

from types import SimpleNamespace

from obsidience.harness.knowledge import retrieval


def test_checked_out_source_scope_only_reorders_real_search_results(monkeypatch) -> None:
    monkeypatch.setattr(
        retrieval,
        "_lanes_for",
        lambda _query, _weight, _k: [
            (1.0, [("Knowledge/general", 1.0), ("ADMECH Workstation/Hardware/GPU", 0.9)])
        ],
    )
    notes = {
        "Knowledge/general": SimpleNamespace(
            title="General", kind="knowledge", meta={}, body="General context", links=[]
        ),
        "ADMECH Workstation/Hardware/GPU": SimpleNamespace(
            title="GPU", kind="knowledge", meta={}, body="GPU context", links=[]
        ),
    }
    monkeypatch.setattr(
        retrieval,
        "load_note",
        lambda path: notes.get(path.removesuffix(".md")),
    )
    monkeypatch.setattr(
        retrieval,
        "resolver",
        lambda: SimpleNamespace(resolve=lambda _target: None),
    )

    _brief, refs = retrieval.fast_context_with_refs(
        "hardware question",
        set(),
        budget=1_200,
        limit=2,
        preferred={"ADMECH Workstation/Hardware/GPU"},
    )

    assert refs == ["ADMECH Workstation/Hardware/GPU", "Knowledge/general"]

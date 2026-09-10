from __future__ import annotations

import frontmatter

from obsidience.harness.knowledge import retrieval
from obsidience.harness.knowledge.vault import Note


def _note(
    ref: str,
    *,
    title: str | None = None,
    kind: str = "knowledge",
    meta: dict | None = None,
    body: str = "Context",
    links: list[str] | None = None,
) -> Note:
    return Note(
        path=f"{ref}.md",
        title=title or ref.rsplit("/", 1)[-1],
        meta={"kind": kind, **(meta or {})},
        body=body,
        links=links or [],
    )


def test_checked_out_source_scope_only_reorders_real_search_results(monkeypatch) -> None:
    monkeypatch.setattr(
        retrieval,
        "_lanes_for",
        lambda _query, _weight, _k, _kinds=None: [
            (1.0, [("Knowledge/general", 1.0), ("ADMECH Workstation/Hardware/GPU", 0.9)])
        ],
    )
    notes = [
        _note("Knowledge/general", title="General", body="General context"),
        _note(
            "ADMECH Workstation/Hardware/GPU",
            title="GPU",
            body="GPU context",
        ),
    ]
    monkeypatch.setattr(
        retrieval,
        "iter_notes",
        lambda: notes,
    )

    _brief, refs = retrieval.fast_context_with_refs(
        "hardware question",
        set(),
        budget=1_200,
        limit=2,
        preferred={"ADMECH Workstation/Hardware/GPU"},
    )

    assert refs == ["ADMECH Workstation/Hardware/GPU", "Knowledge/general"]


def test_fast_context_filters_search_lanes_to_knowledge(monkeypatch) -> None:
    calls: list[tuple[str, str | None]] = []

    def lane(name: str):
        def search(_query: str, _k: int, kind=None):
            calls.append((name, kind))
            return [("Knowledge/eligible", 1.0)]

        return search

    monkeypatch.setattr(retrieval.INDEX, "fts", lane("fts"))
    monkeypatch.setattr(retrieval.INDEX, "vector", lane("vector"))
    monkeypatch.setattr(
        retrieval,
        "iter_notes",
        lambda: [_note("Knowledge/eligible", title="Eligible", body="Eligible context")],
    )

    _brief, refs = retrieval.fast_context_with_refs("eligible", set(), limit=1)

    assert refs == ["Knowledge/eligible"]
    assert calls == [
        ("fts", "knowledge"),
        ("vector", "knowledge"),
    ]


def test_fast_context_excludes_nonretrievable_and_system_neighbors(
    monkeypatch, tmp_path,
) -> None:
    def write(ref: str, body: str = "Context", **metadata: object) -> None:
        path = tmp_path / f"{ref}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        post = frontmatter.Post(
            body,
            title=ref.rsplit("/", 1)[-1],
            kind="knowledge",
            **metadata,
        )
        path.write_text(frontmatter.dumps(post) + "\n")

    write(
        "Knowledge/seed",
        "[[Knowledge/eligible]] "
        "[[Knowledge/disabled]] "
        "[[Knowledge/temporary]] "
        "[[_staging/staged]] "
        "[[_archived/archived]]",
    )
    write("Knowledge/eligible", "Eligible context")
    write("Knowledge/disabled", "Disabled context", retrieval=False)
    write("Knowledge/temporary", "Temporary context", temporary=True)
    write("_staging/staged", "Staged context")
    write("_archived/archived", "Archived context")
    monkeypatch.setattr(retrieval.CONFIG, "vault_dir", tmp_path)
    monkeypatch.setattr(
        retrieval,
        "_lanes_for",
        lambda _query, _weight, _k, _kinds=None: [
            (
                1.0,
                [
                    ("Knowledge/seed", 1.0),
                    ("Knowledge/disabled", 0.9),
                    ("Knowledge/temporary", 0.8),
                    ("_staging/staged", 0.7),
                    ("_archived/archived", 0.6),
                ],
            )
        ],
    )

    brief, refs = retrieval.fast_context_with_refs(
        "context",
        set(),
        budget=1_200,
        limit=5,
    )

    assert refs == ["Knowledge/seed", "Knowledge/eligible"]
    assert "Eligible context" in brief
    assert "Disabled context" not in brief
    assert "Temporary context" not in brief
    assert "Staged context" not in brief
    assert "Archived context" not in brief


def test_generic_search_preserves_mixed_article_kinds(monkeypatch) -> None:
    calls: list[str | None] = []

    def lanes(_query: str, _weight: float, _k: int, kind=None):
        calls.append(kind)
        return [
            (1.0, [("Tools/example", 1.0), ("Knowledge/example", 0.9)])
        ]

    notes = {
        "Tools/example": _note("Tools/example", kind="tool"),
        "Knowledge/example": _note("Knowledge/example"),
    }
    monkeypatch.setattr(retrieval, "_lanes_for", lanes)
    monkeypatch.setattr(
        retrieval,
        "load_note",
        lambda path: notes.get(path.removesuffix(".md")),
    )

    results = retrieval.search("example", k=2)

    assert [result["kind"] for result in results] == ["tool", "knowledge"]
    assert calls == [None]

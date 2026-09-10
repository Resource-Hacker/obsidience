from copy import deepcopy

import pytest
import yaml

from obsidience.harness.knowledge.format import (
    ARTICLE_TYPES,
    TASK_RUNTIME_FIELDS,
    decode_metadata,
    dumps,
    encode_metadata,
    loads,
    parse,
    serialize,
    validate_profile,
)


@pytest.mark.parametrize("kind", sorted(ARTICLE_TYPES))
def test_six_article_types_use_one_canonical_type(kind):
    raw, body = parse(dumps({"kind": kind, "title": "Article"}, "Content.\n"))
    assert raw == {"type": kind, "title": "Article"}
    assert body == "Content.\n"
    assert validate_profile(raw, "Articles/example.md") == []
    assert decode_metadata(raw) == {"kind": kind, "title": "Article"}


def test_common_metadata_and_foreign_assertions_round_trip_without_trust():
    raw = {
        "type": "knowledge", "title": "Example", "description": "One sentence.",
        "resource": "../source.pdf", "tags": ["research"],
        "sources": [{"resource": "https://example.org/source", "id": "s1",
                     "title": "Primary source", "usage_count": 2,
                     "last_modified": "2026-09-04T09:20:30-07:00"}],
        "usage_window": {"from": "2026-09-01", "to": "2026-09-04"},
        "generated": {"by": "agent:foreign", "at": "2026-09-04T16:20:30Z"},
        "verified": {"by": "human:foreign", "at": "2026-09-04T16:21:00+00:00"},
        "status": "stable", "stale_after": "2027-01-01T00:00:00Z",
        "foreign_extension": {"version": 2, "flags": [True, "x"]},
    }
    original = deepcopy(raw)
    meta = decode_metadata(raw)
    assert meta["article_status"] == "stable"
    assert "status" not in meta
    assert "trust" not in meta and "approved_at" not in meta
    assert "summary" not in meta
    assert validate_profile(raw) == []
    assert encode_metadata(meta) == original
    assert parse(dumps(meta, "# Content\n"))[0] == original
    assert raw == original


def test_known_application_metadata_flattens_but_unknown_namespace_stays_nested():
    raw = {
        "type": "task", "title": "Query", "foreign_field": [1, {"x": 2}],
        "obsidience": {"assignee": "Agents/Executive", "model": "obsidience-gemma",
                       "reasoning_effort": "high", "runbook": "Runbooks/query",
                       "future_local_extension": {"enabled": True}},
    }
    meta = decode_metadata(raw)
    assert meta["model"] == "obsidience-gemma"
    assert meta["obsidience"] == {"future_local_extension": {"enabled": True}}
    assert encode_metadata(meta) == raw
    meta["model"] = "other-model"
    meta["foreign_field"][1]["x"] = 3
    assert raw["obsidience"]["model"] == "obsidience-gemma"
    assert raw["foreign_field"][1]["x"] == 2
    assert encode_metadata(meta)["obsidience"]["model"] == "other-model"


def test_authored_fields_is_application_metadata_not_an_okf_root_field():
    meta = {"kind": "task", "authored_fields": ["model", "reasoning_effort"]}
    raw = {"type": "task", "obsidience": {"authored_fields": ["model", "reasoning_effort"]}}
    assert encode_metadata(meta) == raw
    assert decode_metadata(raw) == meta
    assert validate_profile(raw) == []


def test_task_runtime_state_never_persists_at_root_or_in_namespace():
    meta = {
        "kind": "task", "title": "Query", "article_status": "stable",
        **dict.fromkeys(TASK_RUNTIME_FIELDS, "runtime-only"),
        "obsidience": {**dict.fromkeys(TASK_RUNTIME_FIELDS, "old-runtime-only"),
                       "future_local_extension": "keep"},
        "description": "Answer the user's question.", "model": "obsidience-gemma",
        "reasoning_effort": "high",
    }
    original = deepcopy(meta)
    raw = encode_metadata(meta)
    assert raw["status"] == "stable"
    assert (TASK_RUNTIME_FIELDS - {"status"}).isdisjoint(raw)
    assert TASK_RUNTIME_FIELDS.isdisjoint(raw["obsidience"])
    assert raw["obsidience"] == {
        "future_local_extension": "keep", "model": "obsidience-gemma",
        "reasoning_effort": "high",
    }
    assert raw["description"] == "Answer the user's question."
    assert validate_profile(raw) == []
    assert meta == original


def test_legacy_task_state_survives_decode_for_ledger_seed_but_not_encode():
    legacy = {"kind": "task", "status": "queued", "params": {"query": "hello"},
              "summary": "Previous execution result", "model": "obsidience-gemma"}
    assert decode_metadata(legacy) == legacy
    assert encode_metadata(decode_metadata(legacy)) == {
        "type": "task", "obsidience": {"model": "obsidience-gemma"},
    }


def test_legacy_local_status_and_summary_do_not_become_okf_assertions():
    legacy = {"kind": "knowledge", "status": "approved", "summary": "Local result"}
    raw = encode_metadata(decode_metadata(legacy))
    assert raw == {"type": "knowledge", "obsidience": {
        "status": "approved", "summary": "Local result",
    }}
    assert validate_profile(raw) == []
    assert decode_metadata(raw) == legacy
    assert "description" not in raw
    assert "verified" not in raw


def test_common_and_local_article_status_are_distinct():
    raw = {"type": "knowledge", "status": "draft", "obsidience": {"status": "approved"}}
    meta = decode_metadata(raw)
    assert meta == {"kind": "knowledge", "article_status": "draft", "status": "approved"}
    assert encode_metadata(meta) == raw


def test_invalid_common_status_is_not_silently_discarded_by_projection():
    raw = {"type": "knowledge", "status": None}
    assert encode_metadata(decode_metadata(raw)) == raw
    assert validate_profile(raw)


def test_unknown_okf_type_and_computation_fields_remain_generic_data():
    raw = {
        "type": "computation", "runtime": "python3",
        "parameters": [{"name": "amount", "type": "number", "required": True}],
        "computation": "./calculate.py",
        "executor": {"resource": "./executor.md", "receipt": "./receipt.json"},
        "attester": {"resource": "./attester.md"},
        "arbitrary": {"claims": ["unknown", 123]},
    }
    text = serialize(raw, "Unexecuted computation.\n")
    assert parse(text) == (raw, "Unexecuted computation.\n")
    assert encode_metadata(loads(text)[0]) == raw
    assert len(validate_profile(raw)) == 1
    assert "type must be one of" in validate_profile(raw)[0]


def test_timestamp_lexemes_preserved_without_modifying_global_yaml_loader():
    text = "---\ntype: knowledge\nstale_after: 2027-01-01T00:00:00Z\nforeign_date: 2026-09-04\n---\n\nBody.\n"
    raw, body = parse(text)
    assert raw["stale_after"] == "2027-01-01T00:00:00Z"
    assert raw["foreign_date"] == "2026-09-04"
    assert parse(serialize(raw, body)) == (raw, body)
    assert not isinstance(yaml.safe_load("date: 2026-09-04")["date"], str)


@pytest.mark.parametrize("path", ["index.md", "log.md", "nested/index.md", "nested/LOG.md"])
def test_reserved_documents_parse_but_are_not_articles(path):
    raw, _ = parse("---\ntype: knowledge\n---\n\nNavigation.\n")
    assert any("reserved OKF documents" in error for error in validate_profile(raw, path))


@pytest.mark.parametrize("raw", [{}, {"type": None}, {"type": 4}, {"type": ["task"]},
                                  {"type": ""}, {"type": "Task"}])
def test_required_type_is_checked_only_at_profile_boundary(raw):
    assert parse(serialize(raw, "Body.\n"))[0] == raw
    assert any("type must be one of" in error for error in validate_profile(raw))


@pytest.mark.parametrize("field,value", [
    ("title", 1), ("description", []), ("resource", {}), ("tags", "single"),
    ("tags", [1]), ("status", "running"), ("generated", True),
    ("generated", {"by": "agent", "at": "2026-09-04T12:00:00"}),
    ("verified", True), ("verified", [{"at": "2026-09-04T12:00:00Z"}]),
    ("sources", "source"), ("sources", ["legacy-source"]),
    ("sources", [{"title": "Missing resource"}]), ("usage_window", []),
    ("stale_after", "2026-09-04"), ("stale_after", "2026-09-04T12:00:00"),
    ("obsidience", []), ("kind", "knowledge"), ("article_status", "stable"),
    ("model", "obsidience-gemma"),
])
def test_malformed_common_and_profile_fields_are_preserved_but_not_admitted(field, value):
    raw = {"type": "knowledge", field: value}
    assert parse(serialize(raw, "Body.\n"))[0] == raw
    assert validate_profile(raw)


@pytest.mark.parametrize("field", sorted(TASK_RUNTIME_FIELDS))
def test_profile_rejects_task_runtime_fields_in_namespace(field):
    assert any("Task execution state" in error for error in validate_profile({
        "type": "task", "obsidience": {field: "runtime"},
    }))


@pytest.mark.parametrize("field", ["type", "kind", "article_status", "title", "verified", "sources"])
def test_common_fields_cannot_be_shadowed_by_namespace(field):
    assert validate_profile({"type": "knowledge", "obsidience": {field: "shadow"}})


def test_no_frontmatter_does_not_invent_an_article_type():
    text = "# Ordinary Markdown\n\nNo metadata.\n"
    assert parse(text) == ({}, text)
    assert loads(text) == ({}, text)
    with pytest.raises(ValueError, match="kind/type"):
        dumps({}, text)


@pytest.mark.parametrize("text", ["---\ntype: knowledge\n", "---\n- not-a-mapping\n---\n"])
def test_invalid_framing_and_nonmapping_yaml_fail_clearly(text):
    with pytest.raises(ValueError):
        parse(text)


def test_yaml_is_safe_and_never_constructs_foreign_python_objects():
    with pytest.raises(yaml.YAMLError):
        parse("---\nvalue: !!python/object/apply:builtins.str [unsafe]\n---\n")


def test_crlf_framing_preserves_markdown_body():
    raw, body = parse("---\r\ntype: knowledge\r\n---\r\n\r\n# Content\r\n")
    assert raw == {"type": "knowledge"}
    assert body == "# Content\r\n"


def test_conflicting_aliases_and_namespace_fields_fail_without_overwriting():
    with pytest.raises(ValueError, match="Conflicting type and kind"):
        decode_metadata({"type": "knowledge", "kind": "task"})
    with pytest.raises(ValueError, match="Conflicting type and kind"):
        encode_metadata({"type": "knowledge", "kind": "task"})
    with pytest.raises(ValueError, match="Conflicting root and obsidience.model"):
        decode_metadata({"type": "task", "model": "old", "obsidience": {"model": "new"}})

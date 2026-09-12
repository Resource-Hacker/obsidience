from __future__ import annotations

import pytest

from obsidience.harness.knowledge import scope as knowledge_scope

from obsidience.harness.capabilities.vault import maintenance
from obsidience.harness.config import CONFIG
from obsidience.harness.knowledge import vault
from obsidience.harness.knowledge.vault import write_note


_SHARED_BODY = """
alpha bridge connection topology graph vault maintenance semantic accepted
article relationship context evidence useful deterministic
"""
_LEFT_BODY = _SHARED_BODY + """
left cedar birch maple oak pine spruce willow aspen elm beech
"""
_RIGHT_BODY = _SHARED_BODY + """
right amber bronze cobalt denim emerald fuchsia gold hazel indigo jade
"""
_LEFT_REF = "Knowledge/left"
_RIGHT_REF = "Knowledge/right"


@pytest.fixture(autouse=True)
def no_historical_outcomes(monkeypatch):
    monkeypatch.setattr(maintenance, "_completed_candidates", lambda: set())


def _write_candidate_pair(left_links: str = "", right_links: str = "") -> None:
    write_note(
        f"{_LEFT_REF}.md",
        {"kind": "knowledge", "title": "Alpha bridge"},
        _LEFT_BODY + left_links,
    )
    write_note(
        f"{_RIGHT_REF}.md",
        {"kind": "knowledge", "title": "Alpha connection"},
        _RIGHT_BODY + right_links,
    )


def _only_candidate(result: dict) -> dict:
    candidates = [row for row in result["candidates"] if row["kind"] == "missing_link"]
    assert len(candidates) == 1
    return candidates[0]


def test_missing_link_reports_isolated_endpoints_and_separate_components(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(CONFIG, "vault_dir", tmp_path)
    _write_candidate_pair()

    result = maintenance._maintenance_candidates()
    candidate = _only_candidate(result)

    assert candidate["kind"] == "missing_link"
    assert candidate["recommended_task"] == "Link"
    assert candidate["connectivity"] == {
        "isolated_endpoint_refs": [_LEFT_REF, _RIGHT_REF],
        "separate_components": True,
        "shared_neighbor_refs": [],
    }
    assert result["connectivity"] == {
        "component_count": 2,
        "isolated_article_count": 2,
        "largest_component_size": 1,
    }


def test_native_parent_coverage_does_not_invent_semantic_relationships(monkeypatch, tmp_path):
    monkeypatch.setattr(CONFIG, "vault_dir", tmp_path)
    _write_candidate_pair()
    write_note("Knowledge/Knowledge.md", {"kind": "knowledge", "title": "Knowledge"},
               "A parent condensation; hierarchy supplies its child navigation.")
    before = {path: path.read_bytes() for path in tmp_path.rglob("*.md")}
    result = maintenance._maintenance_candidates()
    assert [row["kind"] for row in result["candidates"]] == ["missing_link"]
    candidate = _only_candidate(result)
    assert candidate["connectivity"] == {
        "isolated_endpoint_refs": [],
        "separate_components": False, "shared_neighbor_refs": ["Knowledge/Knowledge"],
    }
    assert candidate["signals"]["shared_neighbors"] == 0  # Hierarchy is not a semantic anchor.
    assert result["connectivity"] == {
        "component_count": 1, "isolated_article_count": 0, "largest_component_size": 3,
    }
    assert all(note.links == [] for note in vault.iter_notes())
    assert before == {path: path.read_bytes() for path in before}


def test_connectivity_shared_neighbors_exclude_tool_and_task_targets(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(CONFIG, "vault_dir", tmp_path)
    write_note(
        "Knowledge/hub.md",
        {"kind": "knowledge", "title": "Semantic hub"},
        "A short shared semantic anchor.",
    )
    write_note(
        "Tools/shared.md",
        {"kind": "tool", "title": "shared"},
        "Executable authority is not a semantic topology node.",
    )
    write_note(
        "Tasks/shared.md",
        {"kind": "task", "title": "Shared task"},
        "Task authority is not a semantic topology node.",
    )
    links = "\n[[Knowledge/hub]] [[Tools/shared]] [[Tasks/shared]]"
    _write_candidate_pair(links, links)

    result = maintenance._maintenance_candidates()
    candidate = _only_candidate(result)

    assert candidate["connectivity"] == {
        "isolated_endpoint_refs": [],
        "separate_components": False,
        "shared_neighbor_refs": ["Knowledge/hub"],
    }
    assert result["connectivity"] == {
        "component_count": 1,
        "isolated_article_count": 0,
        "largest_component_size": 3,
    }


def test_claimed_pair_still_resolves_from_the_same_full_snapshot(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(CONFIG, "vault_dir", tmp_path)
    _write_candidate_pair()
    write_note(
        "Tasks/link.md",
        {
            "kind": "task",
            "title": "Link",
            "params": {"candidate_refs": [_RIGHT_REF, _LEFT_REF]},
        },
        "Confirm one missing useful relationship.",
    )

    result = maintenance._maintenance_candidates()

    assert result["checked_articles"] == 2
    assert result["candidate_count"] == 2
    assert result["claimed_count"] == 1
    assert result["unclaimed_count"] == 1
    assert [row["kind"] for row in result["candidates"]] == ["missing_index"]


def test_maintenance_uses_one_snapshot_and_excludes_runtime_observations(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(CONFIG, "vault_dir", tmp_path)
    _write_candidate_pair()
    write_note(
        "Agents/Executive/Observations/temporary.md",
        {"kind": "knowledge", "title": "Temporary", "temporary": True},
        _LEFT_BODY + _RIGHT_BODY,
    )
    original_iter_notes = vault.iter_notes
    calls = 0

    def counted_iter_notes(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original_iter_notes(*args, **kwargs)

    monkeypatch.setattr(vault, "iter_notes", counted_iter_notes)

    result = maintenance._maintenance_candidates()

    assert calls == 1
    assert result["checked_articles"] == 2
    assert result["connectivity"]["isolated_article_count"] == 2


def test_disconnectedness_alone_does_not_create_a_link_candidate(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(CONFIG, "vault_dir", tmp_path)
    write_note(
        "Knowledge/short-left.md",
        {"kind": "knowledge", "title": "Short left"},
        "One independent fact.",
    )
    write_note(
        "Knowledge/short-right.md",
        {"kind": "knowledge", "title": "Short right"},
        "Another independent fact.",
    )

    result = maintenance._maintenance_candidates()

    assert all(row["kind"] == "missing_index" for row in result["candidates"])
    assert result["connectivity"] == {
        "component_count": 2,
        "isolated_article_count": 2,
        "largest_component_size": 1,
    }


@pytest.mark.parametrize('depth', [0, 1, 4])
@pytest.mark.parametrize('reverse', [False, True])
def test_hierarchy_already_connects_link_endpoints(monkeypatch, tmp_path, depth, reverse):
    monkeypatch.setattr(CONFIG, 'vault_dir', tmp_path)
    hub = 'Knowledge/Branch/Branch'
    leaf = 'Knowledge/Branch/' + 'Nested/' * depth + 'leaf'
    pairs = [(hub, 'Alpha bridge', _LEFT_BODY), (leaf, 'Alpha connection', _RIGHT_BODY)]
    for ref, title, body in reversed(pairs) if reverse else pairs:
        write_note(ref + '.md', {'kind': 'knowledge', 'title': title}, body)
    before = {p: p.read_bytes() for p in tmp_path.rglob('*.md')}
    result = maintenance._maintenance_candidates()
    assert not [row for row in result['candidates'] if row['kind'] == 'missing_link']
    assert result['connectivity'] == {
        'component_count': 1, 'isolated_article_count': 0, 'largest_component_size': 2,
    }
    res = vault.resolver(include_system=False)
    params = {'candidate_refs': [leaf, hub], 'candidate_kind': 'missing_link',
              'candidate_key': 'a' * 20,
              'candidate_revision': maintenance.candidate_revision([res.resolve(leaf), res.resolve(hub)])}
    disposition = maintenance.candidate_invalidation('Tasks/link', params, res)
    assert disposition['reason'] == 'native_hierarchy_connection'
    assert disposition['current_revision'] == params['candidate_revision']
    assert before == {p: p.read_bytes() for p in before}


@pytest.mark.parametrize('left,right', [
    ('Knowledge/Branch/Branch', 'Knowledge/BranchOther/leaf'),
    ('Knowledge/Branch', 'Knowledge/Branch/leaf'),
    ('Knowledge/Branch/a', 'Knowledge/Branch/b'),
    ('Knowledge/Branch/One/One', 'Knowledge/Branch/Two/Two'),
])
def test_nonancestral_pairs_remain_link_candidates(monkeypatch, tmp_path, left, right):
    monkeypatch.setattr(CONFIG, 'vault_dir', tmp_path)
    write_note(left + '.md', {'kind': 'knowledge', 'title': 'Alpha bridge'}, _LEFT_BODY)
    write_note(right + '.md', {'kind': 'knowledge', 'title': 'Alpha connection'}, _RIGHT_BODY)
    rows = maintenance._maintenance_candidates()['candidates']
    assert any(row['kind'] == 'missing_link' and set(row['refs']) == {left, right} for row in rows)


def test_agent_brain_is_an_ancestor_of_its_own_folder_articles(monkeypatch, tmp_path):
    monkeypatch.setattr(CONFIG, 'vault_dir', tmp_path)
    write_note('Agents/A/A.md', {'kind': 'agent', 'title': 'Renamed brain'}, 'Role.')
    write_note('Agents/A/Architecture/Architecture.md', {'kind': 'knowledge', 'title': 'Renamed hub'}, 'Overview.')
    write_note('Agents/A/Architecture/Deep/leaf.md', {'kind': 'knowledge', 'title': 'Leaf'}, 'Facts.')
    res = vault.resolver(include_system=False)
    leaf = res.resolve('Agents/A/Architecture/Deep/leaf')
    assert knowledge_scope.knowledge_ancestry(res)[leaf.ref] == [
        'Agents/A/Architecture/Architecture', 'Agents/A/A',
    ]


def test_checked_out_knowledge_is_already_beneath_agent_root(monkeypatch, tmp_path):
    monkeypatch.setattr(CONFIG, 'vault_dir', tmp_path)
    root = 'Agents/A/A'
    hub = 'Knowledge/Shared/Shared'
    leaf = 'Knowledge/Shared/Deep/leaf'
    write_note(root + '.md', {'kind': 'agent', 'title': 'Alpha bridge',
                             'knowledge': ['[[' + hub + ']]']}, _LEFT_BODY)
    write_note(hub + '.md', {'kind': 'knowledge', 'title': 'Shared'}, 'Overview.')
    write_note(leaf + '.md', {'kind': 'knowledge', 'title': 'Alpha connection'}, _RIGHT_BODY)
    res = vault.resolver(include_system=False)
    ancestry = knowledge_scope.knowledge_ancestry(res)
    assert root in ancestry[leaf] and root in ancestry[hub]
    result = maintenance._maintenance_candidates({'_agent_ref': root})
    assert not [row for row in result['candidates'] if row['kind'] == 'missing_link']
    assert result['connectivity']['component_count'] == 1
    # Removing a checkout immediately removes only that structural root edge.
    vault.write_note(root + '.md', {'kind': 'agent', 'title': 'Alpha bridge'}, _LEFT_BODY)
    res = vault.resolver(include_system=False)
    assert root not in knowledge_scope.knowledge_ancestry(res)[leaf]
    assert hub in knowledge_scope.knowledge_ancestry(res)[leaf]

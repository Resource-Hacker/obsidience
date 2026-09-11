"""Parsing reuse cannot cache access, Task state, or evidence integrity."""
from copy import deepcopy
import os
import pytest
import yaml
from obsidience.harness.config import CONFIG
from obsidience.harness.knowledge import format as codec, vault, source


def test_unchanged_articles_parse_once_and_results_are_private(tmp_path, monkeypatch):
    monkeypatch.setattr(CONFIG, 'vault_dir', tmp_path)
    vault.write_note('Docs/one.md', {'kind':'knowledge', 'tags':['original']},
                     'Read [two](two.md).')
    vault._parsed_note.cache_clear()
    original = codec.loads
    calls = []
    def parse(text):
        calls.append(text)
        return original(text)
    monkeypatch.setattr(codec, 'loads', parse)
    first = vault.load_note('Docs/one.md')
    first.meta['tags'].append('injected')
    first.links.clear()
    second = vault.load_note('Docs/one.md')
    assert len(calls) == 1
    assert second.meta['tags'] == ['original']
    assert second.links == ['Docs/two']


def test_same_size_same_mtime_edit_and_deletion_are_immediately_visible(tmp_path, monkeypatch):
    monkeypatch.setattr(CONFIG, 'vault_dir', tmp_path)
    vault.write_note('one.md', {'kind':'agent', 'knowledge':['Docs/yes']}, 'Text')
    path=tmp_path/'one.md'; before=path.stat()
    assert vault.load_note('one.md').meta['knowledge'] == ['Docs/yes']
    path.write_text(path.read_text().replace('Docs/yes','Docs/not'))
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert path.stat().st_size == before.st_size
    assert vault.load_note('one.md').meta['knowledge'] == ['Docs/not']
    path.unlink()
    assert vault.load_note('one.md') is None
    assert vault.iter_notes() == []


def test_identical_bytes_in_different_paths_resolve_relative_links_independently(tmp_path, monkeypatch):
    monkeypatch.setattr(CONFIG, 'vault_dir', tmp_path)
    text=codec.dumps({'kind':'knowledge'}, '[target](target.md).')
    for parent in ('A','B'):
        (tmp_path/parent).mkdir(); (tmp_path/parent/'one.md').write_text(text)
    assert vault.load_note('A/one.md').links == ['A/target']
    assert vault.load_note('B/one.md').links == ['B/target']


def test_task_projection_is_never_cached(tmp_path, monkeypatch, isolated_task_ledger):
    monkeypatch.setattr(CONFIG, 'vault_dir', tmp_path)
    vault.write_note('Tasks/work.md', {'kind':'task'}, 'Work.')
    first=vault.load_note('Tasks/work.md')
    before=(tmp_path/first.path).read_bytes()
    isolated_task_ledger.mutate_task_runtime(first.ref, lambda state: state.update(status='failed', summary='Changed'))
    second=vault.load_note(first.path)
    assert second.meta['status']=='failed' and second.meta['summary']=='Changed'
    assert first.meta['status']=='draft'
    assert (tmp_path/first.path).read_bytes()==before


def test_cache_is_bounded_and_large_articles_bypass_it(tmp_path, monkeypatch):
    monkeypatch.setattr(CONFIG, 'vault_dir', tmp_path)
    vault._parsed_note.cache_clear()
    for number in range(520):
        vault._parsed_note('Content '+str(number), 'one.md')
    assert vault._parsed_note.cache_info().currsize==512
    (tmp_path/'large.md').write_text('x'*(128*1024+1))
    before=vault._parsed_note.cache_info()
    assert len(vault.load_note('large.md').body)==128*1024+1
    assert vault._parsed_note.cache_info()==before


@pytest.mark.parametrize('header', [
    'type: knowledge\ntitle: Ω\nwhen: 2026-09-11T01:02:03-07:00\n',
    'type: knowledge\ntags: &tags [one, two]\nextra: *tags\n',
    'type: knowledge\nbase: &base {a: 1}\nextra: {<<: *base, b: false}\n',
])
def test_accelerated_loader_preserves_timestamp_and_safe_metadata_semantics(header):
    class Reference(yaml.SafeLoader):
        pass
    Reference.yaml_implicit_resolvers=deepcopy(codec._Loader.yaml_implicit_resolvers)
    raw, body=codec.parse('---\r\n'+header.replace('\n','\r\n')+'---\r\n\r\nBody Ω\r\n')
    assert raw==yaml.load(header, Loader=Reference)
    assert body=='Body Ω\r\n'
    if 'when' in raw: assert isinstance(raw['when'],str)


def test_accelerated_loaders_reject_python_object_tags():
    for loader in (codec._Loader, source._StrictLoader):
        with pytest.raises(yaml.YAMLError):
            yaml.load('x: !!python/object:builtins.object {}', Loader=loader)
    with pytest.raises(source.SourceError, match='duplicate'):
        yaml.load('a: 1\na: 2\n', Loader=source._StrictLoader)

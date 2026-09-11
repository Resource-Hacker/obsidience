"""Agent access, displayed membership and owner checkout share one contract."""
from dataclasses import replace
import json
import pytest
from fastapi import HTTPException
from obsidience.harness.config import CONFIG
from obsidience.harness.knowledge import scope, vault, retrieval
from obsidience.harness.knowledge.vault import Note, Resolver
from obsidience.harness.capabilities.vault import read, search, list as listing
from obsidience.harness.interfaces.api import app as api

@pytest.fixture
def scoped(tmp_path, monkeypatch, isolated_task_ledger):
    monkeypatch.setattr(CONFIG, "vault_dir", tmp_path / "vault")
    real_sync = api.INDEX.sync
    monkeypatch.setattr(api.INDEX, "sync", lambda **kwargs: real_sync(embed=False))
    records = [
        ("Agents/Executive/Executive", "agent", {"role": "executive", "knowledge": ["[[Shared/Shared]]"]}, "Executive"),
        ("Agents/Darwin/Darwin", "agent", {"role": "researcher", "knowledge": []}, "Researcher"),
        ("Agents/Executive/Observations/Observations", "knowledge", {}, "Executive private facts"),
        ("Agents/Darwin/Observations/Observations", "knowledge", {}, "Research private facts"),
        ("Shared/Shared", "knowledge", {}, "Shared facts"),
        ("Shared/first", "knowledge", {}, "First shared fact"),
        ("Shared/second", "knowledge", {}, "Second shared fact"),
        ("Other/private", "knowledge", {}, "Must not leak"),
    ]
    for ref, kind, meta, body in records:
        vault.write_note(ref+'.md', {"kind": kind, "title": ref.rsplit('/',1)[-1], **meta}, body)
    return lambda: Resolver(vault.iter_notes())

def test_scope_is_explicit_and_observations_are_owned(scoped):
    res = scoped(); executive = res.resolve('Agents/Executive/Executive'); darwin = res.resolve('Agents/Darwin/Darwin')
    assert scope.knowledge_refs(executive,res) == {'Shared/Shared','Shared/first','Shared/second','Agents/Executive/Observations/Observations'}
    assert scope.knowledge_refs(darwin,res) == {'Agents/Darwin/Observations/Observations'}
    with pytest.raises(ValueError):
        scope.knowledge_refs(replace(darwin,meta={**darwin.meta,'knowledge':['[[Agents/Executive/Observations/Observations]]']}),res)
    with pytest.raises(PermissionError): scope.execution_scope({'agent':'Executive'},res)

def test_owner_checkout_revision_inheritance_and_revocation(scoped):
    res=scoped(); agent=res.resolve('Agents/Darwin/Darwin')
    payload={'agent':'researcher','assigned':True,'expected_revision':scope.revision(agent)}
    result=api.set_library_assignment('Shared/Shared',payload)
    assert result['checked'] and result['direct']
    with pytest.raises(HTTPException) as error: api.set_library_assignment('Shared/first',payload)
    assert error.value.status_code==409
    result=api.set_library_assignment('Shared/first',{'agent':'researcher','assigned':False,'expected_revision':result['revision']})
    assert not result['checked'] and result['excluded']
    allowed=scope.knowledge_refs(scoped().resolve(agent.ref),scoped())
    assert 'Shared/second' in allowed and 'Shared/first' not in allowed
    result=api.set_library_assignment('Shared/Shared',{'agent':'researcher','assigned':False,'expected_revision':result['revision']})
    assert scope.knowledge_refs(scoped().resolve(agent.ref),scoped()) == {'Agents/Darwin/Observations/Observations'}

@pytest.mark.parametrize('target',['Other/private','../Other/private','Agents/Executive/Observations/Observations','private'])
def test_read_cannot_escape_own_graph(scoped,target):
    result=read.execute({'ref':target},{'_agent_ref':'Agents/Darwin/Darwin'})
    assert 'Must not leak' not in result and 'Executive private facts' not in result
    assert 'not found' in result.lower()

def test_search_filters_before_index_limits_and_cannot_spoof_agent(scoped,monkeypatch):
    calls=[]
    def lane(query,weight,k,kind=None,*,eligible_refs=None):
        calls.append(eligible_refs)
        return [(weight,[(ref,1.0) for ref in sorted(eligible_refs or [])])]
    monkeypatch.setattr(retrieval,'_lanes_for',lane)
    result=search.execute({'query':'facts','agent':'Executive'},{'_agent_ref':'Agents/Darwin/Darwin'})
    assert calls==[{'Agents/Darwin/Darwin','Agents/Darwin/Observations/Observations'}]
    assert 'Research private facts' in result and 'Shared/first' not in result
    assert 'scope is unavailable' in search.execute({'query':'facts'},{}).lower()

def test_listing_and_backlinks_do_not_expose_other_scopes(scoped):
    vault.write_note('Other/private.md',{'kind':'knowledge','title':'Hidden incoming'},'[Shared](/Shared/first.md)')
    result=read.execute({'ref':'Shared/first'},{'_agent_ref':'Agents/Executive/Executive'})
    assert 'Hidden incoming' not in result and 'Other/private' not in result
    assert 'Shared/first' not in listing.execute({}, {'_agent_ref':'Agents/Darwin/Darwin'})

def test_graph_manifest_and_library_use_same_access(scoped,isolated_task_ledger):
    # Direct snapshot generation avoids any model, service or embedding work.
    isolated_task_ledger.sync(embed=False)
    result=api.graph(); groups={row['id']:row for row in result['navigation']['groups']}
    for role in ('executive','researcher'):
        res=scoped(); agent=res.resolve(groups[role]['root_ref'])
        actual={ref for ref in groups[role]['article_refs'] if ref in {n.ref for n in res.by_ref.values()}}
        assert actual==scope.readable_refs(agent,res)
    assert 'Other/private' in groups['library']['article_refs']
    assert 'Agents/Executive/Observations/Observations' in groups['library']['article_refs']

def test_relevant_passage_is_not_always_the_prefix():
    body=('Unrelated introduction. '*100)+'\n\n## Launch readiness\n\nNever redispatch after an uncertain application launch.\n'
    start,end=retrieval.passage_range(body,'application launch readiness')
    assert start>1200 and 'Never redispatch' in body[start:end]
    assert end-start<=1200

def test_passage_offsets_preserve_negation_and_short_documents():
    body='  Do not click twice.  '
    start,end=retrieval.passage_range(body,'click')
    assert body[start:end]=='Do not click twice.'


def test_unchecking_a_branch_revokes_earlier_direct_descendant_checkouts(scoped):
    agent = scoped().resolve('Agents/Darwin/Darwin')
    result = api.set_library_assignment('Shared/first', {'agent':'researcher','assigned':True,
        'expected_revision':scope.revision(agent)})
    parent = scope.checkout_state(scoped().resolve('Shared/Shared'), scoped().resolve(agent.ref), scoped())
    assert parent['partial'] and not parent['checked']
    result = api.set_library_assignment('Shared/Shared', {'agent':'researcher','assigned':True,
        'expected_revision':result['revision']})
    result = api.set_library_assignment('Shared/Shared', {'agent':'researcher','assigned':False,
        'expected_revision':result['revision']})
    assert scope.knowledge_refs(scoped().resolve(agent.ref), scoped()) == {'Agents/Darwin/Observations/Observations'}


@pytest.mark.parametrize('origin', ['absolute', 'file_url', 'normalized'])
def test_raw_source_does_not_bypass_knowledge_checkout(scoped, monkeypatch, origin):
    from obsidience.harness.capabilities.source import read as source_read
    from obsidience.harness.knowledge import source
    path = CONFIG.vault_dir / 'Other/private.md'
    reference = str(path) if origin == 'absolute' else path.as_uri()
    if origin == 'normalized':
        reference = str(CONFIG.vault_dir / 'Shared/../Other/private.md')
    result = {'citation':'source://fixture','source_ref':reference,'content':'PRIVATE EVIDENCE',
        'content_sha256':'hash','source_type':'document','captured_at':'now'}
    monkeypatch.setattr(source, 'get_source', lambda _: result)
    context = {'_agent_ref':'Agents/Darwin/Darwin'}
    output = source_read.execute({'source':'fixture'}, context)
    assert 'PRIVATE EVIDENCE' not in output and 'permitted evidence scope' in output
    assert not context.get('_source_reads')


def test_observation_archive_handoff_is_exact_not_global_access(scoped):
    from obsidience.harness.capabilities.source.read import _private_source_allowed
    result = {'citation':'source://fixture','content_sha256':'hash',
        'source_ref':'obsidience://observations/temporary/session/key',
        'content':'## [[Agents/Executive/Observations/Temporary Observations/example]]'}
    context = {'_agent_ref':'Agents/Darwin/Darwin'}
    assert not _private_source_allowed(result, context)
    context['_observation_archive'] = {'citation':'source://fixture','content_sha256':'hash'}
    assert _private_source_allowed(result, context)
    assert not _private_source_allowed({**result,'content_sha256':'changed'}, context)
    assert 'Agents/Executive/Observations/Observations' not in scope.execution_scope(context, scoped())[1]


def test_working_context_retains_objective_and_rejects_late_progress(scoped):
    from obsidience.harness.conversation.observations import project_activation_context
    agent = scoped().resolve('Agents/Executive/Executive')
    vault.write_note(agent.path, {**agent.meta,'auto_curate':True}, agent.body)
    first = project_activation_context(agent.ref, 'Tasks/query', 'first', {}, [],
        objective='Exact current request', context_refs=['Shared/first'], begin=True)
    assert first['materialized']
    note = vault.load_note(first['ref'] + '.md')
    assert 'Exact current request' in note.body and 'Shared/first' in note.body
    assert note.runtime_observation and note.meta['retrieval'] is False
    assert first['context']['current_objective'] != 'Exact current request'  # The prompt has one Objective.
    project_activation_context(agent.ref, 'Tasks/query', 'second', {}, [], objective='Next request', begin=True)
    for state in ('running','completed','interrupted'):
        late = project_activation_context(agent.ref, 'Tasks/query', 'first', {}, [], state)
        assert not late['materialized']
    assert vault.load_note(first['ref'] + '.md').meta['activation_id'] == 'second'


def test_reader_library_indexes_include_all_agents_and_procedures(scoped):
    vault.write_note('Runbooks/example.md', {'kind':'runbook','title':'Example'}, 'Procedure.')
    root = api._base_article('@library')
    assert '@library/Agents' in root['children'] and '@library/Runbooks' in root['children']
    agents = api._base_article('@library/Agents')
    assert 'Agents/Executive/Executive' in agents['children']
    assert 'Agents/Darwin/Darwin' in agents['children']
    assert 'Runbooks/example' in api._base_article('@library/Runbooks')['children']


def test_reader_scope_proxy_does_not_show_unselected_parent_or_siblings(scoped, isolated_task_ledger):
    agent = scoped().resolve('Agents/Darwin/Darwin')
    api.set_library_assignment('Shared/first', {'agent':'researcher','assigned':True,
        'expected_revision':scope.revision(agent)})
    isolated_task_ledger.sync(embed=False)
    doc = api.get_article('@branch/Shared', graph_id='Darwin')
    assert doc['read_only'] and doc['meta']['scope_proxy'] == 'true'
    assert doc['children'] == ['Shared/first']
    assert 'Shared facts' not in doc['body'] and 'sibling' not in doc['body']
    with pytest.raises(Exception) as failure:
        api.get_article('Shared/second', graph_id='Darwin')
    assert failure.value.status_code == 404
    assert 'Second shared fact' in api.get_article('Shared/second', graph_id='library')['body']


def test_link_never_stages_unread_or_out_of_scope_endpoints(scoped):
    from obsidience.harness.capabilities.vault import propose
    vault.write_note('Tasks/link.md', {'kind':'task','title':'Link','taxonomy_path':'wiki/link'}, 'Link read Articles.')
    context={'_agent_ref':'Agents/Executive/Executive','agent':'Executive','task':'Tasks/link','run_id':'link-scope'}
    args={'target':'Shared/first','action':'update','title':'First',
          'body':'First shared fact. [Second](/Shared/second.md) supplies a related fact.'}
    assert 'complete current vault.read' in propose.execute(args,context)
    assert not context.get('staged_proposals')
    read.execute({'refs':['Shared/first','Shared/second']},context)
    outside={**args,'body':'First fact. [Private](/Agents/Darwin/Observations/Observations.md)'}
    assert 'Knowledge scope' in propose.execute(outside,context)
    assert not context.get('staged_proposals')
    assert 'staged for owner review' in propose.execute(args,context)
    assert len(context['staged_proposals'])==1


def test_queued_private_candidate_stops_before_compiler_or_model(scoped, monkeypatch, execution):
    import asyncio
    from obsidience.harness.execution import executor
    execution.task.ref='Tasks/link'
    execution.task.meta['assignee']='Agents/Darwin/Darwin'
    monkeypatch.setattr(executor,'resolver',lambda **_kwargs:scoped())
    monkeypatch.setattr(executor.model_runtime,'resolve_model',lambda *_args:pytest.fail('Out-of-scope candidate acquired model'))
    monkeypatch.setattr(executor,'compile_activation',lambda *_a,**_kw:pytest.fail('Out-of-scope candidate compiled'))
    with pytest.raises(PermissionError,match='current Knowledge scope'):
        asyncio.run(execution.run(runtime_params={'event':'task.create','activation_key':'private-candidate',
            'candidate_key':'candidate','candidate_refs':['Shared/first','Agents/Executive/Observations/Observations']}))
    assert execution.calls==[]
    assert execution.records[-1]['status']=='failed'
    receipts=executor.INDEX.tool_run_receipts(execution.records[-1]['id'])
    assert receipts['task_ref']=='Tasks/link' and receipts['calls']==[]
    assert execution.events[-1]['phase']=='query_completed'
    assert execution.events[-1]['graph_id']=='Darwin'


from obsidience.tests.test_execution_cancellation import execution  # noqa: F401

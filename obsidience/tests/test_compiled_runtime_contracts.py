"""Typed Tool contracts and narrow exact-source instruction compilation."""
from dataclasses import replace
import pytest
import json
from obsidience.harness.capabilities import registry
from obsidience.harness.execution import executor
from obsidience.harness.knowledge.vault import Note, Resolver, resolver
from obsidience.harness.knowledge import scope


def test_every_registered_tool_has_a_distinct_argument_contract():
    schema=registry.action_schema(list(registry.REGISTRY))
    assert len(schema['anyOf'])==len(registry.REGISTRY)==30
    byname={row['properties']['tool']['enum'][0]:row['properties']['args'] for row in schema['anyOf']}
    assert byname['application.launch']['required']==['application']
    assert byname['application.launch']['properties']['application']['enum']
    assert byname['computer.act']['properties']['point']['properties']['x']['maximum']==999
    assert byname['window.place']['required']==['target','destination']
    assert byname['harness.status']['additionalProperties'] is False
    with pytest.raises(ValueError): registry.action_schema(['imaginary.tool'])
    with pytest.raises(ValueError): registry.action_schema([])
    byname['application.launch']['properties'].clear()
    assert registry.argument_schema('application.launch')['properties']


def test_runtime_sections_are_exact_noncontiguous_source_ranges():
    body='Intro.\n\n## Runtime\n\nNever replay.\n\n## Launch\n\nWait for ready.\n\n## Action\n\nObserve first.\n\n## Reference\n\nExtra detail.\n'
    note=Note('Runbooks/demo.md','Demo',{'kind':'runbook','runtime_sections':{'launch':'Launch'}},body)
    text=executor._instruction_text(note,'launch')
    assert 'Never replay' in text and 'Wait for ready' in text
    assert 'Observe first' not in text and 'Extra detail' not in text
    assert all(body[a:b].strip() in text for a,b in executor._instruction_ranges(note,'launch'))
    with pytest.raises(ValueError): executor._instruction_text(replace(note,meta={**note.meta,'runtime_sections':{'launch':'Missing'}}),'launch')


def test_operation_profile_cannot_grant_an_unassigned_tool():
    book=Note('Runbooks/demo.md','Demo',{'kind':'runbook','operation_tools':{'launch':['Tools/imaginary']}},'Procedure')
    with pytest.raises(ValueError,match='widen'):
        executor._operation_spine({'runbook':book,'tools':['task.complete']},{'computer_outcome':'launch'})


def test_actual_launch_packet_uses_two_tools_and_not_reference_prose():
    res=resolver(); task=res.resolve('Tasks/executive/operate'); agent=res.resolve('Agents/Executive/Executive')
    complete=executor.resolve_spine(task,res)
    assert not complete.get('error'),complete
    narrow=executor._operation_spine(complete,{'computer_outcome':'launch'})
    assert narrow['tools']==['application.launch','task.complete']
    binding=executor.ActivationBinding(objective='Open Microsoft Edge.',bindings={'computer_outcome':'launch','application':'microsoft_edge'})
    packet,refs=executor._activation_packet(task,agent,narrow,binding,'','',accepted_resolver=res)
    assert 'Tools/application.launch' in refs and 'Tools/computer.act' not in refs
    assert '## Reference' not in packet
    assert 'Wait for ready' not in packet  # This exact synthetic fixture cannot contaminate real contracts.
    full_chars=sum(len(note.body) for note in [task,*complete['runbooks'],*complete['skills'],*complete['tool_articles']])
    compiled_chars=sum(len(executor._instruction_text(note,'launch')) for note in [*narrow['runbooks'],*narrow['skills'],*narrow['tool_articles']])
    assert compiled_chars<full_chars*0.30,(compiled_chars,full_chars)


def test_required_context_fails_closed_when_revoked_or_stale():
    agent=Note('Agents/A/A.md','A',{'kind':'agent'},'A')
    task=Note('Tasks/a.md','A',{'kind':'task','required_context':['Shared/rule']},'Outcome')
    rule=Note('Shared/rule.md','Rule',{'kind':'knowledge'},'Never repeat an uncertain effect.')
    res=Resolver([agent,task,rule])
    with pytest.raises(ValueError,match='unavailable'):
        executor._required_context(task,agent,{},res,set())
    assert executor._required_context(task,agent,{},res,{rule.ref})==[rule]
    stale=replace(rule,meta={'kind':'knowledge','stale_after':'2000-01-01T00:00:00Z'})
    with pytest.raises(ValueError,match='stale'):
        executor._required_context(task,agent,{},Resolver([stale]),{rule.ref})


def test_decoder_schema_keeps_tool_structure_without_expanding_size_bound_repetitions():
    from obsidience.harness.capabilities.registry import action_schema, decoder_action_schema
    canonical = action_schema(['task.complete', 'task.create'])
    decoded = decoder_action_schema(['task.complete', 'task.create'])
    assert 'maxLength' in json.dumps(canonical)
    assert 'maxLength' not in json.dumps(decoded) and 'maxItems' not in json.dumps(decoded)
    assert [item['properties']['tool'] for item in canonical['anyOf']] == [item['properties']['tool'] for item in decoded['anyOf']]
    assert all(item['additionalProperties'] is False and item['required'] == ['tool','args'] for item in decoded['anyOf'])
    assert 'required' in json.dumps(decoded) and 'enum' in json.dumps(decoded)
    assert action_schema(['task.complete','task.create']) == canonical


def test_shipped_articles_use_native_okf_namespacing():
    from obsidience.harness.config import CONFIG
    from obsidience.harness.knowledge.format import parse, validate_profile
    failures = []
    for path in CONFIG.vault_dir.rglob('*.md'):
        relative = path.relative_to(CONFIG.vault_dir)
        if any(part.startswith(('_','.')) for part in relative.parts): continue
        metadata, _body = parse(path.read_text())
        if 'type' not in metadata and path.name in {'index.md','log.md'}: continue
        failures.extend(f'{relative}: {error}' for error in validate_profile(metadata,relative))
    assert failures == []


def test_evidence_bound_completion_schema_requires_fields_without_forcing_success():
    from obsidience.harness.capabilities.task.complete import completion_requires_no_change
    from obsidience.harness.models import llm, runtime
    ctx={'task':'Tasks/link','maintenance_candidate':{'candidate_refs':['A','B']}}
    assert completion_requires_no_change(ctx)
    payload=llm._chat_payload([{'role':'user','content':'Finish the inspection.'}],
        runtime.MODELS[runtime.EXECUTIVE_MODEL], max_tokens=100, temperature=0,
        reasoning_effort='none', allowed_tools=['task.complete'], completion_no_change=True)
    branches=payload['response_format']['json_schema']['schema']['anyOf'][0]['properties']['args']['anyOf']
    success, other=branches
    assert success['properties']['status']=={'const':'completed'}
    assert success['properties']['outcome']=={'const':'no_change'}
    assert {'outcome','evidence'} <= set(success['required'])
    assert success['properties']['evidence']['minItems']==1
    assert 'failed' in other['properties']['status']['enum']
    assert 'outcome' not in other['required']
    assert not completion_requires_no_change({'task':'Tasks/query'})
    assert not completion_requires_no_change({**ctx,'staged_proposals':[{'auto_approved':True,'target':'A.md'}]})
    assert not completion_requires_no_change({**ctx,'staged_proposals':[{'staged':'','target':'A.md'}]})
    assert 'outcome' not in registry.argument_schema('task.complete')['required']

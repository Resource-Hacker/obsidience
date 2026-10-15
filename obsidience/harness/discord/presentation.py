"""A read-only public presentation of the Discord Agent's accepted graph.

This is a filtered projection over existing owners. It receives no transcript,
model reasoning, Tool arguments/results, credentials or desktop state.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import re

from ..knowledge import projection

AGENT_REF = 'Agents/Discord/Discord'
GRAPH_ID = 'Discord'
MAX_NODES = 512
MAX_LINKS = 1024
MAX_MEMORY_NODES = 1000
MAX_MEMORY_EDGES = 4000
_PHASES = {'query_started', 'path', 'query_completed', 'cleared'}
_KINDS = {'context': 'Context in use', 'read': 'Reading', 'search': 'Searching',
          'list': 'Listing', 'tool': 'Tool activity'}
_MEMORY_KINDS = {'search': 'Recalling memory', 'read': 'Reading memory',
                 'retain': 'Memory retained', 'consolidate': 'Memory consolidated',
                 'retire': 'Memory retired'}
_STATUSES = {'running', 'returned', 'completed', 'failed', 'interrupted'}


def opaque(value):
    return 'd' + hashlib.sha256(str(value).encode()).hexdigest()[:24]


def public_title(title, kind='knowledge'):
    if (not isinstance(title, str) or not title.strip() or len(title) > 160
            or any(ord(char) < 32 for char in title)
            or re.search(r'(?:/(?:home|var|mnt|run|etc)/|(?:file|source|https?)://)', title, re.I)):
        return 'Discord Agent' if kind == 'agent' else kind.title()
    return title


@dataclass
class Presentation:
    graph: dict
    refs: dict[str, str]
    memory_refs: dict[str, str] = field(default_factory=dict)
    memory_graph_id: str = ""


def snapshot():
    """Redact the canonical accepted Agent graph without another scope owner."""
    empty = Presentation({'available': False, 'nodes': [], 'links': [], 'group': None}, {})
    native = projection.graph()
    group = next((entry for entry in native['navigation']['groups']
                  if entry['root_ref'] == AGENT_REF and entry['id'] == 'discord'), None)
    if group is None:
        return empty
    members = set(group['article_refs'])
    nodes = [node for node in native['nodes'] if node['id'] in members
             and not str(node['id']).startswith(('_', '.'))
             and (not str(node['id']).startswith('Agents/') or node['id'] == AGENT_REF)]
    if len(nodes) > MAX_NODES:
        return empty
    # The canonical graph absorbs some folder Articles into subjects. Preserve
    # those exact aliases while changing all public identities to opaque IDs.
    subjects = [subject for subject in group['subjects']
                if not subject['id'].endswith('/other-agents')]
    mapping = {}
    for subject in subjects:
        key = subject['id'].rsplit('/', 1)[-1]
        suffix = '/' + key if key in {'tools', 'skills', 'tasks', 'runbooks', 'observations'} else ''
        mapping[subject['id']] = opaque(subject['id']) + suffix
        if subject.get('article_ref'):
            mapping[subject['article_ref']] = mapping[subject['id']]
    for node in nodes:
        identifier = mapping.get(node.get('navigation_ref')) or mapping.get(node['id']) or opaque(node['id'])
        mapping[node['id']] = identifier
        if node.get('article_ref'):
            mapping[node['article_ref']] = identifier
    if AGENT_REF not in mapping:
        return empty
    public_nodes = []
    seen = set()
    for node in nodes:
        identifier = mapping[node['id']]
        if identifier in seen:
            continue
        seen.add(identifier)
        row = {'id': identifier, 'title': public_title(node.get('title'), node['kind']), 'kind': node['kind'],
               'children': [mapping[ref] for ref in node.get('children', []) if ref in mapping]}
        for key in ('parent_id', 'navigation_ref'):
            if node.get(key) in mapping:
                row[key] = mapping[node[key]]
        public_nodes.append(row)
    public_subjects = [{'id': mapping[subject['id']], 'title': public_title(subject.get('title')),
                        'parent_id': mapping.get(subject.get('parent_id')),
                        **({'article_ref': mapping[subject['article_ref']]}
                           if subject.get('article_ref') in mapping else {})}
                       for subject in subjects]
    links = []
    for link in native['links']:
        if (link['source'] not in mapping or link['target'] not in mapping
                or link.get('for_agent') not in {None, AGENT_REF}
                or any(ref not in mapping for ref in link.get('via', []))):
            continue
        source, target = mapping[link['source']], mapping[link['target']]
        if source != target:
            links.append({'source': source, 'target': target})
    if len(links) > MAX_LINKS:
        return empty
    public_group = {'id': 'discord', 'role': 'discord', 'title': public_title(group['title'], 'agent'),
                    'subtitle': 'Discord Agent', 'root_ref': mapping[AGENT_REF],
                    'subjects': public_subjects, 'article_refs': sorted(set(mapping.values()))}
    graph = {'available': True, 'nodes': public_nodes, 'links': links, 'group': public_group}
    memory, memory_refs, memory_graph_id = memory_snapshot()
    graph['memory'] = memory
    graph['revision'] = opaque(repr(graph))
    return Presentation(graph, mapping, memory_refs, memory_graph_id)


def memory_snapshot():
    """Use the existing exact-bank provider projection, strip all Memory prose.

    Record type, discussion day and actual links retain the native timeline.
    No query, body, entity, provenance, bank identity or other Agent is public.
    """
    empty = {'available': False, 'provider': 'hindsight', 'graph_id': 'memory:discord',
             'nodes': [], 'edges': [], 'total': 0, 'limited': False}
    bank = ''
    try:
        from ..memory.hindsight import MEMORY, bank_for
        from ..interfaces.api.routes.graphs import memory_graph
        bank = bank_for(AGENT_REF)
        if MEMORY.banks.get(bank) != AGENT_REF:
            return empty, {}, ''
        native = json.loads(memory_graph(bank, limit=MAX_MEMORY_NODES).body)
        if len(native['nodes']) > MAX_MEMORY_NODES:
            return empty, {}, 'memory:' + bank
        mapping = {node['id']: opaque(node['id']) for node in native['nodes']}
        kinds = {'experience': ('Experience', '#38bdf8'), 'world': ('World memory', '#5eead4'),
                 'observation': ('Observation', '#c4b5fd')}
        nodes = []
        for node in native['nodes']:
            kind = node['kind'] if node['kind'] in kinds else 'memory'
            name, color = kinds.get(kind, ('Memory', '#94a3b8'))
            date = str(node.get('date', ''))[:10]
            nodes.append({'id': mapping[node['id']], 'name': name, 'kind': kind, 'color': color,
                          'date': date if re.fullmatch(r'\d{4}-\d{2}-\d{2}', date) else ''})
        edges = [{'source': mapping[edge['source']], 'target': mapping[edge['target']],
                  'kind': 'supports' if edge['kind'] == 'supports' else 'related',
                  'weight': 1, 'color': '#6d8baa'}
                 for edge in native['edges'][:MAX_MEMORY_EDGES]
                 if edge['source'] in mapping and edge['target'] in mapping]
        return {**empty, 'available': True, 'nodes': nodes, 'edges': edges,
                'total': native['total'],
                'limited': native['limited'] or len(native['edges']) > MAX_MEMORY_EDGES}, mapping, 'memory:' + bank
    except Exception:
        return empty, {}, 'memory:' + bank if bank else ''


class ActivityProjection:
    """Admit operations only after an exact Discord Agent/run correlation."""
    def __init__(self, view: Presentation):
        self.view = view
        self.runs: dict[str, None] = {}

    def project(self, entry):
        if not self.view.graph['available'] or not isinstance(entry, dict):
            return None
        if entry.get('type') == 'operation':
            operation = entry.get('operation')
            if not isinstance(operation, dict):
                return None
            if self.view.memory_graph_id and operation.get('graph_id') == self.view.memory_graph_id:
                # Native retain/consolidation and recall are bank-owned events;
                # they can finish after the conversational run has ended.
                kind = operation.get('kind')
                if kind not in _MEMORY_KINDS or operation.get('status') not in _STATUSES:
                    return None
                return {'type': 'operation', 'operation': {
                    'id': opaque(operation.get('id')), 'kind': kind, 'status': operation['status'],
                    'label': _MEMORY_KINDS[kind], 'graph_id': 'memory:discord',
                    'refs': [self.view.memory_refs[ref] for ref in operation.get('refs', [])
                             if ref in self.view.memory_refs][:128],
                    'at': operation.get('at', 0), 'expires_at': operation.get('expires_at', 0),
                    'refresh': False,
                }}
            if operation.get('run_id') not in self.runs:
                return None
            if operation.get('kind') not in _KINDS or operation.get('status') not in _STATUSES:
                return None
            if operation.get('graph_id') not in {GRAPH_ID, '*'}:
                return None
            refs = [self.view.refs[ref] for ref in operation.get('refs', []) if ref in self.view.refs]
            return {'type': 'operation', 'operation': {
                'id': opaque(operation.get('id')), 'kind': operation['kind'],
                'status': operation['status'], 'label': _KINDS[operation['kind']],
                'refs': refs[:128], 'run_id': opaque(operation['run_id']), 'graph_id': 'discord',
                'at': operation.get('at', 0), 'started_at': operation.get('started_at', 0),
                'expires_at': operation.get('expires_at', 0), 'omitted_refs': 0,
            }}
        phase, run = entry.get('phase'), entry.get('run_id')
        if (phase not in _PHASES or entry.get('graph_id') != GRAPH_ID
                or not isinstance(run, str) or not run or len(run) > 128):
            return None
        refs = entry.get('refs', [])
        if phase in {'query_started', 'path'} and AGENT_REF in refs:
            self.runs[run] = None
            while len(self.runs) > 64:
                self.runs.pop(next(iter(self.runs)))
        if run not in self.runs:
            return None
        result = {'type': 'activity', 'phase': phase, 'run_id': opaque(run),
                  'refs': [self.view.refs[ref] for ref in refs if ref in self.view.refs][:128],
                  'graph_id': 'discord', 'at': entry.get('at', 0)}
        if phase in {'query_completed', 'cleared'}:
            self.runs.pop(run, None)
        return result

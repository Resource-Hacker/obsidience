"""Execute native Source/Reader logic against isolated requests and file fixtures."""
import json
from pathlib import Path
import re
import subprocess

import pytest


ROOT = Path(__file__).parents[1]
SOURCE = ROOT / "shell/qml/panes/source/SourcePane.qml"
READER = ROOT / "shell/qml/panes/reader/ReaderPane.qml"


def run_native(path, functions, setup, script):
    text = path.read_text()
    methods = "\n".join(
        re.search(rf"^    function {name}\([^\n]*\) \{{.*?^    \}}", text, re.M | re.S)[0]
        for name in functions
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", "import {strict as assert} from 'node:assert';\n"
         "import vm from 'node:vm';\n" + setup + "\nstate.root=state;vm.createContext(state);\n"
         + f"vm.runInContext({json.dumps(methods)},state);\n" + script],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr


TREE_SETUP = r"""
const state={systemPrefix:'obsidience/state/system', evidencePrefix:'obsidience/evidence',
 vaultPrefix:'obsidience/vault',files:[],issues:[],articleRefs:{},selectedRef:'',selectedKey:'',showAll:true,
 query:'',expandedPaths:{},visibleRows:[]};
const file=path=>({key:path,path,name:path.split('/').at(-1),articles:[],read_only:true});
const flatten=nodes=>nodes.flatMap(node=>[node,...flatten(node.children||[])]);
const plain=value=>JSON.parse(JSON.stringify(value));
"""
TREE_FUNCTIONS = ("folder", "route", "buildTree", "filterTree",
                  "sourceMatchesArticle", "rebuildRows")


def test_initial_expansion_exposes_four_sections_without_opening_code_or_raw_items():
    source = SOURCE.read_text()
    defaults = json.loads(re.search(r"property var expandedPaths: \((\{.*?\})\)", source, re.S)[1])
    assert set(defaults) == {"@view/system", "@view/knowledge"}
    run_native(SOURCE, TREE_FUNCTIONS + ("toggleFolder",), TREE_SETUP,
               "state.expandedPaths=" + json.dumps(defaults) + r""";
state.files=[file('obsidience/harness/knowledge/source.py'),
 file('obsidience/state/system/hardware/network/connections.json'),
 file('obsidience/state/system/applications/obsidience/application.json'),
 file('obsidience/vault/ADMECH Workstation/ADMECH Workstation.md'),
 ...Array.from({length:1000},(_,i)=>file('obsidience/evidence/raw/2026-09-10/item-'+i+'.md'))];
state.rebuildRows();
assert.deepEqual(plain(state.visibleRows.filter(row=>row.depth===0).map(row=>row.node.name)),
 ['SYSTEM','KNOWLEDGE MARKDOWN','EVIDENCE','PROJECT FILES']);
assert(state.visibleRows.length<=8);
assert(!state.visibleRows.some(row=>row.type==='file'));
state.toggleFolder('@view/evidence');
assert(state.visibleRows.some(row=>row.node.name==='incoming'));
assert(!state.visibleRows.some(row=>row.type==='file'));
state.toggleFolder('@view/evidence');
assert(!state.visibleRows.some(row=>row.node.name==='incoming'));
""")
    fallback = (ROOT / "ui/src/renderer/src/panes/reader-pane.tsx").read_text()
    initial = re.search(r"const \[expanded, setExpanded\] = useState<Set<string>>\(\(\) => new Set\(\[(.*?)\]\)\);",
                        fallback, re.S)[1]
    assert re.findall(r"SOURCE_VIEW\.(\w+)", initial) == ["system", "knowledge"]


def test_source_roots_and_manual_import_description_are_always_available():
    run_native(SOURCE, TREE_FUNCTIONS, TREE_SETUP, r"""
const roots=state.buildTree([]);
assert.deepEqual(plain(roots.map(node=>node.name)),['SYSTEM','KNOWLEDGE MARKDOWN','EVIDENCE','PROJECT FILES']);
assert.equal(roots[0].backingPath,'obsidience/state/system');
assert.equal(roots[1].backingPath,'obsidience/vault');
assert.equal(roots[2].backingPath,'obsidience/evidence');
assert.equal(roots[3].backingPath,'');
assert.deepEqual(plain(roots[2].children.map(node=>[node.name,node.backingPath])),[
 ['raw','obsidience/evidence/raw'],['inbox','obsidience/evidence/inbox'],
 ['system','obsidience/evidence/system'],['incoming','obsidience/evidence/incoming']]);
assert.match(roots[2].children.at(-1).subtitle,/Manual text imports.*Darwin Learn.*originals remain/);
assert(!flatten(roots[0].children).some(node=>node.name==='RECORDED EVIDENCE'));
""")


PHYSICAL_TREE_ASSERTIONS = r"""
const paths=[
 'obsidience/state/system/hardware/network/connections.json',
 'obsidience/state/system/hardware/compute/cpu.json',
 'obsidience/state/system/snapshots/network/2026-09-10/evidence--old.md',
 'obsidience/evidence/incoming/import/Exact Article.txt',
 'obsidience/evidence/raw/2026-09-10/article--exact.md',
 'obsidience/evidence/inbox/2026-09-10/research--exact.md',
 'obsidience/evidence/evaluations/cases/fixture.json',
 'obsidience/evidence/models/Model/artifact.json',
 'obsidience/evidence/system/schema.network/2026-09-10/evidence--current.md',
 'obsidience/vault/News & Research/Story.md',
 'obsidience/harness/knowledge/source.py'];
const files=paths.map(file);
files[0].system_label='Network';
files[0].system_breadcrumbs=[{path:'obsidience/state/system',title:'System'},
 {path:'obsidience/state/system/hardware',title:'Hardware'},
 {path:'obsidience/state/system/hardware/network',title:'Network'}];
const roots=state.buildTree(files);
const nodes=flatten(roots),leaves=nodes.filter(node=>!node.folder);
assert.equal(leaves.length,paths.length);
assert.equal(new Set(leaves.map(node=>node.file.key)).size,paths.length);
for(const leaf of leaves){assert.equal(leaf.key,leaf.file.key);assert.equal(leaf.file.key,leaf.file.path);}
const hardware=roots[0].children.find(node=>node.key==='obsidience/state/system/hardware');
const network=hardware.children.find(node=>node.key==='obsidience/state/system/hardware/network');
assert.equal(hardware.name,'Hardware');assert.equal(network.name,'Network');
assert.equal(network.backingPath,'obsidience/state/system/hardware/network');
assert.equal(network.children[0].file.path,paths[0]);assert.equal(network.children[0].name,'Network');
const keys=root=>plain(flatten(root.children).filter(node=>!node.folder).map(node=>node.key)).sort();
assert.deepEqual(keys(roots[0]),paths.slice(0,2).sort());
assert.deepEqual(keys(roots[1]),[paths[9]]);
assert.deepEqual(keys(roots[2]),paths.slice(2,9).sort());
assert.deepEqual(keys(roots[3]),[paths[10]]);
assert.equal(nodes.find(node=>node.key==='obsidience/vault/News & Research').backingPath,
 'obsidience/vault/News & Research');
assert(!nodes.some(node=>node.key==='@view/system/hardware/drives/system-volume/obsidience'));
"""


def test_source_routes_descriptors_vault_evidence_and_code_once_with_exact_keys():
    run_native(SOURCE, TREE_FUNCTIONS, TREE_SETUP, PHYSICAL_TREE_ASSERTIONS)


def test_optional_article_filter_keeps_intake_and_does_not_reset_on_selection():
    run_native(SOURCE, TREE_FUNCTIONS + ("applyShellEvent",), TREE_SETUP, r"""
state.files=[file('obsidience/evidence/raw/Original.md'),file('obsidience/harness/other.py')];
state.showAll=true;
state.applyShellEvent(JSON.stringify({schema:'obsidience.shell.event.v1',type:'pane.state',
 pane:{pane_id:'reader'},selection:{kind:'article',ref:'Knowledge/Selected'}}));
assert.equal(state.showAll,true);
state.showAll=false;
state.expandedPaths={'@view/evidence':true,'obsidience/evidence/raw':true};
state.rebuildRows();
assert(state.visibleRows.some(row=>row.node.key==='obsidience/evidence/raw/Original.md'));
assert(!state.visibleRows.some(row=>row.node.key==='obsidience/harness/other.py'));
state.query='original';state.rebuildRows();
assert(state.visibleRows.some(row=>row.node.key==='obsidience/evidence/raw/Original.md'));
""")
    assert "property bool showAll: true" in SOURCE.read_text()


REQUEST_SETUP = r"""
const requests=[];
class Request {
 static DONE=4;
 open(method,url){this.method=method;this.url=url;}
 setRequestHeader(){}
 send(body){this.body=body;requests.push(this);}
 respond(data,status=200){this.status=status;this.readyState=4;
  this.responseText=typeof data==='string'?data:JSON.stringify(data);this.onreadystatechange();}
}
"""


def test_system_refresh_retains_prior_evidence_rejects_stale_get_and_reload_is_explicit():
    run_native(SOURCE, ("loadSystemKnowledge", "systemKnowledgeLabel", "systemKnowledgeDetails"), REQUEST_SETUP + r"""
const previous={status:'ready',updated_at:'2026-09-10T03:00:00Z',categories:Array.from({length:7},()=>({title:'Category',status:'current'})),
 current_count:7,article_count:7};
const state={XMLHttpRequest:Request,systemRequestGeneration:0,systemRefreshBusy:false,
 systemKnowledge:previous,systemError:'',reloads:0,refresh(){this.reloads++;}};
""", r"""
state.loadSystemKnowledge(false);
const old=requests.at(-1);assert.equal(old.method,'GET');
assert(old.url.endsWith('/api/system/knowledge'));
state.loadSystemKnowledge(true);
const capture=requests.at(-1);assert.equal(capture.method,'POST');
assert(capture.url.endsWith('/api/system/refresh'));
state.loadSystemKnowledge(true);assert.equal(requests.at(-1),capture);
assert.match(state.systemKnowledgeLabel(),/Recording/);
const fresh={...previous,updated_at:'2026-09-10T04:00:00Z'};
capture.respond(fresh);
assert.equal(state.reloads,1);assert.equal(state.systemRefreshBusy,false);
old.respond({...previous,status:'degraded'});
assert.equal(state.systemKnowledge.updated_at,fresh.updated_at);
state.loadSystemKnowledge(true);requests.at(-1).respond('Unavailable',503);
assert.equal(state.systemKnowledge.updated_at,fresh.updated_at);
assert.equal(state.reloads,1);assert.match(state.systemKnowledgeLabel(),/previous evidence retained/);
state.loadSystemKnowledge(false);requests.at(-1).respond({...fresh,status:'degraded',current_count:5,article_count:5,
 categories:previous.categories.map((item,i)=>i<5?item:{title:'Camera',status:'unavailable',detail:'Permission denied'})});
assert.match(state.systemKnowledgeLabel(),/5\/7 current.*Some observations unavailable.*Checked /);
assert.match(state.systemKnowledgeDetails(),/Camera: Permission denied/);
assert.equal(state.reloads,1); // Reading status never triggers collection or a Source refresh.
state.loadSystemKnowledge(true);requests.at(-1).respond('broken JSON');
assert.equal(state.systemRefreshBusy,false);assert.equal(state.reloads,1);
assert.equal(state.systemKnowledge.status,'degraded');
""")


@pytest.mark.parametrize("management", ["{read_only:true}", "{managed_by:'system'}"])
def test_native_reader_owned_articles_cannot_edit_save_or_change_auto_curate(management):
    run_native(READER, ("resetDocument", "loadDocument", "startEdit", "saveArticle", "setAutoCurate"),
               REQUEST_SETUP + r"""
const state={XMLHttpRequest:Request,feedItemMode:false,feedItemId:'',sourceMode:false,sourceKey:'',
 previewMode:false,previewItem:{},selectionKind:'article',articleRef:'ADMECH Workstation/System Identity',
 requestGeneration:0,loadArticleTitles(){}};
""", "const management=" + management + r""";
state.loadDocument();
requests.at(-1).respond({title:'System Identity',kind:'knowledge',body:'Exact observed evidence',
 auto_curate_supported:true,auto_curate:true,...management});
assert.equal(state.articleReadOnly,true);assert.equal(state.autoCurateSupported,false);
const count=requests.length;
state.startEdit();assert.equal(state.editing,false);
state.draftTitle='Attempted edit';state.draftBody='Replacement';state.saveArticle();
state.setAutoCurate(false);assert.equal(requests.length,count);
state.articleRef='Knowledge/Ordinary';state.loadDocument();
requests.at(-1).respond({title:'Ordinary',body:'Editable',auto_curate_supported:true});
assert.equal(state.articleReadOnly,false);assert.equal(state.articleManagedBy,'');
state.startEdit();assert.equal(state.editing,true);
state.saveArticle();assert.equal(requests.at(-1).method,'PATCH');
""")


def test_source_leaf_and_checkout_commands_keep_exact_physical_identity():
    run_native(SOURCE, ("presentSource", "toggleCheckout", "checkoutKey", "isCheckedOut"),
               REQUEST_SETUP + r"""
const commands=[];
const state={XMLHttpRequest:Request,checkouts:{},busyCheckouts:{},sendShellCommand(c){commands.push(c);}};
""", r"""
const path='obsidience/state/system/snapshots/network/2026-09-10/evidence--exact.md';
state.presentSource(path);
assert.equal(commands[0].selection.kind,'source');assert.equal(commands[0].selection.key,path);
const tree='obsidience/evidence/raw';
state.toggleCheckout(tree,'researcher');
assert.equal(requests.at(-1).method,'PUT');
assert(requests.at(-1).url.endsWith('/api/source-checkouts/'+tree));
assert.deepEqual(JSON.parse(requests.at(-1).body),{agent:'researcher',checked_out:true});
""")


def test_react_fallback_uses_the_same_physical_system_and_intake_roots():
    reader = ROOT / "ui/src/renderer/src/panes/reader-pane.tsx"
    source = reader.read_text()
    start = source.index("interface SourceTreeNode {")
    end = source.index("function SourceFolderGlyph(", start)
    compiler = ROOT / "ui/node_modules/typescript/lib/typescript.js"
    script = (
        "import {strict as assert} from 'node:assert';\nimport vm from 'node:vm';\n"
        + f"import ts from {json.dumps(compiler.as_uri())};\n"
        + "const state={};vm.createContext(state);\n"
        + f"vm.runInContext(ts.transpile({json.dumps(source[start:end])}),state);\n"
        + TREE_SETUP.replace("const state=", "const unusedState=")
        + "state.buildTree=state.buildSourceTree;\n"
        + PHYSICAL_TREE_ASSERTIONS
        + r"""
assert.deepEqual(plain(state.buildTree([]).map(node=>node.name)),
 ['SYSTEM','KNOWLEDGE MARKDOWN','EVIDENCE','PROJECT FILES']);
const selected=files.at(-2);
assert.deepEqual(plain(state.sourcePresentationAncestors(selected)),
 ['@view/knowledge','obsidience/vault/News & Research']);
assert(!state.sourcePresentationAncestors(files.at(-1)).includes('@view/system'));
"""
    )
    result = subprocess.run(["node", "--input-type=module", "-e", script],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "const [showAll, setShowAll] = useState(true)" in source
    assert 'Generated from System evidence · read only' in source
    assert 'Generated from System evidence · read only' in READER.read_text()


def test_native_citations_resolve_exact_source_and_reject_changed_identity_or_selection():
    run_native(READER, ("openArticleLink", "openSourceCitation"), REQUEST_SETUP + r"""
const commands=[];
const state={XMLHttpRequest:Request,WebSocket:{Open:1},
 shellSocket:{status:1,sendTextMessage(value){commands.push(JSON.parse(value));}},
 selectionKind:'article',articleRef:'ADMECH Workstation/System Identity',graphId:'executive',
 requestGeneration:1,citationRequestGeneration:0,errorMessage:''};
""", r"""
const id='01234567-89ab-cdef-0123-456789abcdef',citation='source://'+id;
const path='obsidience/state/system/snapshots/identity/2026-09-10/evidence--'+id+'.md';
const source={id,citation,immutable:true,source_path:path};
state.openArticleLink(citation);
assert.equal(requests.at(-1).method,'GET');
assert.equal(requests.at(-1).url,'http://127.0.0.1:8765/api/sources/'+id);
requests.at(-1).respond(source);
assert.deepEqual(commands[0].selection,{kind:'source',key:path});
for(const invalid of [
 {...source,id:'01234567-89ab-cdef-0123-456789abcdee'},
 {...source,citation:'source://different'}, {...source,immutable:false},
 {...source,source_path:'obsidience/evidence/../vault/other.md'},
 {...source,source_path:'obsidience/state/system/system.json'},
 {...source,source_path:'https://example.org/other.md'}, {...source,source_path:null}]){
 state.openArticleLink(citation);requests.at(-1).respond(invalid);
 assert.equal(commands.length,1);assert.match(state.errorMessage,/identity/);
}
state.openArticleLink(citation);const oldSelection=requests.at(-1);
state.requestGeneration++;oldSelection.respond(source);assert.equal(commands.length,1);
state.openArticleLink(citation);const oldArticle=requests.at(-1);
state.articleRef='Knowledge/Another';oldArticle.respond(source);assert.equal(commands.length,1);
state.openArticleLink(citation);const oldKind=requests.at(-1);
state.selectionKind='source';oldKind.respond(source);assert.equal(commands.length,1);
state.selectionKind='article';
state.openArticleLink(citation);const oldClick=requests.at(-1);
state.openArticleLink(citation);requests.at(-1).respond({...source,source_path:'obsidience/evidence/raw/exact.md'});
oldClick.respond(source);assert.equal(commands.length,2);
assert.equal(commands.at(-1).selection.key,'obsidience/evidence/raw/exact.md');
const count=requests.length;
state.openArticleLink('source://not-a-uuid');state.openArticleLink(citation+'?redirect=other');
state.openArticleLink('https://example.org');assert.equal(requests.length,count);
""")


def test_react_citation_resolver_retains_exact_source_and_stale_selection_guards():
    source = (ROOT / "ui/src/renderer/src/panes/reader-pane.tsx").read_text()
    method = re.search(r"^  async function openSourceCitation\([^\n]*\) \{.*?^  \}",
                       source, re.M | re.S)[0]
    compiler = ROOT / "ui/node_modules/typescript/lib/typescript.js"
    script = (
        "import {strict as assert} from 'node:assert';\nimport vm from 'node:vm';\n"
        + f"import ts from {json.dumps(compiler.as_uri())};\n"
        + r"""
const requests=[],opened=[],errors=[];
const state={API_BASE:'http://127.0.0.1:8765',sourceRequest:{current:1},citationRequest:{current:0},
 setError(error){errors.push(error);},openSourceFile(path){opened.push(path);},
 fetch(url){return new Promise(resolve=>requests.push({url,respond(data){resolve({ok:true,json:async()=>data});}}));}};
vm.createContext(state);
"""
        + f"vm.runInContext(ts.transpile({json.dumps(method)}),state);\n"
        + r"""
const id='01234567-89ab-cdef-0123-456789abcdef',citation='source://'+id;
const source={id,citation,immutable:true,source_path:'obsidience/state/system/snapshots/identity/2026-09-10/evidence--'+id+'.md'};
let pending=state.openSourceCitation(citation);requests.at(-1).respond(source);await pending;
assert.deepEqual(opened,[source.source_path]);
assert.equal(requests[0].url,'http://127.0.0.1:8765/api/sources/'+id);
for(const invalid of [{...source,id:'wrong'},{...source,citation:'wrong'},
 {...source,source_path:'obsidience/evidence/../vault/other.md'}]){
 pending=state.openSourceCitation(citation);requests.at(-1).respond(invalid);await pending;
 assert.equal(opened.length,1);assert.match(errors.at(-1),/identity/);
}
pending=state.openSourceCitation(citation);state.sourceRequest.current++;
requests.at(-1).respond(source);await pending;assert.equal(opened.length,1);
const old=state.openSourceCitation(citation),oldRequest=requests.at(-1);
pending=state.openSourceCitation(citation);requests.at(-1).respond(source);await pending;
oldRequest.respond(source);await old;assert.equal(opened.length,2);
const count=requests.length;await state.openSourceCitation(citation+'?other');assert.equal(requests.length,count);
"""
    )
    result = subprocess.run(["node", "--input-type=module", "-e", script],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr


def test_markdown_citation_is_an_internal_button_and_remote_links_remain_inert():
    markdown = ROOT / "ui/src/renderer/src/components/themes/obsidience/workspace/article-markdown.tsx"
    packages = ROOT / "ui/node_modules"
    script = (
        "import {strict as assert} from 'node:assert';\n"
        + f"import ts from {json.dumps((packages / 'typescript/lib/typescript.js').as_uri())};\n"
        + f"import React from {json.dumps((packages / 'react/index.js').as_uri())};\n"
        + f"import {{renderToStaticMarkup}} from {json.dumps((packages / 'react-dom/server.node.js').as_uri())};\n"
        + f"let source={json.dumps(markdown.read_text())};\n"
        + f"const packages={json.dumps(packages.as_uri())};\n"
        + r"""
let output=ts.transpileModule(source,{compilerOptions:{jsx:ts.JsxEmit.ReactJSX,
 module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
for(const [name,path] of [['react/jsx-runtime','react/jsx-runtime.js'],
 ['react-markdown','react-markdown/index.js'],['remark-gfm','remark-gfm/index.js']]){
 output=output.replaceAll('"'+name+'"','"'+packages+'/'+path+'"');
}
const {ArticleMarkdown}=await import('data:text/javascript;base64,'+Buffer.from(output).toString('base64'));
const citation='source://01234567-89ab-cdef-0123-456789abcdef',opened=[];
const props={content:'[Immutable evidence]('+citation+') [Remote](https://example.org)',
 onSourceNavigate(value){opened.push(value);}};
const markup=renderToStaticMarkup(React.createElement(ArticleMarkdown,props));
assert.match(markup,/<button[^>]*>Immutable evidence<\/button>/);
assert(!markup.includes('href='));assert.match(markup,/<span[^>]*>Remote<\/span>/);
const markdownElement=ArticleMarkdown(props).props.children;
const button=markdownElement.props.components.a({href:citation,children:'Immutable evidence'});
button.props.onClick();assert.deepEqual(opened,[citation]);
assert.equal(markdownElement.props.urlTransform('javascript:alert(1)'),'');
assert.equal(markdownElement.props.urlTransform('source://not-an-id'),'');
"""
    )
    result = subprocess.run(["node", "--input-type=module", "-e", script],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr

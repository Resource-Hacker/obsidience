"""Exercise the actual native dock controller's four-slot state transitions."""

import json
from pathlib import Path
import re
import subprocess


LAYOUT = Path(__file__).parents[1] / "shell/qml/workspace/PaneDockLayout.qml"


def run_layout(body):
    functions = "\n".join(re.findall(r"^    function \w+\([^\n]*\) \{.*?^    \}", LAYOUT.read_text(), re.M | re.S))
    code = """
import {strict as assert} from 'node:assert';
import vm from 'node:vm';
const writes=[];
const state={authoritative:true,revision:0,modules:{},schema:'obsidience.pane-dock-layout.v1',
  layoutFile:{setText(text){writes.push(JSON.parse(text))}}};
state.root=state;
vm.createContext(state);
""" + f"vm.runInContext({json.dumps(functions)},state);\n" + """
state.modules=state.defaultModules();
const dock=(pane,side,position)=>state.commitDock(state.revision,pane,'reader',side,position);
const location=pane=>state.modules[pane].side+':'+state.modules[pane].order;
const distinct=()=>new Set(Object.values(state.modules).map(m=>m.side+':'+m.order)).size===Object.keys(state.modules).length;
""" + body
    result = subprocess.run(["node", "--input-type=module", "-e", code], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr


def test_each_reader_slot_is_exact_and_docked_occupants_swap():
    run_layout("""
assert.equal(location('knowledge'),'left:0');
assert.equal(location('source'),'right:0');
assert(dock('knowledge','left','bottom'));
assert(dock('feeds','right','bottom'));
assert.equal(location('knowledge'),'left:1');
assert.equal(location('feeds'),'right:1');
assert(state.commitCollapsed(state.revision,'source',true));
assert(dock('knowledge','right','top'));
assert.equal(location('knowledge'),'right:0');
assert.equal(location('source'),'left:1');
assert.equal(state.modules.source.collapsed,true);
assert(dock('feeds','left','top'));
assert.equal(location('feeds'),'left:0');
assert.equal(state.slotState('reader','right',1),null);
assert(distinct());
assert(Object.values(state.modules).every(m=>m.order===0||m.order===1));
assert.equal(writes.length,state.revision);
""")


def test_floating_incoming_keeps_displaced_module_and_its_collapse_state():
    run_layout("""
assert(state.commitCollapsed(state.revision,'knowledge',true));
assert(dock('feeds','left','top'));
assert.equal(location('feeds'),'left:0');
assert.equal(location('knowledge'),'left:1');
assert.equal(state.modules.knowledge.collapsed,true);
assert.equal(location('source'),'right:0');
assert(distinct());
assert.equal(Object.keys(state.modules).length,3);
assert.equal(state.modulesFor('reader','left',true)[0].pane_id,'knowledge');
""")


def test_collapse_expand_and_float_preserve_sibling_slots():
    run_layout("""
assert(dock('feeds','left','bottom'));
const prior=JSON.stringify(state.modules.feeds);
assert(state.commitCollapsed(state.revision,'knowledge',true));
assert.equal(JSON.stringify(state.modules.feeds),prior);
assert(state.commitCollapsed(state.revision,'knowledge',false));
assert.equal(JSON.stringify(state.modules.feeds),prior);
assert(state.commitFloat(state.revision,'knowledge'));
assert.equal(JSON.stringify(state.modules.feeds),prior);
assert.equal(state.slotState('reader','left',0),null);
assert.equal(state.slotState('reader','left',1).pane_id,'feeds');
""")


def test_unknown_modules_hosts_and_stale_mutations_leave_state_untouched():
    run_layout("""
const before=JSON.stringify(state.record());
assert(!state.commitDock(1,'feeds','reader','left','bottom'));
assert(!state.commitDock(0,'tasks','reader','left','bottom'));
assert(!state.commitDock(0,'feeds','terminal','left','bottom'));
assert(!state.commitDock(0,'feeds','reader','left','middle'));
assert(!state.commitFloat(3,'knowledge'));
assert(!state.commitCollapsed(3,'source',true));
assert.equal(JSON.stringify(state.record()),before);
assert.equal(writes.length,0);
""")


def test_legacy_order_migrates_once_without_losing_or_reordering_modules():
    run_layout("""
const module=(pane,side,order,collapsed=false)=>({pane_id:pane,host_pane_id:'reader',side,order,collapsed});
assert(state.applyRecord({schema:state.schema,revision:4,modules:[
 module('knowledge','left',1),module('source','left',2),module('feeds','right',1,true)
]}));
assert.equal(location('knowledge'),'left:0');
assert.equal(location('source'),'left:1');
assert.equal(location('feeds'),'right:1');
assert.equal(state.modules.feeds.collapsed,true);
const normalized=JSON.stringify(state.record());
assert(state.applyRecord(JSON.parse(normalized)));
assert.equal(JSON.stringify(state.record()),normalized);
assert(!state.applyRecord({schema:state.schema,revision:3,modules:[]}));
assert(!state.applyRecord({schema:state.schema,revision:5,modules:[module('tasks','left',0)]}));
assert.equal(JSON.stringify(state.record()),normalized);
assert(state.applyRecord({schema:state.schema,revision:5,modules:[
 module('knowledge','left',-3),module('source','left',-2),module('feeds','left',-1)
]}));
assert.equal(Object.keys(state.modules).length,3);assert(distinct());
assert.equal(location('knowledge'),'left:0');assert.equal(location('source'),'left:1');
assert.equal(location('feeds'),'right:0');
""")

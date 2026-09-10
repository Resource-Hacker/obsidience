"""Exercise the native Review pane with adversarial response ordering."""

import json
from pathlib import Path
import re
import subprocess

import pytest


@pytest.mark.parametrize("scenario", ["rapid_decision", "stale_refresh", "failed_decision"])
@pytest.mark.parametrize("approve", [True, False])
def test_review_queue_reconciles_without_replaying_decisions(scenario, approve):
    source = (Path(__file__).parents[1] / "shell/qml/panes/reviews/ReviewsPane.qml").read_text()
    functions = "\n".join(
        re.search(rf"^    function {name}\(.*?^    \}}", source, re.M | re.S)[0]
        for name in ("refresh", "decide")
    )
    script = r"""
const assert = require('node:assert/strict'), vm = require('node:vm');
const first = {file:'first.md', approvable:true}, second = {file:'second.md', approvable:true};
const requests = [];
const state = {proposals:[first, second], loading:false, decidingFile:'',
  expandedFile:'first.md', actionError:'', loadError:'', refreshGeneration:0,
  requestJson(method,path,callback) { requests.push({method,path,callback}); }};
state.root = state;
vm.createContext(state);
vm.runInContext(FUNCTIONS, state);
const ids = () => Array.from(state.proposals, p => p.file);
const decisions = () => requests.filter(r => r.method === 'POST');
if (SCENARIO === 'rapid_decision') {
  state.refresh(); // A poll sent before the decision may arrive much later.
  state.decide(first,true);
  state.decide(first,true);
  assert.equal(decisions().length,1);
  decisions()[0].callback(true,{approved:'first'},'');
  assert.deepEqual(ids(),['second.md']); // Remove only after acknowledgement.
  state.decide(first,true); // The old delegate cannot resubmit it.
  assert.equal(decisions().length,1);
  requests.at(-1).callback(true,[second],'');
  requests[0].callback(true,[first,second],''); // Delayed pre-decision snapshot.
  assert.deepEqual(ids(),['second.md']);
  assert.equal(state.expandedFile,'');
  state.decide(second,true);
  assert.equal(decisions().length,2);
  decisions()[1].callback(true,{approved:'second'},'');
  requests.at(-1).callback(true,[],'');
  assert.deepEqual(ids(),[]);
  assert.equal(state.actionError,'');
} else if (SCENARIO === 'stale_refresh') {
  state.refresh(); state.refresh();
  requests[1].callback(true,[second],'');
  requests[0].callback(true,[first,second],'');
  assert.deepEqual(ids(),['second.md']);
  state.refresh(); state.refresh();
  requests[3].callback(true,[],'');
  requests[2].callback(false,null,'outdated poll failure');
  assert.equal(state.loadError,'');
} else {
  state.decide(first,true);
  assert.deepEqual(ids(),['first.md','second.md']); // Never optimistic publication.
  decisions()[0].callback(false,null,'Connection lost');
  assert.equal(state.actionError,'Connection lost');
  assert.deepEqual(ids(),['first.md','second.md']);
  assert.equal(requests.at(-1).method,'GET'); // Reconcile, never replay a POST.
  requests.at(-1).callback(true,[second],''); // Server actually applied it.
  assert.deepEqual(ids(),['second.md']);
  assert.equal(decisions().length,1);
}
""".replace("FUNCTIONS", json.dumps(functions)).replace("SCENARIO", json.dumps(scenario))
    script = script.replace("decide(first,true)", f"decide(first,{json.dumps(approve)})")
    script = script.replace("decide(second,true)", f"decide(second,{json.dumps(approve)})")
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr

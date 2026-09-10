"""Native Task execution presentation and exact-attempt retry dispatch."""
import json
import re
import subprocess
from pathlib import Path

SOURCE = Path(__file__).parents[1] / 'shell/qml/panes/tasks/TasksPane.qml'


def run_js(body):
    source = SOURCE.read_text()
    names = ('retryTask', 'runBlockedReason', 'runNow', 'taskDetail', 'taskHint')
    functions = '\n'.join(re.search(
        rf'^    function {name}\(.*?^    \}}', source, re.M | re.S,
    )[0] for name in names)
    code = '''
import {strict as assert} from 'node:assert';
import vm from 'node:vm';
const requests=[];
const state={busyRef:'',actionError:'',refresh(){},requestJson(method,path,body,callback){requests.push({method,path,body,callback});}};
state.root=state;
vm.createContext(state);
''' + f'vm.runInContext({json.dumps(functions)},state);\n' + body
    result = subprocess.run(['node', '--input-type=module', '-e', code],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr


def test_current_wait_is_distinct_from_last_failure_and_waiting_fifo():
    run_js(r'''
const task={ref:'Tasks/link',status:'failed',queue_depth:38,triggers:['task.create'],
 blocked_reason:'stale legacy reason',execution:{state:'waiting',label:'Paused: Realtime',reason:'Realtime owns foreground execution.',
 last_run:{id:'attempt-42',status:'failed',finished:1788692400,summary:'The previous attempt failed after retaining its Tool effects.'},
 retry_allowed:false,retry_blocked_reason:'Committed effects require resolution.'}};
const row={task,children:[]};
const detail=state.taskDetail(row);
assert.match(detail,/^PAUSED: REALTIME\s+·\s+38 LATER/);
assert.equal(detail.includes('LAST ATTEMPT'),false);
assert.equal(detail.includes('stale legacy reason'),false);
assert.equal(detail.includes('QUEUED'),false);
const hint=state.taskHint(row);
assert.match(hint,/attempt-42/);
assert.match(hint,/attempt-42 · FAILED · /);
assert.match(hint,/previous attempt failed after retaining its Tool effects/);
assert.match(hint,/Realtime owns foreground execution/);
task.execution.state='idle';
delete task.execution.label;
assert.match(state.taskDetail(row),/LAST ATTEMPT FAILED \d+\/\d+ \d\d:\d\d/);
''')
    source = SOURCE.read_text()
    assert 'text: root.taskHint(taskRow.modelData)' in source
    assert 'text: executionHint.text' in source and 'wrapMode: Text.Wrap' in source


def test_retry_is_exact_attempt_bound_and_never_replayed_after_rejection():
    run_js(r'''
const task={ref:'Tasks/link',status:'failed',reasoning_effort:'xhigh',execution:{state:'needs_attention',
 retry_allowed:true,last_run:{id:'attempt-42',status:'failed'}}};
state.runNow(task);
assert.equal(requests.length,1);
assert.equal(requests[0].method,'POST');
assert.equal(requests[0].path,'/api/tasks/Tasks/link/run');
assert.deepEqual(JSON.parse(JSON.stringify(requests[0].body)),{reasoning_effort:'xhigh',retry_run_id:'attempt-42'});
state.runNow(task); // The same activation is single flight.
assert.equal(requests.length,1);
requests[0].callback(false,null,'The selected attempt is no longer current.');
assert.equal(state.busyRef,'');
assert.equal(state.actionError,'The selected attempt is no longer current.');
assert.equal(requests.length,1); // No retry or new unbound request on failure.
''')


def test_retry_and_normal_run_follow_current_api_eligibility():
    run_js(r'''
const blocked={ref:'Tasks/merge',status:'failed',execution:{state:'needs_attention',retry_allowed:false,
 last_run:{id:'attempt-43'},retry_blocked_reason:'Completed Tool effects must not be repeated.'}};
state.runNow(blocked);
assert.equal(requests.length,0);
assert.match(state.taskHint({task:blocked,children:[]}),/Completed Tool effects must not be repeated/);
for(const phase of ['running','review','waiting']){
 state.runNow({ref:'Tasks/link',status:'failed',execution:{state:phase,retry_allowed:true,last_run:{id:'attempt-42'}}});
}
state.runNow({ref:'Tasks/link',status:'failed',execution:{state:'needs_attention',retry_allowed:true}});
state.runNow({ref:'Tasks/link',status:'failed'}); // An older API cannot authorize retry.
assert.equal(requests.length,0);
state.runNow({ref:'Tasks/curate',status:'completed',reasoning_effort:'high',execution:{state:'ready',retry_allowed:false}});
assert.equal(requests.length,1);
assert.deepEqual(JSON.parse(JSON.stringify(requests[0].body)),{reasoning_effort:'high'});
''')

"""Click command integrity using inert callbacks and the actual QML functions."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
from types import ModuleType, SimpleNamespace

import pytest

from obsidience.shell.adapter.windows import transport as transport_module
from obsidience.shell.adapter.windows.model import ApplicationWindow, LocalRect, WindowStateStore
from obsidience.shell.adapter.windows.transport import ShellWindowTransport


ROOT = Path(__file__).parents[1]
WITNESS = {
    "stable_id": "18000002", "pid": 321, "process_start_time": 456,
    "local_rect": {"x": 10, "y": 20, "width": 800, "height": 600},
    "image_width": 800, "image_height": 600, "x": 12.25, "y": 43.5,
    "captured_at_unix_ns": 1788659000000000000, "label": "Continue",
}


def request(token="click-1", **changes):
    return {
        "schema": "obsidience.shell.event.v1", "type": "window.click.request",
        "token": token, "surface_id": "samsung", "window_id": "0x123",
        "expected_revision": 1, "witness": deepcopy(WITNESS), "lock_generation": 2,
        **changes,
    }


def transport(click):
    return ShellWindowTransport(
        WindowStateStore(), lambda *_: (True, "", 1), lambda *_: (True, ""),
        lambda *_: (True, ""), lambda *_: (True, ""), lambda *_: (True, "", 1),
        lambda *_: (True, ""), lambda *_: (True, ""), click=click,
    )


def handle(adapter, event):
    sent = []
    adapter._handle(SimpleNamespace(send=sent.append), json.dumps(event))
    assert len(sent) == 1
    return json.loads(sent[0])


def test_click_dispatches_once_and_correlates_only_bounded_result():
    calls = []
    adapter = transport(lambda *args: calls.append(args) or {
        "ok": True, "reason": "", "delivery": "acknowledged", "private": "not forwarded",
    })
    result = handle(adapter, request())
    assert calls == [("samsung", "0x123", 1, WITNESS, "click-1", 2)]
    assert result["type"] == "window.click.result"
    assert result["success"] is True and result["delivery"] == "acknowledged"
    assert result["token"] == "click-1" and result["window_id"] == "0x123"
    assert "witness" not in result and "private" not in result
    # A new connection on the same host still cannot replay the consumed token.
    duplicate = handle(adapter, request(witness={**WITNESS, "x": 15}))
    assert duplicate["reason"] == "duplicate_token"
    assert duplicate["delivery"] == "uncertain" and len(calls) == 1


@pytest.mark.parametrize("change", [
    {"extra": True}, {"pid": True}, {"process_start_time": 0},
    {"captured_at_unix_ns": -1}, {"stable_id": "0x123"}, {"stable_id": "a" * 33},
    {"stable_id": "abc\n"},
    {"label": ""}, {"label": " "}, {"label": "a" * 129},
    {"label": "bad\nlabel"}, {"x": True}, {"x": float("nan")}, {"y": float("inf")},
    {"x": -0.1}, {"x": 800}, {"x": 10**1000}, {"image_width": 40000},
    {"image_height": False}, {"local_rect": {**WITNESS["local_rect"], "width": 0}},
    {"local_rect": {**WITNESS["local_rect"], "extra": 1}},
    {"roi": {"x": 0, "y": 0, "width": 10, "height": 10}},
    {"roi_luma": "removed"}, {"roi_sha256": "a" * 64},
])
def test_invalid_witness_is_definitely_not_dispatched(change):
    calls = []
    adapter = transport(lambda *args: calls.append(args))
    result = handle(adapter, request(witness={**WITNESS, **change}))
    assert result["success"] is False and result["delivery"] == "not_dispatched"
    assert result["reason"] == "invalid_click_request" and not calls


def test_click_token_capacity_and_invalid_request_never_evict_consumed_tokens(monkeypatch):
    calls = []
    adapter = transport(lambda *args: calls.append(args) or {
        "ok": False, "reason": "not_visible", "delivery": "not_dispatched",
    })
    monkeypatch.setattr(transport_module, "_CLICK_TOKEN_LIMIT", 2)
    assert handle(adapter, request(extra=True))["reason"] == "invalid_click_request"
    assert handle(adapter, request())["reason"] == "duplicate_token"
    handle(adapter, request("click-2"))
    assert handle(adapter, request("click-3"))["reason"] == "click_token_capacity"
    assert handle(adapter, request("click-2"))["reason"] == "duplicate_token"
    assert len(calls) == 1


@pytest.mark.parametrize("outcome", [None, {"ok": True, "reason": "", "delivery": "uncertain"}])
def test_invalid_backend_result_cannot_acknowledge_or_repeat_click(outcome):
    adapter = transport(lambda *_: outcome)
    result = handle(adapter, request())
    assert result["success"] is False and result["delivery"] == "uncertain"
    assert handle(adapter, request())["reason"] == "duplicate_token"


def test_backend_exception_is_delivery_uncertainty():
    def failed(*_):
        raise RuntimeError("inert backend failed")
    result = handle(transport(failed), request())
    assert result["reason"] == "click_error" and result["delivery"] == "uncertain"


def test_guard_uses_independent_bounded_read_only_socket(monkeypatch):
    sent, received, connections = [], [], []
    events = iter([
        {"schema": "obsidience.shell.event.v1", "type": "workspace.state"},
        {"schema": "obsidience.shell.event.v1", "type": "window.click.guard.result",
         "token": "another", "allowed": True},
        {"schema": "obsidience.shell.event.v1", "type": "window.click.guard.result",
         "token": "click-1", "allowed": True},
    ])

    class Socket:
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass
        def send(self, data):
            sent.append(json.loads(data))
        def recv(self, *, timeout):
            received.append(timeout)
            return json.dumps(next(events))

    monkeypatch.setattr(transport_module, "connect", lambda *args, **kwargs:
                        connections.append((args, kwargs)) or Socket())
    assert ShellWindowTransport.click_guard("click-1", "samsung", "0x123", 1, 2)
    assert len(connections) == 1 and len(sent) == 1
    assert sent[0] == {"schema": "obsidience.shell.command.v1", "type": "window.click.guard",
                       "token": "click-1", "surface_id": "samsung", "window_id": "0x123",
                       "expected_revision": 1, "lock_generation": 2}
    assert all(0 < timeout <= 0.5 for timeout in received)
    assert connections[0][1]["max_size"] == 65536
    assert not ShellWindowTransport.click_guard("click-1", "samsung", "0x123", 1, 2)


@pytest.fixture
def adapter_host(monkeypatch):
    # GLib starts the production host loop; no loop or display backend is started here.
    gi = ModuleType("gi")
    repository = ModuleType("gi.repository")
    repository.GLib = SimpleNamespace()
    monkeypatch.setitem(sys.modules, "gi", gi)
    monkeypatch.setitem(sys.modules, "gi.repository", repository)
    spec = importlib.util.spec_from_file_location(
        "obsidience.shell.adapter.windows._click_test_host",
        ROOT / "shell/adapter/windows/host.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    host = module.WindowAdapterHost.__new__(module.WindowAdapterHost)
    host.store = WindowStateStore()
    return host


def test_host_binds_exact_target_and_supplies_current_guard(adapter_host):
    host = adapter_host
    target = ApplicationWindow("0x123", "example", "Example", LocalRect(10, 20, 800, 600),
                               pid=321, stable_id="18000002")
    host.store.update("samsung", "", (target,))
    guards = []
    host.transport = SimpleNamespace(click_guard=lambda *args: guards.append(args) or True)
    def click(surface_id, actual, witness, *, guard):
        assert (surface_id, actual, witness) == ("samsung", target, WITNESS)
        assert guard() and guard()
        return {"ok": True, "reason": "", "delivery": "acknowledged"}
    host.hyprland = SimpleNamespace(click=click)
    assert host._click("samsung", "0x123", 1, WITNESS, "click-1", 2)["ok"] is True
    assert guards == [("click-1", "samsung", "0x123", 1, 2)] * 2


@pytest.mark.parametrize("change,awake,revision,reason", [
    ({}, True, 2, "stale_scene"), ({}, False, 1, "target_not_visible"),
    ({"minimized": True}, True, 1, "target_not_visible"),
    ({"visible_on_workspace": False}, True, 1, "target_not_visible"),
    ({"window_kind": "module", "app_id": "io.obsidience.shell", "pane_id": "reader"},
     True, 1, "unsupported_target"),
    ({"pid": 999}, True, 1, "stale_witness"),
    ({"stable_id": "abc"}, True, 1, "stale_witness"),
    ({"local_rect": LocalRect(11, 20, 800, 600)}, True, 1, "stale_witness"),
])
def test_host_rejects_stale_invisible_or_unbound_targets(adapter_host, change, awake, revision, reason):
    target = ApplicationWindow("0x123", "example", "Example", LocalRect(10, 20, 800, 600),
                               pid=321, stable_id="18000002")
    adapter_host.store.update("samsung", "", (replace(target, **change),), awake)
    # No backend/transport exists: a rejected request cannot call either.
    result = adapter_host._click("samsung", "0x123", revision, WITNESS, "click-1", 2)
    assert result == {"ok": False, "reason": reason, "delivery": "not_dispatched"}


def test_qml_click_owner_correlation_lock_cancellation_and_no_replay():
    source = (ROOT / "shell/qml/api/ShellCommandServer.qml").read_text()
    functions = re.findall(r"^    function \w+\([^\n]*\) \{.*?^    \}", source, re.S | re.M)
    script = r"""
const assert=require('node:assert/strict'),vm=require('node:vm');
let now=1000,out=[];
const socket=id=>({id,status:1,active:true,sendTextMessage:message=>out.push({to:id,...JSON.parse(message)})});
const owner=socket('owner'),other=socket('other'),adapter=socket('adapter'),guard=socket('guard');
const context={WebSocket:{Open:1},Date:{now:()=>now},eventSchema:'obsidience.shell.event.v1',
  clients:[owner,other,adapter,guard],windowAdapterSocket:adapter,sessionLocked:false,
  lockGeneration:2,clickTokens:[],clickRequests:[],clickTokenLimit:4096,clickRequestLifetimeMs:6000,
  surfaceLayout:{surface:id=>['samsung','usb-c','dp-4'].includes(id)},windowStates:{samsung:{
    revision:1,surface_awake:true,windows:[{window_id:'0x123',window_kind:'application',
    minimized:false,visible_on_workspace:true}]}}};
vm.createContext(context);vm.runInContext(FUNCTIONS,context);
const request=token=>({schema:'obsidience.shell.command.v1',type:'window.click',token,
  surface_id:'samsung',window_id:'0x123',expected_revision:1,witness:WITNESS});
const check=token=>{context.handleWindowCommand(guard,{schema:'obsidience.shell.command.v1',
  type:'window.click.guard',token,surface_id:'samsung',window_id:'0x123',expected_revision:1,
  lock_generation:2});return out.at(-1).allowed};
const result=token=>({schema:'obsidience.shell.command.v1',type:'window.click.result',token,
  surface_id:'samsung',window_id:'0x123',success:true,reason:'',delivery:'acknowledged'});
context.handleWindowCommand(owner,request('click-1'));
assert.equal(out.at(-1).to,'adapter');assert.equal(out.at(-1).type,'window.click.request');
assert.equal(out.at(-1).lock_generation,2);assert(check('click-1'));
const before=out.length;
context.handleWindowCommand(other,result('click-1'));assert.equal(out.length,before);
context.handleWindowCommand(adapter,{...result('click-1'),window_id:'0xBAD'});
assert.equal(out.length,before);
context.handleWindowCommand(adapter,result('click-1'));
assert.equal(out.at(-1).to,'owner');assert.equal(out.at(-1).delivery,'acknowledged');
assert(!check('click-1'));
context.handleWindowCommand(owner,request('click-1'));
assert.equal(out.at(-1).reason,'duplicate_token');assert.equal(out.at(-1).delivery,'uncertain');
context.handleWindowCommand(owner,request('cancel'));
context.handleWindowCommand(other,{type:'window.click.cancel',token:'cancel'});assert(check('cancel'));
context.handleWindowCommand(owner,{type:'window.click.cancel',token:'cancel'});assert(!check('cancel'));
context.handleWindowCommand(owner,request('close'));
context.removeClient(owner);assert(!check('close'));
context.clients.push(owner);
context.handleWindowCommand(owner,request('expiry'));now+=6000;assert(!check('expiry'));
context.handleWindowCommand(adapter,result('expiry'));assert.equal(out.at(-1).delivery,'uncertain');
context.handleWindowCommand(owner,request('lock'));
context.sessionLocked=true;assert(!check('lock'));
context.sessionLocked=false;context.lockGeneration++;assert(!check('lock'));
context.handleWindowCommand(adapter,result('lock'));assert.equal(out.at(-1).delivery,'uncertain');
context.lockGeneration=2;
context.handleWindowCommand(owner,request('asleep'));
context.windowStates.samsung.surface_awake=false;assert(!check('asleep'));
context.handleWindowCommand(owner,request('asleep-new'));
assert.equal(out.at(-1).delivery,'not_dispatched');
context.windowStates.samsung.surface_awake=true;
for(const [index,change] of [{minimized:true},{visible_on_workspace:false},{window_kind:'module'}].entries()){
 const original=context.windowStates.samsung.windows[0];
 context.windowStates.samsung.windows[0]={...original,...change};
 context.handleWindowCommand(owner,request('hidden-'+index));
 assert.equal(out.at(-1).delivery,'not_dispatched');
 assert.equal(out.at(-1).reason,'stale_or_unavailable');
 context.windowStates.samsung.windows[0]=original;
}
context.handleWindowCommand(owner,request('revision'));
context.windowStates.samsung.revision++;assert(!check('revision'));
context.windowStates.samsung.revision=1;
// A causal post-click scene change invalidates further input, but cannot erase
// the current adapter's already delivered, correlated acknowledgement.
for(const change of ['revision','title','geometry','visibility','removed','sleep']){
 const original=JSON.stringify(context.windowStates.samsung);
 const token='post-click-'+change;
 context.handleWindowCommand(owner,request(token));assert(check(token));
 const state=context.windowStates.samsung;
 state.revision++;
 if(change==='title')state.windows[0].title='Selection opened';
 if(change==='geometry')state.windows[0].local_rect={x:30,y:40,width:900,height:500};
 if(change==='visibility')state.windows[0].visible_on_workspace=false;
 if(change==='removed')state.windows=[];
 if(change==='sleep')state.surface_awake=false;
 assert(!check(token));
 context.handleWindowCommand(adapter,result(token));
 assert.equal(out.at(-1).to,'owner');assert.equal(out.at(-1).success,true);
 assert.equal(out.at(-1).delivery,'acknowledged');
 assert(!check(token));
 context.windowStates.samsung=JSON.parse(original);
 context.handleWindowCommand(owner,request(token));
 assert.equal(out.at(-1).reason,'duplicate_token');
 assert.equal(out.at(-1).delivery,'uncertain');
}
context.handleWindowCommand(owner,request('adapter-replaced'));
const replacement=socket('replacement');context.clients.push(replacement);
context.handleWindowCommand(replacement,{type:'window.adapter.subscribe'});
assert.equal(context.clickRequests.length,0);assert(!check('adapter-replaced'));
assert.equal(adapter.active,false);
context.clickTokenLimit=context.clickTokens.length;
context.handleWindowCommand(owner,request('capacity'));
assert.equal(out.at(-1).reason,'click_token_capacity');
for(const change of [{extra:true},{pid:true},{label:' '},{stable_id:'abc\n'},
 {roi_luma:'removed'},{roi_sha256:'a'.repeat(64)},{roi:{x:0,y:0,width:10,height:10}},
 {x:Infinity},{x:800},{image_width:40000},
 {local_rect:{x:0,y:0,width:1,height:1,extra:1}}]){
 assert.equal(context.cleanClickWitness({...WITNESS,...change}),null);
}
assert(context.cleanClickWitness(WITNESS));
assert.equal(context.cleanClickToken('bad\n'),'');
""".replace("FUNCTIONS", json.dumps("\n".join(functions))).replace("WITNESS", json.dumps(WITNESS))
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
    lock_callback = re.search(r"    onSessionLockedChanged: \{(.*?)\n    \}", source, re.S).group(1)
    assert "lockGeneration += 1" in lock_callback
    assert 'invalidateClickRequests("scene_unavailable")' in lock_callback

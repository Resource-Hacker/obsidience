"""Readiness progress observes one dispatch and never manufactures success."""
import threading
from types import SimpleNamespace
import pytest
from obsidience.harness.capabilities.application import launch
from obsidience.harness.capabilities.task.complete import computer_completion_evidence
from obsidience.tests.test_application_launch import scene, window


def test_delayed_window_completes_original_dispatch(monkeypatch,scene):
    monkeypatch.setattr(launch, 'READINESS_TIMEOUT_SECONDS', 0.5)
    commands=[]
    timer=None
    def dispatch(command,**kwargs):
        nonlocal timer
        commands.append(command)
        timer=threading.Timer(0.02,lambda: scene(windows=[window('microsoft-edge','Ready')]))
        timer.start()
        return SimpleNamespace(returncode=0,stdout='',stderr='')
    monkeypatch.setattr(launch.subprocess,'run',dispatch)
    result=launch._launch_application({'application':'microsoft_edge'})
    timer.join()
    assert result['ready'] and result['dispatched'] and result['wait_status']=='observed'
    assert len(commands)==1
    assert computer_completion_evidence('application.launch',result)['verified']


def test_timeout_does_not_dispatch_twice_or_claim_ready(monkeypatch,scene):
    monkeypatch.setattr(launch,'READINESS_TIMEOUT_SECONDS',0.01)
    commands=[]
    monkeypatch.setattr(launch.subprocess,'run',lambda cmd,**kwargs: commands.append(cmd) or SimpleNamespace(returncode=0,stdout='',stderr=''))
    result=launch._launch_application({'application':'microsoft_edge'})
    assert result['wait_status']=='timeout' and not result['ready'] and result['must_not_replay']
    assert len(commands)==1


def test_cancelled_wait_keeps_dispatch_evidence(monkeypatch,scene):
    cancelled=threading.Event()
    def dispatch(*args,**kwargs):
        cancelled.set()
        return SimpleNamespace(returncode=0,stdout='',stderr='')
    monkeypatch.setattr(launch.subprocess,'run',dispatch)
    result=launch._launch_application({'application':'microsoft_edge'},{'_capability_cancel_event':cancelled})
    assert result['dispatched'] and result['wait_status']=='cancelled' and not result['ready']


def test_cancelled_before_dispatch_never_launches(monkeypatch,scene):
    cancelled=threading.Event(); cancelled.set()
    monkeypatch.setattr(launch.subprocess,'run',lambda *args,**kwargs: pytest.fail('No dispatch'))
    with pytest.raises(ValueError,match='cancelled'):
        launch._launch_application({'application':'microsoft_edge'},{'_capability_cancel_event':cancelled})


def test_ambiguity_without_managed_unit_never_launches(monkeypatch,scene):
    scene(windows=[window('microsoft-edge','First'),window('microsoft-edge','Second',window_id='0xsecond')])
    monkeypatch.setattr(launch.subprocess,'run',lambda *args,**kwargs: pytest.fail('No dispatch'))
    with pytest.raises(ValueError,match='ambiguous'):
        launch._launch_application({'application':'microsoft_edge'})


def test_scene_wait_returns_on_publication(scene):
    cache=launch.SCENE; token=cache.change_token()
    scene(windows=[window('microsoft-edge','Ready')])
    assert cache.wait_for_change(token,0.5)>token

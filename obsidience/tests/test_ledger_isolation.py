import sys
from types import ModuleType

from obsidience.harness.knowledge import index
from obsidience.tests.conftest import isolated_task_ledger


def test_late_module_import_does_not_retain_closed_test_ledger(tmp_path, monkeypatch):
    original = index.INDEX
    nested = tmp_path / "nested"
    nested.mkdir()
    fixture = isolated_task_ledger.__wrapped__(nested)
    ledger = next(fixture)
    module = ModuleType("obsidience.tests._late_index_alias")
    module.INDEX = index.INDEX
    monkeypatch.setitem(sys.modules, module.__name__, module)

    assert module.INDEX is ledger
    fixture.close()

    assert index.INDEX is original
    assert module.INDEX is original
    module.INDEX.seed_task_runtime("Tasks/after-cleanup", {"status": "pending"})
    assert original.task_runtime("Tasks/after-cleanup") == {"status": "pending"}

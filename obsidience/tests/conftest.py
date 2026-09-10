"""Runtime-backed Article tests must never write the workstation ledger."""

import sys

import pytest


@pytest.fixture(autouse=True)
def isolated_task_ledger(tmp_path):
    from obsidience.harness.config import CONFIG
    from obsidience.harness.knowledge import index

    original = index.INDEX
    # Own this patch lifecycle so test-specific monkeypatch fixtures unwind
    # before we restore imports and close the per-test connection.
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(CONFIG, "db_path", tmp_path / "test-runtime.sqlite3")
        ledger = index.Index()
        for module in tuple(sys.modules.values()):
            if getattr(module, "__name__", "").startswith("obsidience.") and getattr(module, "INDEX", None) is original:
                patch.setattr(module, "INDEX", ledger)
        try:
            yield ledger
        finally:
            # A module first imported during this test captured the temporary
            # INDEX without participating in the setup patch list.
            for module in tuple(sys.modules.values()):
                if getattr(module, "__name__", "").startswith("obsidience.") and getattr(module, "INDEX", None) is ledger:
                    module.INDEX = original
            ledger.db.close()

"""Runtime-backed Article tests must never write the workstation ledger."""

import atexit
import sys
import shutil
import tempfile
from pathlib import Path

import pytest

from obsidience.harness.config import CONFIG

# Module singletons (INDEX, CONVERSATION) open CONFIG.db_path when test modules
# are imported, before any fixture runs. Never let that be the live ledger.
_IMPORT_STATE = Path(tempfile.mkdtemp(prefix="obsidience-tests-"))
atexit.register(shutil.rmtree, _IMPORT_STATE, True)
CONFIG.db_path = _IMPORT_STATE / "import-runtime.sqlite3"


@pytest.fixture(autouse=True)
def isolated_task_ledger(tmp_path, tmp_path_factory):
    from obsidience.harness import config
    from obsidience.harness.execution import refinement
    from obsidience.harness.knowledge import index

    original = index.INDEX
    # Own this patch lifecycle so test-specific monkeypatch fixtures unwind
    # before we restore imports and close the per-test connection.
    with pytest.MonkeyPatch.context() as patch:
        # Executor decisions record optimization evidence under the checked-in
        # evidence directory; keep it disposable unless a test owns PROJECT_ROOT.
        project, evidence_root = config.PROJECT_ROOT, refinement._root
        evaluations = tmp_path_factory.mktemp("evaluation-evidence")
        patch.setattr(refinement, "_root", lambda: evaluations
                      if config.PROJECT_ROOT == project else evidence_root())
        # Tests may exercise real context publication, but never the checked-in
        # or live Vault. Each case gets complete input and disposable outputs.
        isolated_vault = tmp_path_factory.mktemp("accepted-vault")
        shutil.copytree(CONFIG.vault_dir, isolated_vault, dirs_exist_ok=True)
        patch.setattr(CONFIG, "vault_dir", isolated_vault)
        patch.setattr(CONFIG, "db_path", tmp_path / "test-runtime.sqlite3")
        ledger = index.Index()
        occurrence_token = index._ACTIVE_OCCURRENCE.set(None)
        for module in tuple(sys.modules.values()):
            if getattr(module, "__name__", "").startswith("obsidience.") and getattr(module, "INDEX", None) is original:
                patch.setattr(module, "INDEX", ledger)
        try:
            yield ledger
        finally:
            # A module first imported during this test captured the temporary
            # INDEX (or a test fixture's private Index, closed at its teardown)
            # without participating in the setup patch list.
            for module in tuple(sys.modules.values()):
                captured = getattr(module, "INDEX", None)
                if (getattr(module, "__name__", "").startswith("obsidience.")
                        and isinstance(captured, index.Index) and captured is not original):
                    module.INDEX = original
            index._ACTIVE_OCCURRENCE.reset(occurrence_token)
            ledger.db.close()
            shutil.rmtree(isolated_vault)


@pytest.fixture
def authorized_reader_scope(monkeypatch):
    """A declared principal for codec/pagination unit tests, not an ACL bypass in production.

    Isolation and revocation are exercised with the real resolver in
    test_agent_knowledge_scope. These unit tests isolate rendering and paging.
    """
    from obsidience.harness.knowledge import scope, vault
    principal = vault.Note("Agents/Fixture/Fixture.md", "Fixture", {"kind": "agent"}, "")
    def authorized(_context, snapshot):
        refs = {note.ref for note in snapshot.by_ref.values()
                if not any(part.startswith(("_", ".")) for part in note.path.split("/"))}
        return principal, refs
    monkeypatch.setattr(scope, "execution_scope", authorized)

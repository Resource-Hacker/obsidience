"""Runtime-backed Article tests must never write the workstation ledger."""

import sys
import shutil

import pytest


@pytest.fixture(autouse=True)
def isolated_task_ledger(tmp_path, tmp_path_factory):
    from obsidience.harness.config import CONFIG
    from obsidience.harness.knowledge import index

    original = index.INDEX
    # Own this patch lifecycle so test-specific monkeypatch fixtures unwind
    # before we restore imports and close the per-test connection.
    with pytest.MonkeyPatch.context() as patch:
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
            # INDEX without participating in the setup patch list.
            for module in tuple(sys.modules.values()):
                if getattr(module, "__name__", "").startswith("obsidience.") and getattr(module, "INDEX", None) is ledger:
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

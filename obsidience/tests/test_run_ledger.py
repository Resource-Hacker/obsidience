from __future__ import annotations

import sqlite3

from obsidience.harness.knowledge import index as indexer


def test_legacy_runs_adds_objective_without_rebuilding(tmp_path, monkeypatch) -> None:
    database = tmp_path / "legacy.sqlite3"
    connection = sqlite3.connect(database)
    connection.execute(
        """CREATE TABLE runs(
        id TEXT PRIMARY KEY, task_ref TEXT, agent TEXT, started REAL, finished REAL,
        status TEXT, summary TEXT, trace TEXT, receipt_path TEXT
        )"""
    )
    connection.execute(
        "INSERT INTO runs VALUES(?,?,?,?,?,?,?,?,?)",
        (
            "historical",
            "Tasks/query",
            "Executive",
            1.0,
            2.0,
            "completed",
            "done",
            "[]",
            "Receipts/historical.md",
        ),
    )
    connection.commit()
    connection.close()

    monkeypatch.setattr(indexer.CONFIG, "db_path", database)
    ledger = indexer.Index()
    try:
        columns = {
            row[1]: row
            for row in ledger.db.execute("PRAGMA table_info(runs)").fetchall()
        }
        assert columns["objective"][3] == 1
        assert columns["objective"][4] == "''"
        historical = ledger.runs()[0]
        assert historical["objective"] == ""
        assert ledger.db.execute(
            "SELECT receipt_path FROM runs WHERE id='historical'"
        ).fetchone() == ("Receipts/historical.md",)

        objective = "Inspect GPU #2 — keep  two spaces."
        ledger.record_run(
            id="current",
            task_ref="Tasks/research/model",
            objective=objective,
            agent="Darwin",
            started=3.0,
            finished=4.0,
            status="completed",
            summary="measured",
            trace="[]",
        )
        current = next(row for row in ledger.runs() if row["id"] == "current")
        assert current["objective"] == objective
        assert current["task_ref"] == "Tasks/research/model"
        assert current["status"] == "completed"
    finally:
        ledger.db.close()

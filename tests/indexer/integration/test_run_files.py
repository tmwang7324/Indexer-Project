"""The `run` command over the files source: idempotent, and honest about what it skips."""
import logging

from indexer import run
from indexer.db import connect
from indexer_support.invariants import check_invariants, counts


def test_run_twice_leaves_the_same_rows(clean_db, monkeypatch, caplog):
    for key, value in clean_db.as_env().items():
        monkeypatch.setenv(key, value)
    caplog.set_level(logging.INFO)
    results = []
    for _ in range(2):
        assert run.main(["run", "--source", "files:test_blocks"]) == 0
        conn = connect(clean_db)
        try:
            results.append(counts(conn))
            check_invariants(conn)
        finally:
            conn.close()
    assert results[0] == results[1] == (1, 3, 4)
    assert "skipping 7078406: raw transaction bytes and no decoded file" in caplog.text

"""The `run` command over the curated Terra sample."""
from indexer import run
from indexer.db import connect
from indexer_support.db import REPO
from indexer_support.invariants import check_invariants, counts, snapshot

SAMPLE = f"replay:{REPO / 'tests' / 'indexer' / 'data' / 'terra'}"


def test_every_curated_block_indexes_and_a_second_run_changes_nothing(clean_db, monkeypatch):
    for key, value in clean_db.as_env().items():
        monkeypatch.setenv(key, value)
    snaps = []
    for _ in range(2):
        assert run.main(["run", "--source", SAMPLE]) == 0
        conn = connect(clean_db)
        try:
            check_invariants(conn)
            snaps.append(snapshot(conn))
        finally:
            conn.close()
    assert snaps[0] == snaps[1]
    conn = connect(clean_db)
    try:
        assert counts(conn)[0] == 50
        with conn.cursor() as cur:
            # failed transactions carry their non-zero code, codespace and log; successful ones have code 0
            cur.execute("SELECT height, code, codespace, left(log, 24) FROM transactions WHERE code <> 0 "
                        "ORDER BY height")
            assert cur.fetchall() == [
                (23270383, 5, "sdk", "failed to execute messag"), (23318983, 5, "sdk", "failed to execute messag"),
                (23452983, 11, "sdk", "out of gas in location: "), (23454383, 11, "sdk", "out of gas in location: "),
                (23563215, 5, "sdk", "failed to execute messag")]
            cur.execute("SELECT count(*) FROM transactions WHERE code IS NULL")
            assert cur.fetchone() == (0,)
            # the message type without a handler is stored in messages only
            cur.execute("SELECT count(*) FROM messages WHERE type = '/cosmos.feegrant.v1beta1.MsgGrantAllowance'")
            assert cur.fetchone() == (1,)
    finally:
        conn.close()


def test_from_height_skips_lower_blocks(clean_db, monkeypatch):
    for key, value in clean_db.as_env().items():
        monkeypatch.setenv(key, value)
    assert run.main(["run", "--source", SAMPLE, "--from-height", "23563000"]) == 0
    conn = connect(clean_db)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT min(height) FROM blocks")
            assert cur.fetchone()[0] >= 23563000
    finally:
        conn.close()

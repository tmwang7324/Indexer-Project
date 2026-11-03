"""I6[sync]: crash, restart, finish (single worker). Nothing is stored twice, nothing is missed, and the
checkpoint ends at the last height."""
import json

import pytest

from indexer import run
from indexer.checkpoint import read_checkpoint
from indexer.db import connect
from indexer.pipeline import Pipeline
from indexer.sources.replay import ReplaySource
from indexer.writer import Hooks
from indexer_support.cache import renumbered_cache
from indexer_support.db import db_test_settings, truncate_all
from indexer_support.fake_node import FakeNode
from indexer_support.gates import Gates
from indexer_support.invariants import check_invariants, counts, snapshot

START = 1000
CRASH_AT = 1025
CHAIN = "phoenix-1"


@pytest.fixture
def chain(tmp_path):
    heights = renumbered_cache(tmp_path / "cache", START)
    return tmp_path / "cache", heights


@pytest.fixture
def db(clean_db):
    conn = connect(clean_db)
    yield conn
    conn.close()


def go(cache, hooks=None, workers=1):
    """Run the cache to its end against the test database."""
    return Pipeline(ReplaySource(cache), workers=workers, settings=db_test_settings(), hooks=hooks).run()


def crash_at(height):
    def hook(h):
        if h == height:
            raise SystemExit("killed")
    return Hooks(before_commit=hook)


def test_crash_then_restart_stores_every_block_once(db, chain):
    cache, heights = chain
    with pytest.raises(SystemExit):
        go(cache, hooks=crash_at(CRASH_AT))
    assert counts(db)[0] == 25                             # 1000..1024 are committed; 1025 rolled back
    assert read_checkpoint(db, CHAIN) == CRASH_AT - 1
    check_invariants(db)

    db.close()                                             # the process is gone; a new one connects afresh
    db2 = connect(db_test_settings())
    try:
        stats = go(cache)
        assert (stats.stored, stats.skipped, stats.failed) == (25, 25, 0)
        assert counts(db2)[0] == 50
        assert read_checkpoint(db2, CHAIN) == heights[-1] == START + 49
        check_invariants(db2)
    finally:
        db2.close()


def test_the_restarted_run_gives_the_same_rows_as_an_uninterrupted_one(clean_db, chain):
    cache, _ = chain
    snaps = []
    for crash in (None, CRASH_AT):
        truncate_all(clean_db)
        conn = connect(clean_db)
        try:
            if crash:
                with pytest.raises(SystemExit):
                    go(cache, hooks=crash_at(crash))
                conn.close()
                conn = connect(clean_db)
            go(cache)
            snaps.append(snapshot(conn))
        finally:
            conn.close()
    assert snaps[0] == snaps[1]


def test_restarting_a_finished_run_does_nothing(db, chain):
    cache, _ = chain
    go(cache)
    before = snapshot(db)
    stats = go(cache)
    assert (stats.stored, stats.skipped, stats.failed) == (0, 50, 0)
    assert snapshot(db) == before
    check_invariants(db)


def test_the_cli_restart_of_a_finished_run_exits_zero(indexer_env, chain):
    cache, _ = chain
    assert run.main(["run", "--source", f"replay:{cache}"]) == 0
    assert run.main(["run", "--source", f"replay:{cache}"]) == 0


def test_a_rest_run_resumes_above_the_checkpoint_and_never_asks_for_lower_heights(indexer_env, chain, monkeypatch):
    cache, heights = chain
    with FakeNode(cache, CHAIN) as node:
        monkeypatch.setenv("INDEXER_ENDPOINTS", json.dumps(
            [{"name": "n", "rest": node.url, "rpc": node.url, "rate": 1000}]))
        assert run.main(["run", "--source", "rest", "--from-height", str(START), "--to-height", str(START + 9)]) == 0
        asked_before = len(node.paths)
        # no --from-height: the checkpoint says where to start
        assert run.main(["run", "--source", "rest", "--to-height", str(START + 14)]) == 0
        later = node.paths[asked_before:]
    wanted = [int(p.rsplit("/", 1)[1]) for p in later if "/txs/block/" in p]
    assert wanted == list(range(START + 10, START + 15))
    conn = connect(indexer_env)
    try:
        assert read_checkpoint(conn, CHAIN) == START + 14
        check_invariants(conn)
    finally:
        conn.close()


def test_crash_between_out_of_order_commits_then_restart_leaves_no_gap(clean_db, chain):
    """I6, out-of-order case: 1003 is held while 1004 and 1005 commit; the process dies before 1006 commits
    and 1003 never lands. The checkpoint must be 1002 (not 1005), and the restart must fill the gap."""
    cache, heights = chain
    truncate_all(clean_db)
    uninterrupted = go(cache)
    reference = connect(clean_db)
    expected = snapshot(reference)
    reference.close()
    truncate_all(clean_db)

    gates = Gates(hold=[1003], crash_at=1006, crash_after=[1004, 1005])
    p = Pipeline(gates.wrap(ReplaySource(cache)), workers=4, settings=db_test_settings(), hooks=gates.hooks)
    with pytest.raises(SystemExit):
        p.run()
    conn = connect(clean_db)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT height FROM blocks WHERE height IN (1003, 1004, 1005, 1006) ORDER BY height")
            stored = [h for (h,) in cur.fetchall()]
        conn.rollback()
        assert stored[:2] == [1004, 1005] and 1003 not in stored and 1006 not in stored
        assert read_checkpoint(conn, CHAIN) == 1002
        check_invariants(conn, p)
    finally:
        conn.close()

    restarted = Pipeline(ReplaySource(cache), workers=4, settings=db_test_settings())
    stats = restarted.run()
    assert stats.stored + stats.skipped == 50 and stats.failed == 0
    conn = connect(clean_db)
    try:
        assert read_checkpoint(conn, CHAIN) == START + 49
        assert snapshot(conn) == expected                 # every block once, same rows as an uninterrupted run
        check_invariants(conn, restarted)
    finally:
        conn.close()
    assert uninterrupted.stored == 50

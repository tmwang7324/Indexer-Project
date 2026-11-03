"""I6[sync]: crash, restart, finish (single worker). Nothing is stored twice, nothing is missed, and the
checkpoint ends at the last height."""
import json

import pytest

from indexer import run
from indexer.checkpoint import read_checkpoint
from indexer.db import connect
from indexer.pipeline import run_items
from indexer.sources.replay import ReplaySource
from indexer.writer import Hooks
from indexer_support.cache import renumbered_cache
from indexer_support.db import db_test_settings, truncate_all
from indexer_support.fake_node import FakeNode
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


def crash_at(height):
    def hook(h):
        if h == height:
            raise SystemExit("killed")
    return Hooks(before_commit=hook)


def test_crash_then_restart_stores_every_block_once(db, chain):
    cache, heights = chain
    with pytest.raises(SystemExit):
        run_items(ReplaySource(cache).items(), db, hooks=crash_at(CRASH_AT))
    assert counts(db)[0] == 25                             # 1000..1024 are committed; 1025 rolled back
    assert read_checkpoint(db, CHAIN) == CRASH_AT - 1
    check_invariants(db)

    db.close()                                             # the process is gone; a new one connects afresh
    db2 = connect(db_test_settings())
    try:
        stats = run_items(ReplaySource(cache).items(), db2)
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
                    run_items(ReplaySource(cache).items(), conn, hooks=crash_at(crash))
                conn.close()
                conn = connect(clean_db)
            run_items(ReplaySource(cache).items(), conn)
            snaps.append(snapshot(conn))
        finally:
            conn.close()
    assert snaps[0] == snaps[1]


def test_restarting_a_finished_run_does_nothing(db, chain):
    cache, _ = chain
    run_items(ReplaySource(cache).items(), db)
    before = snapshot(db)
    stats = run_items(ReplaySource(cache).items(), db)
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

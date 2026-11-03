"""I9: catch up to a scripted head, then follow new blocks; restart while following; the start rule; blocks
older than the node keeps (D3, D16)."""
import json
import logging
import signal
import subprocess
import sys
import time

import pytest

from indexer import run
from indexer.checkpoint import read_checkpoint
from indexer.db import connect
from indexer.pipeline import Pipeline
from indexer.sources.endpoints import EndpointPool, load_endpoints
from indexer.sources.rest import BACKFILL_DEPTH, POLL_INTERVAL, RestSource
from indexer_support.cache import CHAIN, renumbered_cache
from indexer_support.db import REPO, child_env, db_test_settings
from indexer_support.fake_node import FakeNode
from indexer_support.gates import Gates, start
from indexer_support.invariants import check_invariants, counts

S = 1000            # the first height of the run
POLL = 0.05         # seconds between head lookups in these tests


@pytest.fixture
def cache(tmp_path):
    renumbered_cache(tmp_path / "cache", S)
    return tmp_path / "cache"


@pytest.fixture
def db(clean_db):
    conn = connect(clean_db)
    yield conn
    conn.close()


def endpoints_json(node):
    return json.dumps([{"name": "n", "rest": node.url, "rpc": node.url, "rate": 1000}])


def rest_source(node, monkeypatch, **kw):
    monkeypatch.setenv("INDEXER_ENDPOINTS", endpoints_json(node))
    kw.setdefault("poll_interval", POLL)
    return RestSource(pool=EndpointPool(load_endpoints(), cooldown=0.01), **kw)


def wait_for(condition, what, timeout=15):
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, f"timed out waiting for {what}"
        time.sleep(0.01)


def test_catch_up_to_the_head_then_follow_each_new_block(db, cache, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    gates = Gates()
    with FakeNode(cache, CHAIN) as node:
        node.head = S + 20
        source = rest_source(node, monkeypatch, from_height=S, follow=True)
        p = Pipeline(source, workers=4, settings=db_test_settings(), hooks=gates.hooks, retry_delay=0.0)
        running = start(p)
        for h in range(S, S + 21):
            assert gates.committed[h].wait(15), f"{h} was never stored"
        wait_for(lambda: read_checkpoint(db, CHAIN) == S + 20, "the checkpoint to reach the head")

        for n in range(1, 6):                                  # the chain produces blocks; each is picked up soon
            asked = time.monotonic()
            node.head = S + 20 + n
            assert gates.committed[S + 20 + n].wait(5), f"block {S + 20 + n} was not picked up"
            assert time.monotonic() - asked < 2.0

        p.stop.set()                                           # SIGTERM's effect, without a process
        stats = running.join()
    assert stats.stored == 26 and stats.failed == 0
    assert read_checkpoint(db, CHAIN) == S + 25
    assert "caught up at height" in caplog.text
    assert f"checkpoint {S + 25}, head {S + 25}, lag 0" in caplog.text           # the lag line
    check_invariants(db, p)


def test_a_restart_while_following_resumes_above_the_checkpoint_without_a_gap(db, cache, monkeypatch):
    with FakeNode(cache, CHAIN) as node:
        node.head = S + 9
        first = Pipeline(rest_source(node, monkeypatch, from_height=S, follow=False), settings=db_test_settings())
        first.run()
        assert read_checkpoint(db, CHAIN) == S + 9
        asked_before = len(node.paths)

        node.head = S + 12
        gates = Gates()
        restarted = RestSource(follow=True, poll_interval=POLL, pool=rest_source(node, monkeypatch).pool)
        restarted.from_height = S + 9 + 1                      # what `run` resolves from the checkpoint
        p = Pipeline(restarted, workers=2, settings=db_test_settings(), hooks=gates.hooks)
        running = start(p)
        assert gates.committed[S + 12].wait(15)
        node.head = S + 14
        assert gates.committed[S + 14].wait(5)
        p.stop.set()
        running.join()
        later = node.paths[asked_before:]
    wanted = sorted({int(path.rsplit("/", 1)[1]) for path in later if "/txs/block/" in path})
    assert wanted == list(range(S + 10, S + 15))               # nothing at or below the checkpoint was asked again
    assert read_checkpoint(db, CHAIN) == S + 14
    assert counts(db)[0] == 15
    check_invariants(db, p)


def test_with_no_checkpoint_and_no_from_height_it_starts_below_the_head(indexer_env, cache, monkeypatch):
    assert BACKFILL_DEPTH == 25000 and POLL_INTERVAL > 1      # the documented defaults
    monkeypatch.setenv("INDEXER_BACKFILL_DEPTH", "10")
    with FakeNode(cache, CHAIN) as node:                      # head: the highest cached block, S + 49
        monkeypatch.setenv("INDEXER_ENDPOINTS", endpoints_json(node))
        assert run.main(["run", "--source", "rest", "--no-follow"]) == 0
        first_asked = min(int(p.rsplit("/", 1)[1]) for p in node.paths if "/txs/block/" in p)
    assert first_asked == S + 49 - 10
    conn = connect(indexer_env)
    try:
        assert counts(conn)[0] == 11
        assert read_checkpoint(conn, CHAIN) == S + 49
        check_invariants(conn)
    finally:
        conn.close()


def test_the_cli_follows_the_head_and_stops_cleanly_on_sigterm(db, cache):
    settings = db_test_settings()
    with FakeNode(cache, CHAIN) as node:
        node.head = S + 20
        env = child_env(settings, INDEXER_ENDPOINTS=endpoints_json(node), INDEXER_POLL_INTERVAL=str(POLL),
                        INDEXER_RETRY_DELAY="0.01")
        proc = subprocess.Popen([sys.executable, "-m", "indexer", "run", "--source", "rest", "--from-height", str(S),
                                 "--workers", "3"], cwd=REPO, env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True)
        try:
            wait_for(lambda: proc.poll() is not None or read_checkpoint(db, CHAIN) == S + 20, "catching up", 30)
            assert proc.poll() is None, "the indexer exited instead of following"
            node.head = S + 21
            wait_for(lambda: read_checkpoint(db, CHAIN) == S + 21, "the new block")
            proc.send_signal(signal.SIGTERM)
            output, _ = proc.communicate(timeout=30)
        finally:
            if proc.poll() is None:
                proc.kill()
    assert proc.returncode == run.EXIT_SIGNAL, output
    assert "caught up at height" in output and "stopped:" in output
    check_invariants(db)


@pytest.mark.parametrize("pruned", ["lowest_txs", "lowest_results"])
def test_heights_older_than_the_node_keeps_are_recorded_and_not_retried_forever(indexer_env, cache, monkeypatch,
                                                                              pruned):
    with FakeNode(cache, CHAIN, **{pruned: S + 4}) as node:
        monkeypatch.setenv("INDEXER_ENDPOINTS", endpoints_json(node))
        assert run.main(["run", "--source", "rest", "--from-height", str(S), "--to-height", str(S + 7)]) \
            == run.EXIT_FAILED_BLOCKS
        asked = [p for p in node.paths if p.endswith(f"/txs/block/{S}")]
    assert len(asked) == 1, "a height every endpoint says it no longer keeps is asked once, not retried"
    conn = connect(indexer_env)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT height, attempts, error FROM failed_blocks ORDER BY height")
            failed = cur.fetchall()
            cur.execute("SELECT height FROM blocks ORDER BY height")
            stored = [h for (h,) in cur.fetchall()]
        conn.rollback()
        assert [(h, a) for h, a, _ in failed] == [(S + n, 1) for n in range(4)]
        assert all("retention window" in e and "lowest height" in e for _, _, e in failed)
        assert stored == [S + 4, S + 5, S + 6, S + 7]
        assert read_checkpoint(conn, CHAIN) == S - 1
        check_invariants(conn)
    finally:
        conn.close()

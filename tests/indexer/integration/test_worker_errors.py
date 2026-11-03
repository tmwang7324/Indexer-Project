"""I4 (the six ways a worker run can go wrong) and I5 (a crash while another worker commits), D21 and D22.

Every case ends with the invariant checker: no partial block, every height stored or failed (never both),
the checkpoint contiguous, every connection returned, every worker thread gone."""
import json
import logging
import os
import signal
import subprocess
import sys
import time

import pytest

from indexer import run
from indexer.checkpoint import read_checkpoint
from indexer.db import connect
from indexer.errors import TransientError
from indexer.pipeline import Pipeline
from indexer.sources.replay import ReplayCache, ReplaySource
from indexer_support.cache import CHAIN, copy_blocks, renumbered_cache
from indexer_support.db import REPO, child_env, db_test_settings
from indexer_support.fake_node import FakeNode
from indexer_support.faults import FaultySource
from indexer_support.invariants import check_invariants, counts, snapshot
from indexer_support.gates import WAIT

START, LAST = 1000, 1009


@pytest.fixture
def cache(tmp_path):
    renumbered_cache(tmp_path / "cache", START)
    return tmp_path / "cache"


@pytest.fixture
def db(clean_db):
    conn = connect(clean_db)
    yield conn
    conn.close()


def pipeline(source, workers=1, **kw):
    kw.setdefault("max_attempts", 3)
    kw.setdefault("retry_delay", 0.0)
    return Pipeline(source, workers=workers, settings=db_test_settings(), **kw)


def first_with_transactions(cache, after):
    store = ReplayCache(cache)
    return next(h for h in store.heights(CHAIN) if h > after and store.block(CHAIN, h).tx_num > 0)


def rows(db, sql, params=()):
    with db.cursor() as cur:
        cur.execute(sql, params)
        found = cur.fetchall()
    db.rollback()
    return found


# --- I4 ------------------------------------------------------------------------------------------
def test_a_transient_error_that_recovers_stores_the_block_once(db, cache):
    source = FaultySource(ReplaySource(cache, to_height=LAST), {1004: [TransientError("t1"), TransientError("t2")]})
    p = pipeline(source, max_attempts=4)
    stats = p.run()
    assert (stats.stored, stats.failed, stats.retries) == (10, 0, 2)
    assert source.loads[1004] == 3
    assert rows(db, "SELECT count(*) FROM blocks WHERE height = 1004") == [(1,)]
    assert rows(db, "SELECT count(*) FROM failed_blocks") == [(0,)]
    assert read_checkpoint(db, CHAIN) == LAST
    check_invariants(db, p)


def test_a_transient_error_that_never_ends_is_recorded_and_a_restart_retries_it(db, cache):
    source = FaultySource(ReplaySource(cache, to_height=LAST), {1004: TransientError("node says no")})
    p = pipeline(source, workers=2)
    stats = p.run()
    assert (stats.stored, stats.failed) == (9, 1)
    [(height, attempts, error)] = rows(db, "SELECT height, attempts, error FROM failed_blocks")
    assert (height, attempts) == (1004, 3) and "node says no" in error and "gave up after 3 attempts" in error
    assert rows(db, "SELECT count(*) FROM blocks WHERE height > 1004") == [(5,)]          # later heights went on
    assert read_checkpoint(db, CHAIN) == 1003                                              # and stops below the gap
    check_invariants(db, p)

    restarted = pipeline(ReplaySource(cache, to_height=LAST))
    stats = restarted.run()
    assert (stats.stored, stats.failed) == (1, 0)
    assert rows(db, "SELECT count(*) FROM failed_blocks") == [(0,)]
    assert read_checkpoint(db, CHAIN) == LAST
    check_invariants(db, restarted)


def test_a_dropped_database_connection_is_closed_not_reused_and_the_block_is_retried(db, cache):
    killed = []

    def kill_the_workers_connection(height):
        if height == 1004 and not killed:
            killed.append(height)
            ctl = connect(db_test_settings())
            ctl.autocommit = True
            with ctl.cursor() as cur:
                cur.execute("""SELECT pg_terminate_backend(pid) FROM pg_stat_activity
                               WHERE application_name = 'indexer' AND pid <> pg_backend_pid()
                                 AND state LIKE 'idle in transaction%%'""")
                assert cur.rowcount == 1, "expected to terminate exactly the block's own connection"
            ctl.close()

    from indexer.writer import Hooks
    p = pipeline(ReplaySource(cache, to_height=LAST), hooks=Hooks(before_commit=kill_the_workers_connection))
    stats = p.run()
    assert killed == [1004]
    assert (stats.stored, stats.failed, stats.retries) == (10, 0, 1)
    assert p.pool.discarded == 1                                  # the broken connection was closed, not pooled
    assert rows(db, "SELECT count(*) FROM blocks WHERE height = 1004") == [(1,)]
    assert read_checkpoint(db, CHAIN) == LAST
    check_invariants(db, p)


def test_bad_data_is_recorded_without_a_retry_and_the_run_goes_on(db, tmp_path):
    cache = copy_blocks(tmp_path, [23561832, 23561833, 23561834],
                        results={23561833: lambda doc: (doc.get("result") or doc)["txs_results"].pop()}).root
    source = FaultySource(ReplaySource(cache))
    p = pipeline(source)
    assert run.execute(p) == run.EXIT_FAILED_BLOCKS               # finished, but with a block in failed_blocks
    assert (p.stats.stored, p.stats.failed, p.stats.retries) == (2, 1, 0)
    assert source.loads[23561833] == 1                            # no second attempt
    assert rows(db, "SELECT height, attempts FROM failed_blocks") == [(23561833, 1)]
    check_invariants(db, p)


class RegistryThatBreaks:
    """The real handlers, except that one message makes a handler raise KeyError (a bug)."""

    def __init__(self, bad_raw):
        from indexer.handlers import get_registry
        self.real, self.bad_raw = get_registry(), bad_raw

    def handle(self, type_url, raw):
        if raw == self.bad_raw:
            raise KeyError("handler bug")
        return self.real.handle(type_url, raw)


@pytest.mark.parametrize("workers", [1, 4])
def test_an_unexpected_exception_stops_the_run_in_an_orderly_way(db, cache, caplog, workers):
    bad_height = first_with_transactions(cache, after=1003)
    bad = ReplayCache(cache).block(CHAIN, bad_height).transactions[0].messages[0].raw
    source = FaultySource(ReplaySource(cache))
    p = pipeline(source, workers=workers, registry=RegistryThatBreaks(bad))
    caplog.set_level(logging.INFO)

    started = time.monotonic()
    assert run.execute(p) == run.EXIT_ERROR
    assert time.monotonic() - started < WAIT                      # all threads joined well inside the timeout

    assert f"unexpected error at block {CHAIN}/{bad_height}" in caplog.text
    assert "KeyError" in caplog.text and "handler bug" in caplog.text and "Traceback" in caplog.text
    assert rows(db, "SELECT count(*) FROM blocks WHERE height = %s", (bad_height,)) == [(0,)]
    if workers == 1:
        assert max(source.loads) == bad_height                    # no height after it was handed out
    assert read_checkpoint(db, CHAIN) < bad_height
    check_invariants(db, p)


def test_sigterm_stops_a_running_indexer_in_an_orderly_way(db, cache):
    settings = db_test_settings()
    with FakeNode(cache, CHAIN, delay=0.2) as node:               # keeps the run busy for several seconds
        env = child_env(settings, INDEXER_RETRY_DELAY="0.01", INDEXER_ENDPOINTS=json.dumps(
            [{"name": "n", "rest": node.url, "rpc": node.url, "rate": 1000}]))
        proc = subprocess.Popen(
            [sys.executable, "-m", "indexer", "run", "--source", "rest", "--from-height", str(START),
             "--to-height", str(START + 49), "--workers", "2"],
            cwd=REPO, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            deadline = time.monotonic() + 30
            while counts(db)[0] < 3:
                assert time.monotonic() < deadline and proc.poll() is None, "the indexer never got going"
                time.sleep(0.05)
            proc.send_signal(signal.SIGTERM)
            output, _ = proc.communicate(timeout=30)
        finally:
            if proc.poll() is None:
                proc.kill()
    assert proc.returncode == run.EXIT_SIGNAL, output
    assert "received signal" in output and "stopped:" in output
    stored = counts(db)[0]
    assert 3 <= stored < 50
    check_invariants(db)


# --- I5 ------------------------------------------------------------------------------------------
def test_a_crash_while_another_worker_is_waiting_to_commit_leaves_whole_blocks_only(db, cache):
    """Two workers: whichever block reaches its commit first holds the checkpoint lock; the hook waits until the
    other block is blocked on that lock, then 'kills the process'. The crashed block must vanish entirely, the
    waiting block must commit entirely."""
    crashed = []

    def crash_when_the_other_block_is_waiting(height):
        if crashed:
            return
        ctl = connect(db_test_settings())
        try:
            deadline = time.monotonic() + WAIT
            while True:
                with ctl.cursor() as cur:
                    cur.execute("SELECT count(*) FROM pg_stat_activity WHERE application_name = 'indexer' "
                                "AND wait_event_type = 'Lock'")
                    waiting = cur.fetchone()[0]
                ctl.rollback()
                if waiting >= 1:
                    break
                assert time.monotonic() < deadline, "the other block never reached the lock"
                time.sleep(0.01)
        finally:
            ctl.close()
        crashed.append(height)
        raise SystemExit(f"killed before committing {height}")

    from indexer.writer import Hooks
    p = pipeline(ReplaySource(cache, to_height=START + 1), workers=2,
                 hooks=Hooks(before_commit=crash_when_the_other_block_is_waiting))
    with pytest.raises(SystemExit):
        p.run()
    [lost] = crashed
    survivor = ({START, START + 1} - {lost}).pop()
    assert rows(db, "SELECT count(*) FROM blocks WHERE height = %s", (lost,)) == [(0,)]
    assert rows(db, "SELECT count(*) FROM transactions WHERE height = %s", (lost,)) == [(0,)]
    assert rows(db, "SELECT count(*) FROM blocks WHERE height = %s", (survivor,)) == [(1,)]
    check_invariants(db, p)                          # no partial block, whichever one it was


def test_many_blocks_in_a_row_given_up_on_is_an_outage_and_stops_the_run(db, cache, caplog):
    """A dead node must not turn every remaining height into a failed_blocks row."""
    everything_fails = {h: TransientError("node unreachable") for h in range(START, START + 50)}
    p = pipeline(FaultySource(ReplaySource(cache), everything_fails), max_giveups_in_a_row=3)
    assert run.execute(p) == run.EXIT_ERROR
    assert "3 blocks in a row were given up" in caplog.text
    assert rows(db, "SELECT count(*) FROM failed_blocks") == [(3,)]
    check_invariants(db, p)

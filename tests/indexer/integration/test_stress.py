"""I7 (slow): seeded random delays and faults over the curated sample, a fixed number of rounds (D22).

Each round injects transient errors that recover, transient errors that never end and bad data on random
heights, with random per-block delays and a random worker count. Afterwards: every height is stored or in
failed_blocks, the checkpoint stops below the lowest failure, the invariants hold, and a restart without
faults gives exactly the rows of a clean run. The seed is in every failure message and in the test id."""
import random
import time

import pytest

from indexer.checkpoint import read_checkpoint
from indexer.db import connect
from indexer.errors import BadDataError, TransientError
from indexer.pipeline import Pipeline
from indexer.sources.replay import ReplaySource
from indexer_support.cache import CHAIN, renumbered_cache
from indexer_support.db import db_test_settings, truncate_all
from indexer_support.faults import FaultySource
from indexer_support.invariants import check_invariants, diff_snapshots, snapshot

START, COUNT, MAX_ATTEMPTS = 1000, 50, 3
ROUNDS = range(1, 7)


@pytest.fixture(scope="module")
def cache(tmp_path_factory):
    path = tmp_path_factory.mktemp("stress") / "cache"
    renumbered_cache(path, START)
    return path


@pytest.fixture(scope="module")
def clean_run(migrated_db, cache):
    """The rows of a fault-free run: what every round must end up with."""
    truncate_all(migrated_db)
    Pipeline(ReplaySource(cache), workers=4, settings=db_test_settings()).run()
    conn = connect(migrated_db)
    try:
        return snapshot(conn)
    finally:
        conn.close()
        truncate_all(migrated_db)


def plan(seed):
    """(faults, permanent failures, per-height delays, workers) for a seed."""
    rng = random.Random(seed)
    faults, permanent = {}, set()
    for h in range(START, START + COUNT):
        roll = rng.random()
        if roll < 0.15:
            faults[h] = [TransientError(f"flaky {h}")] * rng.randint(1, MAX_ATTEMPTS - 1)
        elif roll < 0.20:
            faults[h], permanent = TransientError(f"down {h}"), permanent | {h}
        elif roll < 0.25:
            faults[h], permanent = BadDataError(f"bad {h}"), permanent | {h}
    delays = {h: rng.uniform(0, 0.004) for h in range(START, START + COUNT)}
    return faults, permanent, delays, rng.choice([2, 4, 8])


@pytest.mark.slow
@pytest.mark.parametrize("seed", ROUNDS, ids=[f"seed-{s}" for s in ROUNDS])
def test_random_faults_and_delays_never_break_the_invariants(clean_db, cache, clean_run, seed):
    faults, permanent, delays, workers = plan(seed)
    try:
        source = FaultySource(ReplaySource(cache), faults, before_load=lambda h: time.sleep(delays[h]))
        p = Pipeline(source, workers=workers, settings=clean_db, max_attempts=MAX_ATTEMPTS, retry_delay=0.0,
                     max_giveups_in_a_row=1000)
        stats = p.run()
        conn = connect(clean_db)
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT height FROM blocks")
                stored = {h for (h,) in cur.fetchall()}
                cur.execute("SELECT height FROM failed_blocks")
                failed = {h for (h,) in cur.fetchall()}
            conn.rollback()
            assert stored | failed == set(range(START, START + COUNT)) and not stored & failed
            assert failed == permanent, "exactly the heights that could not succeed are in failed_blocks"
            assert stats.failed == len(permanent)
            expected_checkpoint = (min(permanent) - 1) if permanent else START + COUNT - 1
            assert read_checkpoint(conn, CHAIN) == expected_checkpoint
            check_invariants(conn, p)
        finally:
            conn.close()

        again = Pipeline(ReplaySource(cache), workers=workers, settings=clean_db)       # restart, no faults
        again.run()
        conn = connect(clean_db)
        try:
            final = snapshot(conn)
            assert final == clean_run, diff_snapshots(final, clean_run)
            assert read_checkpoint(conn, CHAIN) == START + COUNT - 1
            check_invariants(conn, again)
        finally:
            conn.close()
    except AssertionError as exc:
        raise AssertionError(f"stress round failed with seed={seed} (workers={workers}): {exc}") from exc

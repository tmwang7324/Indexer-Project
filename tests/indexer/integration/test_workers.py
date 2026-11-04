"""I2 and I3: N worker threads give exactly the rows one worker gives, and the checkpoint stays contiguous
while blocks finish out of order (D7, D22)."""
import pytest

from indexer import run
from indexer.checkpoint import read_checkpoint
from indexer.db import connect
from indexer.pipeline import Pipeline
from indexer.sources.replay import ReplaySource
from indexer_support.cache import CHAIN, renumbered_cache
from indexer_support.db import REPO, db_test_settings, truncate_all
from indexer_support.gates import Gates, start
from indexer_support.invariants import check_invariants, counts, diff_snapshots, snapshot

SAMPLE = REPO / "tests" / "indexer" / "data" / "terra"
START = 1000


@pytest.fixture
def db(clean_db):
    conn = connect(clean_db)
    yield conn
    conn.close()


def pipeline(source, workers=1, **kw):
    return Pipeline(source, workers=workers, settings=db_test_settings(), **kw)


def test_eight_workers_give_the_same_rows_as_one(clean_db, tmp_path):
    cache = tmp_path / "cache"
    renumbered_cache(cache, START)
    results = {}
    for source, label in ((SAMPLE, "sparse"), (cache, "contiguous")):
        snaps = []
        for workers in (1, 8):
            truncate_all(clean_db)
            p = pipeline(ReplaySource(source), workers)
            stats = p.run()
            assert (stats.stored, stats.failed) == (50, 0)
            conn = connect(clean_db)
            try:
                check_invariants(conn, p)
                snaps.append((snapshot(conn), read_checkpoint(conn, CHAIN)))
            finally:
                conn.close()
        (one, cp1), (eight, cp8) = snaps
        assert one == eight, f"{label}: 1 worker vs 8 workers differ:\n{diff_snapshots(one, eight)}"
        assert cp1 == cp8
        results[label] = cp8
    assert results["contiguous"] == START + 49


def test_a_late_block_holds_the_checkpoint_back_until_it_lands(db, tmp_path):
    """I3: 103 and 104 are held, 105 commits: the checkpoint stays at 102. Releasing 104 changes nothing;
    releasing 103 moves it through 104 to 105."""
    cache = tmp_path / "cache"
    renumbered_cache(cache, START)
    h = lambda n: START + n - 100         # noqa: E731 - heights 100.. map onto the cache's heights
    gates = Gates(hold=[h(103), h(104)])
    source = ReplaySource(cache, from_height=h(100), to_height=h(105))
    running = start(pipeline(gates.wrap(source), workers=4, hooks=gates.hooks))

    for n in (100, 101, 102, 105):
        assert gates.committed[h(n)].wait(15), f"{h(n)} never committed"
    assert read_checkpoint(db, CHAIN) == h(102)
    assert counts(db)[0] == 4                                # 100, 101, 102 and 105

    gates.release(h(104))
    assert gates.committed[h(104)].wait(15)
    assert read_checkpoint(db, CHAIN) == h(102)              # 103 is still missing

    gates.release(h(103))
    stats = running.join()
    assert stats.stored == 6
    assert read_checkpoint(db, CHAIN) == h(105)
    check_invariants(db, running.pipeline)


def test_the_cli_takes_a_worker_count(indexer_env, tmp_path):
    cache = tmp_path / "cache"
    renumbered_cache(cache, START)
    assert run.main(["run", "--source", f"replay:{cache}", "--workers", "4"]) == 0
    conn = connect(indexer_env)
    try:
        assert counts(conn)[0] == 50
        assert read_checkpoint(conn, CHAIN) == START + 49
        check_invariants(conn)
    finally:
        conn.close()


def test_connections_are_reused_not_reopened_for_every_block(clean_db, tmp_path, monkeypatch):
    """The pool keeps one connection per worker open for the whole run. (It once kept only one, so with several
    workers nearly every block opened and closed a database connection, which made 8 workers 5 times slower than 1.)"""
    import psycopg2
    cache = tmp_path / "cache"
    renumbered_cache(cache, START)
    opened = []
    real_connect = psycopg2.connect

    def counting_connect(*args, **kwargs):
        opened.append(1)
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(psycopg2, "connect", counting_connect)
    p = pipeline(ReplaySource(cache), workers=4)
    assert p.run().stored == 50
    assert len(opened) <= 4 + 1, f"{len(opened)} connections were opened for 4 workers and 50 blocks"
    assert p.pool.in_use == 0

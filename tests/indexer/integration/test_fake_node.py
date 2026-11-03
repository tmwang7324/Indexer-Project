"""I8: a local fake node serves the curated sample: rotation, rate limit, recording; replay gives the same rows."""
import json
import logging

import pytest

from indexer import run
from indexer.db import connect
from indexer.sources.replay import ReplayCache
from indexer_support.fake_node import FakeNode
from indexer_support.invariants import check_invariants, counts, snapshot
from indexer_support.db import REPO, truncate_all

SAMPLE = REPO / "tests" / "indexer" / "data" / "terra"
CHAIN = "phoenix-1"
RATE, BURST = 8, 2          # requests per second and burst, per endpoint
COOLDOWN = 0.4              # seconds a failing endpoint is skipped


def consecutive_run():
    heights = ReplayCache(SAMPLE).heights(CHAIN)
    manifest = json.loads((SAMPLE / "manifest.json").read_text())
    start = next(int(h) for h, v in manifest.items() if "consecutive run" in v["why"])
    run_heights = [h for h in heights if start <= h < start + 6]
    assert len(run_heights) == 6
    return run_heights[0], run_heights[-1]


def max_in_window(arrivals, seconds=1.0):
    return max((sum(1 for t in arrivals if start <= t < start + seconds) for start in arrivals), default=0)


@pytest.fixture
def env(monkeypatch, clean_db):
    for key, value in clean_db.as_env().items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("INDEXER_ENDPOINT_COOLDOWN", str(COOLDOWN))
    return clean_db


def endpoints_env(monkeypatch, *nodes):
    monkeypatch.setenv("INDEXER_ENDPOINTS", json.dumps([
        {"name": f"node-{i}", "rest": n.url, "rpc": n.url, "rate": RATE, "burst": BURST}
        for i, n in enumerate(nodes)]))


def test_record_and_replay_through_a_fake_node_with_a_failing_endpoint(env, monkeypatch, tmp_path, caplog):
    first, last = consecutive_run()
    caplog.set_level(logging.WARNING)
    # node A answers 429, then 503, then recovers; node B is always healthy
    with FakeNode(SAMPLE, CHAIN, script=[429, 503]) as a, FakeNode(SAMPLE, CHAIN) as b:
        endpoints_env(monkeypatch, a, b)
        recorded = tmp_path / "recorded"
        assert run.main(["run", "--source", "rest", "--from-height", str(first), "--to-height", str(last),
                         "--record", str(recorded)]) == 0

    # 1. the blocks were indexed
    conn = connect(env)
    try:
        from_nodes = snapshot(conn)
        assert counts(conn)[0] == 6
        check_invariants(conn)
    finally:
        conn.close()

    # 2. the request rate never exceeds the limit (burst + rate over any one-second window)
    for node in (a, b):
        assert max_in_window(node.arrivals) <= BURST + RATE, node.paths

    # 3. rotation: A failed first (429, then 503), B served in the meantime, and A was left alone
    #    for the whole cool-down before each retry (arrival times can only be later than the cool-down, never earlier)
    assert "node-0: HTTP 429" in caplog.text and "node-0: HTTP 503" in caplog.text
    assert len(a.arrivals) >= 3 and len(b.arrivals) > 0 and a.arrivals[0] < b.arrivals[0]
    assert a.arrivals[1] - a.arrivals[0] >= COOLDOWN and a.arrivals[2] - a.arrivals[1] >= COOLDOWN
    assert any(a.arrivals[0] < t < a.arrivals[1] for t in b.arrivals)       # B served while A was cooling

    # 4. the recording is exactly what the node served
    sample, copy = ReplayCache(SAMPLE), ReplayCache(recorded)
    assert copy.heights(CHAIN) == list(range(first, last + 1))
    for height in range(first, last + 1):
        assert copy.read(CHAIN, height) == sample.read(CHAIN, height)

    # 5. replaying the recording gives the same rows
    truncate_all(env)
    assert run.main(["run", "--source", f"replay:{recorded}"]) == 0
    conn = connect(env)
    try:
        assert snapshot(conn) == from_nodes
        check_invariants(conn)
    finally:
        conn.close()


def test_run_fails_when_every_endpoint_keeps_failing(env, monkeypatch, tmp_path, caplog):
    first, _ = consecutive_run()
    monkeypatch.setenv("INDEXER_ENDPOINT_COOLDOWN", "0.01")
    with FakeNode(SAMPLE, CHAIN, script=lambda n: 503) as only:
        endpoints_env(monkeypatch, only)
        assert run.main(["run", "--source", "rest", "--from-height", str(first), "--to-height", str(first),
                         "--record", str(tmp_path / "rec")]) == 1
    assert "could not fetch height" in caplog.text
    assert ReplayCache(tmp_path / "rec").heights(CHAIN) == []

"""I11: the `bench` command on a 5-block slice of the curated sample, with local fakes only (D25).

The new indexer reads a replay cache, the old pipeline decodes transactions from a local fake endpoint, and the
baseline is the current tree's copy of tools/bench_single_threaded.py. No node is called.
"""
import json
import sys

import psycopg2
import pytest
import requests

from indexer import run
from indexer.bench import DecodeServer, Inputs
from indexer.db import connect
from indexer_support.cache import renumbered_cache

BASELINE = f"{sys.executable} tools/bench_single_threaded.py --replay {{cache}} --reset"
HEIGHTS = "1000:1004"


@pytest.fixture
def prepared(tmp_path, indexer_env):
    source = tmp_path / "source"
    renumbered_cache(source)
    folder = tmp_path / "bench"
    assert run.main(["bench", "--heights", HEIGHTS, "--prepare", "--from-cache", str(source),
                     "--dir", str(folder)]) == 0
    return folder


def bench(folder, *extra):
    return run.main(["bench", "--heights", HEIGHTS, "--dir", str(folder), "--decode", "local",
                     "--baseline-cmd", BASELINE, "--workers", "2", *extra])


def scratch_databases(settings):
    conn = psycopg2.connect(host=settings.host, port=settings.port, dbname=settings.name, user=settings.user,
                            password=settings.password)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT datname FROM pg_database WHERE datname LIKE 'bench\\_%'")
            return [r[0] for r in cur.fetchall()]
    finally:
        conn.close()


def test_prepare_writes_the_replay_cache_and_the_old_format_files(prepared):
    inputs = Inputs(prepared)
    assert sorted(p.name for p in inputs.blocks.iterdir()) == ["1000", "1001", "1002", "1003", "1004"]
    block = json.loads((inputs.blocks / "1000").read_text())
    assert set(block) == {"block_id", "block", "sdk_block"}
    assert block["block"]["header"]["height"] == "1000"
    assert len(list((inputs.cache / "phoenix-1").glob("*.results.json.gz"))) == 5


def test_the_five_block_run_reports_all_three_pipelines_with_matching_counts(prepared, indexer_env, capsys):
    assert bench(prepared) == 0
    out = capsys.readouterr().out
    reports = list(prepared.glob("report-*.md"))
    assert len(reports) == 1
    text = reports[0].read_text()
    for label in ("old pipeline", "single-threaded baseline", "revamped pipeline (2 workers)"):
        assert label in text
    assert "All contenders stored the same blocks, transactions and messages" in text
    assert "2 decode requests per transaction" in text
    # each contender was timed on its own and counted five blocks
    for name in ("old", "baseline", "new"):
        assert f"bench: {name}: 5 blocks in" in out
    assert scratch_databases(indexer_env) == [], "the scratch databases are dropped afterwards"


def test_a_contender_that_stored_the_wrong_rows_is_reported_per_height_and_fails_the_run(prepared, indexer_env,
                                                                                         capsys):
    # a baseline that reports success but writes nothing
    stub = f"{sys.executable} -c \"print('{{\\\"blocks\\\": 5, \\\"transactions\\\": 4, \\\"messages\\\": 6, \\\"seconds\\\": 1.0}}')\""
    code = run.main(["bench", "--heights", HEIGHTS, "--dir", str(prepared), "--only", "baseline",
                     "--baseline-cmd", stub])
    assert code == 1
    out = capsys.readouterr().out
    for height in range(1000, 1005):
        assert f"{height}: baseline: block: expected stored, found missing" in out
    assert "mismatch(es)" in next(prepared.glob("report-*.md")).read_text()


def test_it_refuses_to_start_while_an_indexer_session_is_active(prepared, indexer_env, capsys):
    session = connect(indexer_env)                                  # application_name = 'indexer'
    try:
        assert bench(prepared, "--only", "new") == 2
    finally:
        session.close()
    assert "indexer session(s) are active" in capsys.readouterr().err
    assert not list(prepared.glob("report-*.md"))
    assert scratch_databases(indexer_env) == []


def test_unprepared_heights_are_refused(tmp_path, indexer_env, capsys):
    assert bench(tmp_path / "empty") == 2
    assert "run with --prepare first" in capsys.readouterr().err


def test_an_unknown_contender_is_refused(prepared, capsys):
    assert bench(prepared, "--only", "old,fastest") == 2
    assert "unknown contender" in capsys.readouterr().err


def test_the_local_decode_endpoint_answers_like_the_node(prepared):
    from indexer.sources.replay import ReplayCache
    inputs = Inputs(prepared)
    cache = ReplayCache(inputs.cache)
    pages, _ = cache.read("phoenix-1", 1000)
    raw = json.loads(pages[0])["block"]["data"]["txs"][0]
    with DecodeServer.for_cache(cache, "phoenix-1", range(1000, 1005)) as server:
        ok = requests.post(f"{server.url}/cosmos/tx/v1beta1/decode", json={"tx_bytes": raw}, timeout=5)
        unknown = requests.post(f"{server.url}/cosmos/tx/v1beta1/decode", json={"tx_bytes": "AAAA"}, timeout=5)
    assert ok.status_code == 200 and "body" in ok.json()["tx"] and "auth_info" in ok.json()["tx"]
    assert unknown.status_code == 400
    assert server.requests == 2

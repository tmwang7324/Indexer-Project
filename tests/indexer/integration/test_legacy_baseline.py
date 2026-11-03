"""I10: the old pipeline, run alone, loads into its own `legacy` schema and leaves the `indexer` schema untouched (D9).

The old pipeline is a performance baseline, not a second writer: nothing here runs it at the same time as the
indexer. The indexer's data is loaded first, the indexer is idle, then `load_transactions.sh` runs on the Migaloo
fixture block with a local stand-in for the decode endpoint.
"""
import json
import os
import shutil
import subprocess

import psycopg2
import pytest

from indexer import run
from indexer.bench import DecodeServer
from indexer.db import connect
from indexer_support.db import REPO
from indexer_support.invariants import snapshot

SAMPLE = f"replay:{REPO / 'tests' / 'indexer' / 'data' / 'terra'}"
BLOCK = REPO / "test_blocks" / "7027410"
DECODED = REPO / "tests" / "fixtures" / "decoded" / "7027410.json"

pytestmark = pytest.mark.skipif(not (shutil.which("psql") and shutil.which("jq")), reason="needs psql and jq")


def _legacy_workdir(tmp_path, settings, schema_in_info_json):
    work = tmp_path / "work"
    work.mkdir()
    for path in REPO.glob("*.py"):
        (work / path.name).symlink_to(path)
    for name in ("Txs.sql", "type.json", "types_script", "load_transactions.sh"):
        (work / name).symlink_to(REPO / name)
    psql = {"db_name": settings.name, "db_user": settings.user, "db_password": settings.password,
            "db_host": settings.host, "db_port": str(settings.port)}
    if schema_in_info_json:
        psql["db_schema"] = "legacy"
    (work / "info.json").write_text(json.dumps({"psql": psql}))
    blocks = tmp_path / "blocks"
    blocks.mkdir()
    shutil.copy(BLOCK, blocks / "7027410")
    return work, blocks


def _count(settings, sql):
    conn = psycopg2.connect(host=settings.host, port=settings.port, dbname=settings.name, user=settings.user,
                            password=settings.password)
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            return cur.fetchone()[0]
    finally:
        conn.close()


@pytest.fixture
def legacy_cleanup(indexer_env):
    yield
    conn = psycopg2.connect(host=indexer_env.host, port=indexer_env.port, dbname=indexer_env.name,
                            user=indexer_env.user, password=indexer_env.password)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("DROP SCHEMA IF EXISTS legacy CASCADE")
    conn.close()


@pytest.mark.parametrize("where", ["info.json", "environment"])
def test_the_legacy_load_fills_the_legacy_schema_and_leaves_the_indexer_schema_unchanged(
        tmp_path, indexer_env, legacy_cleanup, where):
    assert run.main(["run", "--source", SAMPLE]) == 0                    # the indexer holds data; it is now idle
    conn = connect(indexer_env)
    try:
        before = snapshot(conn)
    finally:
        conn.close()
    assert before["blocks"], "the test needs indexed data to protect"

    work, blocks = _legacy_workdir(tmp_path, indexer_env, schema_in_info_json=(where == "info.json"))
    block = json.loads(BLOCK.read_text())
    decoded = dict(zip(block["block"]["data"]["txs"], json.loads(DECODED.read_text())))
    env = {k: v for k, v in os.environ.items() if not k.startswith("INDEXER_DB_SCHEMA")}
    if where == "environment":
        env["INDEXER_DB_SCHEMA"] = "legacy"
    with DecodeServer(decoded) as server:
        env["LEGACY_DECODE_URLS"] = server.url
        done = subprocess.run(["bash", "load_transactions.sh", "-t", "-b", str(blocks), "-o", str(tmp_path / "log")],
                              cwd=work, env=env, capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "1 blocks were processed." in done.stdout and "0 transactions failed" in done.stdout

    assert _count(indexer_env, "SELECT count(*) FROM legacy.blocks") == 1
    assert _count(indexer_env, "SELECT count(*) FROM legacy.transactions") == 3
    # nothing of the old pipeline's landed in public, and the indexer schema is exactly as it was
    assert _count(indexer_env, "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'") == 0
    conn = connect(indexer_env)
    try:
        assert snapshot(conn) == before
    finally:
        conn.close()
    assert server.requests == 6                                           # two decode requests per transaction


def test_a_schema_name_that_is_not_plain_is_refused(tmp_path, indexer_env):
    work, blocks = _legacy_workdir(tmp_path, indexer_env, schema_in_info_json=False)
    env = dict(os.environ, INDEXER_DB_SCHEMA="legacy; DROP SCHEMA indexer CASCADE")
    done = subprocess.run(["bash", "load_transactions.sh", "-t", "-b", str(blocks), "-o", str(tmp_path / "log")],
                          cwd=work, env=env, capture_output=True, text=True, timeout=60)
    assert done.returncode == 1 and "not a plain schema name" in done.stderr


def _search_path(connection):
    with connection.cursor() as cur:
        cur.execute("SHOW search_path")
        return cur.fetchone()[0]


@pytest.mark.parametrize("module", ["functions", "types_script_functions"])
def test_the_python_scripts_apply_the_schema_without_the_shell_script(indexer_env, monkeypatch, tmp_path, module):
    """`PGOPTIONS` from load_transactions.sh would hide a missing `options` in create_connection, so call it directly."""
    import importlib.util
    path = REPO / ("functions.py" if module == "functions" else "types_script/functions.py")
    spec = importlib.util.spec_from_file_location(f"legacy_{module}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.delenv("PGOPTIONS", raising=False)
    monkeypatch.chdir(tmp_path)                                  # no info.json here: the environment decides
    s = indexer_env
    args = ("wrong", "wrong", "wrong", "wrong", "1")             # info.json values; INDEXER_DB_* must win (D13)

    monkeypatch.setenv("INDEXER_DB_SCHEMA", "legacy")
    conn = mod.create_connection(*args)
    try:
        assert _search_path(conn) == "legacy"
    finally:
        conn.close()

    monkeypatch.delenv("INDEXER_DB_SCHEMA")                      # and with no schema set, the default is unchanged
    conn = mod.create_connection(*args)
    try:
        assert "legacy" not in _search_path(conn)
    finally:
        conn.close()

    (tmp_path / "info.json").write_text(json.dumps({"psql": {"db_schema": "from_info_json"}}))
    conn = mod.create_connection(*args)                          # info.json's db_schema is the fallback
    try:
        assert _search_path(conn) == "from_info_json"
    finally:
        conn.close()
    monkeypatch.setenv("INDEXER_DB_SCHEMA", "bad name")
    with pytest.raises(ValueError):
        mod.create_connection(*args)

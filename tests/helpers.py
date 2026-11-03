"""Shared helpers for the indexer test suite.

Tests that need PostgreSQL are skipped unless INDEXER_TEST_DB_NAME is set.
WARNING: those tests DROP and recreate the public schema of that database, so
point them at a throwaway database, never at real data. Connection settings:

    INDEXER_TEST_DB_NAME      (required to enable the database tests)
    INDEXER_TEST_DB_USER      (default: postgres)
    INDEXER_TEST_DB_PASSWORD  (default: empty)
    INDEXER_TEST_DB_HOST      (default: localhost)
    INDEXER_TEST_DB_PORT      (default: 5432)
"""
import contextlib
import copy
import io
import json
import os
import runpy
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"

# The scripts import 'functions' and 'address_load' from the repository root
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# Block 7027410 (migaloo-1) has three transactions:
#   tx 0: MsgExec   tx 1: MsgUpdateClient + MsgAcknowledgement   tx 2: MsgVote
BLOCK_HEIGHT = "7027410"
BLOCK_FILE = REPO / "test_blocks" / BLOCK_HEIGHT


def load_block():
    with open(BLOCK_FILE) as f:
        return json.load(f)


def load_decoded():
    """Decoded transactions for BLOCK_FILE, in block order (saved from the decode endpoint)."""
    with open(FIXTURES / "decoded" / f"{BLOCK_HEIGHT}.json") as f:
        return json.load(f)


def db_config():
    return {
        "db_name": os.getenv("INDEXER_TEST_DB_NAME", ""),
        "db_user": os.getenv("INDEXER_TEST_DB_USER", "postgres"),
        "db_password": os.getenv("INDEXER_TEST_DB_PASSWORD", ""),
        "db_host": os.getenv("INDEXER_TEST_DB_HOST", "localhost"),
        "db_port": os.getenv("INDEXER_TEST_DB_PORT", "5432"),
    }


requires_db = unittest.skipUnless(
    os.getenv("INDEXER_TEST_DB_NAME"),
    "set INDEXER_TEST_DB_NAME (and friends) to run the PostgreSQL tests",
)


def connect():
    import psycopg2
    c = db_config()
    return psycopg2.connect(
        dbname=c["db_name"], user=c["db_user"], password=c["db_password"],
        host=c["db_host"], port=c["db_port"],
    )


def reset_db():
    """Drop everything in the test database and recreate the tables from Txs.sql."""
    conn = connect()
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("SET client_min_messages TO WARNING")
        cur.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        cur.execute((REPO / "Txs.sql").read_text())
    conn.close()


def query(sql, params=()):
    conn = connect()
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall() if cur.description else None
    conn.commit()
    conn.close()
    return rows


def make_workdir(tmp, db=None):
    """Create a working directory laid out like the repository root.

    The scripts read info.json, type.json and types_script/ relative to the
    current directory, so tests run them from here with their own info.json.
    """
    tmp = Path(tmp)
    info = {"psql": db if db is not None else db_config()}
    (tmp / "info.json").write_text(json.dumps(info))
    for name in ("type.json", "types_script", "Txs.sql"):
        (tmp / name).symlink_to(REPO / name)
    (tmp / "log").mkdir()
    return tmp


def run_script_in_process(script, workdir, env, decoded_by_tx=None):
    """Run one of the pipeline scripts the way load_transactions.sh does.

    It runs in this process so decode_tx can be replaced with saved fixtures
    (no network). Returns (exit_code, stdout, stderr).
    """
    def fake_decode(tx, *args, **kwargs):
        return copy.deepcopy(decoded_by_tx[tx])

    out, err = io.StringIO(), io.StringIO()
    code = 0
    old_cwd = os.getcwd()
    os.chdir(workdir)
    try:
        with mock.patch.dict(os.environ, {k: v for k, v in os.environ.items() if not k.startswith("INDEXER_DB_")}, clear=True), \
                mock.patch.dict(os.environ, env), \
                mock.patch("functions.decode_tx", fake_decode), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                runpy.run_path(str(REPO / script), run_name="__main__")
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
            except Exception:
                import traceback
                traceback.print_exc()
                code = 1
    finally:
        os.chdir(old_cwd)
    return code, out.getvalue(), err.getvalue()


def run_script_subprocess(script, workdir, env):
    """Run a script as a separate process. Returns CompletedProcess."""
    # INDEXER_DB_* variables win over info.json (D13); these tests must use the info.json they wrote
    full_env = {k: v for k, v in os.environ.items() if not k.startswith("INDEXER_DB_")}
    full_env.update(env)
    return subprocess.run(
        [sys.executable, str(REPO / script)], cwd=workdir, env=full_env,
        capture_output=True, text=True, timeout=120,
    )


class BlockLoader:
    """Loads BLOCK_FILE into the test database with loading_files.py and loading_tx.py."""

    def __init__(self, workdir, block_path=BLOCK_FILE, decoded=None):
        self.workdir = Path(workdir)
        self.block_path = Path(block_path)
        self.block = json.loads(self.block_path.read_text())
        self.decoded = decoded if decoded is not None else load_decoded()
        txs = self.block["block"]["data"]["txs"]
        self.decoded_by_tx = dict(zip(txs, self.decoded))

    def env(self, index=None):
        env = {
            "FILE_PATH": str(self.block_path),
            "FILE_NAME": self.block_path.name,
            "txt": str(self.workdir / "log"),
        }
        if index is not None:
            env["x"] = str(index)
        return env

    def load_block_row(self):
        result = run_script_subprocess("loading_files.py", self.workdir, self.env())
        assert result.returncode == 0, result.stderr
        return result

    def load_tx(self, index):
        return run_script_in_process("loading_tx.py", self.workdir, self.env(index), self.decoded_by_tx)

    def verify_tx(self, index):
        return run_script_in_process("verify_tx.py", self.workdir, self.env(index), self.decoded_by_tx)

    def load_all(self):
        self.load_block_row()
        for i in range(len(self.decoded)):
            code, _, err = self.load_tx(i)
            assert code == 0, err


def messages_by_tx():
    """{tx_hash: sorted [(table, comment), ...]} across every message table."""
    tables = [r[0] for r in query(
        "SELECT table_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND column_name = 'tx_id' AND table_name <> 'transactions'"
    )]
    result = {}
    for (tx_hash,) in query("SELECT tx_hash FROM transactions"):
        result[tx_hash] = []
    for table in tables:
        for tx_hash, comment in query(
            f'SELECT t.tx_hash, m.comment FROM "{table}" m JOIN transactions t ON t.tx_id = m.tx_id'
        ):
            result[tx_hash].append((table, comment))
    return {k: sorted(v) for k, v in result.items()}

#!/usr/bin/env python3
"""Baseline benchmark: the single-threaded pipeline (fetch or read one block, write it, then the next).

This is the reference the final multi-threaded pipeline (tickets 07 to 10) is compared against.
It is a tool, not a test (D25): the live mode uses the network.

    python tools/bench_single_threaded.py --replay <replay cache> [--limit N] --reset
    python tools/bench_single_threaded.py --live N --from-height H --reset

`--reset` empties the indexer tables of the database named by INDEXER_DB_* first, so use a scratch database.
Prints one line of JSON per run. Each figure is blocks, transactions and messages per second.
"""
import argparse
import json
import platform
import subprocess
import sys
import time
from itertools import islice
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from indexer.config import SCHEMA, DbSettings  # noqa: E402
from indexer.db import connect  # noqa: E402
from indexer.sources.replay import ReplaySource  # noqa: E402
from indexer.sources.rest import RestSource  # noqa: E402
from indexer.writer import write_block  # noqa: E402


def reset(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT tablename FROM pg_tables WHERE schemaname = %s AND tablename <> 'alembic_version'",
                    (SCHEMA,))
        tables = [r[0] for r in cur.fetchall()]
        cur.execute("TRUNCATE " + ", ".join(f"{SCHEMA}.{t}" for t in tables) + " RESTART IDENTITY CASCADE")
    conn.commit()


def run(blocks, conn):
    """Write each block as it arrives, exactly as `python -m indexer run` does."""
    n = tx = msgs = 0
    start = time.perf_counter()
    for block in blocks:
        write_block(conn, block)
        n += 1
        tx += block.tx_num
        msgs += sum(len(t.messages) for t in block.transactions)
    seconds = time.perf_counter() - start
    return {"blocks": n, "transactions": tx, "messages": msgs, "seconds": round(seconds, 2),
            "blocks_per_s": round(n / seconds, 2), "tx_per_s": round(tx / seconds, 1),
            "msgs_per_s": round(msgs / seconds, 1)}


def main():
    ap = argparse.ArgumentParser()
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--replay", metavar="DIR")
    mode.add_argument("--live", type=int, metavar="N", help="fetch N blocks from the live nodes")
    ap.add_argument("--from-height", type=int)
    ap.add_argument("--limit", type=int, help="replay: only the first N blocks")
    ap.add_argument("--reset", action="store_true", required=True, help="empty the indexer tables first")
    args = ap.parse_args()

    s = DbSettings.from_env()
    conn = connect(s)
    reset(conn)
    if args.replay:
        blocks = ReplaySource(args.replay).blocks()
        if args.limit:
            blocks = islice(blocks, args.limit)
        label = f"replay:{args.replay}"
    else:
        if args.from_height is None:
            ap.error("--live needs --from-height")
        blocks = RestSource(args.from_height, args.from_height + args.live - 1).blocks()
        label = f"live from {args.from_height}"
    with conn.cursor() as cur:
        cur.execute("SELECT version()")
        pg = cur.fetchone()[0].split(",")[0]
    conn.rollback()
    result = run(blocks, conn)
    conn.close()
    repo = Path(__file__).parents[1]
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=repo).stdout.strip()
    if subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, cwd=repo).stdout.strip():
        commit += "-dirty"
    print(json.dumps({"pipeline": "single-threaded", "source": label, **result, "python": platform.python_version(),
                      "postgres": pg, "database": f"{s.host}:{s.port}/{s.name}", "git": commit}))


if __name__ == "__main__":
    main()

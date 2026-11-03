"""CLI entry point: python -m indexer run --source files:<dir>"""
import argparse
import logging
import os
import random
import sys

from .checkpoint import resolve_start
from .db import connect
from .errors import BadDataError, TransientError
from .sources.files import FilesSource
from .sources.replay import ReplaySource
from .sources.rest import RestSource
from .pipeline import Pipeline
from .verify import diff_block, pick_sample

log = logging.getLogger("indexer")

# Exit codes: 0 finished; 1 stopped by an error; 3 finished, but some blocks are in failed_blocks.
EXIT_OK, EXIT_ERROR, EXIT_FAILED_BLOCKS = 0, 1, 3


def build_source(spec: str, from_height=None, to_height=None, record=None):
    kind, _, arg = spec.partition(":")
    if kind == "files" and arg:
        return FilesSource(arg)
    if kind == "replay" and arg:
        return ReplaySource(arg, from_height=from_height)
    if spec == "rest":
        return RestSource(from_height, to_height, record=record)
    raise SystemExit(f"unknown --source {spec!r} (expected files:<dir>, replay:<dir> or rest)")


def cmd_run(args) -> int:
    source = build_source(args.source, args.from_height, args.to_height, args.record)
    try:
        if isinstance(source, RestSource):
            conn = connect()
            try:
                source.from_height = resolve_start(conn, source.chain_id, args.from_height)
            finally:
                conn.close()
            if source.from_height is None:
                raise SystemExit("--source rest needs --from-height when nothing has been indexed yet")
        stats = Pipeline(source, workers=args.workers).run()
    except TransientError as exc:
        log.error("giving up: %s", exc)
        return 1
    except BadDataError as exc:          # not tied to a height (e.g. a file that is not a block)
        log.error("bad data: %s", exc)
        return 1
    skipped = getattr(source, "skipped", [])
    log.info("done: %d blocks indexed, %d failed, %d already stored, %d without decoded transactions",
             stats.stored, stats.failed, stats.skipped, len(skipped))
    return EXIT_FAILED_BLOCKS if stats.failed else EXIT_OK


def cmd_verify(args) -> int:
    source_spec = args.source or (f"replay:{os.environ['INDEXER_REPLAY_DIR']}" if os.environ.get("INDEXER_REPLAY_DIR") else None)
    if source_spec is None:
        raise SystemExit("verify needs --source (or INDEXER_REPLAY_DIR)")
    source = build_source(source_spec)
    if not hasattr(source, "fetch"):
        raise SystemExit("verify supports replay:<dir> and rest sources")
    seed = args.seed if args.seed is not None else random.SystemRandom().randrange(2 ** 32)
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT chain_id, height FROM blocks")
            stored = cur.fetchall()
        conn.rollback()
        sample = pick_sample(stored, args.sample, seed)
        print(f"verify: seed {seed}, {len(sample)} of {len(stored)} stored blocks")
        differences = []
        for chain_id, height in sample:
            differences += diff_block(conn, source.fetch(chain_id, height))
    finally:
        conn.close()
    for d in differences:
        print(d)
    print(f"verify: {len(differences)} difference(s)")
    return 1 if differences else EXIT_OK


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m indexer")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="index blocks from a source")
    run.add_argument("--source", required=True, help="files:<dir>, replay:<dir> or rest")
    run.add_argument("--from-height", type=int, default=None, help="first height (replay: skip lower ones)")
    run.add_argument("--to-height", type=int, default=None, help="last height for --source rest (default: the head)")
    run.add_argument("--workers", type=int, default=1, help="worker threads (default 1)")
    run.add_argument("--record", default=None, metavar="DIR",
                     help="with --source rest: save every response into this replay cache")
    verify = sub.add_parser("verify", help="compare a random sample of stored blocks with the source")
    verify.add_argument("--sample", type=int, required=True, help="how many stored blocks to check")
    verify.add_argument("--seed", type=int, default=None, help="random seed (printed, so a run can be repeated)")
    verify.add_argument("--source", default=None, help="replay:<dir> or rest (default: replay:$INDEXER_REPLAY_DIR)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.command == "run":
        return cmd_run(args)
    if args.command == "verify":
        return cmd_verify(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())

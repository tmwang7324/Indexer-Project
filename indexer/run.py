"""CLI entry point: python -m indexer run --source files:<dir>"""
import argparse
import logging
import sys

from .db import connect
from .errors import BadDataError, TransientError
from .sources.files import FilesSource
from .sources.replay import ReplaySource
from .sources.rest import RestSource
from .writer import write_block

log = logging.getLogger("indexer")


def build_source(spec: str, from_height=None, to_height=None, record=None, prefetch=1):
    kind, _, arg = spec.partition(":")
    if kind == "files" and arg:
        return FilesSource(arg)
    if kind == "replay" and arg:
        return ReplaySource(arg, from_height=from_height)
    if spec == "rest":
        if from_height is None:
            raise SystemExit("--source rest needs --from-height")
        return RestSource(from_height, to_height, record=record, prefetch=prefetch)
    raise SystemExit(f"unknown --source {spec!r} (expected files:<dir>, replay:<dir> or rest)")


def cmd_run(args) -> int:
    source = build_source(args.source, args.from_height, args.to_height, args.record, args.prefetch)
    conn = connect()
    written = 0
    try:
        for block in source.blocks():
            write_block(conn, block)
            written += 1
            log.info("indexed %s block %s (%d transactions)", block.chain_id, block.height, block.tx_num)
    except BadDataError as exc:
        log.error("bad data: %s", exc)
        return 1
    except TransientError as exc:
        log.error("giving up: %s", exc)
        return 1
    finally:
        conn.close()
    skipped = getattr(source, "skipped", [])
    log.info("done: %d blocks indexed, %d skipped", written, len(skipped))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m indexer")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="index blocks from a source")
    run.add_argument("--source", required=True, help="files:<dir>, replay:<dir> or rest")
    run.add_argument("--from-height", type=int, default=None, help="first height (replay: skip lower ones)")
    run.add_argument("--to-height", type=int, default=None, help="last height for --source rest (default: the head)")
    run.add_argument("--record", default=None, metavar="DIR",
                     help="with --source rest: save every response into this replay cache")
    run.add_argument("--prefetch", type=int, default=4, metavar="N",
                     help="with --source rest: fetch up to N blocks at once, written in height order (default 4)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.command == "run":
        return cmd_run(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())

"""CLI entry point: python -m indexer run --source files:<dir>"""
import argparse
import logging
import sys

from .db import connect
from .errors import BadDataError
from .sources.files import FilesSource
from .writer import write_block

log = logging.getLogger("indexer")


def build_source(spec: str):
    kind, _, arg = spec.partition(":")
    if kind == "files" and arg:
        return FilesSource(arg)
    raise SystemExit(f"unknown --source {spec!r} (expected files:<dir>)")


def cmd_run(args) -> int:
    source = build_source(args.source)
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
    finally:
        conn.close()
    skipped = getattr(source, "skipped", [])
    log.info("done: %d blocks indexed, %d skipped", written, len(skipped))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m indexer")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="index blocks from a source")
    run.add_argument("--source", required=True, help="files:<dir>")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.command == "run":
        return cmd_run(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())

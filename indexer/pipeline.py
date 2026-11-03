"""The run loop: take heights from a source, load each block, write it, record the ones that fail."""
import logging
from dataclasses import dataclass, field

from .checkpoint import read_checkpoint
from .errors import BadDataError
from .writer import Hooks, record_failure, write_block

log = logging.getLogger(__name__)


@dataclass
class RunStats:
    stored: int = 0
    skipped: int = 0           # already stored (or below the checkpoint): not fetched again
    failed: int = 0
    failures: list = field(default_factory=list)      # [(chain_id, height, error)]


def already_stored(conn, chain_id: str, height: int) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM blocks WHERE chain_id = %s AND height = %s", (chain_id, height))
        found = cur.fetchone() is not None
    conn.rollback()
    return found


def run_items(items, conn, registry=None, hooks: Hooks = None) -> RunStats:
    """Write each item's block in its own transaction, in the order given.

    - Heights at or below the chain's checkpoint, and heights that already have a `blocks` row, are skipped
      without fetching (re-writing would be harmless, but slow).
    - The first height of a chain in this run fixes the checkpoint's starting point (`base`).
    - A block with bad data (including a count mismatch) is rolled back and recorded in failed_blocks; the
      next block is still indexed (D14).
    """
    stats = RunStats()
    checkpoints, bases = {}, {}
    for item in items:
        if item.chain_id not in checkpoints:
            checkpoints[item.chain_id] = read_checkpoint(conn, item.chain_id)
            bases[item.chain_id] = item.height - 1
        done = checkpoints[item.chain_id]
        if (done is not None and item.height <= done) or already_stored(conn, item.chain_id, item.height):
            stats.skipped += 1
            continue
        try:
            block = item.load()
            write_block(conn, block, registry, base=bases[item.chain_id], hooks=hooks)
        except BadDataError as exc:
            log.error("block %s/%s failed: %s", item.chain_id, item.height, exc)
            record_failure(conn, item.chain_id, item.height, str(exc))
            stats.failed += 1
            stats.failures.append((item.chain_id, item.height, str(exc)))
            continue
        stats.stored += 1
        log.info("indexed %s block %s (%d transactions)", block.chain_id, block.height, block.tx_num)
    return stats

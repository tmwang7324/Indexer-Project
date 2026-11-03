"""The run loop: take heights from a source, load each block, write it, record the ones that fail."""
import logging
from dataclasses import dataclass, field

from .errors import BadDataError
from .writer import record_failure, write_block

log = logging.getLogger(__name__)


@dataclass
class RunStats:
    stored: int = 0
    failed: int = 0
    failures: list = field(default_factory=list)      # [(chain_id, height, error)]


def run_items(items, conn, registry=None) -> RunStats:
    """Write each item's block in its own transaction. A block with bad data (including a count mismatch)
    is rolled back and recorded in failed_blocks; the next block is still indexed (D14)."""
    stats = RunStats()
    for item in items:
        try:
            block = item.load()
            write_block(conn, block, registry)
        except BadDataError as exc:
            log.error("block %s/%s failed: %s", item.chain_id, item.height, exc)
            record_failure(conn, item.chain_id, item.height, str(exc))
            stats.failed += 1
            stats.failures.append((item.chain_id, item.height, str(exc)))
            continue
        stats.stored += 1
        log.info("indexed %s block %s (%d transactions)", block.chain_id, block.height, block.tx_num)
    return stats

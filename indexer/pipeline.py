"""The run: N worker threads take heights from one source, fetch and parse each block, and write it in its own
database transaction (D7). Blocks finish out of order; the checkpoint (checkpoint.py) is what stays contiguous.
"""
import logging
import threading
from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from typing import Optional

from .db import ConnectionPool
from .errors import BadDataError
from .handlers import get_registry
from .writer import Hooks, record_failure, write_block

log = logging.getLogger(__name__)

THREAD_PREFIX = "indexer-worker"


@dataclass
class RunStats:
    stored: int = 0
    skipped: int = 0           # already stored (or below the checkpoint): not fetched again
    failed: int = 0
    failures: list = field(default_factory=list)      # [(chain_id, height, error)]


class _Producer:
    """Hands out the source's items one at a time, in the source's order, to whichever worker asks."""

    def __init__(self, items):
        self._items = iter(items)
        self._lock = threading.Lock()
        self._bases = {}

    def next(self):
        """(item, base) or None when the source is exhausted. `base` is the height just below the first
        height of the item's chain in this run: it is where a new checkpoint starts."""
        with self._lock:
            item = next(self._items, None)
            if item is None:
                return None
            base = self._bases.setdefault(item.chain_id, item.height - 1)
            return item, base


class Pipeline:
    def __init__(self, source, *, workers: int = 1, settings=None, registry=None, hooks: Optional[Hooks] = None,
                 stop: Optional[threading.Event] = None):
        self.source, self.workers = source, max(1, workers)
        self.settings, self.registry, self.hooks = settings, registry or get_registry(), hooks
        self.stop = stop or threading.Event()
        self.stats = RunStats()
        self.pool: Optional[ConnectionPool] = None
        self._stats_lock = threading.Lock()

    # --- the run -------------------------------------------------------------------------------
    def run(self) -> RunStats:
        self.pool = ConnectionPool(self.workers, self.settings)
        producer = _Producer(self.source.items(self.stop))
        try:
            with ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix=THREAD_PREFIX) as executor:
                futures = [executor.submit(self._worker, producer) for _ in range(self.workers)]
                wait(futures, return_when=FIRST_EXCEPTION)
                self.stop.set()                      # an error anywhere: no new heights, in-flight blocks finish
                wait(futures)
            for future in futures:                   # re-raise the first error, now that every thread has ended
                if future.exception() is not None:
                    raise future.exception()
        finally:
            self.pool.closeall()
        return self.stats

    def _worker(self, producer: _Producer) -> None:
        while not self.stop.is_set():
            got = producer.next()
            if got is None:
                return
            self._process(*got)

    # --- one block -----------------------------------------------------------------------------
    def _borrowed(self):
        """`with self._borrowed() as conn:` borrows a connection and always returns it."""
        pool = self.pool

        class _Lease:
            def __enter__(self_):
                self_.conn = pool.getconn()
                return self_.conn

            def __exit__(self_, exc_type, exc, tb):
                pool.putconn(self_.conn, broken=False)
                return False
        return _Lease()

    def _is_done(self, chain_id: str, height: int) -> bool:
        """Already stored, or at or below the chain's checkpoint: nothing to fetch."""
        with self._borrowed() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT EXISTS (SELECT 1 FROM blocks WHERE chain_id = %s AND height = %s),
                              COALESCE((SELECT contiguous_height FROM checkpoints WHERE chain_id = %s), -1)""",
                    (chain_id, height, chain_id))
                stored, checkpoint = cur.fetchone()
            conn.rollback()
        return stored or height <= checkpoint

    def _count(self, **deltas) -> None:
        with self._stats_lock:
            for name, n in deltas.items():
                setattr(self.stats, name, getattr(self.stats, name) + n)

    def _process(self, item, base: int) -> None:
        if self._is_done(item.chain_id, item.height):
            self._count(skipped=1)
            return
        try:
            block = item.load()                      # no database connection is held while fetching
            with self._borrowed() as conn:
                write_block(conn, block, self.registry, base=base, hooks=self.hooks)
        except BadDataError as exc:
            log.error("block %s/%s failed: %s", item.chain_id, item.height, exc)
            with self._borrowed() as conn:
                record_failure(conn, item.chain_id, item.height, str(exc))
            with self._stats_lock:
                self.stats.failed += 1
                self.stats.failures.append((item.chain_id, item.height, str(exc)))
            return
        self._count(stored=1)
        log.info("indexed %s block %s (%d transactions)", block.chain_id, block.height, block.tx_num)

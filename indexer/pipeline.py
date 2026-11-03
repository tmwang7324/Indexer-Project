"""The run: N worker threads take heights from one source, fetch and parse each block, and write it in its own
database transaction (D7). Blocks finish out of order; the checkpoint (checkpoint.py) is what stays contiguous.
"""
import logging
import threading
from contextlib import contextmanager
from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from typing import Optional

from .db import ConnectionPool
from .errors import BadDataError, OutageError
from .handlers import get_registry
from .retry import RetriesExhausted, Stopped, call_with_retries, is_broken_connection
from .writer import Hooks, record_failure, write_block

log = logging.getLogger(__name__)

THREAD_PREFIX = "indexer-worker"


@dataclass
class RunStats:
    stored: int = 0
    skipped: int = 0           # already stored (or below the checkpoint): not fetched again
    failed: int = 0
    retries: int = 0           # transient errors that were retried
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
                 stop: Optional[threading.Event] = None, max_attempts: int = 5, retry_delay: float = 1.0,
                 max_giveups_in_a_row: int = 10):
        self.source, self.workers = source, max(1, workers)
        self.max_attempts, self.retry_delay = max_attempts, retry_delay
        self.max_giveups_in_a_row, self._giveups = max_giveups_in_a_row, 0
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
        try:
            while not self.stop.is_set():
                got = producer.next()
                if got is None:
                    return
                self._process(*got)
        except BaseException:
            self.stop.set()              # no new heights for anyone; blocks already in flight finish or roll back
            raise

    # --- one block -----------------------------------------------------------------------------
    @contextmanager
    def _borrowed(self):
        """`with self._borrowed() as conn:` borrows a connection and always returns it; a connection that broke
        is closed, not pooled."""
        conn = self.pool.getconn()
        broken = False
        try:
            yield conn
        except BaseException as exc:
            broken = is_broken_connection(exc)
            raise
        finally:
            self.pool.putconn(conn, broken=broken)

    def _is_done(self, conn, chain_id: str, height: int) -> bool:
        """Already stored, or at or below the chain's checkpoint: nothing to fetch."""
        with conn.cursor() as cur:
            cur.execute(
                """SELECT EXISTS (SELECT 1 FROM blocks WHERE chain_id = %s AND height = %s),
                          COALESCE((SELECT contiguous_height FROM checkpoints WHERE chain_id = %s), -1)""",
                (chain_id, height, chain_id))
            stored, checkpoint = cur.fetchone()
        conn.rollback()
        return stored or height <= checkpoint

    def _retrying(self, fn):
        def on_retry(attempt, exc):
            log.warning("transient error (attempt %d of %d): %s: %s; retrying", attempt, self.max_attempts,
                        exc.__class__.__name__, exc)
            with self._stats_lock:
                self.stats.retries += 1
        return call_with_retries(fn, max_attempts=self.max_attempts, delay=self.retry_delay,
                                 sleep=self.stop.wait, on_retry=on_retry)

    def _attempt(self, item, base: int):
        """One try at a block. Returns the Block, or None when it was already stored."""
        with self._borrowed() as conn:
            if self._is_done(conn, item.chain_id, item.height):
                return None
        block = item.load()                          # no database connection is held while fetching
        with self._borrowed() as conn:
            write_block(conn, block, self.registry, base=base, hooks=self.hooks)
        return block

    def _record_failure(self, item, error: str, attempts: int) -> None:
        def record():
            with self._borrowed() as conn:
                record_failure(conn, item.chain_id, item.height, error, attempts)
        self._retrying(record)
        with self._stats_lock:
            self.stats.failed += 1
            self.stats.failures.append((item.chain_id, item.height, error))

    def _process(self, item, base: int) -> None:
        try:
            block = self._retrying(lambda: self._attempt(item, base))
        except Stopped:
            return                                   # told to stop while waiting to retry: leave the block for a restart
        except BadDataError as exc:
            log.error("block %s/%s has bad data: %s", item.chain_id, item.height, exc)
            self._record_failure(item, str(exc), attempts=1)
            return
        except RetriesExhausted as exc:
            log.error("block %s/%s given up after %d attempts: %s", item.chain_id, item.height, exc.attempts, exc)
            self._record_failure(item, f"gave up after {exc.attempts} attempts: {exc}", attempts=exc.attempts)
            with self._stats_lock:
                self._giveups += 1
                outage = self._giveups >= self.max_giveups_in_a_row
            if outage:
                raise OutageError(f"{self._giveups} blocks in a row were given up on after repeated transient "
                                  f"errors (last: {item.chain_id}/{item.height}: {exc}); stopping") from exc
            return
        except Exception:
            log.exception("unexpected error at block %s/%s: stopping the run", item.chain_id, item.height)
            raise
        if block is None:
            self._count(skipped=1)
            return
        with self._stats_lock:
            self._giveups = 0
        self._count(stored=1)
        log.info("indexed %s block %s (%d transactions)", block.chain_id, block.height, block.tx_num)

    def _count(self, **deltas) -> None:
        with self._stats_lock:
            for name, n in deltas.items():
                setattr(self.stats, name, getattr(self.stats, name) + n)

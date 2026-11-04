"""PostgreSQL connections. Everything lives in the `indexer` schema (D9)."""
import threading

import psycopg2
from psycopg2.pool import ThreadedConnectionPool

from .config import SCHEMA, DbSettings

# Statement timeout is generous but finite so a stuck query cannot hang a run (D21).
STATEMENT_TIMEOUT_MS = 60000


def _kwargs(s: DbSettings) -> dict:
    return dict(host=s.host, port=s.port, dbname=s.name, user=s.user, password=s.password,
                options=f"-c search_path={SCHEMA} -c statement_timeout={STATEMENT_TIMEOUT_MS}",
                application_name="indexer", connect_timeout=10)


def connect(settings: DbSettings | None = None):
    """Open a connection whose search_path is the indexer schema."""
    return psycopg2.connect(**_kwargs(settings or DbSettings.from_env()))


class ConnectionPool:
    """A thread-safe pool sized to the number of workers (D7). Each block borrows one connection for its
    transaction and returns it in a `finally`; a connection that broke is closed, never reused."""

    def __init__(self, size: int, settings: DbSettings | None = None):
        self.size = size
        # minconn == maxconn: psycopg2 closes a returned connection when more than `minconn` are idle, so a
        # smaller minimum made every worker but one reconnect for nearly every block (found by the benchmark).
        self._pool = ThreadedConnectionPool(size, size, **_kwargs(settings or DbSettings.from_env()))
        self._lock = threading.Lock()
        self._borrowed = 0
        self.discarded = 0              # connections closed instead of pooled because they broke

    @property
    def in_use(self) -> int:
        """Connections borrowed and not yet returned (the invariant checker wants 0 after a run)."""
        with self._lock:
            return self._borrowed

    def getconn(self):
        conn = self._pool.getconn()
        with self._lock:
            self._borrowed += 1
        return conn

    def putconn(self, conn, broken: bool = False) -> None:
        """Return a connection. `broken` (or an already closed one) is closed instead of pooled."""
        close = True
        try:
            if not broken and not conn.closed:
                try:
                    conn.rollback()       # never hand a half-finished transaction to the next block
                except psycopg2.Error:
                    broken = True
            close = broken or bool(conn.closed)
            self._pool.putconn(conn, close=close)
        finally:
            with self._lock:
                self._borrowed -= 1
                if close:
                    self.discarded += 1

    def closeall(self) -> None:
        self._pool.closeall()

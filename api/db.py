"""A small read-only connection pool; blocking queries run in a worker thread."""
import threading
from contextlib import contextmanager

from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool
from starlette.concurrency import run_in_threadpool

from indexer.config import SCHEMA, DbSettings

_pool = None
_lock = threading.Lock()


def get_pool() -> ThreadedConnectionPool:
    global _pool
    with _lock:
        if _pool is None:
            s = DbSettings.from_env()
            _pool = ThreadedConnectionPool(
                1, 8, host=s.host, port=s.port, dbname=s.name, user=s.user, password=s.password,
                options=f"-c search_path={SCHEMA} -c TimeZone=UTC -c statement_timeout=15000 "
                        f"-c default_transaction_read_only=on",
            )
        return _pool


def close_pool() -> None:
    global _pool
    with _lock:
        if _pool is not None:
            _pool.closeall()
            _pool = None


@contextmanager
def _cursor():
    pool = get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            yield cur
        conn.rollback()  # read-only: end the transaction without keeping anything
        pool.putconn(conn)
    except BaseException:
        pool.putconn(conn, close=True)
        raise


def _fetch(sql, params):
    with _cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


async def fetch(sql: str, params=()) -> list:
    return await run_in_threadpool(_fetch, sql, params)


async def fetch_one(sql: str, params=()):
    rows = await fetch(sql, params)
    return rows[0] if rows else None

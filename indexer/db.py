"""PostgreSQL connections. Everything lives in the `indexer` schema (D9)."""
import psycopg2

from .config import SCHEMA, DbSettings


def connect(settings: DbSettings | None = None):
    """Open a connection whose search_path is the indexer schema.

    Statement timeout is generous but finite so a stuck query cannot hang a run (D21).
    """
    s = settings or DbSettings.from_env()
    return psycopg2.connect(
        host=s.host,
        port=s.port,
        dbname=s.name,
        user=s.user,
        password=s.password,
        options=f"-c search_path={SCHEMA} -c statement_timeout=60000",
    )

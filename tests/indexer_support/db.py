"""Test database helpers: settings, reachability, migrations, cleanup (D19, D20)."""
import os
import subprocess
import sys
from pathlib import Path

import psycopg2

from indexer.config import SCHEMA, DbSettings

REPO = Path(__file__).resolve().parents[2]


def db_test_settings() -> DbSettings:
    """The postgres-test service of docker-compose.yml, unless INDEXER_TEST_DB_* say otherwise."""
    env = os.environ
    return DbSettings(
        host=env.get("INDEXER_TEST_DB_HOST", "127.0.0.1"),
        port=int(env.get("INDEXER_TEST_DB_PORT", "5433")),
        name=env.get("INDEXER_TEST_DB_NAME", "indexer_test"),
        user=env.get("INDEXER_TEST_DB_USER", "indexer"),
        password=env.get("INDEXER_TEST_DB_PASSWORD", "indexer"),
    )




def child_env(settings: DbSettings, **extra) -> dict:
    """Environment for a subprocess that must talk to the test database."""
    env = dict(os.environ)
    env.update(settings.as_env())
    env["PYTHONPATH"] = str(REPO) + os.pathsep + env.get("PYTHONPATH", "")
    env.update(extra)
    return env


def run_alembic(settings: DbSettings, *args: str) -> None:
    subprocess.run([sys.executable, "-m", "alembic", *args], cwd=REPO, env=child_env(settings),
                   check=True, capture_output=True, text=True)


def truncate_all(settings: DbSettings) -> None:
    """Empty every table of the indexer schema except alembic_version (D20)."""
    conn = psycopg2.connect(host=settings.host, port=settings.port, dbname=settings.name,
                            user=settings.user, password=settings.password)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT tablename FROM pg_tables WHERE schemaname = %s AND tablename <> 'alembic_version'",
                        (SCHEMA,))
            tables = [r[0] for r in cur.fetchall()]
            if tables:
                cur.execute("TRUNCATE " + ", ".join(f"{SCHEMA}.{t}" for t in tables) + " RESTART IDENTITY CASCADE")
        conn.commit()
    finally:
        conn.close()

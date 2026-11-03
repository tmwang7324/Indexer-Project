"""Fixtures for the new indexer's tests.

Database-backed layers FAIL (not skip) when the test database is unreachable (D19).
"""
import json
from pathlib import Path

import psycopg2
import pytest

from indexer.db import connect
from indexer_support import db as dbtools

HERE = Path(__file__).parent
REPO = HERE.parents[1]
DATA = HERE / "data"


@pytest.fixture(scope="session")
def db_settings():
    return dbtools.db_test_settings()


@pytest.fixture(scope="session")
def migrated_db(db_settings):
    """alembic upgrade head, once per test run. Fails loudly if postgres-test is down."""
    s = db_settings
    try:
        psycopg2.connect(host=s.host, port=s.port, dbname=s.name, user=s.user, password=s.password,
                         connect_timeout=5).close()
    except psycopg2.OperationalError as exc:
        pytest.fail(f"test database not reachable at {s.host}:{s.port}/{s.name} "
                    f"(start it with `docker compose up -d postgres-test`): {exc}", pytrace=False)
    dbtools.run_alembic(s, "upgrade", "head")
    return s


@pytest.fixture
def conn(migrated_db):
    """Component tests: everything the test does is rolled back (D20). Code under test never commits."""
    c = connect(migrated_db)
    try:
        yield c
    finally:
        c.rollback()
        c.close()


@pytest.fixture
def clean_db(migrated_db):
    """Integration tests: commits are real, so truncate afterwards (D20)."""
    dbtools.truncate_all(migrated_db)
    yield migrated_db
    dbtools.truncate_all(migrated_db)


@pytest.fixture
def indexer_env(clean_db, monkeypatch):
    """A clean test database, and the INDEXER_DB_* variables pointing `python -m indexer` at it."""
    for key, value in clean_db.as_env().items():
        monkeypatch.setenv(key, value)
    return clean_db


def load_json(path):
    return json.loads(Path(path).read_text())

"""C1: the migrations apply from empty, downgrade to empty and apply again (D17)."""
import psycopg2

from indexer_support import db as dbtools


def _tables(s):
    conn = psycopg2.connect(host=s.host, port=s.port, dbname=s.name, user=s.user, password=s.password)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'indexer' "
                        "AND tablename <> 'alembic_version' ORDER BY 1")
            return [r[0] for r in cur.fetchall()]
    finally:
        conn.close()


def test_upgrade_downgrade_upgrade(migrated_db):
    dbtools.run_alembic(migrated_db, "downgrade", "base")
    assert _tables(migrated_db) == []
    dbtools.run_alembic(migrated_db, "upgrade", "head")
    first = _tables(migrated_db)
    assert {"blocks", "transactions", "messages", "checkpoints"} <= set(first)

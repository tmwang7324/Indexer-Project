"""Alembic environment: hand-written SQL migrations, no SQLAlchemy models (D17)."""
from alembic import context
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

from indexer.config import SCHEMA, DbSettings

config = context.config


def _url() -> URL:
    s = DbSettings.from_env()
    return URL.create("postgresql+psycopg2", username=s.user, password=s.password,
                      host=s.host, port=s.port, database=s.name)


def run_migrations_online() -> None:
    engine = create_engine(_url())
    with engine.connect() as connection:
        # The version table lives in the indexer schema, so create it first.
        connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))
        connection.commit()
        context.configure(connection=connection, target_metadata=None, version_table_schema=SCHEMA)
        with context.begin_transaction():
            context.run_migrations()
        connection.commit()
    engine.dispose()


run_migrations_online()

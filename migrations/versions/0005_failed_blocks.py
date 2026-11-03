"""failed_blocks

Revision ID: 0005
Revises: 0004

A block that cannot be indexed (bad data, or a transient error that outlasted its retries) is recorded
here instead of stopping the run (D14, D21). The row is deleted in the same transaction as the block
when a later attempt succeeds, so a height is never both stored and failed.
"""
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE indexer.failed_blocks (
        chain_id    TEXT        NOT NULL,
        height      BIGINT      NOT NULL,
        error       TEXT        NOT NULL,
        attempts    INTEGER     NOT NULL DEFAULT 1,
        last_tried  TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (chain_id, height)
    )""")


def downgrade() -> None:
    op.execute("DROP TABLE indexer.failed_blocks")

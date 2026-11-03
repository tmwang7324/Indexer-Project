"""blocks, transactions, messages, checkpoints

Revision ID: 0001
Revises:

Numbers are BIGINT/NUMERIC, never text (REVAMP.md 5.4). Block time is stored as
timestamptz, which has microsecond precision (the node reports nanoseconds).
"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE indexer.blocks (
        block_id    BIGSERIAL PRIMARY KEY,
        chain_id    TEXT        NOT NULL,
        height      BIGINT      NOT NULL,
        block_hash  TEXT        NOT NULL,
        tx_num      INTEGER     NOT NULL,
        created_at  TIMESTAMPTZ NOT NULL,
        UNIQUE (chain_id, height)
    )""")
    op.execute("""
    CREATE TABLE indexer.transactions (
        tx_id       BIGSERIAL PRIMARY KEY,
        block_id    BIGINT      NOT NULL REFERENCES indexer.blocks (block_id) ON DELETE CASCADE,
        chain_id    TEXT        NOT NULL,
        height      BIGINT      NOT NULL,
        tx_index    INTEGER     NOT NULL,
        tx_hash     TEXT        NOT NULL,
        memo        TEXT        NOT NULL DEFAULT '',
        gas_limit   BIGINT,
        created_at  TIMESTAMPTZ NOT NULL,
        tx_info     JSONB       NOT NULL,
        UNIQUE (chain_id, tx_hash),
        UNIQUE (block_id, tx_index)
    )""")
    op.execute("""
    CREATE TABLE indexer.messages (
        message_id  BIGSERIAL PRIMARY KEY,
        tx_id       BIGINT  NOT NULL REFERENCES indexer.transactions (tx_id) ON DELETE CASCADE,
        msg_index   INTEGER NOT NULL,
        type        TEXT    NOT NULL,
        raw         JSONB   NOT NULL,
        UNIQUE (tx_id, msg_index)
    )""")
    op.execute("CREATE INDEX messages_type_idx ON indexer.messages (type)")
    # Table only: filled by the checkpoint ticket.
    op.execute("""
    CREATE TABLE indexer.checkpoints (
        chain_id           TEXT PRIMARY KEY,
        contiguous_height  BIGINT      NOT NULL,
        updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
    )""")


def downgrade() -> None:
    op.execute("DROP TABLE indexer.checkpoints")
    op.execute("DROP TABLE indexer.messages")
    op.execute("DROP TABLE indexer.transactions")
    op.execute("DROP TABLE indexer.blocks")

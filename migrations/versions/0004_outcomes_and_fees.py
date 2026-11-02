"""transaction outcomes, events and fee coins

Revision ID: 0004
Revises: 0003

A transaction's outcome comes from /block_results (D4). The columns are NULL for transactions whose
source has no outcome (the Migaloo files). Every fee coin is stored in transaction_fees, with the
amount as NUMERIC because it can exceed 64 bits.
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE indexer.transactions
        ADD COLUMN code       INTEGER,
        ADD COLUMN codespace  TEXT,
        ADD COLUMN gas_wanted BIGINT,
        ADD COLUMN gas_used   BIGINT,
        ADD COLUMN log        TEXT,
        ADD COLUMN events     JSONB""")
    op.execute("""
    CREATE TABLE indexer.transaction_fees (
        tx_id       BIGINT  NOT NULL REFERENCES indexer.transactions (tx_id) ON DELETE CASCADE,
        coin_index  INTEGER NOT NULL,
        denom       TEXT    NOT NULL,
        amount      NUMERIC NOT NULL,
        PRIMARY KEY (tx_id, coin_index)
    )""")
    # Transactions stored before this migration keep their fee coins.
    op.execute("""
    INSERT INTO indexer.transaction_fees (tx_id, coin_index, denom, amount)
    SELECT t.tx_id, c.ordinality - 1, c.coin ->> 'denom', (c.coin ->> 'amount')::numeric
    FROM indexer.transactions t,
         LATERAL jsonb_array_elements(COALESCE(t.tx_info -> 'auth_info' -> 'fee' -> 'amount', '[]'::jsonb))
             WITH ORDINALITY AS c(coin, ordinality)""")


def downgrade() -> None:
    op.execute("DROP TABLE indexer.transaction_fees")
    op.execute("""
    ALTER TABLE indexer.transactions
        DROP COLUMN code, DROP COLUMN codespace, DROP COLUMN gas_wanted,
        DROP COLUMN gas_used, DROP COLUMN log, DROP COLUMN events""")

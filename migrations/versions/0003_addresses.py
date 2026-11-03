"""addresses and message_addresses

Revision ID: 0003
Revises: 0002

`address` holds each address once. `message_addresses` links a message to every address it
mentions, with the role the address plays in it, so "everything involving address X" is one
indexed lookup (D2). created_at is TIMESTAMPTZ, so it is an absolute UTC instant.
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE indexer.address (
        address_id    BIGSERIAL PRIMARY KEY,
        value         TEXT        NOT NULL UNIQUE,
        address_type  TEXT        NOT NULL,
        created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
    )""")
    op.execute("""
    CREATE TABLE indexer.message_addresses (
        message_id  BIGINT NOT NULL REFERENCES indexer.messages (message_id) ON DELETE CASCADE,
        address_id  BIGINT NOT NULL REFERENCES indexer.address (address_id),
        role        TEXT   NOT NULL,
        PRIMARY KEY (message_id, address_id, role)
    )""")
    op.execute("CREATE INDEX message_addresses_address_idx ON indexer.message_addresses (address_id, message_id)")


def downgrade() -> None:
    op.execute("DROP TABLE indexer.message_addresses")
    op.execute("DROP TABLE indexer.address")

"""Writer: one database transaction per block (D14, D20).

Every `insert_*` function takes a cursor and NEVER commits, so a component test can
wrap it in a transaction it rolls back. Only `write_block` controls BEGIN/COMMIT.
Inserts use ON CONFLICT DO NOTHING, then look the existing row up when no row comes back.
"""
import logging

from psycopg2.extras import Json

from .models import Block, Message, Transaction

log = logging.getLogger(__name__)


def _insert_or_lookup(cur, insert_sql: str, params, lookup_sql: str, lookup_params) -> int:
    """INSERT ... ON CONFLICT DO NOTHING RETURNING id; on conflict RETURNING gives no row."""
    cur.execute(insert_sql, params)
    row = cur.fetchone()
    if row is None:
        cur.execute(lookup_sql, lookup_params)
        row = cur.fetchone()
    return row[0]


def insert_block(cur, block: Block) -> int:
    return _insert_or_lookup(
        cur,
        """INSERT INTO blocks (chain_id, height, block_hash, tx_num, created_at)
           VALUES (%s, %s, %s, %s, %s)
           ON CONFLICT DO NOTHING RETURNING block_id""",
        (block.chain_id, block.height, block.hash, block.tx_num, block.time),
        "SELECT block_id FROM blocks WHERE chain_id = %s AND height = %s",
        (block.chain_id, block.height),
    )


def insert_transaction(cur, block_id: int, block: Block, tx: Transaction) -> int:
    return _insert_or_lookup(
        cur,
        """INSERT INTO transactions
               (block_id, chain_id, height, tx_index, tx_hash, memo, gas_limit, created_at, tx_info)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT DO NOTHING RETURNING tx_id""",
        (block_id, block.chain_id, block.height, tx.index, tx.hash, tx.memo, tx.gas_limit,
         block.time, Json(tx.info)),
        "SELECT tx_id FROM transactions WHERE chain_id = %s AND tx_hash = %s",
        (block.chain_id, tx.hash),
    )


def insert_message(cur, tx_id: int, msg: Message) -> int:
    return _insert_or_lookup(
        cur,
        """INSERT INTO messages (tx_id, msg_index, type, raw)
           VALUES (%s, %s, %s, %s)
           ON CONFLICT DO NOTHING RETURNING message_id""",
        (tx_id, msg.index, msg.type, Json(msg.raw)),
        "SELECT message_id FROM messages WHERE tx_id = %s AND msg_index = %s",
        (tx_id, msg.index),
    )


def write_block_rows(cur, block: Block) -> int:
    """All the rows of one block, on an open transaction. Returns the block id."""
    block_id = insert_block(cur, block)
    for tx in block.transactions:
        tx_id = insert_transaction(cur, block_id, block, tx)
        for msg in tx.messages:
            insert_message(cur, tx_id, msg)
    return block_id


def write_block(conn, block: Block) -> int:
    """Save a block completely or not at all."""
    try:
        with conn.cursor() as cur:
            block_id = write_block_rows(cur, block)
        conn.commit()
        return block_id
    except BaseException:
        conn.rollback()
        raise

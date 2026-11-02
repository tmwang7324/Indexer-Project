"""Writer: one database transaction per block (D14, D20).

Every `insert_*` function takes a cursor and NEVER commits, so a component test can
wrap it in a transaction it rolls back. Only `write_block` controls BEGIN/COMMIT.
Inserts use ON CONFLICT DO NOTHING, then look the existing row up when no row comes back.
"""
import logging
from typing import Optional

from psycopg2 import sql
from psycopg2.extras import Json

from .handlers import Registry, get_registry
from .handlers.spec import HandlerResult
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


def _insert_row(cur, table: str, row: dict) -> None:
    """INSERT ... ON CONFLICT DO NOTHING for a typed or side row. Table and column names come from
    the handlers, never from message data; values are always parameters."""
    columns = list(row)
    values = [Json(v) if isinstance(v, (dict, list)) else v for v in row.values()]
    cur.execute(
        sql.SQL("INSERT INTO {} ({}) VALUES ({}) ON CONFLICT DO NOTHING").format(
            sql.Identifier(table),
            sql.SQL(", ").join(map(sql.Identifier, columns)),
            sql.SQL(", ").join(sql.Placeholder() * len(columns)),
        ),
        values,
    )


def insert_typed(cur, message_id: int, result: HandlerResult) -> None:
    """The typed copy of a message, plus its side rows."""
    _insert_row(cur, result.table, {"message_id": message_id, **result.row})
    for table, row in result.children:
        _insert_row(cur, table, {"message_id": message_id, **row})


def write_block_rows(cur, block: Block, registry: Optional[Registry] = None) -> int:
    """All the rows of one block, on an open transaction. Returns the block id."""
    registry = registry or get_registry()
    block_id = insert_block(cur, block)
    for tx in block.transactions:
        tx_id = insert_transaction(cur, block_id, block, tx)
        for msg in tx.messages:
            message_id = insert_message(cur, tx_id, msg)
            result = registry.handle(msg.type, msg.raw)
            if result is None:
                log.info("no handler for message type %s (block %s/%s): stored in messages only",
                         msg.type, block.chain_id, block.height)
            else:
                insert_typed(cur, message_id, result)
    return block_id


def write_block(conn, block: Block, registry: Optional[Registry] = None) -> int:
    """Save a block completely or not at all."""
    try:
        with conn.cursor() as cur:
            block_id = write_block_rows(cur, block, registry)
        conn.commit()
        return block_id
    except BaseException:
        conn.rollback()
        raise

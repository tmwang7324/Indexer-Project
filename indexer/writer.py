"""Writer: one database transaction per block (D14, D20).

Every `insert_*` function takes a cursor and NEVER commits, so a component test can
wrap it in a transaction it rolls back. Only `write_block` controls BEGIN/COMMIT.
Inserts use ON CONFLICT DO NOTHING, then look the existing row up when no row comes back.
"""
import logging
from dataclasses import dataclass
from typing import Callable, Optional

import psycopg2
from psycopg2 import sql
from psycopg2.extras import Json, execute_values

from .addresses import classify_address
from .checkpoint import advance_checkpoint
from .errors import CountMismatchError
from .handlers import Registry, get_registry
from .handlers.spec import HandlerResult
from .models import Block, Message, Transaction
from .verify import check_counts, source_summary, written_summary

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
    o = tx.outcome
    tx_id = _insert_or_lookup(
        cur,
        """INSERT INTO transactions
               (block_id, chain_id, height, tx_index, tx_hash, memo, gas_limit, created_at, tx_info,
                code, codespace, gas_wanted, gas_used, log, events)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT DO NOTHING RETURNING tx_id""",
        (block_id, block.chain_id, block.height, tx.index, tx.hash, tx.memo, tx.gas_limit,
         block.time, Json(tx.info),
         o and o.code, o and o.codespace, o and o.gas_wanted, o and o.gas_used, o and o.log,
         o and Json(o.events)),
        "SELECT tx_id FROM transactions WHERE chain_id = %s AND tx_hash = %s",
        (block.chain_id, tx.hash),
    )
    insert_fees(cur, tx_id, tx.fee)
    return tx_id


def insert_fees(cur, tx_id: int, coins: list) -> None:
    """Every fee coin, not just the first one."""
    for i, coin in enumerate(coins):
        cur.execute(
            "INSERT INTO transaction_fees (tx_id, coin_index, denom, amount) VALUES (%s, %s, %s, %s) "
            "ON CONFLICT DO NOTHING", (tx_id, i, coin["denom"], coin["amount"]))


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


def insert_addresses(cur, values) -> dict:
    """Insert each distinct address once and return {address: address_id}.

    ON CONFLICT DO NOTHING plus a lookup, in bulk: addresses already known keep their id.
    """
    distinct = sorted(set(values))
    if not distinct:
        return {}
    execute_values(
        cur,
        "INSERT INTO address (value, address_type) VALUES %s ON CONFLICT DO NOTHING",
        [(a, classify_address(a)) for a in distinct],
    )
    cur.execute("SELECT value, address_id FROM address WHERE value = ANY(%s)", (distinct,))
    return dict(cur.fetchall())


def insert_message_addresses(cur, message_id: int, links) -> None:
    """links: [(address_id, role)]."""
    for address_id, role in links:
        cur.execute(
            "INSERT INTO message_addresses (message_id, address_id, role) VALUES (%s, %s, %s) "
            "ON CONFLICT DO NOTHING", (message_id, address_id, role))


def write_block_rows(cur, block: Block, registry: Optional[Registry] = None) -> int:
    """All the rows of one block, on an open transaction. Returns the block id."""
    registry = registry or get_registry()
    # Handlers are pure, so run them all first: the block's addresses are inserted together.
    results = {(tx.index, msg.index): registry.handle(msg.type, msg.raw)
               for tx in block.transactions for msg in tx.messages}
    address_ids = insert_addresses(
        cur, (a for r in results.values() if r for _, a in r.addresses))

    block_id = insert_block(cur, block)
    for tx in block.transactions:
        tx_id = insert_transaction(cur, block_id, block, tx)
        for msg in tx.messages:
            message_id = insert_message(cur, tx_id, msg)
            result = results[(tx.index, msg.index)]
            if result is None:
                log.info("no handler for message type %s (block %s/%s): stored in messages only",
                         msg.type, block.chain_id, block.height)
                continue
            insert_typed(cur, message_id, result)
            insert_message_addresses(cur, message_id, [(address_ids[a], role) for role, a in result.addresses])
    return block_id


def check_block_counts(cur, block: Block, block_id: int) -> None:
    """D14: compare what this transaction wrote with what the source said. Raises CountMismatchError."""
    mismatches = check_counts(source_summary(block), written_summary(cur, block_id))
    if mismatches:
        raise CountMismatchError(block.chain_id, block.height, mismatches)


def clear_failure(cur, chain_id: str, height: int) -> None:
    """A stored height is never also in failed_blocks: the row goes in the block's own transaction."""
    cur.execute("DELETE FROM failed_blocks WHERE chain_id = %s AND height = %s", (chain_id, height))


def record_failure(conn, chain_id: str, height: int, error: str, attempts: int = 1) -> None:
    """Remember a block that could not be indexed. A separate short transaction, after the block's rollback."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO failed_blocks (chain_id, height, error, attempts) VALUES (%s, %s, %s, %s)
                   ON CONFLICT (chain_id, height) DO UPDATE
                   SET error = EXCLUDED.error, attempts = failed_blocks.attempts + EXCLUDED.attempts,
                       last_tried = now()""",
                (chain_id, height, error, attempts))
        conn.commit()
    except BaseException:
        _rollback(conn)
        raise


def _rollback(conn) -> None:
    """Roll back without hiding the error that made us: a dropped connection cannot roll back."""
    try:
        conn.rollback()
    except psycopg2.Error:
        pass


@dataclass(frozen=True)
class Hooks:
    """Test seams around the commit (D22). Production passes none.

    `before_commit` runs while the block's transaction holds the checkpoint row's lock: it may raise (a crash),
    but it must not wait for another block to commit, which would deadlock."""
    before_commit: Optional[Callable[[int], None]] = None      # called with the height, rows written, not committed
    after_commit: Optional[Callable[[int], None]] = None


def write_block(conn, block: Block, registry: Optional[Registry] = None, *,
                base: Optional[int] = None, hooks: Optional[Hooks] = None) -> int:
    """Save a block completely or not at all: rows, count checks, checkpoint, then COMMIT.

    `base` (the height just below the run's first block) switches the checkpoint on; without it the
    checkpoint is not touched.
    """
    try:
        with conn.cursor() as cur:
            block_id = write_block_rows(cur, block, registry)
            check_block_counts(cur, block, block_id)
            clear_failure(cur, block.chain_id, block.height)
            if base is not None:
                advance_checkpoint(cur, block.chain_id, base)     # last: it holds a lock until the commit
        if hooks and hooks.before_commit:
            hooks.before_commit(block.height)
        conn.commit()
    except BaseException:
        _rollback(conn)
        raise
    if hooks and hooks.after_commit:
        hooks.after_commit(block.height)
    return block_id

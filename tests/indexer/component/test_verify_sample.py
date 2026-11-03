"""C5: the sampled verify compares every stored field with the source (D14)."""
import pytest

from indexer import writer
from indexer.verify import diff_block
from indexer_support.cache import CHAIN, sample_cache

CACHE = sample_cache()
# A block with several transactions and messages, and typed rows with side tables or amounts.
HEIGHT = 23550183


@pytest.fixture
def stored(conn):
    block = CACHE.block(CHAIN, HEIGHT)
    writer.write_block_rows(conn.cursor(), block)
    return block


def change(conn, sql, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        assert cur.rowcount >= 1, "the test changed nothing"


def test_every_sample_block_verifies_clean(conn):
    """Normalisation (numbers, timestamps, JSON) must not produce false differences, over all 50 blocks."""
    blocks = [CACHE.block(CHAIN, h) for h in CACHE.heights(CHAIN)]
    with conn.cursor() as cur:
        for block in blocks:
            writer.write_block_rows(cur, block)
    for block in blocks:
        assert diff_block(conn, block) == [], block.height


def test_a_changed_block_field_is_reported(conn, stored):
    change(conn, "UPDATE blocks SET block_hash = 'FF' WHERE height = %s", (HEIGHT,))
    [d] = diff_block(conn, stored)
    assert (d.height, d.table, d.column, d.stored) == (HEIGHT, "blocks", "block_hash", "FF")
    assert str(d).startswith(f"{HEIGHT} / blocks / block_hash: 'FF' != ")


def test_a_changed_transaction_field_is_reported(conn, stored):
    change(conn, "UPDATE transactions SET memo = 'edited' WHERE height = %s AND tx_index = 1", (HEIGHT,))
    [d] = diff_block(conn, stored)
    assert (d.table, d.column, d.stored, d.source) == ("transactions[1]", "memo", "edited", stored.transactions[1].memo)


def test_a_changed_outcome_field_is_reported(conn, stored):
    change(conn, "UPDATE transactions SET gas_used = gas_used + 1 WHERE height = %s AND tx_index = 0", (HEIGHT,))
    [d] = diff_block(conn, stored)
    assert (d.table, d.column) == ("transactions[0]", "gas_used")


def test_a_changed_message_field_is_reported(conn, stored):
    change(conn, """UPDATE messages SET type = '/edited.Type' WHERE msg_index = 0
                    AND tx_id = (SELECT tx_id FROM transactions WHERE height = %s AND tx_index = 0)""", (HEIGHT,))
    found = {(d.table, d.column) for d in diff_block(conn, stored)}
    assert ("messages[0.0]", "type") in found


def test_a_changed_typed_row_is_reported(conn, stored):
    msg = stored.transactions[0].messages[0]
    from indexer.handlers import get_registry
    handler = get_registry().get(msg.type)
    assert handler is not None, "pick a block whose first message has a handler"
    column = next(iter(handler.columns))
    change(conn, f"UPDATE {handler.table} SET {column} = NULL WHERE message_id IN "
                 "(SELECT message_id FROM messages m JOIN transactions t USING (tx_id) "
                 "WHERE t.height = %s AND t.tx_index = 0 AND m.msg_index = 0)", (HEIGHT,))
    found = [(d.table, d.column) for d in diff_block(conn, stored)]
    assert found == [(f"{handler.table}[0.0]", column)]


def test_a_missing_row_is_reported(conn, stored):
    change(conn, "DELETE FROM transactions WHERE height = %s AND tx_index = 2", (HEIGHT,))
    found = {(d.table, d.column) for d in diff_block(conn, stored)}
    assert ("transactions[2]", "<row>") in found

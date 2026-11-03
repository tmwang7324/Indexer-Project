"""C4: the count check, against rows written in an open transaction (D14)."""
import pytest

from indexer import writer
from indexer.errors import CountMismatchError
from indexer.verify import Mismatch, check_counts, source_summary, written_summary
from indexer_support.sample import BLOCK


@pytest.fixture
def written(conn):
    """BLOCK (3 transactions, 4 messages, no outcomes) written but not committed."""
    with conn.cursor() as cur:
        block_id = writer.write_block_rows(cur, BLOCK)
        yield cur, block_id


def mismatches(cur, block_id):
    return check_counts(source_summary(BLOCK), written_summary(cur, block_id))


def test_a_clean_block_passes(written):
    cur, block_id = written
    assert written_summary(cur, block_id).transactions == 3
    assert mismatches(cur, block_id) == []
    writer.check_block_counts(cur, BLOCK, block_id)      # does not raise


def test_a_missing_transaction_is_reported(written):
    cur, block_id = written
    cur.execute("DELETE FROM transactions WHERE block_id = %s AND tx_index = 2", (block_id,))
    assert Mismatch("transactions", 3, 2) in mismatches(cur, block_id)
    with pytest.raises(CountMismatchError, match="transactions: the source has 3, the database has 2"):
        writer.check_block_counts(cur, BLOCK, block_id)


def test_a_duplicate_transaction_is_reported(written):
    cur, block_id = written
    cur.execute("""INSERT INTO transactions (block_id, chain_id, height, tx_index, tx_hash, created_at, tx_info)
                   SELECT block_id, chain_id, height, 99, 'DUPLICATE', created_at, tx_info
                   FROM transactions WHERE block_id = %s LIMIT 1""", (block_id,))
    assert mismatches(cur, block_id) == [Mismatch("transactions", 3, 4)]


def test_a_missing_outcome_is_reported(written):
    """The source says every transaction has an outcome; one row has none."""
    cur, block_id = written
    cur.execute("UPDATE transactions SET code = 0 WHERE block_id = %s", (block_id,))
    cur.execute("UPDATE transactions SET code = NULL WHERE block_id = %s AND tx_index = 0", (block_id,))
    expected = source_summary(BLOCK)
    with_outcomes = type(expected)(expected.transactions, 3, expected.messages)
    assert check_counts(with_outcomes, written_summary(cur, block_id)) == [Mismatch("outcomes", 3, 2)]


def test_a_wrong_message_count_is_reported(written):
    cur, block_id = written
    cur.execute("DELETE FROM messages WHERE message_id = (SELECT max(message_id) FROM messages)")
    assert mismatches(cur, block_id) == [Mismatch("messages", 4, 3)]

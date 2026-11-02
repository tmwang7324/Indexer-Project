"""C2 (typed row) and the contract between the handlers and the migrated schema."""
import pytest

from indexer import writer
from indexer.handlers import get_registry
from indexer.models import Message
from indexer_support.messages import MESSAGES
from indexer_support.sample import BLOCK

TYPES = get_registry().type_urls()
VOTE = BLOCK.transactions[2].messages[0]


def _message_id(cur, msg):
    block_id = writer.insert_block(cur, BLOCK)
    tx_id = writer.insert_transaction(cur, block_id, BLOCK, BLOCK.transactions[2])
    return writer.insert_message(cur, tx_id, msg)


def test_typed_row_is_idempotent(conn):
    result = get_registry().handle(VOTE.type, VOTE.raw)
    with conn.cursor() as cur:
        message_id = _message_id(cur, VOTE)
        writer.insert_typed(cur, message_id, result)
        writer.insert_typed(cur, message_id, result)
        cur.execute("SELECT message_id, proposal_id, voter, option, metadata FROM cosmos_vote_msg")
        rows = cur.fetchall()
    assert rows == [(message_id, 39, "migaloo1fc4kjfau480nr503yl0r8ml7vvn07d2r7ztjky", "VOTE_OPTION_YES", "")]


@pytest.mark.parametrize("type_url", TYPES, ids=lambda t: t.rsplit(".", 1)[-1] + ":" + t.split(".")[0].lstrip("/"))
def test_handler_output_fits_the_migrated_table(conn, type_url):
    """Every column a handler fills exists with a compatible type, and its side rows are accepted."""
    handler = get_registry().get(type_url)
    result = handler(MESSAGES[type_url])
    msg = Message(index=0, type=type_url, raw=MESSAGES[type_url])
    with conn.cursor() as cur:
        message_id = _message_id(cur, msg)
        writer.insert_typed(cur, message_id, result)
        cur.execute(f"SELECT count(*) FROM {handler.table} WHERE message_id = %s", (message_id,))
        assert cur.fetchone()[0] == 1
        for side in handler.side_tables:
            cur.execute(f"SELECT count(*) FROM {side} WHERE message_id = %s", (message_id,))
            assert cur.fetchone()[0] == sum(1 for t, _ in result.children if t == side)

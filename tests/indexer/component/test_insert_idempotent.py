"""C2: every insert is idempotent: twice -> one row, equal to the expected row, same id both times."""
import pytest

from indexer import writer
from indexer_support.sample import BLOCK

VOTE = BLOCK.transactions[2]


def _block(cur):
    return writer.insert_block(cur, BLOCK)


def _tx(cur):
    return writer.insert_transaction(cur, _block(cur), BLOCK, VOTE)


def _msg(cur):
    return writer.insert_message(cur, _tx(cur), VOTE.messages[0])


CASES = {
    "block": (_block,
              "SELECT chain_id, height, block_hash, tx_num, created_at FROM blocks",
              [("migaloo-1", 7027410, "8C91618FA1CAC47603C51FC49A26F98BE65FE393577216126EC7858ADC382FB7", 3)]),
    "transaction": (_tx,
                    "SELECT tx_hash, tx_index, height, memo, gas_limit FROM transactions",
                    [(VOTE.hash, 2, 7027410, "LFG! --Voted by Polkachu", 100644)]),
    "message": (_msg,
                "SELECT msg_index, type, raw ->> 'proposal_id' FROM messages",
                [(0, "/cosmos.gov.v1.MsgVote", "39")]),
}


@pytest.mark.parametrize("name", CASES)
def test_insert_is_idempotent(conn, name):
    insert, select, expected = CASES[name]
    with conn.cursor() as cur:
        first = insert(cur)
        second = insert(cur)
        assert first == second
        cur.execute(select)
        rows = [r[:len(expected[0])] for r in cur.fetchall()]
    assert rows == expected


def test_address_insert_is_idempotent(conn):
    addresses = ["migaloo194ytn50yhh67rdha8akhs7c6zulnz4n2yrqeed",
                 "migaloovaloper16skk5gcmazhkv945gauuuhlugd099ltnf9qkey"]
    with conn.cursor() as cur:
        first = writer.insert_addresses(cur, addresses + addresses[:1])    # duplicates in one call
        second = writer.insert_addresses(cur, addresses[::-1])
        assert first == second and len(first) == 2
        cur.execute("SELECT value, address_type, created_at FROM address ORDER BY value")
        rows = cur.fetchall()
    assert [(v, t) for v, t, _ in rows] == [
        ("migaloo194ytn50yhh67rdha8akhs7c6zulnz4n2yrqeed", "user"),
        ("migaloovaloper16skk5gcmazhkv945gauuuhlugd099ltnf9qkey", "validator")]
    assert all(created.utcoffset().total_seconds() == 0 for _, _, created in rows)   # UTC

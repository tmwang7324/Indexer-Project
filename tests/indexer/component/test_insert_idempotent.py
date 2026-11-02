"""C2: every insert is idempotent: twice -> one row, equal to the expected row, same id both times."""
import json
from pathlib import Path

import pytest

from indexer import writer
from indexer.parse import parse_block

REPO = Path(__file__).resolve().parents[3]
MIGALOO = json.loads((REPO / "test_blocks" / "7027410").read_text())
DECODED = json.loads((REPO / "tests" / "fixtures" / "decoded" / "7027410.json").read_text())
BLOCK = parse_block(MIGALOO["block_id"], MIGALOO["block"], [d["tx"] for d in DECODED])
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

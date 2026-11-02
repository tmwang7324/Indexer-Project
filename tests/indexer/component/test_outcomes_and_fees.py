"""C2 (outcome, events, fee coins) and C3 (amounts above 64 bits)."""
from dataclasses import replace
from decimal import Decimal

from indexer import writer
from indexer.models import Outcome
from indexer_support.sample import BLOCK

VOTE = BLOCK.transactions[2]
EVENTS = [{"type": "tx", "attributes": [{"key": "fee", "value": "5uluna", "index": True}]}]


def _insert(cur, tx):
    block_id = writer.insert_block(cur, BLOCK)
    return writer.insert_transaction(cur, block_id, BLOCK, tx)


def test_outcome_events_and_every_fee_coin_are_stored_idempotently(conn):
    fee = [{"denom": "uluna", "amount": "36000"}, {"denom": "uusd", "amount": "7"}]
    tx = replace(VOTE, fee=fee, outcome=Outcome(code=11, codespace="sdk", gas_wanted=100, gas_used=90,
                                                log="out of gas in location", events=EVENTS))
    with conn.cursor() as cur:
        first, second = _insert(cur, tx), _insert(cur, tx)
        assert first == second
        cur.execute("SELECT code, codespace, gas_wanted, gas_used, log, events FROM transactions")
        assert cur.fetchall() == [(11, "sdk", 100, 90, "out of gas in location", EVENTS)]
        cur.execute("SELECT coin_index, denom, amount FROM transaction_fees ORDER BY coin_index")
        assert cur.fetchall() == [(0, "uluna", Decimal(36000)), (1, "uusd", Decimal(7))]


def test_a_transaction_without_an_outcome_has_null_outcome_columns(conn):
    with conn.cursor() as cur:
        _insert(cur, VOTE)
        cur.execute("SELECT code, codespace, gas_wanted, gas_used, log, events FROM transactions")
        assert cur.fetchall() == [(None,) * 6]


def test_amount_above_64_bits_is_stored_exactly(conn):
    big = 2 ** 64 + 1
    tx = replace(VOTE, fee=[{"denom": "uluna", "amount": str(big)}])
    with conn.cursor() as cur:
        tx_id = _insert(cur, tx)
        cur.execute("SELECT amount FROM transaction_fees WHERE tx_id = %s", (tx_id,))
        assert cur.fetchone()[0] == Decimal(big)

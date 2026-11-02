"""U3: transactions are matched to their results by position; a count disagreement is bad data."""
import pytest

from indexer.errors import BadDataError
from indexer.parse import match_outcomes, parse_txs_block
from indexer_support.sample import BLOCK, BLOCK_FILE
from indexer_support.messages import DECODED

RESULTS = [
    {"code": 0, "gas_wanted": "10", "gas_used": "7", "log": "", "events": [{"type": "tx", "attributes": []}]},
    {"code": 5, "codespace": "sdk", "gas_wanted": "20", "gas_used": "9", "log": "out of gas", "events": []},
    {"code": 0, "gas_wanted": "30", "gas_used": "30", "events": None},
]


def test_counts_agree():
    matched = match_outcomes(BLOCK.transactions, RESULTS)
    assert [(t.index, t.outcome.code, t.outcome.codespace, t.outcome.gas_wanted, t.outcome.gas_used,
             t.outcome.log, t.outcome.events) for t in matched] == [
        (0, 0, "", 10, 7, "", [{"type": "tx", "attributes": []}]),
        (1, 5, "sdk", 20, 9, "out of gas", []),
        (2, 0, "", 30, 30, "", []),
    ]


@pytest.mark.parametrize("results", [RESULTS[:2], RESULTS + RESULTS[:1]], ids=["one result missing", "one extra"])
def test_counts_disagree(results):
    with pytest.raises(BadDataError, match="3 transactions but"):
        match_outcomes(BLOCK.transactions, results)


def test_results_for_another_height_are_bad_data():
    page = {"block_id": BLOCK_FILE["block_id"], "block": BLOCK_FILE["block"], "txs": [d["tx"] for d in DECODED]}
    with pytest.raises(BadDataError, match="block_results is for height 1"):
        parse_txs_block([page], {"result": {"height": "1", "txs_results": RESULTS}})

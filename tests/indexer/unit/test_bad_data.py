"""Malformed input is reported as bad data (D21), never as a KeyError deep inside the parser."""
import copy

import pytest

from indexer.errors import BadDataError
from indexer.parse import parse_block, parse_outcome, parse_txs_block
from indexer_support.messages import DECODED
from indexer_support.sample import BLOCK_FILE

INFOS = [d["tx"] for d in DECODED]


def _block(**changes):
    block = copy.deepcopy(BLOCK_FILE["block"])
    block.update(changes)
    return block


def _break_tx(mutate):
    infos = copy.deepcopy(INFOS)
    mutate(infos[0])
    return infos


CASES = {
    "block hash is not base64": lambda: parse_block({"hash": "***"}, _block(), INFOS),
    "block id without a hash": lambda: parse_block({}, _block(), INFOS),
    "height is not a number": lambda: parse_block(
        BLOCK_FILE["block_id"], _block(header={**BLOCK_FILE["block"]["header"], "height": "x"}), INFOS),
    "transaction without auth_info": lambda: parse_block(
        BLOCK_FILE["block_id"], _block(), _break_tx(lambda t: t.pop("auth_info"))),
    "message without @type": lambda: parse_block(
        BLOCK_FILE["block_id"], _block(), _break_tx(lambda t: t["body"]["messages"][0].pop("@type"))),
    "gas limit is not a number": lambda: parse_block(
        BLOCK_FILE["block_id"], _block(), _break_tx(lambda t: t["auth_info"]["fee"].update(gas_limit="lots"))),
    "raw transaction is not base64": lambda: parse_block(
        BLOCK_FILE["block_id"], _block(data={"txs": ["***", "***", "***"]}), INFOS),
    "result code is not a number": lambda: parse_outcome({"code": "x"}),
    "result is not an object": lambda: parse_outcome(None),
    "txs response without a block": lambda: parse_txs_block([{"txs": []}], {"result": {"height": "1"}}),
    "block_results without a height": lambda: parse_txs_block(
        [{"block_id": BLOCK_FILE["block_id"], "block": BLOCK_FILE["block"], "txs": INFOS}], {"result": {}}),
}


@pytest.mark.parametrize("name", CASES)
def test_malformed_input_is_bad_data(name):
    with pytest.raises(BadDataError):
        CASES[name]()

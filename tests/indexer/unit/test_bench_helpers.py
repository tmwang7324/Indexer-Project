"""The pure parts of the benchmark tool (ticket 14): heights, the old file format, parity."""
import base64
import json
import sys

import pytest

from indexer.bench import (BenchError, Mismatch, Result, bech32_encode, check_parity, decoded_by_tx_bytes,
                           old_format_from_cache, parse_heights)
from indexer_support.db import REPO

TERRA_FIXTURE = REPO / "tests" / "fixtures" / "terra_blocks" / "23263983"


def test_heights_are_inclusive():
    assert list(parse_heights("5:7")) == [5, 6, 7]


@pytest.mark.parametrize("spec", ["", "5", "a:b", "7:5", "1:2:3"])
def test_bad_heights_are_refused(spec):
    with pytest.raises(BenchError):
        parse_heights(spec)


def test_bech32_reproduces_a_real_consensus_address():
    """The node's own sdk_block carries terravalcons1..., which is bech32 of the tendermint proposer address."""
    real = json.loads(TERRA_FIXTURE.read_text())
    raw = base64.b64decode(real["block"]["header"]["proposer_address"])
    assert bech32_encode("terravalcons", raw) == real["sdk_block"]["header"]["proposer_address"]


def test_a_derived_old_format_block_passes_the_old_validator(tmp_path):
    """Built from the real block's own tendermint half, the derived file must equal the node's file in the
    only field the old validator inspects."""
    real = json.loads(TERRA_FIXTURE.read_text())
    page = json.dumps({"txs": [], "block_id": real["block_id"], "block": real["block"],
                       "pagination": {"next_key": None}}).encode()
    derived = old_format_from_cache([page], "phoenix-1")
    assert derived["block_id"] == real["block_id"]
    assert derived["sdk_block"]["header"]["proposer_address"] == real["sdk_block"]["header"]["proposer_address"]
    sys.path.insert(0, str(REPO))
    from functions import Validate_json
    assert Validate_json(derived, "23263983") == 1


def test_decoded_transactions_are_keyed_by_their_raw_bytes():
    page = json.dumps({"block": {"header": {"height": "9"}, "data": {"txs": ["AAAA", "BBBB"]}},
                       "txs": [{"body": 1}, {"body": 2}]}).encode()
    assert decoded_by_tx_bytes([page]) == {"AAAA": {"tx": {"body": 1}}, "BBBB": {"tx": {"body": 2}}}


def test_a_transaction_count_that_does_not_match_the_decoded_list_is_refused():
    page = json.dumps({"block": {"header": {"height": "9"}, "data": {"txs": ["AAAA"]}}, "txs": []}).encode()
    with pytest.raises(BenchError):
        decoded_by_tx_bytes([page])


def _result(pipeline, summary):
    return Result(pipeline, pipeline, summary=summary)


def test_parity_passes_when_every_height_matches():
    expected = {1: (0, 0), 2: (2, 3)}
    assert check_parity([_result("new", dict(expected)), _result("baseline", dict(expected))], expected) == []


def test_parity_names_each_height_and_field_that_differs():
    expected = {1: (0, 0), 2: (2, 3), 3: (1, 1)}
    got = {1: (0, 0), 2: (1, 3), 4: (0, 0)}
    problems = check_parity([_result("new", got)], expected)
    assert {(p.height, p.what) for p in problems} == {(2, "transactions"), (3, "block"), (4, "block")}
    assert all(isinstance(p, Mismatch) for p in problems)
    assert "2: new: transactions: expected 2, found 1" in {str(p) for p in problems}


def test_the_old_pipeline_is_held_to_the_messages_it_supports():
    expected = {1: (1, 3)}
    old_expected = {1: (1, 2)}                                  # one message has a type the old pipeline lacks
    assert check_parity([_result("old", {1: (1, 2)})], expected, old_expected) == []
    assert check_parity([_result("old", {1: (1, 3)})], expected, old_expected) != []
    assert check_parity([_result("new", {1: (1, 3)})], expected, old_expected) == []

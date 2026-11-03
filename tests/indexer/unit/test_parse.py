"""U1: parse a block once into Block / Transaction / Message objects."""
import copy
import json
from pathlib import Path

import pytest

from indexer.errors import BadDataError
from indexer.parse import parse_block
from indexer.sources.replay import ReplayCache

REPO = Path(__file__).resolve().parents[3]
MIGALOO = json.loads((REPO / "test_blocks" / "7027410").read_text())
DECODED = json.loads((REPO / "tests" / "fixtures" / "decoded" / "7027410.json").read_text())
VOTE_TX = "E77D14CB104E70372F151F73C5C233A351C6A014B64A67F9BCA9E5EB7B445C20"


def migaloo():
    return parse_block(MIGALOO["block_id"], MIGALOO["block"], [d["tx"] for d in DECODED])


def empty_block():
    block = copy.deepcopy(MIGALOO["block"])
    block["data"]["txs"] = []
    return parse_block(MIGALOO["block_id"], block, [])


def test_migaloo_block():
    b = migaloo()
    assert (b.chain_id, b.height, b.tx_num) == ("migaloo-1", 7027410, 3)
    assert b.hash == "8C91618FA1CAC47603C51FC49A26F98BE65FE393577216126EC7858ADC382FB7"
    assert b.time == "2024-05-24T16:22:01.677147708Z"
    vote = b.transactions[2]
    assert (vote.hash, vote.index, vote.memo, vote.gas_limit) == (VOTE_TX, 2, "LFG! --Voted by Polkachu", 100644)
    assert vote.fee == [{"denom": "uwhale", "amount": "150000"}]
    assert [(m.index, m.type) for m in vote.messages] == [(0, "/cosmos.gov.v1.MsgVote")]


def test_empty_block():
    b = empty_block()
    assert (b.height, b.tx_num, b.transactions) == (7027410, 0, [])


def test_multi_message_transaction():
    tx = migaloo().transactions[1]
    assert [(m.index, m.type) for m in tx.messages] == [
        (0, "/ibc.core.client.v1.MsgUpdateClient"), (1, "/ibc.core.channel.v1.MsgAcknowledgement")]


@pytest.mark.parametrize("break_it", ["fewer decoded than raw", "no header"])
def test_inconsistent_block_is_bad_data(break_it):
    infos = [d["tx"] for d in DECODED]
    block = copy.deepcopy(MIGALOO["block"])
    if break_it == "fewer decoded than raw":
        infos = infos[:2]
    else:
        del block["header"]
    with pytest.raises(BadDataError):
        parse_block(MIGALOO["block_id"], block, infos)


SAMPLE = ReplayCache(REPO / "tests" / "indexer" / "data" / "terra")


def test_terra_block_with_outcomes():
    b = SAMPLE.block("phoenix-1", 23561237)
    assert (b.chain_id, b.height, b.tx_num) == ("phoenix-1", 23561237, 1)
    assert b.hash == "711081E02E766D2E54AEF52CDC44DE9FB47632FFC99741DFC84D5B3891A11567"
    tx = b.transactions[0]
    assert tx.hash == "F2DEF6ED1C41E463E2C679E531F56FE058BAF37B1AC1E89AA135FBC88307375F"
    assert [m.type for m in tx.messages] == ["/cosmos.distribution.v1beta1.MsgWithdrawDelegatorReward"] * 2
    assert (tx.gas_limit, tx.outcome.code, tx.outcome.gas_wanted, tx.outcome.gas_used) == (451767, 0, 451767, 327860)
    assert tx.outcome.events and "data" not in vars(tx.outcome)       # events kept, the base64 `data` is not


def test_terra_empty_block():
    b = SAMPLE.block("phoenix-1", 23264383)
    assert (b.height, b.tx_num, b.transactions) == (23264383, 0, [])
    assert b.hash == "987ECB35D4B6276082974370D5BF260AC71C46F27505D25853CC1E892172F0FF"

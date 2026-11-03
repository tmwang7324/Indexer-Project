"""The REST source against the fake node: head lookup and the ways a fetch can go wrong. No database needed."""
import json

import pytest

from indexer.errors import BadDataError, TransientError
from indexer.sources.endpoints import EndpointPool, load_endpoints
from indexer.sources.replay import ReplayCache
from indexer.sources.rest import RestSource
from indexer_support.db import REPO
from indexer_support.fake_node import FakeNode

SAMPLE = REPO / "tests" / "indexer" / "data" / "terra"
CHAIN = "phoenix-1"
FIRST = ReplayCache(SAMPLE).heights(CHAIN)[0]
HEAD = ReplayCache(SAMPLE).heights(CHAIN)[-1]


class Clock:
    """Fake time: sleeping advances it, so cool-downs pass without waiting."""
    now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def source(*urls, from_height=FIRST, to_height=FIRST, chain_id=CHAIN, max_rounds=4, cooldown=5.0):
    clock = Clock()
    endpoints = load_endpoints(clock=clock, sleep=clock.sleep, environ={"INDEXER_ENDPOINTS": json.dumps(
        [{"name": f"n{i}", "rest": u, "rpc": u, "rate": 1000} for i, u in enumerate(urls)])})
    return RestSource(from_height, to_height, chain_id=chain_id, clock=clock, sleep=clock.sleep,
                      pool=EndpointPool(endpoints, cooldown=cooldown, clock=clock), max_rounds=max_rounds)


def test_without_an_end_height_it_stops_at_the_head():
    with FakeNode(SAMPLE, CHAIN) as node:
        blocks = list(source(node.url, from_height=HEAD, to_height=None).blocks())
    assert [b.height for b in blocks] == [HEAD]
    assert "/cosmos/base/tendermint/v1beta1/blocks/latest" in node.paths


def test_the_head_is_looked_up_on_the_next_endpoint_when_one_fails():
    with FakeNode(SAMPLE, CHAIN, script=[503]) as bad, FakeNode(SAMPLE, CHAIN) as good:
        assert source(bad.url, good.url).latest_height() == HEAD


@pytest.mark.parametrize("script, error, message", [
    ([(404, b'{"message": "not found"}')], BadDataError, "HTTP 404"),
    ([(200, b"<html>gateway</html>")], BadDataError, "not JSON"),
    ([(200, b"[1, 2]")], BadDataError, "not a JSON object"),
], ids=["unknown height", "not json", "not an object"])
def test_bad_responses_are_bad_data_not_retried(script, error, message):
    with FakeNode(SAMPLE, CHAIN, script=script) as node:
        with pytest.raises(error, match=message):
            source(node.url).block(FIRST)
        assert len(node.arrivals) == 1


def test_a_block_of_another_chain_is_bad_data():
    with FakeNode(SAMPLE, CHAIN) as node:
        with pytest.raises(BadDataError, match="expected chain osmosis-1"):
            source(node.url, chain_id="osmosis-1").block(FIRST)


def test_an_unreachable_endpoint_is_transient_after_rotation_is_exhausted():
    with FakeNode(SAMPLE, CHAIN) as node:
        dead = node.url
    src = source(dead, max_rounds=3)       # the server is stopped: connection refused
    with pytest.raises(TransientError, match="could not fetch height"):
        src.block(FIRST)
    with pytest.raises(TransientError, match="chain head"):
        src.latest_height()


def test_when_every_endpoint_is_cooling_down_it_waits_for_the_first_to_return():
    with FakeNode(SAMPLE, CHAIN, script=[503]) as a, FakeNode(SAMPLE, CHAIN, script=[503]) as b:
        src = source(a.url, b.url, cooldown=7.0, max_rounds=3)
        block = src.block(FIRST)
    # a fails, b fails, both are cooling: the wait (7 s of fake time) is not one of the 3 attempts, so a's retry is
    assert block.height == FIRST
    assert src.pool._clock.now >= 7.0
    assert len(a.arrivals) >= 3 and len(b.arrivals) == 1      # a: failure + the retry's two requests (txs, results)

"""In-order prefetch: several blocks in flight, yielded in height order, window bounded. No database needed.

Gates on the fake node force exact orderings (Rule 8): hold the oldest height and check what else is requested.
"""
import json
import threading

import pytest

from indexer.errors import BadDataError
from indexer.sources.endpoints import EndpointPool, load_endpoints
from indexer.sources.replay import ReplayCache
from indexer.sources.rest import RestSource
from indexer_support.db import REPO
from indexer_support.fake_node import FakeNode

SAMPLE = REPO / "tests" / "indexer" / "data" / "terra"
CHAIN = "phoenix-1"
MANIFEST = json.loads((SAMPLE / "manifest.json").read_text())
FIRST = next(int(h) for h, v in MANIFEST.items() if "consecutive run" in v["why"])
RUN = list(range(FIRST, FIRST + 6))                 # six heights the fake node can serve

pytestmark = pytest.mark.timeout(30)


def source(url, from_height, to_height, prefetch):
    endpoints = load_endpoints(environ={"INDEXER_ENDPOINTS": json.dumps(
        [{"name": "n", "rest": url, "rpc": url, "rate": 1000}])})
    return RestSource(from_height, to_height, chain_id=CHAIN, pool=EndpointPool(endpoints), prefetch=prefetch)


def requested_heights(paths):
    return sorted({FakeNode._height_of(p) for p in paths if FakeNode._height_of(p)})


def test_later_blocks_are_fetched_while_the_oldest_is_held_and_still_come_out_in_order():
    with FakeNode(SAMPLE, CHAIN) as node:
        node.gates[RUN[0]] = gate = threading.Event()
        got = []
        consumer = threading.Thread(target=lambda: got.extend(b.height for b in source(node.url, RUN[0], RUN[-1], 3).blocks()))
        consumer.start()
        # while RUN[0] is held, RUN[1] and RUN[2] are fetched (3 in flight), but not RUN[3]: the window is bounded
        assert node.wait_for(lambda paths: {RUN[1], RUN[2]} <= set(requested_heights(paths)))
        assert got == [] and RUN[3] not in requested_heights(node.paths)
        gate.set()
        consumer.join(timeout=15)
        assert not consumer.is_alive()
    assert got == RUN


def test_the_window_slides_as_blocks_are_taken():
    with FakeNode(SAMPLE, CHAIN) as node:
        it = source(node.url, RUN[0], RUN[-1], 2).blocks()
        assert next(it).height == RUN[0]
        # after taking one block, the next height has entered the window: RUN[0..2] requested, RUN[3] not yet
        assert node.wait_for(lambda paths: RUN[2] in requested_heights(paths))
        assert RUN[3] not in requested_heights(node.paths)
        assert [b.height for b in it] == RUN[1:]


def test_blocks_are_identical_to_the_sequential_ones():
    with FakeNode(SAMPLE, CHAIN) as node:
        sequential = list(source(node.url, RUN[0], RUN[-1], 1).blocks())
        concurrent = list(source(node.url, RUN[0], RUN[-1], 4).blocks())
    assert concurrent == sequential and len(sequential) == 6


def test_an_error_is_raised_at_its_own_height_after_the_earlier_blocks():
    beyond = RUN[-1] + 1                                  # not in the sample: the node answers 404 (bad data)
    with FakeNode(SAMPLE, CHAIN) as node:
        it = source(node.url, RUN[0], beyond + 1, 4).blocks()
        got = []
        with pytest.raises(BadDataError, match="HTTP 404"):
            for block in it:
                got.append(block.height)
    assert got == RUN                                     # every earlier block was delivered first


def test_closing_early_stops_the_workers_and_asks_for_no_more_heights():
    with FakeNode(SAMPLE, CHAIN) as node:
        it = source(node.url, RUN[0], RUN[-1], 2).blocks()
        next(it)
        it.close()
        asked = len(node.paths)
    assert not [t for t in threading.enumerate() if t.name.startswith("prefetch")]
    assert asked <= 2 * 3 * 2                             # at most the window's heights, 2 requests each
    assert RUN[-1] not in requested_heights(node.paths)

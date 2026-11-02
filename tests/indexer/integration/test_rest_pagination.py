"""A `txs/block` response with pagination.next_key: the follow-up pages are fetched, parsed and recorded."""
import json

from indexer.sources.endpoints import EndpointPool, load_endpoints
from indexer.sources.replay import ReplayCache
from indexer.sources.rest import RestSource
from indexer_support.fake_node import FakeNode
from indexer_support.messages import DECODED
from indexer_support.sample import BLOCK_FILE

CHAIN = "migaloo-1"
HEIGHT = 7027410


def _page(txs, next_key):
    body = {"txs": txs, "pagination": {"next_key": next_key, "total": "0"}}
    if next_key is not None or not txs:     # the node repeats the block in every page; the parser uses the first
        body.update(block_id=BLOCK_FILE["block_id"], block=BLOCK_FILE["block"])
    return json.dumps(body).encode()


def test_follow_up_pages_are_fetched_and_recorded(tmp_path):
    txs = [d["tx"] for d in DECODED]
    pages = [_page(txs[:2], "AQID/+="), _page(txs[2:], None)]
    results = json.dumps({"result": {"height": str(HEIGHT), "txs_results": [{"code": 0}] * 3}}).encode()
    ReplayCache(tmp_path / "served").write(CHAIN, HEIGHT, pages, results)

    with FakeNode(tmp_path / "served", CHAIN) as node:
        endpoints = load_endpoints(environ={"INDEXER_ENDPOINTS": json.dumps(
            [{"name": "n", "rest": node.url, "rpc": node.url, "rate": 100}])})
        source = RestSource(HEIGHT, HEIGHT, chain_id=CHAIN, pool=EndpointPool(endpoints),
                            record=str(tmp_path / "recorded"))
        block = next(source.blocks())

    assert [tx.hash[:8] for tx in block.transactions] == ["5A8011C0", "AB116FEE", "E77D14CB"]
    assert [tx.outcome.code for tx in block.transactions] == [0, 0, 0]
    assert any("pagination.key=AQID%2F%2B%3D" in p for p in node.paths)       # the key is URL-encoded
    assert ReplayCache(tmp_path / "recorded").read(CHAIN, HEIGHT) == (pages, results)

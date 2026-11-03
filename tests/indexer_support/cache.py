"""Build small replay caches for tests from the curated sample (D24)."""
import json
from pathlib import Path

from indexer.sources.replay import ReplayCache

from .db import REPO

SAMPLE = REPO / "tests" / "indexer" / "data" / "terra"
CHAIN = "phoenix-1"


def sample_cache() -> ReplayCache:
    return ReplayCache(SAMPLE)


def copy_blocks(dst: Path, heights, chain_id: str = CHAIN, results=None) -> ReplayCache:
    """Copy the given sample heights into a new cache. `results` maps a height to a function that edits that
    block's /block_results document (to build a block whose two responses disagree)."""
    src, out = sample_cache(), ReplayCache(dst)
    for h in heights:
        pages, res = src.read(chain_id, h)
        if results and h in results:
            doc = json.loads(res)
            results[h](doc)
            res = json.dumps(doc).encode()
        out.write(chain_id, h, pages, res)
    return out


def renumbered_cache(dst: Path, start: int = 1000, chain_id: str = CHAIN) -> list:
    """The 50 sample blocks written as consecutive heights start, start+1, ... in sample order.

    The sample's real heights have gaps, and the ordering tests (checkpoint, workers, following) need a
    contiguous run. Only the height fields change; transactions, hashes and results are the real ones.
    Returns the new heights."""
    src, out = sample_cache(), ReplayCache(dst)
    heights = []
    for new, old in enumerate(src.heights(chain_id), start=start):
        pages, res = src.read(chain_id, old)
        new_pages = []
        for p in pages:
            doc = json.loads(p)
            doc["block"]["header"]["height"] = str(new)
            new_pages.append(json.dumps(doc).encode())
        doc = json.loads(res)
        (doc.get("result") or doc)["height"] = str(new)
        out.write(chain_id, new, new_pages, json.dumps(doc).encode())
        heights.append(new)
    return heights

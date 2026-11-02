"""Replay cache (D5): the raw bytes of a block's two responses, gzipped, in a folder.

    <dir>/<chain_id>/<height>.txs.json.gz        GET /cosmos/tx/v1beta1/txs/block/{h}
    <dir>/<chain_id>/<height>.txs.<n>.json.gz    follow-up pages (n = 1, 2, ...) when pagination.next_key is set
    <dir>/<chain_id>/<height>.results.json.gz    RPC /block_results?height={h}

The bytes are stored unchanged, so a replayed block is exactly what the node served.
"""
import gzip
import json
import logging
import os
from pathlib import Path
from typing import Iterator, Optional

from ..errors import BadDataError
from ..models import Block
from ..parse import parse_txs_block

log = logging.getLogger(__name__)


def _gz(data: bytes) -> bytes:
    return gzip.compress(data, compresslevel=9, mtime=0)   # mtime=0: the same bytes give the same file


class ReplayCache:
    def __init__(self, root):
        self.root = Path(root)

    def _path(self, chain_id: str, height: int, kind: str) -> Path:
        return self.root / chain_id / f"{height}.{kind}.json.gz"

    # --- writing -------------------------------------------------------------------------------
    def has(self, chain_id: str, height: int) -> bool:
        return self._path(chain_id, height, "txs").exists() and self._path(chain_id, height, "results").exists()

    def write(self, chain_id: str, height: int, txs_pages: list, results: bytes) -> bool:
        """Store a block's responses. Returns False (and writes nothing) if it is already cached."""
        if self.has(chain_id, height):
            return False
        names = ["txs"] + [f"txs.{n}" for n in range(1, len(txs_pages))]
        for kind, data in [*zip(names, txs_pages), ("results", results)]:
            path = self._path(chain_id, height, kind)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_bytes(_gz(data))
            os.replace(tmp, path)      # a half-written file is never visible under its final name
        return True

    # --- reading -------------------------------------------------------------------------------
    def read(self, chain_id: str, height: int) -> tuple:
        """(list of txs pages as bytes, results as bytes)."""
        pages, n = [], 0
        while True:
            path = self._path(chain_id, height, "txs" if n == 0 else f"txs.{n}")
            if not path.exists():
                break
            pages.append(gzip.decompress(path.read_bytes()))
            n += 1
        if not pages:
            raise BadDataError(f"replay cache has no txs response for {chain_id}/{height}")
        results_path = self._path(chain_id, height, "results")
        if not results_path.exists():
            raise BadDataError(f"replay cache has no block_results for {chain_id}/{height}")
        return pages, gzip.decompress(results_path.read_bytes())

    def heights(self, chain_id: str) -> list:
        folder = self.root / chain_id
        if not folder.is_dir():
            return []
        return sorted(int(p.name.split(".")[0]) for p in folder.glob("*.results.json.gz"))

    def chains(self) -> list:
        return sorted(p.name for p in self.root.iterdir() if p.is_dir()) if self.root.is_dir() else []

    def block(self, chain_id: str, height: int) -> Block:
        pages, results = self.read(chain_id, height)
        return parse_txs_block([json.loads(p) for p in pages], json.loads(results))


class ReplaySource:
    """Yields every cached block, chain by chain, in ascending height."""

    def __init__(self, folder, from_height: Optional[int] = None):
        self.cache = ReplayCache(folder)
        self.from_height = from_height
        self.skipped: list = []

    def blocks(self) -> Iterator[Block]:
        for chain_id in self.cache.chains():
            for height in self.cache.heights(chain_id):
                if self.from_height is not None and height < self.from_height:
                    continue
                yield self.cache.block(chain_id, height)

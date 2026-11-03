"""REST source: /cosmos/tx/v1beta1/txs/block/{h} (all pages) plus RPC /block_results?height={h}.

Endpoints are rotated; each has a token bucket and a cool-down after a failure. Every request has a timeout.
Responses can be recorded, byte for byte, into a replay cache (D5).
"""
import json
import logging
import os
import threading
import time
from functools import partial
from typing import Iterator, Optional
from urllib.parse import quote

import requests

from ..errors import BadDataError, TransientError
from ..models import Block, WorkItem
from ..parse import parse_txs_block
from .endpoints import Endpoint, EndpointPool, load_endpoints
from .replay import ReplayCache

log = logging.getLogger(__name__)

TIMEOUT = (5, 30)          # connect, read (seconds)
MAX_ROUNDS = 6             # fetch attempts per block (each tries the next usable endpoint)


class _EndpointFailure(Exception):
    """This endpoint failed (timeout, 429, 5xx): try another one."""


class RestSource:
    def __init__(self, from_height: int, to_height: Optional[int] = None, chain_id: str = "phoenix-1",
                 pool: Optional[EndpointPool] = None, record: Optional[str] = None,
                 clock=time.monotonic, sleep=time.sleep, max_rounds: int = MAX_ROUNDS):
        self.from_height, self.to_height, self.chain_id = from_height, to_height, chain_id
        self.pool = pool or EndpointPool(
            load_endpoints(clock, sleep), clock=clock,
            cooldown=float(os.environ.get("INDEXER_ENDPOINT_COOLDOWN", "30")))
        self.cache = ReplayCache(record) if record else None
        self._sleep, self._max_rounds = sleep, max_rounds
        self._local = threading.local()          # one requests.Session per thread
        self.skipped: list = []

    # --- HTTP ----------------------------------------------------------------------------------
    def _session(self) -> requests.Session:
        if not hasattr(self._local, "session"):
            self._local.session = requests.Session()
        return self._local.session

    def _get(self, endpoint: Endpoint, base: str, path: str) -> bytes:
        endpoint.limiter.acquire()
        try:
            resp = self._session().get(base + path, timeout=TIMEOUT)
        except (requests.Timeout, requests.ConnectionError) as exc:
            raise _EndpointFailure(f"{endpoint.name}: {exc.__class__.__name__}") from exc
        if resp.status_code == 429 or resp.status_code >= 500:
            raise _EndpointFailure(f"{endpoint.name}: HTTP {resp.status_code}")
        if resp.status_code != 200:
            raise BadDataError(f"{endpoint.name}: HTTP {resp.status_code} for {path}")
        return resp.content

    def _fetch_from(self, endpoint: Endpoint, height: int) -> tuple:
        pages = [self._get(endpoint, endpoint.rest, f"/cosmos/tx/v1beta1/txs/block/{height}")]
        while True:
            next_key = _load(pages[-1], "txs/block").get("pagination", {}).get("next_key")
            if not next_key:
                break
            pages.append(self._get(endpoint, endpoint.rest, f"/cosmos/tx/v1beta1/txs/block/{height}"
                                                            f"?pagination.key={quote(next_key, safe='')}"))
        results = self._get(endpoint, endpoint.rpc, f"/block_results?height={height}")
        return pages, results

    def _attempts(self):
        """Yield endpoints to try, at most `max_rounds` of them. Waiting for a cool-down is not an attempt."""
        attempts = 0
        while attempts < self._max_rounds:
            endpoint = self.pool.pick()
            if endpoint is None:                     # all cooling down: wait for the first to come back
                self._sleep(max(self.pool.seconds_until_available(), 0.01))
                continue
            attempts += 1
            yield endpoint

    def fetch_raw(self, height: int) -> tuple:
        """(txs pages, block_results) as raw bytes, rotating endpoints on failure."""
        last = "no endpoint tried"
        for endpoint in self._attempts():
            try:
                return self._fetch_from(endpoint, height)
            except _EndpointFailure as exc:
                last = str(exc)
                log.warning("height %d: %s; rotating", height, last)
                self.pool.mark_failed(endpoint)
        raise TransientError(f"could not fetch height {height} from any endpoint (last: {last})")

    def latest_height(self) -> int:
        last = "no endpoint tried"
        for endpoint in self._attempts():
            try:
                doc = _load(self._get(endpoint, endpoint.rest, "/cosmos/base/tendermint/v1beta1/blocks/latest"),
                            "blocks/latest")
                return int(doc["block"]["header"]["height"])
            except _EndpointFailure as exc:
                last = str(exc)
                self.pool.mark_failed(endpoint)
            except (KeyError, TypeError, ValueError) as exc:
                raise BadDataError(f"blocks/latest is malformed: {exc!r}") from exc
        raise TransientError(f"could not read the chain head from any endpoint (last: {last})")

    # --- blocks --------------------------------------------------------------------------------
    def block(self, height: int) -> Block:
        pages, results = self.fetch_raw(height)
        block = parse_txs_block([_load(p, "txs/block") for p in pages], _load(results, "block_results"))
        if block.chain_id != self.chain_id:
            raise BadDataError(f"expected chain {self.chain_id}, the node served {block.chain_id}")
        if block.height != height:
            raise BadDataError(f"asked for height {height}, the node served {block.height}")
        if self.cache is not None:
            self.cache.write(block.chain_id, height, pages, results)   # raw bytes, only for blocks that parsed
        return block

    def fetch(self, chain_id: str, height: int) -> Block:
        if chain_id != self.chain_id:
            raise BadDataError(f"this source serves {self.chain_id}, not {chain_id}")
        return self.block(height)

    def items(self, stop=None) -> Iterator[WorkItem]:
        last = self.to_height if self.to_height is not None else self.latest_height()
        for height in range(self.from_height, last + 1):
            yield WorkItem(self.chain_id, height, partial(self.block, height))

    def blocks(self) -> Iterator[Block]:
        for item in self.items():
            yield item.load()


def _load(data: bytes, what: str) -> dict:
    try:
        doc = json.loads(data)
    except ValueError as exc:
        raise BadDataError(f"{what} response is not JSON: {exc}") from exc
    if not isinstance(doc, dict):
        raise BadDataError(f"{what} response is not a JSON object")
    return doc

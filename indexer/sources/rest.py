"""REST source: /cosmos/tx/v1beta1/txs/block/{h} (all pages) plus RPC /block_results?height={h}.

Endpoints are rotated; each has a token bucket and a cool-down after a failure. Every request has a timeout.
Responses can be recorded, byte for byte, into a replay cache (D5).
"""
import json
import logging
import os
import re
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
BACKFILL_DEPTH = 25000     # first start with no checkpoint and no --from-height: this far below the head (D3)
POLL_INTERVAL = 6.0        # seconds between head lookups once caught up (about one Terra block)
# What a node says when a height is older than it keeps (publicnode and others prune after a while).
PRUNED = re.compile(r"lowest height|is not available|pruned", re.IGNORECASE)


class _EndpointFailure(Exception):
    """This endpoint failed (timeout, 429, 5xx): try another one."""

    pruned = False


class _Pruned(_EndpointFailure):
    """This endpoint no longer keeps that height. Another endpoint may; the endpoint itself is healthy."""

    pruned = True


class RestSource:
    def __init__(self, from_height: Optional[int] = None, to_height: Optional[int] = None,
                 chain_id: str = "phoenix-1", pool: Optional[EndpointPool] = None, record: Optional[str] = None,
                 clock=time.monotonic, sleep=time.sleep, max_rounds: int = MAX_ROUNDS, follow: bool = False,
                 poll_interval: Optional[float] = None, backfill_depth: Optional[int] = None):
        """`from_height` None means BACKFILL_DEPTH below the head. With `follow` (and no `to_height`) the source
        keeps polling the head after catching up (D16)."""
        self.from_height, self.to_height, self.chain_id = from_height, to_height, chain_id
        self.follow = follow and to_height is None
        self.poll_interval = poll_interval if poll_interval is not None else float(
            os.environ.get("INDEXER_POLL_INTERVAL", POLL_INTERVAL))
        self.backfill_depth = backfill_depth if backfill_depth is not None else int(
            os.environ.get("INDEXER_BACKFILL_DEPTH", BACKFILL_DEPTH))
        self.head: Optional[int] = None            # the latest head this source has seen
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
        if resp.status_code != 200 and PRUNED.search(resp.text[:2000]):
            raise _Pruned(f"{endpoint.name}: HTTP {resp.status_code}: {resp.text[:200].strip()}")
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
        self._check_rpc_error(endpoint, results)
        return pages, results

    @staticmethod
    def _check_rpc_error(endpoint: Endpoint, body: bytes) -> None:
        """CometBFT answers HTTP 200 with a JSON-RPC `error` object for a height it cannot serve."""
        try:
            error = json.loads(body).get("error")
        except (ValueError, AttributeError):
            return                                   # not JSON / not an object: `block()` reports it as bad data
        if error:
            text = json.dumps(error)[:300]
            raise (_Pruned if PRUNED.search(text) else _EndpointFailure)(f"{endpoint.name}: RPC error {text}")

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
        last, failures, pruned_by = "no endpoint tried", [], set()
        for endpoint in self._attempts():
            try:
                return self._fetch_from(endpoint, height)
            except _EndpointFailure as exc:
                last = str(exc)
                failures.append(exc)
                log.warning("height %d: %s; rotating", height, last)
                if not exc.pruned:
                    self.pool.mark_failed(endpoint)          # a pruned height is no fault of the endpoint
                    continue
                pruned_by.add(endpoint.name)
                if len(pruned_by) == len(self.pool.endpoints):
                    break                                    # every endpoint has said it: asking again changes nothing
        if failures and all(f.pruned for f in failures):
            raise BadDataError(f"height {height} is older than every endpoint tried keeps "
                               f"(below the retention window): {last}")
        raise TransientError(f"could not fetch height {height} from any endpoint (last: {last})")

    def fetch_old_format(self, height: int) -> bytes:
        """The block in the old pipeline's file format (`block_id`, `block` and `sdk_block`), for the benchmark."""
        last = "no endpoint tried"
        for endpoint in self._attempts():
            try:
                return self._get(endpoint, endpoint.rest, f"/cosmos/base/tendermint/v1beta1/blocks/{height}")
            except _EndpointFailure as exc:
                last = str(exc)
                if not exc.pruned:
                    self.pool.mark_failed(endpoint)
        raise TransientError(f"could not fetch the old-format block {height} from any endpoint (last: {last})")

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
        """Ascending heights from `from_height` (or BACKFILL_DEPTH below the head) to the head, then, when
        following, every new height as the head moves: one stream, no gap (D16)."""
        stop = stop or threading.Event()
        head = self.to_height if self.to_height is not None else self.latest_height()
        self.head = head
        height = self.from_height if self.from_height is not None else max(1, head - self.backfill_depth)
        log.info("starting at height %d, head %d (%d blocks behind)", height, head, max(0, head - height + 1))
        while True:
            while height <= head:
                if stop.is_set():
                    return
                yield WorkItem(self.chain_id, height, partial(self.block, height))
                height += 1
            if not self.follow:
                return
            log.info("caught up at height %d; following the head every %.1fs", head, self.poll_interval)
            head = self._wait_for_new_head(head, stop)
            if head is None:
                return

    def _wait_for_new_head(self, head: int, stop) -> Optional[int]:
        """Poll until the head is above `head`. Returns it, or None when told to stop. A failed poll is
        logged and tried again at the next interval: following must survive a node having a bad moment."""
        while not stop.wait(self.poll_interval):
            try:
                latest = self.latest_height()
            except TransientError as exc:
                log.warning("head lookup failed: %s", exc)
                continue
            if latest > head:
                self.head = latest
                return latest
        return None

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

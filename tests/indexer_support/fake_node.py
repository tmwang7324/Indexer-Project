"""A local fake node: the only HTTP server tests use (D25). Serves a replay cache the way a node would.

    GET /cosmos/tx/v1beta1/txs/block/{h}[?pagination.key=K]
    GET /block_results?height={h}
    GET /cosmos/base/tendermint/v1beta1/blocks/latest

`script` decides, for the n-th request this node receives (from 0), whether to answer with an error status
instead: a list of statuses or (status, body) pairs (None = serve normally), or a callable n -> the same.
"""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from indexer.sources.replay import ReplayCache


class FakeNode:
    def __init__(self, cache_root, chain_id="phoenix-1", script=()):
        self.cache = ReplayCache(cache_root)
        self.chain_id = chain_id
        self.script = script if callable(script) else (lambda n, _s=list(script): _s[n] if n < len(_s) else None)
        self.arrivals: list = []          # monotonic time of every request
        self.paths: list = []
        self._lock = threading.Lock()
        self.arrived = threading.Condition(self._lock)       # notified on every request
        self.gates: dict = {}                                # height -> Event: requests for it wait until it is set
        node = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):          # noqa: N802
                node._handle(self)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def start(self):
        self.thread.start()
        return self

    def stop(self):
        self.server.shutdown()
        self.server.server_close()

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()

    # ---------------------------------------------------------------------------------------------
    def _handle(self, h):
        with self._lock:
            n = len(self.arrivals)
            self.arrivals.append(time.monotonic())
            self.paths.append(h.path)
            self.arrived.notify_all()
        gate = self.gates.get(self._height_of(h.path))
        if gate is not None:
            gate.wait(timeout=15)                  # a test releases it; the timeout only stops a hung test
        scripted = self.script(n)
        if scripted is not None:      # a status, or (status, body)
            status, body = scripted if isinstance(scripted, tuple) else (scripted, b'{"error": "scripted"}')
            return self._send(h, status, body)
        url = urlparse(h.path)
        try:
            if url.path == "/cosmos/base/tendermint/v1beta1/blocks/latest":
                top = max(self.cache.heights(self.chain_id))
                return self._send(h, 200, json.dumps({"block": {"header": {"height": str(top)}}}).encode())
            if url.path.startswith("/cosmos/tx/v1beta1/txs/block/"):
                height = int(url.path.rsplit("/", 1)[1])
                pages, _ = self.cache.read(self.chain_id, height)
                key = parse_qs(url.query).get("pagination.key", [None])[0]
                index = 0
                if key is not None:       # the page that follows the one whose next_key is `key`
                    index = next(i + 1 for i, p in enumerate(pages) if json.loads(p)["pagination"]["next_key"] == key)
                return self._send(h, 200, pages[index])
            if url.path == "/block_results":
                height = int(parse_qs(url.query)["height"][0])
                return self._send(h, 200, self.cache.read(self.chain_id, height)[1])
        except Exception:      # unknown height, bad key: what a pruned node says
            return self._send(h, 404, b'{"error": "not found"}')
        return self._send(h, 404, b'{"error": "not found"}')

    def wait_for(self, predicate, timeout: float = 10.0) -> bool:
        """Block until predicate(self.paths) is true (re-checked on every request). No polling, no sleeping."""
        with self.arrived:
            return self.arrived.wait_for(lambda: predicate(list(self.paths)), timeout)

    @staticmethod
    def _height_of(path):
        url = urlparse(path)
        if url.path.startswith("/cosmos/tx/v1beta1/txs/block/"):
            return int(url.path.rsplit("/", 1)[1])
        if url.path == "/block_results":
            return int(parse_qs(url.query)["height"][0])
        return None

    @staticmethod
    def _send(h, status, body):
        h.send_response(status)
        h.send_header("Content-Type", "application/json")
        h.send_header("Content-Length", str(len(body)))
        h.end_headers()
        h.wfile.write(body)

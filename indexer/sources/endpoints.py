"""Endpoint list and rotation with a cool-down for failing endpoints."""
import json
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from .ratelimit import TokenBucket

# Terra (phoenix-1) public nodes; override with INDEXER_ENDPOINTS (a JSON list).
DEFAULT_ENDPOINTS = [
    {"name": "publicnode", "rest": "https://terra-rest.publicnode.com", "rpc": "https://terra-rpc.publicnode.com",
     "rate": 5, "burst": 5},
    {"name": "polkachu", "rest": "https://terra-api.polkachu.com", "rpc": "https://terra-rpc.polkachu.com",
     "rate": 5, "burst": 5},
]


@dataclass
class Endpoint:
    name: str
    rest: str        # base URL of the REST (LCD) API
    rpc: str         # base URL of the CometBFT RPC
    limiter: TokenBucket
    cooling_until: float = field(default=0.0)


def load_endpoints(clock=time.monotonic, sleep=time.sleep, environ=None) -> list:
    env = os.environ if environ is None else environ
    spec = json.loads(env["INDEXER_ENDPOINTS"]) if env.get("INDEXER_ENDPOINTS") else DEFAULT_ENDPOINTS
    return [
        Endpoint(e["name"], e["rest"].rstrip("/"), e["rpc"].rstrip("/"),
                 TokenBucket(e.get("rate", 5), e.get("burst", e.get("rate", 5)), clock=clock, sleep=sleep))
        for e in spec
    ]


class EndpointPool:
    """Round robin over the endpoints that are not cooling down."""

    def __init__(self, endpoints: list, cooldown: float = 30.0, clock=time.monotonic):
        if not endpoints:
            raise ValueError("no endpoints configured")
        self.endpoints, self.cooldown, self._clock = endpoints, cooldown, clock
        self._next = 0
        self._lock = threading.Lock()

    def pick(self) -> Optional[Endpoint]:
        """The next usable endpoint, or None when every one is cooling down."""
        with self._lock:
            now = self._clock()
            for _ in range(len(self.endpoints)):
                ep = self.endpoints[self._next % len(self.endpoints)]
                self._next += 1
                if ep.cooling_until <= now:
                    return ep
            return None

    def mark_failed(self, endpoint: Endpoint) -> None:
        with self._lock:
            endpoint.cooling_until = self._clock() + self.cooldown

    def seconds_until_available(self) -> float:
        with self._lock:
            now = self._clock()
            return max(0.0, min(ep.cooling_until for ep in self.endpoints) - now)

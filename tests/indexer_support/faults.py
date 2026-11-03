"""A source wrapper that fails on chosen heights (REVAMP.md 8.3)."""
import threading
from collections import Counter

from indexer.models import WorkItem


class FaultySource:
    """Wraps a source. `faults` maps a height to what its loads do:
      - a list of exceptions: the n-th load raises the n-th one, later loads succeed;
      - one exception instance: every load raises it.
    `loads` counts the load attempts per height."""

    def __init__(self, source, faults=None, before_load=None):
        self.source, self.faults, self.before_load = source, dict(faults or {}), before_load
        self.loads = Counter()
        self._lock = threading.Lock()

    def items(self, stop=None):
        for item in self.source.items(stop):
            yield WorkItem(item.chain_id, item.height, self._wrap(item))

    def _wrap(self, item):
        def load():
            with self._lock:
                self.loads[item.height] += 1
                n = self.loads[item.height]
            if self.before_load:
                self.before_load(item.height)
            fault = self.faults.get(item.height)
            if isinstance(fault, list):
                if n <= len(fault):
                    raise fault[n - 1]
            elif fault is not None:
                raise fault
            return item.load()
        return load

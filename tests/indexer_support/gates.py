"""Deterministic control of worker threads (D22): a gate per height instead of sleeps (rulebook rule 8).

    gates = Gates(hold=[103])           # block 103 waits before it is loaded
    pipeline = Pipeline(gates.wrap(source), hooks=gates.hooks, workers=4, ...)
    running = start(pipeline)
    gates.committed[105].wait(...)      # an event set after height 105 committed
    gates.release(103)
"""
import threading
from collections import defaultdict

from indexer.models import WorkItem
from indexer.writer import Hooks

WAIT = 15          # seconds any wait may take before the test is declared stuck


class Gates:
    def __init__(self, hold=(), crash_at=None, crash_after=()):
        self._open = {h: threading.Event() for h in hold}
        self.aborted = threading.Event()
        self._lock = threading.Lock()
        self._committed = defaultdict(threading.Event)
        self.crash_at, self.crash_after = crash_at, tuple(crash_after)
        self.loaded = []                                   # heights in the order they started loading
        self.hooks = Hooks(before_commit=self._before_commit, after_commit=self._after_commit)

    @property
    def committed(self):
        outer = self

        class _ByHeight:
            def __getitem__(self, height):
                with outer._lock:
                    return outer._committed[height]
        return _ByHeight()

    # --- control from the test ---------------------------------------------------------------
    def release(self, *heights):
        for h in heights:
            self._open[h].set()

    def abort(self):
        """Simulate the process dying: waiting workers raise SystemExit instead of continuing."""
        self.aborted.set()
        for gate in self._open.values():                   # wake the held workers; they see `aborted` and raise
            gate.set()

    # --- seams the pipeline calls ------------------------------------------------------------
    def _wait_gate(self, height):
        with self._lock:
            self.loaded.append(height)
        if height == self.crash_at:                        # wait here, NOT in before_commit: by then the block holds
            for h in self.crash_after:                     # the checkpoint row's lock and the others could not commit
                assert self.committed[h].wait(WAIT), f"{h} never committed"
        gate = self._open.get(height)
        if gate is None:
            return
        gate.wait(WAIT)
        if self.aborted.is_set():
            raise SystemExit(f"killed while loading {height}")
        assert gate.is_set(), f"gate {height} was never released"

    def _before_commit(self, height):
        if height == self.crash_at:
            self.abort()
            raise SystemExit(f"killed before committing {height}")

    def _after_commit(self, height):
        self.committed[height].set()

    def wrap(self, source):
        return _GatedSource(source, self)


class _GatedSource:
    def __init__(self, source, gates):
        self.source, self.gates = source, gates

    def items(self, stop=None):
        for item in self.source.items(stop):
            yield WorkItem(item.chain_id, item.height, self._gated(item))

    def _gated(self, item):
        def load():
            self.gates._wait_gate(item.height)
            return item.load()
        return load


class Running:
    """A pipeline running in a background thread."""

    def __init__(self, pipeline):
        self.pipeline, self.error, self.stats = pipeline, None, None
        self.thread = threading.Thread(target=self._run, name="test-pipeline")
        self.thread.start()

    def _run(self):
        try:
            self.stats = self.pipeline.run()
        except BaseException as exc:          # noqa: BLE001 - the test inspects it
            self.error = exc

    def join(self, timeout=WAIT):
        self.thread.join(timeout)
        assert not self.thread.is_alive(), "the pipeline did not finish"
        if self.error is not None:
            raise self.error
        return self.stats


def start(pipeline) -> Running:
    return Running(pipeline)

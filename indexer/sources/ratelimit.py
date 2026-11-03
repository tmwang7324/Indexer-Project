"""Token bucket, shared by all threads behind a lock (D7). The clock and sleep are injectable for tests."""
import threading
import time


class TokenBucket:
    def __init__(self, rate: float, capacity: float, clock=time.monotonic, sleep=time.sleep):
        if rate <= 0 or capacity < 1:
            raise ValueError("rate must be positive and capacity at least 1")
        self.rate, self.capacity = float(rate), float(capacity)
        self._clock, self._sleep = clock, sleep
        self._tokens = float(capacity)
        self._updated = clock()
        self._lock = threading.Lock()

    def try_acquire(self) -> float:
        """Take a token if one is there (returns 0.0); otherwise return how long until one is."""
        with self._lock:
            now = self._clock()
            self._tokens = min(self.capacity, self._tokens + (now - self._updated) * self.rate)
            self._updated = now
            if self._tokens >= 1:
                self._tokens -= 1
                return 0.0
            return (1 - self._tokens) / self.rate

    def acquire(self) -> None:
        """Block until a token is available."""
        while True:
            wait = self.try_acquire()
            if wait == 0.0:
                return
            self._sleep(wait)

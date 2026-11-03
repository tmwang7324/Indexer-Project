"""U7: a burst up to capacity, then refill over time (fake clock, no sleeping)."""
import pytest

from indexer.sources.ratelimit import TokenBucket


class FakeClock:
    def __init__(self):
        self.now = 100.0
        self.slept = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


def bucket(rate=2, capacity=3):
    clock = FakeClock()
    return TokenBucket(rate, capacity, clock=clock, sleep=clock.sleep), clock


def test_burst_up_to_capacity_then_wait():
    b, _ = bucket()
    assert [b.try_acquire() for _ in range(3)] == [0.0, 0.0, 0.0]
    assert b.try_acquire() == pytest.approx(0.5)      # 1 token at 2/s


def test_refill_over_time_never_beyond_capacity():
    b, clock = bucket()
    for _ in range(3):
        b.try_acquire()
    clock.now += 0.5
    assert b.try_acquire() == 0.0 and b.try_acquire() > 0       # exactly one token came back
    clock.now += 60
    assert [b.try_acquire() for _ in range(4)] == [0.0, 0.0, 0.0, pytest.approx(0.5)]   # capped at 3


def test_acquire_sleeps_just_long_enough():
    b, clock = bucket(rate=4, capacity=1)
    b.acquire()
    b.acquire()
    assert clock.slept == [pytest.approx(0.25)]


def test_invalid_settings():
    with pytest.raises(ValueError):
        TokenBucket(0, 1)

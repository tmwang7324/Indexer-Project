"""U9: a failing endpoint is skipped, then retried after its cool-down (fake clock)."""
from indexer.sources.endpoints import EndpointPool, load_endpoints


class Clock:
    now = 0.0

    def __call__(self):
        return self.now


def pool(cooldown=30.0):
    clock = Clock()
    endpoints = load_endpoints(clock=clock, environ={"INDEXER_ENDPOINTS": (
        '[{"name": "a", "rest": "http://a/", "rpc": "http://a-rpc/"},'
        ' {"name": "b", "rest": "http://b", "rpc": "http://b-rpc"}]')})
    return EndpointPool(endpoints, cooldown=cooldown, clock=clock), clock


def names(p, n):
    return [e.name if (e := p.pick()) else None for _ in range(n)]


def test_endpoints_alternate_and_urls_are_normalised():
    p, _ = pool()
    assert names(p, 4) == ["a", "b", "a", "b"]
    assert p.endpoints[0].rest == "http://a"


def test_failing_endpoint_is_skipped_then_retried_after_cooldown():
    p, clock = pool(cooldown=30)
    a = p.endpoints[0]
    p.mark_failed(a)
    assert names(p, 3) == ["b", "b", "b"]
    clock.now = 29.9
    assert names(p, 2) == ["b", "b"]
    clock.now = 30.0
    assert "a" in names(p, 2)


def test_all_cooling_down_gives_none_and_the_wait():
    p, clock = pool(cooldown=30)
    clock.now = 10
    for e in p.endpoints:
        p.mark_failed(e)
    assert p.pick() is None
    assert p.seconds_until_available() == 30
    clock.now = 25
    assert p.seconds_until_available() == 15

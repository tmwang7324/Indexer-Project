"""U8: the retry policy (D21). Classification, then the four behaviours."""
import psycopg2
import pytest
import requests

from indexer.errors import BadDataError, CountMismatchError, TransientError
from indexer.retry import BAD_DATA, BUG, TRANSIENT, RetriesExhausted, Stopped, call_with_retries, classify


@pytest.mark.parametrize("exc, expected", [
    (TransientError("no endpoint"), TRANSIENT),
    (requests.Timeout(), TRANSIENT),
    (requests.ConnectionError(), TRANSIENT),
    (psycopg2.OperationalError("server closed the connection"), TRANSIENT),
    (psycopg2.InterfaceError("connection already closed"), TRANSIENT),
    (BadDataError("not JSON"), BAD_DATA),
    (CountMismatchError("c", 1, []), BAD_DATA),
    (KeyError("boom"), BUG),
    (psycopg2.IntegrityError("unique"), BUG),
], ids=["TransientError", "Timeout", "ConnectionError", "OperationalError", "InterfaceError", "BadDataError",
        "CountMismatchError", "KeyError", "IntegrityError"])
def test_classification(exc, expected):
    assert classify(exc) == expected


class Flaky:
    """Fails with the given exceptions, one per call, then succeeds."""

    def __init__(self, *errors):
        self.errors, self.calls = list(errors), 0

    def __call__(self):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return "ok"


def policy(fn, sleeps, **kw):
    return call_with_retries(fn, max_attempts=kw.pop("max_attempts", 4), delay=1.0, sleep=sleeps.append, **kw)


def test_transient_then_success_backs_off_between_attempts():
    fn, sleeps = Flaky(TransientError("a"), TransientError("b")), []
    assert policy(fn, sleeps) == "ok"
    assert (fn.calls, sleeps) == (3, [1.0, 2.0])


def test_transient_past_the_limit_gives_up_with_the_attempt_count_and_last_error():
    fn, sleeps = Flaky(*[TransientError(f"try {i}") for i in range(10)]), []
    with pytest.raises(RetriesExhausted) as info:
        policy(fn, sleeps, max_attempts=3)
    assert (info.value.attempts, fn.calls, sleeps) == (3, 3, [1.0, 2.0])
    assert "try 2" in str(info.value)


def test_bad_data_is_not_retried():
    fn, sleeps = Flaky(BadDataError("malformed")), []
    with pytest.raises(BadDataError):
        policy(fn, sleeps)
    assert (fn.calls, sleeps) == (1, [])


def test_an_unexpected_exception_is_re_raised_unchanged_and_not_retried():
    boom = KeyError("bug")
    fn, sleeps = Flaky(boom), []
    with pytest.raises(KeyError) as info:
        policy(fn, sleeps)
    assert info.value is boom and fn.calls == 1 and sleeps == []


def test_the_delay_is_capped():
    fn, sleeps = Flaky(*[TransientError("x")] * 5), []
    call_with_retries(
        fn, max_attempts=6, delay=10.0, max_delay=25.0, sleep=sleeps.append)
    assert sleeps == [10.0, 20.0, 25.0, 25.0, 25.0]


def test_a_stop_request_during_the_backoff_abandons_the_attempt():
    fn = Flaky(TransientError("a"))
    with pytest.raises(Stopped):
        call_with_retries(fn, max_attempts=4, delay=1.0, sleep=lambda seconds: True)
    assert fn.calls == 1

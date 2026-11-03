"""Error classes and the retry policy (D21).

    transient   timeouts, connection errors, HTTP 429/5xx, a database connection that dropped -> retry with backoff
    bad data    malformed responses, count mismatches                                          -> record, never retry
    bug         anything else                                                                  -> stop the whole run
"""
import time
from typing import Callable

import psycopg2
import requests

from .errors import BadDataError, TransientError

TRANSIENT, BAD_DATA, BUG = "transient", "bad data", "bug"

_TRANSIENT_TYPES = (TransientError, requests.Timeout, requests.ConnectionError,
                    psycopg2.OperationalError, psycopg2.InterfaceError)


def classify(exc: BaseException) -> str:
    if isinstance(exc, BadDataError):
        return BAD_DATA
    if isinstance(exc, _TRANSIENT_TYPES):
        return TRANSIENT
    return BUG


def is_broken_connection(exc: BaseException) -> bool:
    """The database connection itself is unusable (killed backend, network drop): close it, do not pool it."""
    return isinstance(exc, (psycopg2.OperationalError, psycopg2.InterfaceError))


class RetriesExhausted(Exception):
    """Transient errors went on past the attempt limit."""

    def __init__(self, attempts: int, last: BaseException):
        self.attempts, self.last = attempts, last
        super().__init__(f"{last.__class__.__name__}: {last}")


class Stopped(Exception):
    """The run is stopping: the attempt was abandoned during its backoff, not failed."""


def call_with_retries(fn: Callable, *, max_attempts: int, delay: float = 1.0, max_delay: float = 30.0,
                      sleep: Callable[[float], object] = time.sleep, on_retry: Callable = None):
    """Call `fn()` until it succeeds.

    Transient errors are retried with a doubling delay up to `max_attempts` calls in all, then raise
    RetriesExhausted. Bad data and bugs are raised at once, unchanged. `sleep` returns true when the run
    was told to stop; the attempt is then abandoned with Stopped.
    """
    attempt = 0
    while True:
        attempt += 1
        try:
            return fn()
        except Exception as exc:                                  # noqa: BLE001 - classified right below
            if classify(exc) != TRANSIENT:
                raise
            if attempt >= max_attempts:
                raise RetriesExhausted(attempt, exc) from exc
            if on_retry:
                on_retry(attempt, exc)
            if sleep(min(delay * 2 ** (attempt - 1), max_delay)):
                raise Stopped() from exc

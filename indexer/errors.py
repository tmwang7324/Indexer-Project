class BadDataError(Exception):
    """The source data is malformed or inconsistent (D21): retrying will not help."""


class TransientError(Exception):
    """A fetch or database problem that may go away: timeouts, 429/5xx, no endpoint available (D21)."""
